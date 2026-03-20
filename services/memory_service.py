"""
Memory Service — SQLite for structured data (users, logs, goals, personality).
"""
import sqlite3
from datetime import datetime
from contextlib import contextmanager
import config


def _get_conn():
    conn = sqlite3.connect(str(config.SQLITE_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def _db():
    conn = _get_conn()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    """Create all tables if they don't exist."""
    with _db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                timezone TEXT DEFAULT 'Asia/Kolkata',
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS daily_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                date TEXT,
                content TEXT,
                mood TEXT,
                blockers TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            );

            CREATE TABLE IF NOT EXISTS goals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                title TEXT,
                description TEXT DEFAULT '',
                status TEXT DEFAULT 'active',
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            );

            CREATE TABLE IF NOT EXISTS personality_profiles (
                user_id INTEGER PRIMARY KEY,
                motivation_style TEXT DEFAULT '',
                thinking_style TEXT DEFAULT '',
                weakness_patterns TEXT DEFAULT '',
                energy_cycles TEXT DEFAULT '',
                work_habits TEXT DEFAULT '',
                summary TEXT DEFAULT '',
                updated_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            );

            CREATE TABLE IF NOT EXISTS streaks (
                user_id INTEGER PRIMARY KEY,
                current_streak INTEGER DEFAULT 0,
                longest_streak INTEGER DEFAULT 0,
                last_log_date TEXT,
                total_logs INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            );
        """)


# --- Users ---

def upsert_user(user_id: int, username: str = "", first_name: str = ""):
    with _db() as conn:
        conn.execute(
            """INSERT INTO users (user_id, username, first_name)
               VALUES (?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET username=?, first_name=?""",
            (user_id, username, first_name, username, first_name),
        )


def get_user(user_id: int) -> dict | None:
    with _db() as conn:
        row = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        return dict(row) if row else None


# --- Daily Logs ---

def save_log(user_id: int, content: str, mood: str = "", blockers: str = ""):
    today = datetime.now().strftime("%Y-%m-%d")
    with _db() as conn:
        conn.execute(
            "INSERT INTO daily_logs (user_id, date, content, mood, blockers) VALUES (?, ?, ?, ?, ?)",
            (user_id, today, content, mood, blockers),
        )
        # Update streak
        _update_streak(conn, user_id, today)


def get_recent_logs(user_id: int, days: int = 7) -> list[dict]:
    with _db() as conn:
        rows = conn.execute(
            """SELECT * FROM daily_logs WHERE user_id=?
               ORDER BY date DESC LIMIT ?""",
            (user_id, days),
        ).fetchall()
        return [dict(r) for r in rows]


def get_today_logs(user_id: int) -> list[dict]:
    today = datetime.now().strftime("%Y-%m-%d")
    with _db() as conn:
        rows = conn.execute(
            "SELECT * FROM daily_logs WHERE user_id=? AND date=?",
            (user_id, today),
        ).fetchall()
        return [dict(r) for r in rows]


# --- Goals ---

def save_goal(user_id: int, title: str, description: str = ""):
    with _db() as conn:
        conn.execute(
            "INSERT INTO goals (user_id, title, description) VALUES (?, ?, ?)",
            (user_id, title, description),
        )


def get_active_goals(user_id: int) -> list[dict]:
    with _db() as conn:
        rows = conn.execute(
            "SELECT * FROM goals WHERE user_id=? AND status='active' ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def complete_goal(user_id: int, goal_id: int):
    with _db() as conn:
        conn.execute(
            "UPDATE goals SET status='completed', updated_at=datetime('now') WHERE id=? AND user_id=?",
            (goal_id, user_id),
        )


# --- Personality ---

def get_personality(user_id: int) -> dict | None:
    with _db() as conn:
        row = conn.execute(
            "SELECT * FROM personality_profiles WHERE user_id=?", (user_id,)
        ).fetchone()
        return dict(row) if row else None


def save_personality(user_id: int, profile: dict):
    with _db() as conn:
        conn.execute(
            """INSERT INTO personality_profiles
               (user_id, motivation_style, thinking_style, weakness_patterns, energy_cycles, work_habits, summary, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(user_id) DO UPDATE SET
               motivation_style=?, thinking_style=?, weakness_patterns=?,
               energy_cycles=?, work_habits=?, summary=?, updated_at=datetime('now')""",
            (
                user_id,
                profile.get("motivation_style", ""),
                profile.get("thinking_style", ""),
                profile.get("weakness_patterns", ""),
                profile.get("energy_cycles", ""),
                profile.get("work_habits", ""),
                profile.get("summary", ""),
                profile.get("motivation_style", ""),
                profile.get("thinking_style", ""),
                profile.get("weakness_patterns", ""),
                profile.get("energy_cycles", ""),
                profile.get("work_habits", ""),
                profile.get("summary", ""),
            ),
        )


# --- Streaks ---

def _update_streak(conn, user_id: int, today: str):
    row = conn.execute("SELECT * FROM streaks WHERE user_id=?", (user_id,)).fetchone()
    if not row:
        conn.execute(
            "INSERT INTO streaks (user_id, current_streak, longest_streak, last_log_date, total_logs) VALUES (?, 1, 1, ?, 1)",
            (user_id, today),
        )
        return

    streak = dict(row)
    total = streak["total_logs"] + 1

    if streak["last_log_date"] == today:
        # Already logged today, just update total
        conn.execute("UPDATE streaks SET total_logs=? WHERE user_id=?", (total, user_id))
        return

    # Check if yesterday
    from datetime import timedelta
    yesterday = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    if streak["last_log_date"] == yesterday:
        new_streak = streak["current_streak"] + 1
    else:
        new_streak = 1

    longest = max(new_streak, streak["longest_streak"])
    conn.execute(
        "UPDATE streaks SET current_streak=?, longest_streak=?, last_log_date=?, total_logs=? WHERE user_id=?",
        (new_streak, longest, today, total, user_id),
    )


def get_streak(user_id: int) -> dict:
    with _db() as conn:
        row = conn.execute("SELECT * FROM streaks WHERE user_id=?", (user_id,)).fetchone()
        if row:
            return dict(row)
        return {"current_streak": 0, "longest_streak": 0, "total_logs": 0}


# --- All users (for scheduler) ---

def get_all_user_ids() -> list[int]:
    with _db() as conn:
        rows = conn.execute("SELECT user_id FROM users").fetchall()
        return [r["user_id"] for r in rows]
