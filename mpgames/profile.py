from flask import Blueprint, jsonify, session

from auth import login_required
import database
from games import GAMES

profile_bp = Blueprint("profile", __name__)


@profile_bp.route("/api/profile/<user_id>")
@login_required
def api_profile(user_id):
    profile = database.get_profile(user_id)

    if not profile:
        return jsonify({"error": "Player not found."}), 404

    scores = []

    for slug, game in GAMES.items():
        scores.append({
            "game_slug": slug,
            "game_name": game["name"],
            "highest_score": profile["highest_scores"].get(slug, 0)
        })

    return jsonify({
        "user_id": profile["user_id"],
        "username": profile["username"],
        "created_at": profile["created_at"],
        "scores": scores
    })


@profile_bp.route("/api/profile/me")
@login_required
def api_my_profile():
    user_id = session.get("user_id")
    profile = database.get_profile(user_id)

    if not profile:
        session.clear()
        return jsonify({"error": "Player not found."}), 404

    return jsonify(profile)