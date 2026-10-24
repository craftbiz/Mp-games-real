
"""Load and validate game definitions from gamesmeta.json."""

import json
from copy import deepcopy
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
                raise RuntimeError(
                    f"Game metadata is missing '{key}'."
                )

        game_id = game["game_id"]

        if not isinstance(game_id, str) or not game_id.strip():
            raise RuntimeError(
                "Every game must have a non-empty game_id."
            )

        if game_id in seen_ids:
            raise RuntimeError(f"Duplicate game_id: {game_id}")

        seen_ids.add(game_id)

        if not isinstance(game["fields"], list):
            raise RuntimeError(
                f"Game '{game_id}' fields must be a list."
            )

        settings = {}

        for field in game["fields"]:
            if not isinstance(field, dict):
                raise RuntimeError(
                    f"Invalid field definition in '{game_id}'."
                )

            field_id = field.get("id")

            if not isinstance(field_id, str) or not field_id:
                raise RuntimeError(
                    f"Game '{game_id}' has a field without an id."
                )

            if field_id in settings:
                raise RuntimeError(
                    f"Duplicate field id '{field_id}' in '{game_id}'."
                )

            field_type = field.get("type")

            if field_type not in (
                "drop-down",
                "numerical_text",
                "text",
            ):
                raise RuntimeError(
                    f"Unsupported field type '{field_type}' "
                    f"in game '{game_id}'."
                )

            options = [
                item.strip()
                for item in str(field.get("values", "")).split(",")
                if item.strip()
            ]

            settings[field_id] = {
                **field,
                "options": options,
            }

        game["settings"] = settings

    return games


def get_game_list(include_unavailable=True):
    games = deepcopy(_read_metadata())

    if not include_unavailable:
        games = [
            game for game in games
            if game.get("available", False)
        ]

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

    unknown = set(submitted) - set(definitions)

    if unknown:
        raise ValueError(
            "Unknown setting(s): " + ", ".join(sorted(unknown))
        )

    # Resolve conditional visibility before validating values.
    for key, field in definitions.items():
        condition = field.get("show_when")

        if condition:
            dependency = condition.get("field")
            expected = str(condition.get("equals", ""))

            dependency_field = definitions.get(dependency, {})
            actual = str(
                submitted.get(
                    dependency,
                    dependency_field.get("default", "")
                )
            )

            if actual != expected:
                continue

        value = submitted.get(key, field.get("default", ""))

        if field["type"] == "drop-down":
            value = str(value)

            if value not in field.get("options", []):
                raise ValueError(
                    f"Invalid value for {field.get('name', key)}."
                )

        elif field["type"] == "numerical_text":
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

        elif field["type"] == "text":
            value = str(value).strip()

            if field.get("required", True) and not value:
                raise ValueError(
                    f"{field.get('name', key)} is required."
                )

        normalized[key] = value

    return normalized
