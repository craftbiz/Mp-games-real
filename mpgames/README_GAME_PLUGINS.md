# MPGames Game Plugin Developer Guide

This guide defines the supported way to add a new multiplayer game to MPGames.
It is written so a developer or another AI assistant can build a compatible game
without modifying the shared lobby/server code.

## 1. The architecture

MPGames owns shared platform services:

- login/session identity and room membership;
- room creation, player limits, lobby chat, owner-start permissions;
- the secure lobby-to-gameplay handoff;
- the Socket.IO connection and authenticated player session;
- result persistence and the shared leaderboard.

Each game plugin owns its actual gameplay:

- game rules, round/match state, timers and scoring;
- validation of game actions;
- game-specific Socket.IO events;
- its browser JavaScript and CSS;
- deciding when the match is complete and what each player scored.

A game page is rendered at:

`/gameplay.html/<room-id>&<game-id>?handoff=<one-time-token>`

The shared runtime verifies the one-time handoff before the game page starts receiving gameplay events. Do not create your own login or room-join flow.

**The game engine must be authoritative on the server.** Browser JavaScript may display the game and send player actions, but it must not decide final scores or call the database directly.

## 2. Files and folders

For a game called `space_race`, add:

```text
mpgames/
  games/
    gamesmeta.json
    platform_api.py                 # shared trusted platform API; do not edit per game
    plugin_loader.py              # metadata-driven plugin loader; do not edit per game
    space_race/
      __init__.py
      plugin.py                   # required adapter / Socket.IO handlers
      engine.py                   # game rules and authoritative state
      static/
        space_race.js             # browser UI
        space_race.css            # browser styling
```

`__init__.py` may be empty. The page template and browser connection runtime are shared; you do not need a per-game HTML template.

If the game needs additional Python packages, add them to the project's root `requirements.txt`. A dependency placed in a game folder is **not** automatically installed by Python or Render.

## 3. Register the game in gamesmeta.json

Add one object to the existing JSON list. Example:

```json
{
  "game_name": "Space Race",
  "game_id": "space_race",
  "path": "space_race",
  "plugin_module": "games.space_race.plugin",
  "available": true,
  "min_players": 2,
  "max_players": 8,
  "assets": {
    "js": "space_race.js",
    "css": "space_race.css"
  },
  "fields": [
    {
      "id": "rounds",
      "name": "Rounds",
      "type": "numerical_text",
      "default": 5,
      "min": 1,
      "max": 30
    },
    {
      "id": "difficulty",
      "name": "Difficulty",
      "type": "drop-down",
      "values": "easy,normal,hard",
      "default": "normal"
    }
  ],
  "rule_book_compact": [
    "Reach the finish first.",
    "The server validates every move."
  ],
  "rule_book_detailed": []
}
```

Rules:

- `game_id`: unique lowercase ID using letters, numbers and underscores; start with a letter. Use the same ID for the folder and event-name prefix.
- `path`: the plugin folder name. It must be a safe simple name, not a path such as `../something`.
- `plugin_module`: optional; if omitted, the loader imports `games.<path>.plugin`.
- `available`: set to `true` only when the plugin is complete and tested. Keep unfinished entries `false`.
- `min_players` and `max_players`: valid room-size limits.
- `assets.js`: JavaScript filename inside `games/<path>/static/`.
- `assets.css`: CSS filename inside `games/<path>/static/`.
- `fields`: room-setting definitions. Supported field types are `drop-down`, `numerical_text`, and `text`. For dropdowns, `values` is a comma-separated string. `default` must be one of those values.
- `rule_book_compact` and `rule_book_detailed`: the lobby's short and detailed rulebook content.

Do not duplicate a `game_id`. Keep the JSON valid. The registry creates the room settings form from `fields`.

## 4. Required server-side plugin interface

Every available plugin must export these two callables from `plugin.py`:

```python
def start_match(platform, server_id):
    ...

def register_socket_events(socketio, platform):
    ...
```

### `start_match(platform, server_id)`

