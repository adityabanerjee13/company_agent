"""Catch-up sync: fills in whatever the live events missed, inside the bot process.

Live events (apps/slack/app.py) store messages, edits and deletes as they happen. They are lost while the
bot is stopped or reconnecting, so this pass re-reads Slack through the Web API: once at startup, then every
SLACK_SYNC_INTERVAL_SECONDS. It also brings in history from before the bot started, workspace members
(for display names) and channel names. Once a day it checks the last SLACK_PRUNE_DAYS for deleted messages.

It polls instead of opening a second Socket Mode connection: Slack spreads events across all connections
of an app, so a second connection would take events away from the bot.

Token: SLACK_USER_TOKEN (xoxp) if set, else SLACK_BOT_TOKEN. A bot token reads only channels the bot is
in and DMs with the bot; a user token reads everything that user can see, including DMs between people.

The dashboard shows `status`, which is saved to sync_state['sync_status'] as JSON.
"""
import asyncio
import json
import logging
import time
from datetime import datetime, timezone

from slack_sdk.errors import SlackApiError
from slack_sdk.http_retry.builtin_async_handlers import AsyncRateLimitErrorRetryHandler
from slack_sdk.web.async_client import AsyncWebClient

from apps import db
from apps.db import conn
from apps.slack import normalize

log = logging.getLogger(__name__)

CONVERSATION_TYPES = ("public_channel", "private_channel", "mpim", "im")
USERS_REFRESH_S = 600
STATUS_WRITE_S = 1.0


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


# ---------- db (run through db.read / db.write) ----------

