from flask import Blueprint, render_template, request, jsonify, abort

from auth import login_required
import database
from games.register import (
    get_game as registry_get_game,
    get_game_list as registry_get_game_list,
    validate_settings as registry_validate_settings,
)

games_bp = Blueprint("games", __name__)


def _normalize_game(game):
    """Preserve the metadata schema and provide legacy template aliases."""
    if not game:
        return None

    result = dict(game)
    result["slug"] = result.get("game_id", "")
    result["name"] = result.get("game_name", result["slug"])
    result["description"] = result.get("description", "")
    result["settings"] = result.get("settings", {})
    return result


def get_game(game_slug):
    return _normalize_game(registry_get_game(game_slug))


def get_game_list(include_unavailable=True):
    return [
        _normalize_game(game)
        for game in registry_get_game_list(include_unavailable)
    ]


def validate_settings(game_slug, raw_settings):
    game = registry_get_game(game_slug)

    if not game:
        raise ValueError("Unknown game.")

    if not game.get("available", False):
        raise ValueError("This game is not available yet.")

    return registry_validate_settings(game, raw_settings)


@games_bp.route("/games")
@login_required
def games_home():
    games = get_game_list()
    first_available = next(
        (game for game in games if game.get("available")),
        None,
    )

    if first_available:
        return render_template(
            "games.html",
            game=first_available,
            game_slug=first_available["game_id"],
            games=games,
            servers=[],
        )

    return render_template(
        "games.html",
        game=None,
        game_slug=None,
        games=games,
        servers=[],
    )


@games_bp.route("/games/<game_slug>", endpoint="games_page")
@login_required
def game_directory(game_slug):
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
    if not get_game(game_slug):
        return jsonify({"error": "Unknown game."}), 404

    rows = database.get_leaderboard(game_slug, limit=50)
    return jsonify({"game": game_slug, "leaderboard": rows})