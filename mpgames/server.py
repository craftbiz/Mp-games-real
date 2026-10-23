import json
import secrets
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone

from flask import (
    Blueprint, render_template, request,
    jsonify, session, abort
)
from flask_socketio import join_room, leave_room, emit

from auth import login_required
from games import get_game, validate_settings

server_bp = Blueprint("server", __name__)

# Temporary only: all rooms disappear when the process restarts.
SERVERS = {}
SID_TO_SERVER = {}
LOCK = threading.RLock()

MAX_CHAT_MESSAGES = 100


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def _public_server(room):
    return {
        "server_id": room["server_id"],
        "name": room["name"],
        "game_slug": room["game_slug"],
        "game_name": room["game_name"],
        "owner_id": room["owner_id"],
        "owner_name": room["owner_name"],
        "player_count": len(room["players"]),
        "max_players": room["max_players"],
        "status": room["status"],
        "settings": dict(room["settings"]),
        "created_at": room["created_at"]
    }


def list_servers(game_slug=None):
    with LOCK:
        result = []

        for room in SERVERS.values():
            if game_slug and room["game_slug"] != game_slug:
                continue
            result.append(_public_server(room))

        return sorted(
            result,
            key=lambda item: (
                item["status"] != "waiting",
                item["created_at"]
            )
        )


def get_server(server_id):
    with LOCK:
        room = SERVERS.get(str(server_id))
        return _public_server(room) if room else None


def _cancel_timer(room):
    timer = room.get("cleanup_timer")
    if timer:
        timer.cancel()
        room["cleanup_timer"] = None


def _schedule_cleanup(room):
    _cancel_timer(room)

    count = len(room["players"])

    if count == 0:
        delay = 5
    elif count == 1 and room["status"] == "waiting":
        delay = 600
    else:
        return

    server_id = room["server_id"]

    def cleanup():
        with LOCK:
            current = SERVERS.get(server_id)

            if current is not room:
                return

            player_count = len(current["players"])

            if player_count == 0:
                SERVERS.pop(server_id, None)
                return

            if (
                player_count == 1
                and current["status"] == "waiting"
            ):
                # Kick the remaining player by deleting the room.
                remaining = next(iter(current["players"].values()))
                SID_TO_SERVER.pop(remaining.get("sid"), None)
                SERVERS.pop(server_id, None)

    timer = threading.Timer(delay, cleanup)
    timer.daemon = True
    room["cleanup_timer"] = timer
    timer.start()


def _transfer_owner(room):
    if not room["players"]:
        room["owner_id"] = None
        room["owner_name"] = None
        return

    # OrderedDict preserves join order: the earliest remaining player wins.
    new_owner = next(iter(room["players"].values()))
    room["owner_id"] = new_owner["user_id"]
    room["owner_name"] = new_owner["username"]


def _remove_player(server_id, user_id, sid=None):
    room = SERVERS.get(server_id)

    if not room:
        return None

    player = room["players"].get(user_id)

    if not player:
        return room

    # A stale disconnect must not remove a newer connection.
    if sid is not None and player.get("sid") != sid:
        return room

    room["players"].pop(user_id, None)

    if player.get("sid"):
        SID_TO_SERVER.pop(player["sid"], None)

    if room["owner_id"] == user_id:
        _transfer_owner(room)

    _schedule_cleanup(room)
    return room


def _room_snapshot(room):
    return {
        **_public_server(room),
        "players": [
            {
                "user_id": player["user_id"],
                "username": player["username"],
                "is_owner": player["user_id"] == room["owner_id"]
            }
            for player in room["players"].values()
        ],
        "chat": list(room["chat"])
    }


@server_bp.route("/server/<server_id>")
@login_required
def waiting_room(server_id):
    room = get_server(server_id)

    if not room:
        abort(404)

    return render_template(
        "server.html",
        server=room
    )


@server_bp.route("/api/servers", methods=["GET"])
@login_required
def api_list_servers():
    game_slug = request.args.get("game")
    return jsonify({"servers": list_servers(game_slug)})


@server_bp.route("/api/servers", methods=["POST"])
@login_required
def api_create_server():
    data = request.get_json(silent=True) or request.form.to_dict()
    game_slug = str(data.get("game_slug", "")).strip()
    name = str(data.get("name", "")).strip()

    game = get_game(game_slug)

    if not game or not game["available"]:
        return jsonify({"error": "That game is not available."}), 400

    if not 3 <= len(name) <= 40:
        return jsonify({
            "error": "Server name must be 3–40 characters."
        }), 400

    try:
        max_players = int(data.get("max_players", 20))
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid player limit."}), 400

    if not game["min_players"] <= max_players <= game["max_players"]:
        return jsonify({
            "error": (
                f"Player limit must be between "
                f"{game['min_players']} and {game['max_players']}."
            )
        }), 400

    raw_settings = data.get("settings", {})

    if isinstance(raw_settings, str):
        try:
            raw_settings = json.loads(raw_settings)
        except ValueError:
            return jsonify({"error": "Invalid settings data."}), 400

    if not isinstance(raw_settings, dict):
        return jsonify({"error": "Settings must be an object."}), 400

    try:
        settings = validate_settings(game_slug, raw_settings)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    user_id = session.get("user_id")
    username = session.get("username") or "Player"
    server_id = secrets.token_urlsafe(9)

    room = {
        "server_id": server_id,
        "name": name,
        "game_slug": game_slug,
        "game_name": game["name"],
        "owner_id": user_id,
        "owner_name": username,
        "max_players": max_players,
        "status": "waiting",
        "settings": settings,
        "created_at": utc_now(),
        "players": OrderedDict(),
        "chat": [],
        "cleanup_timer": None
    }

    with LOCK:
        SERVERS[server_id] = room
        _schedule_cleanup(room)

    return jsonify({
        "server": _public_server(room),
        "url": f"/server/{server_id}"
    }), 201


