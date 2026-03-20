"""
Memory Service — Google Firestore for cloud-native persistence.
Replacing SQLite to enable 24/7 hosting on Cloud Run.
"""
from datetime import datetime, timedelta
from google.cloud import firestore
import config
import logging

logger = logging.getLogger(__name__)

# Initialize Firestore client
# This will use GOOGLE_APPLICATION_CREDENTIALS locally,
# or the default service account when running on Cloud Run.
db = firestore.Client(project=config.GOOGLE_CLOUD_PROJECT)

def init_db():
    """Firestore is schemaless; no explicit init needed."""
    logger.info("Firestore memory service initialized.")

# --- Users ---

def upsert_user(user_id: int, username: str = "", first_name: str = ""):
    doc_ref = db.collection("users").document(str(user_id))
    doc_ref.set({
        "user_id": user_id,
        "username": username,
        "first_name": first_name,
        "updated_at": firestore.SERVER_TIMESTAMP
    }, merge=True)

def get_user(user_id: int) -> dict | None:
    doc = db.collection("users").document(str(user_id)).get()
    return doc.to_dict() if doc.exists else None

# --- Daily Logs ---

def save_log(user_id: int, content: str, mood: str = "", blockers: str = ""):
    today = datetime.now().strftime("%Y-%m-%d")
    log_data = {
        "user_id": user_id,
        "date": today,
        "content": content,
        "mood": mood,
        "blockers": blockers,
        "created_at": firestore.SERVER_TIMESTAMP
    }
    db.collection("daily_logs").add(log_data)
    # Update streak
    _update_streak(user_id, today)

def get_recent_logs(user_id: int, days: int = 7) -> list[dict]:
    query = db.collection("daily_logs")\
            .where("user_id", "==", user_id)\
            .order_by("date", direction=firestore.Query.DESCENDING)\
            .limit(days)
    return [doc.to_dict() for doc in query.stream()]

def get_today_logs(user_id: int) -> list[dict]:
    today = datetime.now().strftime("%Y-%m-%d")
    query = db.collection("daily_logs")\
            .where("user_id", "==", user_id)\
            .where("date", "==", today)
    return [doc.to_dict() for doc in query.stream()]

# --- Goals ---

def save_goal(user_id: int, title: str, description: str = ""):
    goal_data = {
        "user_id": user_id,
        "title": title,
        "description": description,
        "status": "active",
        "created_at": firestore.SERVER_TIMESTAMP,
        "updated_at": firestore.SERVER_TIMESTAMP
    }
    db.collection("goals").add(goal_data)

def get_active_goals(user_id: int) -> list[dict]:
    query = db.collection("goals")\
            .where("user_id", "==", user_id)\
            .where("status", "==", "active")\
            .order_by("created_at", direction=firestore.Query.DESCENDING)
    return [doc.to_dict() for doc in query.stream()]

def complete_goal(user_id: int, goal_id: str):
    # Note: In Firestore, goal_id is likely a string (the auto-id)
    doc_ref = db.collection("goals").document(goal_id)
    doc_ref.update({
        "status": "completed",
        "updated_at": firestore.SERVER_TIMESTAMP
    })

# --- Personality ---

def get_personality(user_id: int) -> dict | None:
    doc = db.collection("personality_profiles").document(str(user_id)).get()
    return doc.to_dict() if doc.exists else None

def save_personality(user_id: int, profile: dict):
    doc_ref = db.collection("personality_profiles").document(str(user_id))
    profile["updated_at"] = firestore.SERVER_TIMESTAMP
    doc_ref.set(profile, merge=True)

# --- Streaks ---

def _update_streak(user_id: int, today: str):
    doc_ref = db.collection("streaks").document(str(user_id))
    doc = doc_ref.get()

    if not doc.exists:
        doc_ref.set({
            "user_id": user_id,
            "current_streak": 1,
            "longest_streak": 1,
            "last_log_date": today,
            "total_logs": 1
        })
        return

    streak = doc.to_dict()
    total = streak.get("total_logs", 0) + 1

    if streak["last_log_date"] == today:
        doc_ref.update({"total_logs": total})
        return

    yesterday = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    if streak["last_log_date"] == yesterday:
        new_streak = streak["current_streak"] + 1
    else:
        new_streak = 1

    longest = max(new_streak, streak.get("longest_streak", 0))
    doc_ref.update({
        "current_streak": new_streak,
        "longest_streak": longest,
        "last_log_date": today,
        "total_logs": total
    })

def get_streak(user_id: int) -> dict:
    doc = db.collection("streaks").document(str(user_id)).get()
    if doc.exists:
        return doc.to_dict()
    return {"current_streak": 0, "longest_streak": 0, "total_logs": 0}

# --- All users (for scheduler) ---

def get_all_user_ids() -> list[int]:
    # In a large-scale bot, we'd use a better way than streaming all users,
    # but for a personal bot, this is fine.
    docs = db.collection("users").stream()
    return [int(doc.id) for doc in docs]
