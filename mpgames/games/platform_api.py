"""Trusted bridge between game plugins and the main MPGames platform."""

from __future__ import annotations

import math
import threading
from typing import Any

import database


class GamePlatform:
    """Services available to every server-side game plugin.

    Plugin engines may use ``rooms`` and ``lock`` for authoritative game state,
    but must never accept final scores directly from a browser.
    """

    def __init__(self, socketio, rooms, lock, sid_to_server):
        self.socketio = socketio
        self.rooms = rooms
        self.lock = lock
        self.sid_to_server = sid_to_server
        self.plugins = {}

    def register_plugin(self, game_id, plugin):
        self.plugins[str(game_id)] = plugin

    def get_room(self, server_id):
        with self.lock:
            return self.rooms.get(str(server_id))

    def get_player(self, server_id, user_id, sid=None):
        with self.lock:
            room = self.rooms.get(str(server_id))
            player = room.get("players", {}).get(str(user_id)) if room else None
            if not player:
                return None
            if sid is not None and player.get("sid") != sid:
                return None
            return dict(player)

    def server_for_sid(self, sid):
        return self.sid_to_server.get(sid)

    def emit(self, event, payload, server_id):
        """Emit an event only to the given room."""
        self.socketio.emit(str(event), payload or {}, to=str(server_id))

    def start_match(self, server_id):
        server_id = str(server_id)
        with self.lock:
            room = self.rooms.get(server_id)
            if not room:
                raise ValueError("Room no longer exists.")
            game_id = room["game_slug"]
            plugin = self.plugins.get(game_id)
            if not plugin:
                raise RuntimeError(
                    f"Game '{game_id}' has no loaded plugin."
                )
            if room.get("_plugin_start_called"):
                raise ValueError("This match has already been started.")
            room["_plugin_start_called"] = True

        try:
            result = plugin.start_match(self, server_id)
            if result is False:
                raise RuntimeError("The game engine refused to start.")
            return True
        except Exception:
            with self.lock:
                room = self.rooms.get(server_id)
                if room:
                    room["_plugin_start_called"] = False
            raise

    def submit_results(self, server_id, results, match_data=None):
        """Persist trusted engine results and update the shared leaderboard.

        ``results`` is an iterable of dictionaries:
        {"user_id": "...", "score": 123, "data": {...}}

        This method is intended for server-side plugin code only.
        """
        server_id = str(server_id)
        if not isinstance(results, (list, tuple)) or not results:
            raise ValueError("Results must be a non-empty list.")

        with self.lock:
            room = self.rooms.get(server_id)
            if not room:
                raise ValueError("Room no longer exists.")
            if room.get("_platform_results_saved"):
                return False

            game_id = str(room["game_slug"])
            allowed_users = set(room.get("_match_participant_ids", room.get("players", {}).keys()))
            normalized = []
            seen = set()

            for item in results:
                if not isinstance(item, dict):
                    raise ValueError("Every result must be an object.")

                user_id = str(item.get("user_id", ""))
                if not user_id or user_id not in allowed_users:
                    raise ValueError("A result references a non-player.")
                if user_id in seen:
                    raise ValueError("Duplicate player result.")
                seen.add(user_id)

                raw_score = item.get("score", 0)
                if isinstance(raw_score, bool):
                    raise ValueError("Score must be numeric.")
                try:
                    score_number = float(raw_score)
                except (TypeError, ValueError):
                    raise ValueError("Score must be numeric.")
                if not math.isfinite(score_number) or abs(score_number) > 1_000_000_000:
                    raise ValueError("Score is outside the allowed range.")

                detail = item.get("data", {})
                if not isinstance(detail, dict):
                    detail = {"value": str(detail)[:500]}
                normalized.append({
                    "user_id": user_id,
                    "score": int(score_number),
                    "data": detail,
                })

            # Mark before database writes to prevent duplicate concurrent saves.
            room["_platform_results_saved"] = True

        try:
            for item in normalized:
                payload = dict(item["data"])
                payload.update({
                    "match_id": server_id,
                    "game_slug": game_id,
                    "score": item["score"],
                    "match_data": match_data if isinstance(match_data, dict) else {},
                })
                database.record_result(
                    item["user_id"], game_id, item["score"], payload
                )
        except Exception:
            with self.lock:
                room = self.rooms.get(server_id)
                if room:
                    room["_platform_results_saved"] = False
            raise

        with self.lock:
            room = self.rooms.get(server_id)
            if room:
                room["status"] = "completed"
                room["finished_at"] = __import__("datetime").datetime.now(
                    __import__("datetime").timezone.utc
                ).isoformat()

        self.emit("platform_match_finished", {
            "game_slug": game_id,
            "server_id": server_id,
            "results": normalized,
            "match_data": match_data if isinstance(match_data, dict) else {},
        }, server_id)
        return True