Called once by the shared server after the room owner starts the match and all normal start checks pass.

It should:

1. Read the room and its validated settings from `platform.rooms[server_id]`.
2. Initialize authoritative game state in that room, usually under a unique key such as `room["_space_race"]`.
3. Snapshot the participants from `room["players"]`.
4. Start a background task if the game needs a loop or timer, using `platform.socketio.start_background_task(...)`.
5. Return `True` after successful initialization. Return `False` or raise an exception if it cannot start.

Do not create a second room system. Do not trust player IDs, settings, scores, or room IDs sent by the browser without checking them against the server's room/session data.

### `register_socket_events(socketio, platform)`

Register the game-specific Socket.IO event handlers. Use unique event names prefixed with the game ID, for example:

- `space_race:move`
- `space_race:ready`
- `space_race:action`

The existing Maths Trivia example uses the underscore event `maths_trivia_answer`; either naming style works, but be consistent and avoid collisions with shared platform event names.

In every action handler:

1. Get `user_id` from Flask's authenticated `session`, not from the event payload.
2. Get the room ID from `platform.server_for_sid(request.sid)`.
3. Confirm `platform.get_player(server_id, user_id, request.sid)` returns a player.
4. Confirm the room's `game_slug` matches your game ID and the match is still active.
5. Validate the action against server-side state.
6. Emit results only to the relevant room/player using `platform.emit(...)` or `socketio.emit(...)`.

Use `from flask import request, session` and `from flask_socketio import emit` where needed.

## 5. Shared platform API available to plugins

The `platform` argument is a `GamePlatform` instance.

| API | Use |
|---|---|
| `platform.socketio` | The initialized Flask-SocketIO instance |
| `platform.rooms` | The server's in-memory room dictionary; protect reads/writes with `platform.lock` |
| `platform.lock` | Shared re-entrant lock for room/game state |
| `platform.get_room(server_id)` | Get the internal room record; treat it as server-owned state |
| `platform.get_player(server_id, user_id, sid=None)` | Get a player; when `sid` is provided, it must match the current authenticated socket |
| `platform.server_for_sid(sid)` | Find the room associated with a connected socket |
| `platform.emit(event, payload, server_id)` | Broadcast a Socket.IO event to a specific room |
| `platform.submit_results(server_id, results, match_data=None)` | Persist trusted results and update the main leaderboard |

### Submitting results

Call `platform.submit_results(...)` from trusted Python engine code only when the match is over:

```python
platform.submit_results(
    server_id,
    [
        {
            "user_id": "server-known-user-id",
            "score": 120,
            "data": {"rounds_won": 4, "place": 1}
        },
        {
            "user_id": "another-server-known-user-id",
            "score": 75,
            "data": {"rounds_won": 2, "place": 2}
        }
    ],
    {"reason": "normal_finish", "rounds_played": 5}
)
```

This is a schema example, not real user IDs. Build the list from the server's own match state, not from client-submitted scores.

`submit_results` checks that each result belongs to a participant in that room, rejects duplicate user IDs and invalid scores, saves each result using `database.record_result`, updates the shared highest-score leaderboard, marks the room completed, and emits `platform_match_finished`.

The current database stores the latest result per user/game in `GameResults`, while `Leaderboard` keeps the highest score per user/game. If a future game needs a full match-by-match history, that database schema will need a separate match ID column/table.

## 6. Browser contract

The shared gameplay template automatically loads:

1. `/static/js/game-runtime.js`
2. the game JS specified by `assets.js`
3. the game's CSS specified by `assets.css`

The shared runtime creates `window.MPGamesGame` with:

- `socket`: the authenticated Socket.IO socket;
- `serverId`, `gameId`, `userId`;
- `ready`: true only after the server accepts the one-time gameplay handoff;
- `emit(eventName, payload)`: emit a game event only after the handoff succeeds;
- `showError(message)` and `clearError()`.

Your JS should start with a guard like:

