import json
import secrets
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone

from flask import (
    Blueprint,
    render_template,
    request,
    jsonify,
    session,
    abort,
)
from flask_socketio import join_room, leave_room, emit

from auth import login_required
from games import get_game, validate_settings

server_bp = Blueprint("server", __name__)

SERVERS = {}
SID_TO_SERVER = {}
LOCK = threading.RLock()

MAX_CHAT_MESSAGES = 100
HANDOFF_TTL = 12
GAME_PLATFORM = None


def set_game_platform(platform):
    """Attach the shared plugin API after Socket.IO is initialized."""
    global GAME_PLATFORM
    GAME_PLATFORM = platform


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def _public_server(room):
    return {
        "server_id": room["server_id"],
        "id": room["server_id"],
        "name": room["name"],
        "game_slug": room["game_slug"],
        "game_id": room["game_slug"],
        "game_name": room["game_name"],
        "owner_id": room["owner_id"],
        "owner_name": room["owner_name"],
        "player_count": len(room["players"]),
        "max_players": room["max_players"],
        "min_players": room["min_players"],
        "status": room["status"],
        "settings": dict(room["settings"]),
        "created_at": room["created_at"],
    }


def list_servers(game_slug=None):
    with LOCK:
        result = [
            _public_server(room)
            for room in SERVERS.values()
            if not game_slug or room["game_slug"] == game_slug
        ]

        return sorted(
            result,
            key=lambda item: (
                item["status"] != "waiting",
                item["created_at"],
            ),
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

            if not current["players"]:
                SERVERS.pop(server_id, None)
                return

            if (
                len(current["players"]) == 1
                and current["status"] == "waiting"
            ):
                for player in current["players"].values():
                    SID_TO_SERVER.pop(player.get("sid"), None)

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

    player = next(iter(room["players"].values()))
    room["owner_id"] = player["user_id"]
    room["owner_name"] = player["username"]


def _remove_player(server_id, user_id, sid=None):
    room = SERVERS.get(server_id)

    if not room:
        return None

    player = room["players"].get(user_id)

    if not player:
        return room

    if sid is not None and player.get("sid") != sid:
        return room

    room["players"].pop(user_id, None)

    old_sid = player.get("sid")
    if old_sid:
        SID_TO_SERVER.pop(old_sid, None)

    if room["owner_id"] == user_id:
        _transfer_owner(room)

    _schedule_cleanup(room)
    return room


def _ban_and_remove_player(server_id, user_id, sid=None):
    room = SERVERS.get(server_id)

    if not room:
        return None

    player = room["players"].get(user_id)

    # Ignore a stale disconnect from a connection already replaced.
    if player and sid is not None and player.get("sid") != sid:
        return room

    # This ban remains for the lifetime of this room.
    room.setdefault("removed_users", set()).add(user_id)

    # Invalidate any unconsumed navigation tokens.
    handoffs = room.setdefault("handoffs", {})
    room["handoffs"] = {
        token: item
        for token, item in handoffs.items()
        if item["user_id"] != user_id
    }

    return _remove_player(server_id, user_id, sid)


def _room_snapshot(room):
    return {
        **_public_server(room),
        "players": [
            {
                "user_id": player["user_id"],
                "username": player["username"],
                "is_owner": player["user_id"] == room["owner_id"],
            }
            for player in room["players"].values()
        ],
        "chat": list(room["chat"]),
    }


def _broadcast_room(socketio, server_id, room, message=None):
    if not room or SERVERS.get(server_id) is not room:
        return

    snapshot = _room_snapshot(room)

    if message:
        socketio.emit(
            "room_notice",
            {"message": message},
            to=server_id,
        )

    socketio.emit("room_players", snapshot["players"], to=server_id)
    socketio.emit("room_state", snapshot, to=server_id)


def _expire_handoff(socketio, server_id, token):
    with LOCK:
        room = SERVERS.get(server_id)
        if not room:
            return

        handoff = room.get("handoffs", {}).get(token)
        if not handoff or handoff["expires"] > time.time():
            return

        room["handoffs"].pop(token, None)

        user_id = handoff["user_id"]
        player = room["players"].get(user_id)

        if player and player.get("sid") == handoff["old_sid"]:
            _ban_and_remove_player(
                server_id,
                user_id,
                handoff["old_sid"],
            )
            username = player["username"]
        else:
            return

    _broadcast_room(
        socketio,
        server_id,
        room,
        f"{username} failed to complete the gameplay transfer and was removed.",
    )


@server_bp.route("/server/<server_id>")
@login_required
def waiting_room(server_id):
    room = get_server(server_id)

    if not room:
        abort(404)

    return render_template(
        "server.html",
        server=room,
        server_id=room["server_id"],
        user_id=session.get("user_id", ""),
    )


@server_bp.route("/gameplay.html/<path:route_key>")
@login_required
def gameplay_page(route_key):
    parts = route_key.split("&", 1)

    if len(parts) != 2:
        abort(404)

    server_id, game_id = parts
    token = request.args.get("handoff", "")
    user_id = session.get("user_id")

    with LOCK:
        room = SERVERS.get(server_id)
        handoff = (
            room.get("handoffs", {}).get(token)
            if room else None
        )

        valid = (
            room is not None
            and room["game_slug"] == game_id
            and room["status"] == "playing"
            and user_id not in room.get("removed_users", set())
            and handoff is not None
            and handoff["user_id"] == user_id
            and handoff["expires"] > time.time()
        )

        if not valid:
            abort(403)

    game = get_game(game_id)
    if not game or not game.get("available", False):
        abort(404)

    return render_template(
        "gameplay.html",
        server_id=server_id,
        game_id=game_id,
        game=game,
        handoff_token=token,
        user_id=user_id,
    )


@server_bp.route("/api/servers", methods=["GET"])
@login_required
def api_list_servers():
    return jsonify({
        "servers": list_servers(request.args.get("game"))
    })


@server_bp.route("/api/servers", methods=["POST"])
@login_required
def api_create_server():
    data = request.get_json(silent=True) or request.form.to_dict()

    game_slug = str(data.get("game_slug", "")).strip()
    name = str(data.get("name", "")).strip()
    game = get_game(game_slug)

    if not game or not game.get("available", False):
        return jsonify({"error": "That game is not available."}), 400

    if not 3 <= len(name) <= 40:
        return jsonify({
            "error": "Server name must be between 3 and 40 characters."
        }), 400

    try:
        max_players = int(data.get("max_players", game["max_players"]))
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
        "game_name": game["game_name"],
        "owner_id": user_id,
        "owner_name": username,
        "max_players": max_players,
        "min_players": game["min_players"],
        "status": "waiting",
        "settings": settings,
        "created_at": utc_now(),
        "players": OrderedDict(),
        "chat": [],
        "cleanup_timer": None,
        "removed_users": set(),
        "handoffs": {},
    }

    with LOCK:
        SERVERS[server_id] = room
        _schedule_cleanup(room)

    return jsonify({
        "server": _public_server(room),
        "url": f"/server/{server_id}",
    }), 201


