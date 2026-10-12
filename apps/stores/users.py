import json
import os

from apps.config import SUBSCRIPTIONS_FILE
from apps.db import conn


def sync_from_file(path=SUBSCRIPTIONS_FILE):
    """Upsert every user in the subscriptions file into the users table."""
    if not os.path.exists(path):
        print(f"{path} not found - no users have a coding subscription")
        return 0
    with open(path, encoding="utf-8") as f:
        subscriptions = json.load(f)
    for slack_user_id, sub in subscriptions.items():
        if sub["provider"] == "codex":
            credential = json.dumps(sub["auth_json"])
        else:
            credential = sub["token"]
        conn.execute(
            "INSERT INTO users (slack_user_id, name, provider, credential) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(slack_user_id) DO UPDATE SET name=excluded.name, provider=excluded.provider, credential=excluded.credential",
            (slack_user_id, sub.get("name"), sub["provider"], credential),
        )
    conn.commit()
    return len(subscriptions)


def get_user(slack_user_id):
    row = conn.execute("SELECT * FROM users WHERE slack_user_id = ?", (slack_user_id,)).fetchone()
    return dict(row) if row else None
