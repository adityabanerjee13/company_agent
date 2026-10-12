from apps.db import conn
from apps.slack import normalize


def upsert_channel(channel_id, channel_type):
    """Record a channel seen in a live event; the type only, the sync fills in names and the rest."""
    conn.execute(
        "INSERT INTO channels (channel_id, type) VALUES (?, ?) ON CONFLICT(channel_id) DO UPDATE SET type=COALESCE(excluded.type, channels.type)",
        (channel_id, channel_type),
    )
    conn.commit()


def upsert_conversation(c):
    """Record a full conversations.info / conversations.list object."""
    normalize.upsert_conversation(conn, c)
    conn.commit()
