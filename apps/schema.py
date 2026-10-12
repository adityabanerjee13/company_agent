"""The SQLite schema. The bot is the only process that writes to agent.db; the dashboard reads it.

Kept free of apps.config so tests can build a database without the bot's secrets.
"""

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    slack_user_id TEXT PRIMARY KEY,
    name TEXT,
    provider TEXT NOT NULL,          -- "claude" | "codex"
    credential TEXT NOT NULL         -- claude: oauth token; codex: auth.json contents
);

CREATE TABLE IF NOT EXISTS channels (
    channel_id TEXT PRIMARY KEY,
    type TEXT                        -- slack channel_type: im | channel | group | mpim
);

-- slack ts is unique within a channel only, so the key is (channel_id, ts)
CREATE TABLE IF NOT EXISTS messages (
    channel_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    thread_ts TEXT,
    user_id TEXT NOT NULL,           -- "bot" for the bot's own replies
    text TEXT NOT NULL,
    created_at TEXT NOT NULL,
    subtype TEXT,                    -- slack subtype: bot_message, file_share, thread_broadcast, ...
    edited_at TEXT,
    files TEXT,                      -- JSON list of {name, url}
    deleted_at TEXT,                 -- set when the message is deleted in Slack; rows are never removed
    raw TEXT,                        -- the message JSON as Slack sent it
    updated_at TEXT,
    PRIMARY KEY (channel_id, ts)
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    repo TEXT NOT NULL,
    base_branch TEXT NOT NULL,
    task TEXT NOT NULL,
    issue_url TEXT,
    status TEXT NOT NULL,            -- queued | running | succeeded | failed
    pr_url TEXT,
    error TEXT,
    channel_id TEXT NOT NULL,
    thread_ts TEXT NOT NULL,
    created_at TEXT NOT NULL,
    finished_at TEXT
);

-- filled by the bot's Slack sync (apps/slack/sync.py): workspace members and bots, for display names
CREATE TABLE IF NOT EXISTS slack_users (
    user_id TEXT PRIMARY KEY,        -- U... for people and bot users, B... for bots without a user
    name TEXT,
    real_name TEXT,
    display_name TEXT,
    is_bot INTEGER NOT NULL DEFAULT 0,
    deleted INTEGER NOT NULL DEFAULT 0,
    avatar TEXT,
    updated_at TEXT
);

-- sync bookkeeping: per-conversation cursors, workspace facts (bot user id, team) and sync_status
CREATE TABLE IF NOT EXISTS sync_state (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

# columns added after the first release, applied to existing databases
CHANNEL_COLUMNS = {
    "name": "TEXT",                  # slack channel name
    "is_member": "INTEGER",          # whether the syncing token can read it
    "is_private": "INTEGER",
    "dm_user_id": "TEXT",            # the other person in a 1:1 DM
    "topic": "TEXT",
}
MESSAGE_FIELDS = ("channel_id", "ts", "thread_ts", "user_id", "text", "created_at", "subtype", "edited_at",
                  "files", "deleted_at", "raw", "updated_at")


def connect_pragmas(conn):
    """Settings every connection needs: wait for a lock instead of failing, and the cheaper WAL sync level."""
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA synchronous = NORMAL")


def _add_columns(conn, table, columns):
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    for name, kind in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")


def _migrate_messages(conn):
    """Databases from before (channel_id, ts) was the key had ts alone: copy them into the new shape."""
    cols = conn.execute("PRAGMA table_info(messages)").fetchall()
    if [c[1] for c in cols if c[5]] != ["ts"]:
        return
    shared = ", ".join(f for f in MESSAGE_FIELDS if f in {c[1] for c in cols})
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("DROP TABLE IF EXISTS messages_v2")
        create = SCHEMA[SCHEMA.index("CREATE TABLE IF NOT EXISTS messages"):]
        create = create[:create.index(");") + 2].replace("IF NOT EXISTS messages", "messages_v2")
        conn.execute(create)
        conn.execute(f"INSERT INTO messages_v2 ({shared}) SELECT {shared} FROM messages")
        conn.execute("DROP TABLE messages")
        conn.execute("ALTER TABLE messages_v2 RENAME TO messages")
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def init_schema(conn):
    conn.execute("PRAGMA journal_mode = WAL")  # stored in the file: readers no longer block the writer
    conn.executescript(SCHEMA)
    _add_columns(conn, "channels", CHANNEL_COLUMNS)
    _migrate_messages(conn)
    conn.execute("DROP INDEX IF EXISTS messages_channel")  # covered by the primary key
    conn.execute("CREATE INDEX IF NOT EXISTS messages_thread ON messages (channel_id, thread_ts)")
    conn.execute("CREATE INDEX IF NOT EXISTS messages_updated ON messages (updated_at)")  # dashboard change check
    # what every reader should use: deleted messages are kept but hidden, and the raw JSON is left out
    conn.execute("DROP VIEW IF EXISTS visible_messages")
    visible = ", ".join(f for f in MESSAGE_FIELDS if f != "raw")
    conn.execute(f"CREATE VIEW visible_messages AS SELECT {visible} FROM messages WHERE deleted_at IS NULL")
    conn.commit()
