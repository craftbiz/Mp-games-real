"""Maths Trivia plugin adapter for the MPGames plugin contract."""

from flask import request, session
from flask_socketio import emit

from . import engine


def start_match(platform, server_id):
    return engine.start_match(
        platform.socketio,
        str(server_id),
        platform.rooms,
        platform.lock,
        platform,
    )


def register_socket_events(socketio, platform):
    @socketio.on("maths_trivia_answer")
    def handle_maths_trivia_answer(data=None):
        user_id = session.get("user_id")
        server_id = platform.server_for_sid(request.sid)

        if not user_id or not server_id:
            emit("maths_trivia_error", {
                "error": "Your game session is not authenticated."
            })
            return

        room = platform.get_room(server_id)
        player = platform.get_player(server_id, user_id, request.sid)

        if (
            not room
            or room.get("game_slug") != "maths_trivia"
            or room.get("status") not in ("playing", "completed")
            or not player
        ):
            emit("maths_trivia_error", {
                "error": "You are not an active player in this match."
            })
            return

        error = engine.submit_answer(
            server_id,
            user_id,
            data,
            platform.rooms,
            platform.lock,
        )

        if error:
            emit("maths_trivia_error", {"error": error})
        else:
            emit("maths_trivia_answer_status", {"accepted": True})