def register_socket_events(socketio):

    @socketio.on("room_join")
    def handle_room_join(data):
        user_id = session.get("user_id")
        username = session.get("username")

        if not user_id or not username:
            emit("room_error", {"error": "Please log in first."})
            return

        data = data or {}
        server_id = str(data.get("server_id", ""))

        with LOCK:
            room = SERVERS.get(server_id)

            if not room:
                emit("room_error", {"error": "Server no longer exists."})
                return

            if room["status"] != "waiting":
                emit("room_error", {"error": "This game has already started."})
                return

            existing = room["players"].get(user_id)

            if not existing and len(room["players"]) >= room["max_players"]:
                emit("room_error", {"error": "This server is full."})
                return

            _cancel_timer(room)

            if existing and existing.get("sid"):
                SID_TO_SERVER.pop(existing["sid"], None)

            room["players"][user_id] = {
                "user_id": user_id,
                "username": username,
                "sid": request.sid,
                "joined_at": existing["joined_at"] if existing else time.time()
            }

            SID_TO_SERVER[request.sid] = server_id
            join_room(server_id)

            snapshot = _room_snapshot(room)
            player_count = len(room["players"])

        emit("room_state", snapshot)

        socketio.emit(
            "room_notice",
            {"message": f"{username} joined the server."},
            to=server_id,
            include_self=False
        )

        socketio.emit(
            "room_players",
            snapshot["players"],
            to=server_id
        )

        with LOCK:
            current = SERVERS.get(server_id)
            if current:
                _schedule_cleanup(current)

    @socketio.on("room_leave")
    def handle_room_leave(data=None):
        user_id = session.get("user_id")
        server_id = SID_TO_SERVER.get(request.sid)

        if not user_id or not server_id:
            return

        with LOCK:
            room = SERVERS.get(server_id)
            username = session.get("username", "Player")
            _remove_player(server_id, user_id, request.sid)

            if not room or server_id not in SERVERS:
                return

            snapshot = _room_snapshot(room)

        leave_room(server_id)

        socketio.emit(
            "room_notice",
            {"message": f"{username} left the server."},
            to=server_id
        )
        socketio.emit("room_players", snapshot["players"], to=server_id)
        socketio.emit("room_state", snapshot, to=server_id)

    @socketio.on("room_chat")
    def handle_room_chat(data):
        user_id = session.get("user_id")
        server_id = SID_TO_SERVER.get(request.sid)

        if not user_id or not server_id:
            return

        data = data or {}
        message = str(data.get("message", "")).strip()
        message = message[:500]

        if not message:
            return

        with LOCK:
            room = SERVERS.get(server_id)
            if not room or user_id not in room["players"]:
                return

            item = {
                "user_id": user_id,
                "username": session.get("username", "Player"),
                "message": message,
                "sent_at": utc_now()
            }

            room["chat"].append(item)
            room["chat"] = room["chat"][-MAX_CHAT_MESSAGES:]

        # The frontend must render message text safely, not as HTML.
        socketio.emit("room_chat_message", item, to=server_id)

    @socketio.on("start_game")
    def handle_start_game(data=None):
        user_id = session.get("user_id")
        server_id = SID_TO_SERVER.get(request.sid)

        if not user_id or not server_id:
            emit("room_error", {"error": "Join a server first."})
            return

        with LOCK:
            room = SERVERS.get(server_id)

            if not room:
                emit("room_error", {"error": "Server no longer exists."})
                return

            if room["owner_id"] != user_id:
                emit("room_error", {"error": "Only the owner can start."})
                return

            game = get_game(room["game_slug"])

            if len(room["players"]) < game["min_players"]:
                emit("room_error", {
                    "error": f"At least {game['min_players']} players are required."
                })
                return

            if room["status"] != "waiting":
                emit("room_error", {"error": "Game has already started."})
                return

            _cancel_timer(room)
            room["status"] = "playing"
            snapshot = _room_snapshot(room)

        # The actual game engine and countdown will be added next.
        socketio.emit("game_starting", snapshot, to=server_id)

    @socketio.on("disconnect")
    def handle_disconnect(reason=None):
        user_id = session.get("user_id")
        server_id = SID_TO_SERVER.get(request.sid)

        if not user_id or not server_id:
            return

        username = session.get("username", "Player")

        with LOCK:
            room = SERVERS.get(server_id)

            if not room:
                SID_TO_SERVER.pop(request.sid, None)
                return

            _remove_player(server_id, user_id, request.sid)

            if server_id not in SERVERS:
                return

            snapshot = _room_snapshot(room)

        socketio.emit(
            "room_notice",
            {"message": f"{username} disconnected."},
            to=server_id
        )
        socketio.emit("room_players", snapshot["players"], to=server_id)
        socketio.emit("room_state", snapshot, to=server_id)