import sqlite3

from apps.schema import init_schema

V1 = """
CREATE TABLE messages (
    ts TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL,
    thread_ts TEXT,
    user_id TEXT NOT NULL,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL,
    subtype TEXT,
    edited_at TEXT,
    files TEXT
);
CREATE INDEX messages_channel ON messages (channel_id, ts);
"""


def _pk(conn):
    return [c[1] for c in sorted(conn.execute("PRAGMA table_info(messages)"), key=lambda c: c[5]) if c[5]]


def test_v1_messages_are_copied_to_the_new_key(tmp_path):
    conn = sqlite3.connect(tmp_path / "agent.db")
    conn.executescript(V1)
    conn.executemany("INSERT INTO messages (ts, channel_id, thread_ts, user_id, text, created_at, edited_at) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?)",
                     [("1.1", "C1", None, "U1", "root", "t1", None),
                      ("1.2", "C1", "1.1", "U2", "reply", "t2", "e2"),
                      ("1.3", "D1", None, "bot", "hi", "t3", None)])
    conn.commit()

    init_schema(conn)
    assert _pk(conn) == ["channel_id", "ts"]
    assert conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 3
    assert conn.execute("SELECT text, thread_ts, edited_at FROM messages WHERE ts = '1.2'").fetchone() == ("reply", "1.1", "e2")
    assert conn.execute("SELECT COUNT(*) FROM visible_messages").fetchone()[0] == 3
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"

    init_schema(conn)  # runs on every start: the second time changes nothing
    assert conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 3
    conn.close()


def test_fresh_database_gets_the_new_shape(tmp_path):
    conn = sqlite3.connect(tmp_path / "agent.db")
    init_schema(conn)
    assert _pk(conn) == ["channel_id", "ts"]
    conn.close()
