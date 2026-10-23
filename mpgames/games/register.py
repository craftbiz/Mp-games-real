
"""Load and validate game definitions from gamesmeta.json."""

import json
from pathlib import Path

METADATA_FILE = Path(__file__).resolve().parent / "gamesmeta.json"


def _read_metadata():
    try:
        with METADATA_FILE.open("r", encoding="utf-8") as file:
            games = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Unable to load game metadata: {METADATA_FILE}"
        ) from exc

    if not isinstance(games, list):
        raise RuntimeError("gamesmeta.json must contain a JSON list.")

    seen_ids = set()
    for game in games:
        if not isinstance(game, dict):
            raise RuntimeError("Every game entry must be a JSON object.")

        for key in ("game_name", "game_id", "path", "fields"):
            if key not in game:
                raise RuntimeError(f"Game metadata is missing '{key}'.")

        game_id = game["game_id"]
        if not isinstance(game_id, str) or not game_id.strip():
            raise RuntimeError("Every game must have a non-empty game_id.")

        if game_id in seen_ids:
            raise RuntimeError(f"Duplicate game_id: {game_id}")

        seen_ids.add(game_id)

        # Convert field definitions into the settings map used by the
        # existing room-creation and validation code.
        settings = {}
        for field in game.get("fields", []):
            field_id = field.get("id")
            if not field_id:
                raise RuntimeError(
                    f"Game '{game_id}' has a field without an id."
                )
            if field_id in settings:
                raise RuntimeError(
                    f"Duplicate field id '{field_id}' in '{game_id}'."
                )

            options = [
                value.strip()
                for value in str(field.get("values", "")).split(",")
                if value.strip()
            ]

            settings[field_id] = {
                **field,
                "options": options,
            }

        game["settings"] = settings

    return games


def get_game_list(include_unavailable=True):
    games = _read_metadata()
    if not include_unavailable:
        games = [game for game in games if game.get("available", False)]
    return games


def get_game(game_id):
    for game in get_game_list():
        if game["game_id"] == game_id:
            return game
    return None


def validate_settings(game, submitted):
    """Return normalized settings or raise ValueError."""
    if not isinstance(submitted, dict):
        raise ValueError("Settings must be an object.")

    definitions = game.get("settings", {})
    normalized = {}

    # Reject unknown keys instead of silently accepting misspelled settings.
    unknown = set(submitted) - set(definitions)
    if unknown:
        raise ValueError(
            "Unknown setting(s): " + ", ".join(sorted(unknown))
        )

    # Apply defaults and validate every declared setting.
    for key, field in definitions.items():
        should_show = field.get("show_when")
        if should_show:
            condition_field = should_show.get("field")
            expected = str(should_show.get("equals", ""))
            actual = str(submitted.get(
                condition_field,
                definitions.get(condition_field, {}).get("default", "")
            ))
            if actual != expected:
                continue

        value = submitted.get(key, field.get("default", ""))

        if field.get("type") == "drop-down":
            value = str(value)
            if value not in field.get("options", []):
                raise ValueError(
                    f"Invalid value for {field.get('name', key)}."
                )

        elif field.get("type") == "numerical_text":
            try:
                value = int(value)
            except (TypeError, ValueError):
                raise ValueError(
                    f"{field.get('name', key)} must be a whole number."
                )

            if "min" in field and value < int(field["min"]):
                raise ValueError(
                    f"{field.get('name', key)} must be at least "
                    f"{field['min']}."
                )

            if "max" in field and value > int(field["max"]):
                raise ValueError(
                    f"{field.get('name', key)} must be at most "
                    f"{field['max']}."
                )

        elif field.get("type") == "text":
            value = str(value).strip()
            if field.get("required", True) and not value:
                raise ValueError(
                    f"{field.get('name', key)} is required."
                )

        normalized[key] = value

    return normalized
