"""Discovery and validation for metadata-driven game plugins."""

from importlib import import_module
import re

from . import get_game_list


GAME_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,48}$")


def load_plugin(game):
    game_id = game.get("game_id", "")
    path = game.get("path", game_id)

    if not GAME_ID_RE.fullmatch(game_id) or not GAME_ID_RE.fullmatch(path):
        raise RuntimeError(f"Unsafe game id/path in metadata: {game_id!r}")

    module_name = game.get("plugin_module") or f"games.{path}.plugin"
    try:
        plugin = import_module(module_name)
    except Exception as exc:
        raise RuntimeError(
            f"Could not import plugin for '{game_id}' ({module_name})."
        ) from exc

    for required in ("start_match", "register_socket_events"):
        if not callable(getattr(plugin, required, None)):
            raise RuntimeError(
                f"Plugin '{game_id}' must define {required}(...)."
            )

    return plugin


def register_game_plugins(platform):
    """Load every available game and register its Socket.IO handlers."""
    loaded = {}
    for game in get_game_list(include_unavailable=False):
        plugin = load_plugin(game)
        platform.register_plugin(game["game_id"], plugin)
        plugin.register_socket_events(platform.socketio, platform)
        loaded[game["game_id"]] = plugin
    return loaded