```javascript
"use strict";

(() => {
  const game = window.MPGamesGame;
  if (!game || game.gameId !== "space_race") return;

  const socket = game.socket;

  window.addEventListener("mpgames:ready", event => {
    // The authenticated gameplay socket has joined the room.
    // Render the initial UI or request the initial game state here.
  });

  socket.on("space_race:state", state => {
    // Render server-authoritative state safely.
  });

  // Example: game.emit("space_race:move", { direction: "left" });
})();
```

The runtime dispatches the browser event `mpgames:ready` after it receives `gameplay_joined`. Your game must not assume the socket is ready before that event. The server can send game events after players have completed the handoff, so attach listeners as soon as the JS loads.

Use `textContent` for player names/messages rather than inserting untrusted strings with `innerHTML`.

Do not add another Socket.IO connection or send `gameplay_join` yourself. The shared runtime owns the connection and secure handoff.

## 7. A minimal plugin.py outline

```python
from flask import request, session
from flask_socketio import emit

from . import engine

GAME_ID = "space_race"


def start_match(platform, server_id):
    return engine.start_match(platform, server_id)


def register_socket_events(socketio, platform):
    @socketio.on("space_race:move")
    def handle_move(data=None):
        user_id = session.get("user_id")
        server_id = platform.server_for_sid(request.sid)

        if not user_id or not server_id:
            emit("space_race:error", {"error": "Not authenticated"})
            return

        room = platform.get_room(server_id)
        player = platform.get_player(server_id, user_id, request.sid)

        if (
            not room
            or room.get("game_slug") != GAME_ID
            or room.get("status") != "playing"
            or not player
        ):
            emit("space_race:error", {"error": "Not an active player"})
            return

        error = engine.handle_move(platform, server_id, user_id, data or {})
        if error:
            emit("space_race:error", {"error": error})
```

This is a scaffold, not a complete game. Implement `engine.start_match` and `engine.handle_move` for the actual game.

## 8. Adding a game: exact checklist

1. Create `mpgames/games/<game_id>/`.
2. Add `__init__.py`, `plugin.py`, `engine.py`, and `static/<game_id>.js` plus optional CSS.
3. Add the game entry to `gamesmeta.json`.
4. Add any required Python dependencies to root `requirements.txt`.
5. Set `available` to `true` only when the plugin exports both required functions and its assets exist.
6. Deploy/restart the server. Plugins are discovered at process startup; editing JSON alone does not hot-reload a running process.
7. Check startup logs for plugin import errors.
8. Log in as two separate users, create a room, join it, and start the match.
9. Confirm all players redirect to the game page and see the same authoritative state.
10. Finish a test match; confirm `platform_match_finished` is received and `/api/leaderboard/<game_id>` shows the saved score.
11. Test invalid actions, duplicate actions, disconnection/reconnection and a second match.

For a game that requires new third-party server packages, changing only `gamesmeta.json` and the game folder is insufficient until those packages are included in `requirements.txt`. The goal is no edits to `main.py`, `server.py`, `platform_api.py`, or `plugin_loader.py` for normal new games.

## 9. Troubleshooting

- **Game does not appear:** check JSON syntax, `available: true`, unique ID and field definitions.
- **Server fails during startup:** check the Python traceback; an available game must have a valid `plugin.py` with both required functions.
- **404 for JS/CSS:** confirm the asset filename in metadata exactly matches a file in `games/<path>/static/`.
- **Game page says session invalid:** the one-time handoff token may have expired; return to the lobby and start/join a fresh match.
- **No game events:** check that the plugin registers the exact event name the browser emits/listens to.
- **Leaderboard not updated:** ensure the server engine calls `platform.submit_results` at match end and uses user IDs from its own state.
- **Score exploit:** never accept a final score from the browser. Validate every action and calculate results in the server-side engine.

## 10. Project compatibility notes

- The active registry is the `mpgames/games/` package. The legacy sibling file `mpgames/games.py` has been removed to avoid ambiguity.
- Rooms currently live in memory and are lost when the server process restarts.
- This guide describes the plugin contract implemented by this source bundle. Run the integration checklist before deploying it to a live server.