def register_socket_events(socketio):

    @socketio.on("room_join")
    def handle_room_join(data=None):
        user_id = session.get("user_id")
        username = session.get("username")

        if not user_id or not username:
            emit("room_error", {
                "error": "Please log in first.",
                "message": "Please log in first.",
            })
            return

        server_id = str((data or {}).get("server_id", ""))

        with LOCK:
            room = SERVERS.get(server_id)

            if not room:
                emit("room_error", {
                    "error": "Server no longer exists.",
                    "message": "Server no longer exists.",
                })
                return

            if user_id in room.get("removed_users", set()):
                emit("room_error", {
                    "error": "You were removed from this room and cannot rejoin.",
                    "message": "You were removed from this room and cannot rejoin.",
                })
                return

            if room["status"] != "waiting":
                emit("room_error", {
                    "error": "This game has already started.",
                    "message": "This game has already started.",
                })
                return

            if user_id in room["players"]:
                emit("room_error", {
                    "error": "You are already registered in this room.",
                    "message": "You are already registered in this room.",
                })
                return

            if len(room["players"]) >= room["max_players"]:
                emit("room_error", {
                    "error": "This server is full.",
                    "message": "This server is full.",
                })
                return

            _cancel_timer(room)

            room["players"][user_id] = {
                "user_id": user_id,
                "username": username,
                "sid": request.sid,
                "joined_at": time.time(),
                "gameplay_joined": False,
            }

            SID_TO_SERVER[request.sid] = server_id
            join_room(server_id)
            snapshot = _room_snapshot(room)

        emit("room_state", snapshot)
        socketio.emit(
            "room_notice",
            {"message": f"{username} joined the server."},
            to=server_id,
            include_self=False,
        )
        socketio.emit("room_players", snapshot["players"], to=server_id)

    @socketio.on("room_leave")
    def handle_room_leave(data=None):
        user_id = session.get("user_id")
        server_id = SID_TO_SERVER.get(request.sid)

        if not user_id or not server_id:
            return

        with LOCK:
            room = SERVERS.get(server_id)
            if not room:
                SID_TO_SERVER.pop(request.sid, None)
                return

            player = room["players"].get(user_id)
            if not player or player.get("sid") != request.sid:
                SID_TO_SERVER.pop(request.sid, None)
                return

            username = player["username"]
            _ban_and_remove_player(server_id, user_id, request.sid)

        leave_room(server_id)
        _broadcast_room(
            socketio,
            server_id,
            room,
            f"{username} left the room and cannot rejoin.",
        )

    @socketio.on("room_chat")
    def handle_room_chat(data=None):
        user_id = session.get("user_id")
        server_id = SID_TO_SERVER.get(request.sid)
        data = data or {}

        if not user_id or not server_id:
            return

        message = str(data.get("message", "")).strip()[:500]
        if not message:
            return

        with LOCK:
            room = SERVERS.get(server_id)
            player = room["players"].get(user_id) if room else None

            if not player or player.get("sid") != request.sid:
                return

            item = {
                "user_id": user_id,
                "username": player["username"],
                "message": message,
                "sent_at": utc_now(),
            }

            room["chat"].append(item)
            room["chat"] = room["chat"][-MAX_CHAT_MESSAGES:]

        socketio.emit("room_chat_message", item, to=server_id)

    @socketio.on("start_game")
    def handle_start_game(data=None):
        user_id = session.get("user_id")
        server_id = SID_TO_SERVER.get(request.sid)

        if not user_id or not server_id:
            emit("room_error", {
                "error": "Join a server first.",
                "message": "Join a server first.",
            })
            return

        with LOCK:
            room = SERVERS.get(server_id)

            if not room:
                emit("room_error", {
                    "error": "Server no longer exists.",
                    "message": "Server no longer exists.",
                })
                return

            player = room["players"].get(user_id)

            if not player or player.get("sid") != request.sid:
                emit("room_error", {
                    "error": "Your player session is not valid.",
                    "message": "Your player session is not valid.",
                })
                return

            if room["owner_id"] != user_id:
                emit("room_error", {
                    "error": "Only the owner can start.",
                    "message": "Only the owner can start.",
                })
                return

            game = get_game(room["game_slug"])

            if not game or not game.get("available"):
                emit("room_error", {
                    "error": "This game is unavailable.",
                    "message": "This game is unavailable.",
                })
                return

            if len(room["players"]) < game["min_players"]:
                message = (
                    f"At least {game['min_players']} players are required."
                )
                emit("room_error", {"error": message, "message": message})
                return

            if room["status"] != "waiting":
                emit("room_error", {
                    "error": "Game has already started.",
                    "message": "Game has already started.",
                })
                return

            _cancel_timer(room)
            room["_match_participant_ids"] = list(room["players"].keys())
            room["status"] = "playing"
            room["_plugin_start_called"] = False
            room["_platform_results_saved"] = False
            snapshot = _room_snapshot(room)

        try:
            if GAME_PLATFORM is None:
                raise RuntimeError("The game plugin system is not initialized.")
            GAME_PLATFORM.start_match(server_id)
        except Exception as exc:
            with LOCK:
                current = SERVERS.get(server_id)
                if current:
                    current["status"] = "waiting"
                    current.pop("_plugin_start_called", None)
            message = "The game engine could not start. Please try again."
            print(f"[MPGames] Failed to start {room['game_slug']}: {exc}", flush=True)
            emit("room_error", {"error": message, "message": message})
            return

        socketio.emit("game_starting", snapshot, to=server_id)

    @socketio.on("prepare_gameplay")
    def handle_prepare_gameplay(data=None):
        user_id = session.get("user_id")
        server_id = SID_TO_SERVER.get(request.sid)

        with LOCK:
            room = SERVERS.get(server_id) if server_id else None
            player = room["players"].get(user_id) if room else None

            if (
                not room
                or room["status"] != "playing"
                or not player
                or player.get("sid") != request.sid
                or user_id in room.get("removed_users", set())
            ):
                emit("room_error", {
                    "error": "Gameplay transfer denied.",
                    "message": "Gameplay transfer denied.",
                })
                return

            token = secrets.token_urlsafe(32)
            room.setdefault("handoffs", {})[token] = {
                "user_id": user_id,
                "old_sid": request.sid,
                "expires": time.time() + HANDOFF_TTL,
            }
            game_id = room["game_slug"]

        timer = threading.Timer(
            HANDOFF_TTL,
            _expire_handoff,
            args=(socketio, server_id, token),
        )
        timer.daemon = True
        timer.start()

        emit("gameplay_redirect", {
            "url": (
                f"/gameplay.html/{server_id}&{game_id}"
                f"?handoff={token}"
            )
        })

    @socketio.on("gameplay_join")
    def handle_gameplay_join(data=None):
        user_id = session.get("user_id")
        data = data or {}
        server_id = str(data.get("server_id", ""))
        token = str(data.get("handoff_token", ""))

        with LOCK:
            room = SERVERS.get(server_id)
            handoff = (
                room.get("handoffs", {}).get(token)
                if room else None
            )
            player = room["players"].get(user_id) if room else None

            if (
                not room
                or room["status"] != "playing"
                or user_id in room.get("removed_users", set())
                or not handoff
                or handoff["user_id"] != user_id
                or handoff["expires"] <= time.time()
                or not player
                or player.get("sid") != handoff["old_sid"]
            ):
                emit("gameplay_error", {
                    "error": "This gameplay session is invalid or expired."
                })
                return

            old_sid = handoff["old_sid"]
            room["handoffs"].pop(token, None)
            SID_TO_SERVER.pop(old_sid, None)

            player["sid"] = request.sid
            player["gameplay_joined"] = True
            SID_TO_SERVER[request.sid] = server_id
            join_room(server_id)
            snapshot = _room_snapshot(room)

        emit("gameplay_joined", snapshot)

    @socketio.on("disconnect")
    def handle_disconnect(reason=None):
        # A real disconnect is final. The only exception is an unexpired
        # handoff created explicitly before lobby-to-gameplay navigation.
        user_id = session.get("user_id")
        server_id = SID_TO_SERVER.get(request.sid)

        if not user_id or not server_id:
            return

        with LOCK:
            room = SERVERS.get(server_id)

            if not room:
                SID_TO_SERVER.pop(request.sid, None)
                return

            pending_handoff = any(
                item["user_id"] == user_id
                and item["old_sid"] == request.sid
                and item["expires"] > time.time()
                for item in room.get("handoffs", {}).values()
            )

            if pending_handoff:
                return

            player = room["players"].get(user_id)
            if not player or player.get("sid") != request.sid:
                SID_TO_SERVER.pop(request.sid, None)
                return

            username = player["username"]
            _ban_and_remove_player(server_id, user_id, request.sid)

        _broadcast_room(
            socketio,
            server_id,
            room,
            f"{username} disconnected and was permanently removed.",
        )