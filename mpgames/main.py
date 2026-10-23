import os
from flask import (
    Flask, render_template, redirect,
    url_for, session, jsonify
)
from flask_socketio import SocketIO

import database
from auth import auth_bp
from games import games_bp, get_game_list
from server import server_bp, register_socket_events
from profile import profile_bp


app = Flask(__name__)

app.config.update(
    SECRET_KEY=os.environ.get(
        "SECRET_KEY",
        "development-only-change-this-secret"
    ),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=bool(os.environ.get("RENDER")),
    MAX_CONTENT_LENGTH=1 * 1024 * 1024,
    PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 7
)

socketio = SocketIO(
    app,
    async_mode="threading",
    ping_interval=25,
    ping_timeout=60
)

app.register_blueprint(auth_bp)
app.register_blueprint(games_bp)
app.register_blueprint(server_bp)
app.register_blueprint(profile_bp)

register_socket_events(socketio)


@app.route("/")
def home():
    if not session.get("user_id"):
        return redirect(url_for("auth.login"))

    import database as db

    return render_template(
        "home.html",
        username=session.get("username", "Player"),
        user_id=session.get("user_id"),
        games=get_game_list(),
        leaderboard=db.get_leaderboard("maths_trivia", limit=10)
    )


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "service": "multiplayer-game-platform"
    })


if __name__ == "__main__":
    host = "0.0.0.0"
    port = int(os.environ.get("PORT", 8080))

    print(f"Multiplayer platform starting on port {port}")
    print("Open http://127.0.0.1:8080 on this device.")
    print("For other devices, use this phone's LAN IP and port 8080.")

    socketio.run(
        app,
        host=host,
        port=port,
        debug=False,
        allow_unsafe_werkzeug=True
    )