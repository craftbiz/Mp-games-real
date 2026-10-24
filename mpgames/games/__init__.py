
from flask import Blueprint, render_template, request, jsonify, abort, send_from_directory

import database
from pathlib import Path
from auth import login_required
from .register import (
    get_game as registry_get_game,
    get_game_list as registry_get_game_list,
    validate_settings as registry_validate_settings,
)

games_bp = Blueprint("games", __name__)


def _adapt_game(game):
    """Keep metadata fields while supporting the existing templates."""
    if not game:
        return None

    result = dict(game)
    result["slug"] = result["game_id"]
    result["name"] = result["game_name"]
    result["description"] = result.get(
        "description",
        "A multiplayer challenge awaits."
    )
    return result


def get_game(game_slug):
    return _adapt_game(registry_get_game(game_slug))


def get_game_list(include_unavailable=True):
    return [
        _adapt_game(game)
        for game in registry_get_game_list(include_unavailable)
    ]


def validate_settings(game_slug, raw_settings):
    game = registry_get_game(game_slug)

    if not game:
        raise ValueError("Unknown game.")

    if not game.get("available", False):
        raise ValueError("This game is not available yet.")

    return registry_validate_settings(game, raw_settings)


@games_bp.route("/games", defaults={"game_slug": "maths_trivia"})
@games_bp.route("/games/<game_slug>")
@login_required
def games_page(game_slug):
    game = get_game(game_slug)

    if not game:
        abort(404)

    import server as server_module

    return render_template(
        "games.html",
        game=game,
        game_slug=game_slug,
        games=get_game_list(),
        servers=server_module.list_servers(game_slug),
    )


@games_bp.route("/api/games")
@login_required
def api_games():
    return jsonify({"games": get_game_list()})


@games_bp.route("/api/leaderboard/<game_slug>")
@login_required
def api_leaderboard(game_slug):
    game = get_game(game_slug)

    if not game:
        return jsonify({"error": "Unknown game."}), 404

    rows = database.get_leaderboard(game_slug, limit=50)
    return jsonify({"game": game_slug, "leaderboard": rows})


@games_bp.route("/game-assets/<game_slug>/<path:filename>")
@login_required
def game_asset(game_slug, filename):
    """Serve only the selected game's packaged static assets."""
    game = get_game(game_slug)
    if not game or not game.get("available", False):
        abort(404)

    game_root = (Path(__file__).resolve().parent / game["path"]).resolve()
    static_root = (game_root / "static").resolve()
    target = (static_root / filename).resolve()

    # Prevent path traversal and accidental access to engine/source files.
    if static_root not in target.parents or not target.is_file():
        abort(404)

    return send_from_directory(str(static_root), str(target.relative_to(static_root)))

# Backward compatibility for profile.py
GAMES = {
    game["slug"]: game
    for game in get_game_list()
}