from flask import (
    Blueprint, render_template, request,
    jsonify, abort
)

from auth import login_required
import database

games_bp = Blueprint("games", __name__)

GAMES = {
    "maths_trivia": {
        "name": "Maths Trivia",
        "description": "Solve questions before time runs out.",
        "available": True,
        "min_players": 2,
        "max_players": 20,
        "settings": {
            "seconds_per_question": {
                "label": "Seconds per question",
                "type": "select",
                "options": [3, 4, 5, 6, 7, 8, 9, 10],
                "default": 5
            },
            "end_condition": {
                "label": "End game by",
                "type": "select",
                "options": ["questions", "minutes"],
                "default": "questions"
            },
            "question_count": {
                "label": "Number of questions",
                "type": "number",
                "min": 10,
                "max": 200,
                "default": 10,
                "when": {"end_condition": "questions"}
            },
            "duration_minutes": {
                "label": "Duration in minutes",
                "type": "number",
                "min": 3,
                "max": 180,
                "default": 3,
                "when": {"end_condition": "minutes"}
            }
        }
    },
    "wolf_maker": {
        "name": "Wolf Maker 🐺",
        "description": "Coming soon.",
        "available": False,
        "min_players": 2,
        "max_players": 20,
        "settings": {}
    },
    "paper_io": {
        "name": "Paper.io",
        "description": "Coming soon.",
        "available": False,
        "min_players": 2,
        "max_players": 20,
        "settings": {}
    },
    "snake": {
        "name": "Snake",
        "description": "Coming soon.",
        "available": False,
        "min_players": 1,
        "max_players": 20,
        "settings": {}
    }
}


def get_game(game_slug):
    return GAMES.get(game_slug)


def get_game_list():
    return [
        {"slug": slug, **game}
        for slug, game in GAMES.items()
    ]


def validate_settings(game_slug, raw_settings):
    game = get_game(game_slug)

    if not game:
        raise ValueError("Unknown game.")

    if not game["available"]:
        raise ValueError("This game is not available yet.")

    cleaned = {}

    for key, definition in game["settings"].items():
        default = definition.get("default")
        value = raw_settings.get(key, default)

        # Only use values declared by this game's registry.
        if definition["type"] == "select":
            allowed = definition["options"]

            # HTML forms may submit numeric options as strings.
            matching = next(
                (
                    option for option in allowed
                    if str(option) == str(value)
                ),
                None
            )

            if matching is None:
                raise ValueError(f"Invalid value for {key}.")

            cleaned[key] = matching

        elif definition["type"] == "number":
            try:
                number = int(value)
            except (TypeError, ValueError):
                raise ValueError(f"{key} must be a number.")

            if not (
                definition.get("min", number)
                <= number
                <= definition.get("max", number)
            ):
                raise ValueError(f"{key} is outside its allowed range.")

            cleaned[key] = number

    # Validate settings that depend on other settings.
    if game_slug == "maths_trivia":
        if cleaned["end_condition"] == "questions":
            cleaned.pop("duration_minutes", None)
        else:
            cleaned.pop("question_count", None)

    return cleaned


@games_bp.route("/games/<game_slug>")
@login_required
def game_directory(game_slug):
    game = get_game(game_slug)

    if not game:
        abort(404)

    # Import here to avoid a circular import.
    import server as server_module

    return render_template(
        "games.html",
        game=game,
        game_slug=game_slug,
        games=get_game_list(),
        servers=server_module.list_servers(game_slug)
    )


@games_bp.route("/api/games")
@login_required
def api_games():
    return jsonify({"games": get_game_list()})


@games_bp.route("/api/leaderboard/<game_slug>")
@login_required
def api_leaderboard(game_slug):
    if game_slug not in GAMES:
        return jsonify({"error": "Unknown game."}), 404

    rows = database.get_leaderboard(game_slug, limit=50)
    return jsonify({"game": game_slug, "leaderboard": rows})