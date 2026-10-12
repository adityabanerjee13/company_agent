from datetime import datetime, timezone

from apps.db import conn
from apps.slack import normalize


def save_message(ts, channel_id, thread_ts, user_id, text):
    """Store a message the bot posted. Slack echoes it back as an event later, which fills in the full JSON;
    if the echo arrived first, this leaves that row as it is."""
    row = {"channel_id": channel_id, "ts": ts, "thread_ts": thread_ts if thread_ts != ts else None,
           "user_id": user_id, "text": text, "created_at": datetime.now(timezone.utc).isoformat()}
    normalize.upsert(conn, row, keep_existing=True)
    conn.commit()


def apply_event(event, bot_user_id=None, bot_id=None):
    """Store a live Slack `message` event: a new message, an edit or a delete."""
    return normalize.apply_message_event(conn, event, bot_user_id, bot_id)


def recent_messages(channel_id, limit):
    """The last `limit` messages of a channel or DM, oldest first."""
    rows = conn.execute(
        "SELECT * FROM visible_messages WHERE channel_id = ? ORDER BY ts DESC LIMIT ?", (channel_id, limit)
    ).fetchall()
    return [dict(r) for r in reversed(rows)]


def all_in_channel(channel_id):
    rows = conn.execute("SELECT * FROM visible_messages WHERE channel_id = ? ORDER BY ts", (channel_id,)).fetchall()
    return [dict(r) for r in rows]
