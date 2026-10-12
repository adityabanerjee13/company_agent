"""Slack message and conversation JSON -> rows in agent.db.

Live events (apps/slack/app.py) and the catch-up sync (apps/slack/sync.py) both store through here, so a
message is saved the same way whichever path saw it first. Free of apps.config, so it can be tested alone.
"""
import json
from datetime import datetime, timezone

# message_changed/message_deleted are applied as edits and deletes, not stored as messages
SKIP_SUBTYPES = {"message_changed", "message_deleted", "message_replied"}


def _iso(ts):
    return datetime.fromtimestamp(float(ts), timezone.utc).isoformat() if ts else None


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def channel_type(c):
    if c.get("is_im"):
        return "im"
    if c.get("is_mpim"):
        return "mpim"
    if c.get("is_private") or c.get("is_group"):
        return "group"
    return "channel"


def to_row(channel_id, m, bot_user_id=None, bot_id=None):
    """A Slack message as a messages row, or None for messages that aren't stored."""
    if m.get("subtype") in SKIP_SUBTYPES or m.get("hidden"):
        return None
    user = m.get("user") or m.get("bot_id") or "unknown"
    if (bot_user_id and user == bot_user_id) or (bot_id and m.get("bot_id") == bot_id):
        user = "bot"  # same id the bot uses for its own replies
    thread_ts = m.get("thread_ts")
    if thread_ts == m["ts"]:
        thread_ts = None  # thread roots are stored without a thread_ts
    files = [{"name": f.get("name") or f.get("title"), "url": f.get("permalink")} for f in m.get("files") or []]
    return {
        "channel_id": channel_id, "ts": m["ts"], "thread_ts": thread_ts, "user_id": user,
        "text": m.get("text") or "", "created_at": _iso(m["ts"]), "subtype": m.get("subtype"),
        "edited_at": _iso((m.get("edited") or {}).get("ts")), "files": json.dumps(files) if files else None,
        "raw": json.dumps(m, ensure_ascii=False),
    }


def upsert(conn, row, keep_existing=False):
    """Insert or update a message. Returns 1 if anything visible changed, else 0.

    keep_existing: only fill in fields the stored row lacks. Used for the bot's own replies, which are
    saved before Slack echoes them back with the full JSON."""
    if keep_existing:
        cur = conn.execute("""
            INSERT INTO messages (channel_id, ts, thread_ts, user_id, text, created_at, updated_at)
            VALUES (:channel_id, :ts, :thread_ts, :user_id, :text, :created_at, :updated_at)
            ON CONFLICT(channel_id, ts) DO NOTHING""", {**row, "updated_at": _now_iso()})
        return cur.rowcount
    cur = conn.execute("""
        INSERT INTO messages (channel_id, ts, thread_ts, user_id, text, created_at, subtype, edited_at, files,
                              raw, updated_at)
        VALUES (:channel_id, :ts, :thread_ts, :user_id, :text, :created_at, :subtype, :edited_at, :files,
                :raw, :updated_at)
        ON CONFLICT(channel_id, ts) DO UPDATE SET text = excluded.text, thread_ts = excluded.thread_ts,
            subtype = excluded.subtype, edited_at = excluded.edited_at, files = excluded.files,
            raw = excluded.raw, updated_at = excluded.updated_at
        WHERE messages.text IS NOT excluded.text OR messages.thread_ts IS NOT excluded.thread_ts
           OR messages.edited_at IS NOT excluded.edited_at OR messages.files IS NOT excluded.files
           OR messages.subtype IS NOT excluded.subtype OR messages.raw IS NULL""",
        {**row, "updated_at": _now_iso()})
    return cur.rowcount


def mark_deleted(conn, channel_id, ts):
    cur = conn.execute("UPDATE messages SET deleted_at = ?, updated_at = ? "
                       "WHERE channel_id = ? AND ts = ? AND deleted_at IS NULL",
                       (_now_iso(), _now_iso(), channel_id, ts))
    return cur.rowcount


def apply_message_event(conn, event, bot_user_id=None, bot_id=None):
    """Apply one Slack `message` event of any subtype: a new message, an edit or a delete."""
    channel = event["channel"]
    subtype = event.get("subtype")
    if subtype == "message_deleted":
        changed = mark_deleted(conn, channel, event["deleted_ts"])
    elif subtype == "message_changed":
        m = event.get("message") or {}
        if m.get("subtype") == "tombstone":  # a deleted thread root that still has replies
            changed = mark_deleted(conn, channel, m["ts"])
        else:
            row = to_row(channel, m, bot_user_id, bot_id)
            changed = upsert(conn, row) if row else 0
    else:
        row = to_row(channel, event, bot_user_id, bot_id)
        changed = upsert(conn, row) if row else 0
    conn.commit()
    return changed


def upsert_conversation(conn, c):
    """A conversations.list / conversations.info object as a channels row."""
    conn.execute("""
        INSERT INTO channels (channel_id, type, name, is_member, is_private, dm_user_id, topic)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(channel_id) DO UPDATE SET type = excluded.type, name = excluded.name,
            is_member = excluded.is_member, is_private = excluded.is_private,
            dm_user_id = excluded.dm_user_id, topic = excluded.topic""",
        (c["id"], channel_type(c), c.get("name"),
         int(bool(c.get("is_member") or c.get("is_im") or c.get("is_mpim"))),
         int(bool(c.get("is_private") or c.get("is_im") or c.get("is_mpim"))),
         c.get("user"), ((c.get("topic") or {}).get("value") or (c.get("purpose") or {}).get("value"))))
