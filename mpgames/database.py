import os
import sqlite3
import secrets
from pathlib import Path
from contextlib import contextmanager
from datetime import datetime, timezone

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = os.environ.get(
    "DATABASE_PATH",
    str(DATA_DIR / "game_data.db")
)


def now_utc():
    return datetime.now(timezone.utc).isoformat()


def connect_db():
    conn = sqlite3.connect(
        DB_PATH,
        timeout=15,
        check_same_thread=False
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn


@contextmanager
def db_connection():
    conn = connect_db()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with db_connection() as db:
        db.execute("PRAGMA journal_mode = WAL")

        db.execute("""
            CREATE TABLE IF NOT EXISTS Users (
                user_id TEXT PRIMARY KEY,
                username TEXT NOT NULL COLLATE NOCASE UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS Leaderboard (
                user_id TEXT NOT NULL,
                game_slug TEXT NOT NULL,
                highest_score INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (user_id, game_slug),
                FOREIGN KEY (user_id)
                    REFERENCES Users(user_id)
                    ON DELETE CASCADE
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS GameResults (
                user_id TEXT NOT NULL,
                game_slug TEXT NOT NULL,
                score INTEGER NOT NULL DEFAULT 0,
                result_data TEXT NOT NULL DEFAULT '{}',
                played_at TEXT NOT NULL,
                PRIMARY KEY (user_id, game_slug),
                FOREIGN KEY (user_id)
                    REFERENCES Users(user_id)
                    ON DELETE CASCADE
            )
        """)

        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_leaderboard_game
            ON Leaderboard(game_slug, highest_score DESC)
        """)


def generate_user_id(db):
    for _ in range(100):
        candidate = f"{secrets.randbelow(100_000_000):08d}"
        exists = db.execute(
            "SELECT 1 FROM Users WHERE user_id = ?",
            (candidate,)
        ).fetchone()

        if not exists:
            return candidate

    raise RuntimeError("Could not generate a unique user ID.")


def create_user(username, password_hash):
    username = username.strip()

    if not 3 <= len(username) <= 24:
        raise ValueError("Username must be 3–24 characters.")

    if not all(ch.isalnum() or ch in "_-" for ch in username):
        raise ValueError(
            "Use only letters, numbers, underscores and hyphens."
        )

    with db_connection() as db:
        user_id = generate_user_id(db)

        db.execute("""
            INSERT INTO Users (
                user_id, username, password_hash, created_at
            )
            VALUES (?, ?, ?, ?)
        """, (user_id, username, password_hash, now_utc()))

    return get_user_by_id(user_id)


def get_user_by_username(username):
    with db_connection() as db:
        row = db.execute("""
            SELECT user_id, username, password_hash, created_at
            FROM Users
            WHERE username = ? COLLATE NOCASE
        """, (username.strip(),)).fetchone()

    return dict(row) if row else None


def get_user_by_id(user_id):
    with db_connection() as db:
        row = db.execute("""
            SELECT user_id, username, created_at
            FROM Users
            WHERE user_id = ?
        """, (str(user_id),)).fetchone()

    return dict(row) if row else None


def get_profile(user_id):
    with db_connection() as db:
        user = db.execute("""
            SELECT user_id, username, created_at
            FROM Users
            WHERE user_id = ?
        """, (str(user_id),)).fetchone()

        if not user:
            return None

        scores = db.execute("""
            SELECT game_slug, highest_score, updated_at
            FROM Leaderboard
            WHERE user_id = ?
            ORDER BY game_slug
        """, (str(user_id),)).fetchall()

    return {
        "user_id": user["user_id"],
        "username": user["username"],
        "created_at": user["created_at"],
        "highest_scores": {
            row["game_slug"]: row["highest_score"]
            for row in scores
        }
    }


def record_result(user_id, game_slug, score, result_data=None):
    import json

    score = int(score)
    played_at = now_utc()
    serialized = json.dumps(result_data or {})

    with db_connection() as db:
        user = db.execute(
            "SELECT 1 FROM Users WHERE user_id = ?",
            (str(user_id),)
        ).fetchone()

        if not user:
            raise ValueError("User does not exist.")

        db.execute("""
            INSERT INTO GameResults (
                user_id, game_slug, score, result_data, played_at
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id, game_slug) DO UPDATE SET
                score = excluded.score,
                result_data = excluded.result_data,
                played_at = excluded.played_at
        """, (
            str(user_id), game_slug, score, serialized, played_at
        ))

        db.execute("""
            INSERT INTO Leaderboard (
                user_id, game_slug, highest_score, updated_at
            )
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, game_slug) DO UPDATE SET
                highest_score = MAX(
                    Leaderboard.highest_score,
                    excluded.highest_score
                ),
                updated_at = CASE
                    WHEN excluded.highest_score >
                         Leaderboard.highest_score
                    THEN excluded.updated_at
                    ELSE Leaderboard.updated_at
                END
        """, (str(user_id), game_slug, score, played_at))


def get_latest_result(user_id, game_slug):
    with db_connection() as db:
        row = db.execute("""
            SELECT score, result_data, played_at
            FROM GameResults
            WHERE user_id = ? AND game_slug = ?
        """, (str(user_id), game_slug)).fetchone()

    return dict(row) if row else None


def get_leaderboard(game_slug, limit=50):
    with db_connection() as db:
        rows = db.execute("""
            SELECT
                Users.user_id,
                Users.username,
                Leaderboard.game_slug,
                Leaderboard.highest_score,
                Leaderboard.updated_at
            FROM Leaderboard
            JOIN Users ON Users.user_id = Leaderboard.user_id
            WHERE Leaderboard.game_slug = ?
            ORDER BY
                Leaderboard.highest_score DESC,
                Leaderboard.updated_at ASC,
                Users.username COLLATE NOCASE ASC
            LIMIT ?
        """, (game_slug, max(1, min(int(limit), 100)))).fetchall()

    return [dict(row) for row in rows]


# Initialize tables when this module is imported.
init_db()