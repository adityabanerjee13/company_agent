"""Real-time updates for the browser: an in-process pub/sub, plus a watcher on agent.db and traces/.

The bot writes to agent.db and traces/ as it works (Slack messages, job status, the sync status,
trace files), so watching them gives instant updates without any change to the bot.
"""
import asyncio
import json
import os
import sqlite3

POLL_S = 1.5


class Broadcaster:
    def __init__(self):
        self._subscribers = set()

    def subscribe(self):
        q = asyncio.Queue(maxsize=100)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q):
        self._subscribers.discard(q)

    def publish(self, event):
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass  # a stalled tab misses events; it refetches on the next one


class _DbWatcher:
    """One long-lived read-only connection. PRAGMA data_version changes whenever another connection (the bot)
    commits, so checking it costs nothing, unlike counting rows."""

    def __init__(self, db_path):
        self.db_path = db_path
        self.conn = None
        self.version = self.signature = self.sync_status = None

    def check(self):
        """(data signature, sync_status JSON), or None while there's no database yet. The signature is only
        recomputed when data_version moved, and leaves out sync_state, which the bot rewrites every second
        while syncing."""
        if not os.path.exists(self.db_path):
            self.close()
            return None
        try:
            if self.conn is None:
                self.conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True, timeout=5,
                                            check_same_thread=False)  # used from to_thread workers, one at a time
            version = self.conn.execute("PRAGMA data_version").fetchone()[0]
            if version != self.version:
                self.version = version
                try:
                    self.signature = {
                        "messages": (self.conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0],
                                     self.conn.execute("SELECT MAX(updated_at) FROM messages").fetchone()[0]),
                        "jobs": tuple(self.conn.execute(
                            "SELECT COUNT(*), GROUP_CONCAT(status), MAX(finished_at) FROM jobs").fetchone()),
                        "channels": tuple(self.conn.execute(
                            "SELECT COUNT(*), GROUP_CONCAT(name) FROM channels").fetchone()),
                    }
                    row = self.conn.execute("SELECT value FROM sync_state WHERE key = 'sync_status'").fetchone()
                    self.sync_status = row[0] if row else None
                except sqlite3.OperationalError:
                    self.signature, self.sync_status = None, None  # the bot hasn't created/migrated the schema yet
            return self.signature, self.sync_status
        except sqlite3.Error:
            self.close()  # reopen on the next tick
            return None

    def close(self):
        if self.conn is not None:
            self.conn.close()
            self.conn = None
            self.version = None


def _traces_signature(traces_dir):
    count, latest = 0, 0.0
    for root, _dirs, files in os.walk(traces_dir):
        for name in files:
            try:
                mtime = os.path.getmtime(os.path.join(root, name))
            except OSError:
                continue
            count += 1
            latest = max(latest, mtime)
    return count, latest


async def watch(db_path, traces_dir, publish):
    db = _DbWatcher(db_path)
    last_db, last_traces = await asyncio.to_thread(db.check), _traces_signature(traces_dir)
    try:
        while True:
            await asyncio.sleep(POLL_S)
            state, traces = await asyncio.to_thread(db.check), await asyncio.to_thread(_traces_signature, traces_dir)
            if state != last_db:
                sig, last_sig = (state or (None, None))[0] or {}, (last_db or (None, None))[0] or {}
                parts = [k for k in ("messages", "jobs", "channels") if sig.get(k) != last_sig.get(k)]
                if parts:
                    publish({"type": "db", "parts": parts})
                if state and state[1] and (not last_db or state[1] != last_db[1]):
                    try:
                        publish({"type": "sync", "status": json.loads(state[1])})
                    except ValueError:
                        pass
                last_db = state
            if traces != last_traces:
                publish({"type": "traces"})
                last_traces = traces
    finally:
        db.close()