def _get_state(key):
    row = conn.execute("SELECT value FROM sync_state WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def _set_states(values):
    for key, value in values.items():
        conn.execute("INSERT INTO sync_state (key, value) VALUES (?, ?) "
                     "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))
    conn.commit()


def _save_users(users):
    for u in users:
        p = u.get("profile") or {}
        conn.execute("""
            INSERT INTO slack_users (user_id, name, real_name, display_name, is_bot, deleted, avatar, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET name = excluded.name, real_name = excluded.real_name,
                display_name = excluded.display_name, is_bot = excluded.is_bot, deleted = excluded.deleted,
                avatar = excluded.avatar, updated_at = excluded.updated_at""",
            (u["id"], u.get("name"), u.get("real_name") or p.get("real_name"), p.get("display_name"),
             int(bool(u.get("is_bot") or u["id"] == "USLACKBOT")), int(bool(u.get("deleted"))),
             p.get("image_72"), _now_iso()))
        # bot users also post under their B... bot id
        if p.get("bot_id"):
            conn.execute("""INSERT INTO slack_users (user_id, name, real_name, is_bot, updated_at)
                            VALUES (?, ?, ?, 1, ?) ON CONFLICT(user_id) DO UPDATE SET
                            name = excluded.name, real_name = excluded.real_name""",
                         (p["bot_id"], u.get("name"), u.get("real_name"), _now_iso()))
    conn.commit()


def _save_channels(convs):
    for c in convs:
        normalize.upsert_conversation(conn, c)
    conn.commit()


def _first_run(channel_ids):
    return not any(_get_state(f"cursor:{cid}") for cid in channel_ids)


def _save_messages(channel_id, messages, bot_user_id, bot_id):
    """Store history or replies. Bot-posted messages that carry a bot_profile also name their bot."""
    changed = 0
    for m in messages:
        if m.get("bot_id") and not m.get("user") and m.get("bot_profile"):
            conn.execute("INSERT OR IGNORE INTO slack_users (user_id, name, real_name, is_bot, updated_at) "
                         "VALUES (?, ?, ?, 1, ?)", (m["bot_id"], m["bot_profile"].get("name"),
                                                    m["bot_profile"].get("name"), _now_iso()))
        row = normalize.to_row(channel_id, m, bot_user_id, bot_id)
        if row:
            changed += normalize.upsert(conn, row)
    conn.commit()
    return changed


def _save_history(channel_id, messages, cursor, bot_user_id, bot_id):
    """Store a page of channel history; returns (changed, parents whose threads have new replies)."""
    changed = _save_messages(channel_id, messages, bot_user_id, bot_id)
    threads = []
    for m in messages:
        if m.get("reply_count") and m.get("latest_reply"):
            seen = _get_state(f"thread:{channel_id}:{m['ts']}")
            if seen is None or float(m["latest_reply"]) > float(seen):
                threads.append(m)
    if messages:
        _set_states({f"cursor:{channel_id}": max(messages, key=lambda m: float(m["ts"]))["ts"]})
    elif cursor is None:
        _set_states({f"cursor:{channel_id}": "0"})
    return changed, threads


def _save_thread(channel_id, parent_ts, latest_reply, replies, complete, bot_user_id, bot_id):
    """Store a thread's replies. When `complete` (every reply was fetched), stored replies Slack no longer
    returns were deleted."""
    changed = _save_messages(channel_id, replies, bot_user_id, bot_id)
    if complete:
        present = {r["ts"] for r in replies}
        stored = conn.execute("SELECT ts FROM messages WHERE channel_id = ? AND thread_ts = ? AND deleted_at IS NULL",
                              (channel_id, parent_ts)).fetchall()
        for r in stored:
            if r["ts"] not in present and r["ts"] != parent_ts:
                changed += normalize.mark_deleted(conn, channel_id, r["ts"])
    if latest_reply:
        _set_states({f"thread:{channel_id}:{parent_ts}": latest_reply})
    conn.commit()
    return changed


def _active_threads(channel_ids, since_ts):
    """Threads with a stored reply since `since_ts`, and the newest reply stored for each."""
    if not channel_ids:
        return []
    marks = ",".join("?" * len(channel_ids))
    rows = conn.execute(f"""
        SELECT channel_id, thread_ts, MAX(ts) AS last_ts FROM messages
        WHERE thread_ts IS NOT NULL AND channel_id IN ({marks})
        GROUP BY channel_id, thread_ts HAVING CAST(MAX(ts) AS REAL) >= ?""", (*channel_ids, since_ts)).fetchall()
    return [dict(r) for r in rows]


def _prune_top_level(channel_id, oldest, present):
    """Mark deleted the stored top-level messages since `oldest` that Slack's history no longer has."""
    rows = conn.execute("""SELECT ts FROM messages WHERE channel_id = ? AND thread_ts IS NULL
                           AND deleted_at IS NULL AND CAST(ts AS REAL) >= ?""", (channel_id, oldest)).fetchall()
    changed = sum(normalize.mark_deleted(conn, channel_id, r["ts"]) for r in rows if r["ts"] not in present)
    conn.commit()
    return changed


class SlackSync:
    def __init__(self, bot_token, user_token=None, interval_s=300, lookback_hours=24,
                 prune_days=30, prune_interval_hours=24):
        self.interval_s = interval_s
        self.lookback_s = lookback_hours * 3600
        self.prune_s = prune_days * 86400
        self.prune_interval_s = prune_interval_hours * 3600
        self.token = user_token or bot_token
        self.token_kind = "user" if user_token else "bot"
        retry = [AsyncRateLimitErrorRetryHandler(max_retry_count=6)]
        self.client = AsyncWebClient(token=self.token, retry_handlers=retry) if self.token else None
        self.bot_client = AsyncWebClient(token=bot_token, retry_handlers=retry) if bot_token else None
        self.bot_user_id = None
        self.bot_id = None
        self._users_synced_at = 0
        self._status_written_at = 0
        self._started = False
        self.status = {
            "state": "disabled" if not self.token else "starting",
            "token": self.token_kind if self.token else None,
            "team": None,
            "last_sync_at": None,
            "last_duration_s": None,
            "next_sync_at": None,
            "progress": None,
            "conversations": 0,
            "readable": 0,
            "warnings": [],
            "error": None if self.token else "Set SLACK_BOT_TOKEN (or SLACK_USER_TOKEN) to sync Slack.",
        }

    # ---------- lifecycle ----------

    async def _set_status(self, force=False, **changes):
        """Update the status the dashboard shows. Progress updates are written at most once a second."""
        self.status.update(changes)
        if force or time.monotonic() - self._status_written_at >= STATUS_WRITE_S:
            self._status_written_at = time.monotonic()
            await db.write(_set_states, {"sync_status": json.dumps(self.status)})

    async def run(self):
        if not self.client:
            await self._set_status(force=True, state="disabled")
            return
        while True:
            started = time.monotonic()
            try:
                await self.sync_once()
                self.status["error"] = None
            except asyncio.CancelledError:
                raise
            except Exception as e:  # keep polling; the error is shown in the dashboard
                log.exception("slack sync failed")
                self.status.update(state="error", error=f"{type(e).__name__}: {e}")
            next_at = time.time() + self.interval_s
            await self._set_status(
                force=True, state="idle" if self.status["state"] != "error" else "error",
                last_sync_at=_now_iso(), last_duration_s=round(time.monotonic() - started, 1),
                next_sync_at=datetime.fromtimestamp(next_at, timezone.utc).isoformat(), progress=None)
            await asyncio.sleep(self.interval_s)

    # ---------- one pass ----------

    async def sync_once(self):
        warnings = []
        if not self.bot_user_id:
            await self._identify()
        if time.time() - self._users_synced_at > USERS_REFRESH_S:
            await self._sync_users(warnings)
        convs = await self._list_conversations(warnings)
        readable = [c for c in convs if c.get("is_member") or c.get("is_im") or c.get("is_mpim")]
        skipped = [c for c in convs if c not in readable]
        if skipped:
            names = ", ".join(f"#{c.get('name')}" for c in skipped[:8])
            more = f" and {len(skipped) - 8} more" if len(skipped) > 8 else ""
            warnings.append(f"Not a member of {len(skipped)} channel(s): {names}{more}. "
                            "Invite the bot there, or set SLACK_USER_TOKEN to read them.")

        await db.write(_save_channels, convs)
        first_run = await db.read(_first_run, [c["id"] for c in readable])

        await self._set_status(force=True, state="backfilling" if first_run else "syncing",
                               conversations=len(convs), readable=len(readable), warnings=warnings)
        fetched = set()  # (channel, thread_ts) of threads re-read in full during this pass
        for i, c in enumerate(readable):
            await self._set_status(progress={"done": i, "total": len(readable), "current": self._label(c)})
            try:
                await self._sync_conversation(c, fetched)
            except SlackApiError as e:
                warnings.append(f"{self._label(c)}: {e.response.get('error')}")

        # replies to threads older than the lookback window: only the startup pass and the daily pass look
        last_prune = float(await db.read(_get_state, "pruned_at") or 0)
        daily = time.time() - last_prune >= self.prune_interval_s
        if not self._started or daily:
            await self._rescan_threads(readable, fetched, warnings)
        if daily:
            await self._prune(readable, warnings)
            await db.write(_set_states, {"pruned_at": str(time.time())})
        self._started = True
        self.status["warnings"] = warnings

    async def _identify(self):
        if self.bot_client:
            me = await self.bot_client.auth_test()
            self.bot_user_id, self.bot_id = me.get("user_id"), me.get("bot_id")
            self.status["team"] = me.get("team")
        if self.token_kind == "user":
            me = await self.client.auth_test()
            self.status["team"] = me.get("team")
        await db.write(_set_states, {k: v for k, v in (("bot_user_id", self.bot_user_id), ("bot_id", self.bot_id),
                                                       ("team", self.status["team"])) if v})

    async def _paginate(self, method, key, **kwargs):
        cursor = None
        while True:
            resp = await getattr(self.client, method)(cursor=cursor, limit=200, **kwargs)
            for item in resp.get(key, []):
                yield item
            cursor = (resp.get("response_metadata") or {}).get("next_cursor")
            if not cursor:
                return

    async def _sync_users(self, warnings):
        try:
            users = [u async for u in self._paginate("users_list", "members")]
        except SlackApiError as e:
            warnings.append(f"users.list: {e.response.get('error')} (add the users:read scope to show names)")
            return
        await db.write(_save_users, users)
        self._users_synced_at = time.time()

    async def _list_conversations(self, warnings):
        convs = {}
        for kind in CONVERSATION_TYPES:
            try:
                async for c in self._paginate("conversations_list", "channels", types=kind, exclude_archived=True):
                    convs[c["id"]] = c
            except SlackApiError as e:
                err = e.response.get("error")
                needed = e.response.get("needed")
                warnings.append(f"conversations.list ({kind}): {err}{f' — needs {needed}' if needed else ''}")
        return list(convs.values())

    def _label(self, c):
        if c.get("is_im"):
            return f"DM with {c.get('user')}"
        return f"#{c.get('name') or c['id']}"

    async def _sync_conversation(self, c, fetched):
        """New messages since the cursor, plus a re-read of the lookback window to catch edits and new replies."""
        cid = c["id"]
        cursor = await db.read(_get_state, f"cursor:{cid}")
        window = {}
        if cursor and float(cursor) > 0:  # no cursor (or an empty conversation): read the whole history
            window["oldest"] = f"{min(float(cursor), time.time() - self.lookback_s):.6f}"
        messages = [m async for m in self._paginate("conversations_history", "messages", channel=cid, **window)]
        changed, threads = await db.write(_save_history, cid, messages, cursor, self.bot_user_id, self.bot_id)
        for parent in threads:
            replies = [r async for r in self._paginate("conversations_replies", "messages", channel=cid, ts=parent["ts"])]
            changed += await db.write(_save_thread, cid, parent["ts"], parent["latest_reply"], replies, True,
                                      self.bot_user_id, self.bot_id)
            fetched.add((cid, parent["ts"]))
        return changed

    async def _rescan_threads(self, readable, fetched, warnings):
        """Threads active in the last SLACK_PRUNE_DAYS whose parent is outside the lookback window: fetch
        only the replies newer than the last one stored."""
        since = time.time() - self.prune_s
        threads = await db.read(_active_threads, [c["id"] for c in readable], since)
        for t in threads:
            if (t["channel_id"], t["thread_ts"]) in fetched:
                continue
            try:
                replies = [r async for r in self._paginate("conversations_replies", "messages", channel=t["channel_id"],
                                                           ts=t["thread_ts"], oldest=t["last_ts"])]
            except SlackApiError as e:
                if e.response.get("error") != "thread_not_found":
                    warnings.append(f"replies {t['channel_id']}/{t['thread_ts']}: {e.response.get('error')}")
                continue
            await db.write(_save_thread, t["channel_id"], t["thread_ts"], None, replies, False,
                           self.bot_user_id, self.bot_id)

    async def _prune(self, readable, warnings):
        """Mark deleted the top-level messages of the last SLACK_PRUNE_DAYS that Slack no longer has."""
        oldest = time.time() - self.prune_s
        for c in readable:
            try:
                present = {m["ts"] async for m in self._paginate("conversations_history", "messages",
                                                                 channel=c["id"], oldest=f"{oldest:.6f}")}
            except SlackApiError as e:
                warnings.append(f"prune {self._label(c)}: {e.response.get('error')}")
                continue
            await db.write(_prune_top_level, c["id"], oldest, present)
