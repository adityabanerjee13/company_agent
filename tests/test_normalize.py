import json
import os
import sqlite3

import pytest

from apps.schema import init_schema
from apps.slack import normalize

with open(os.path.join(os.path.dirname(__file__), "fixtures", "events.json"), encoding="utf-8") as f:
    EVENTS = json.load(f)

BOT = {"bot_user_id": "UBOT", "bot_id": "BBOT"}


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    init_schema(c)
    yield c
    c.close()


def apply(conn, name):
    return normalize.apply_message_event(conn, EVENTS[name], **BOT)


def row(conn, channel, ts):
    r = conn.execute("SELECT * FROM messages WHERE channel_id = ? AND ts = ?", (channel, ts)).fetchone()
    return dict(r) if r else None


def visible(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM visible_messages ORDER BY channel_id, ts")]


def test_new_message_and_reply(conn):
    assert apply(conn, "message") == 1
    assert apply(conn, "reply") == 1
    root, reply = row(conn, "C1", "1700000000.000100"), row(conn, "C1", "1700000050.000100")
    assert root["thread_ts"] is None and root["user_id"] == "U1" and root["raw"]
    assert reply["thread_ts"] == "1700000000.000100"


def test_same_event_twice_changes_nothing(conn):
    apply(conn, "message")
    assert apply(conn, "message") == 0


def test_edit_updates_text_and_edited_at(conn):
    apply(conn, "message")
    assert apply(conn, "message_changed") == 1
    r = row(conn, "C1", "1700000000.000100")
    assert r["text"] == "deploy is at 4pm"
    assert r["edited_at"] is not None


def test_delete_hides_but_keeps_the_row(conn):
    apply(conn, "message")
    apply(conn, "reply")
    assert apply(conn, "message_deleted") == 1
    assert row(conn, "C1", "1700000050.000100")["deleted_at"] is not None
    assert [m["ts"] for m in visible(conn)] == ["1700000000.000100"]
    # a late copy of the message (a sync page read before the delete) does not bring it back
    normalize.upsert(conn, normalize.to_row("C1", EVENTS["reply"]))
    assert row(conn, "C1", "1700000050.000100")["deleted_at"] is not None


def test_tombstone_marks_thread_root_deleted(conn):
    apply(conn, "message")
    apply(conn, "tombstone")
    r = row(conn, "C1", "1700000000.000100")
    assert r["deleted_at"] is not None
    assert r["text"] == "deploy is at 3pm"  # the tombstone text is not stored over it


def test_file_share_is_stored_with_files(conn):
    apply(conn, "file_share")
    files = json.loads(row(conn, "C1", "1700000400.000500")["files"])
    assert files == [{"name": "app.log", "url": "https://example.slack.com/files/F1"}]


def test_bot_own_message_is_stored_as_bot(conn):
    apply(conn, "bot_own")
    assert row(conn, "C1", "1700000500.000600")["user_id"] == "bot"


def test_bot_reply_saved_before_echo_gets_filled_in(conn):
    saved = {"channel_id": "C1", "ts": "1700000500.000600", "thread_ts": "1700000000.000100", "user_id": "bot",
             "text": "Coding job ab12 finished", "created_at": "2023-11-14T22:21:40+00:00"}
    normalize.upsert(conn, saved, keep_existing=True)
    assert row(conn, "C1", "1700000500.000600")["raw"] is None
    apply(conn, "bot_own")
    assert row(conn, "C1", "1700000500.000600")["raw"] is not None


def test_echo_before_bot_save_is_kept(conn):
    apply(conn, "bot_own")
    saved = {"channel_id": "C1", "ts": "1700000500.000600", "thread_ts": "1700000000.000100", "user_id": "bot",
             "text": "different", "created_at": "2023-11-14T22:21:40+00:00"}
    assert normalize.upsert(conn, saved, keep_existing=True) == 0
    assert row(conn, "C1", "1700000500.000600")["text"] == "Coding job ab12 finished"


def test_channel_join_is_stored(conn):
    # the dashboard shows joins and leaves, so they are stored as the sync always did
    apply(conn, "channel_join")
    assert row(conn, "C1", "1700000600.000700")["subtype"] == "channel_join"


def test_same_ts_in_two_channels_is_two_rows(conn):
    apply(conn, "message")
    apply(conn, "same_ts_other_channel")
    assert row(conn, "C1", "1700000000.000100")["text"] == "deploy is at 3pm"
    assert row(conn, "C2", "1700000000.000100")["text"] == "unrelated"


def test_visible_view_leaves_out_raw(conn):
    apply(conn, "message")
    assert "raw" not in visible(conn)[0]
