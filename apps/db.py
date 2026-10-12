import asyncio
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from functools import partial

from apps.config import DB_PATH
from apps.schema import connect_pragmas, init_schema


class _ThreadLocalConnection:
    """One sqlite3 connection per thread. Sync tools run in executor threads, and parallel
    tool calls would otherwise use one connection at the same time (sqlite3.InterfaceError)."""

    def __init__(self, path):
        self._path = path
        self._local = threading.local()

    def _get(self):
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(self._path, timeout=5)
            c.row_factory = sqlite3.Row
            connect_pragmas(c)
            self._local.conn = c
        return c

    def __getattr__(self, name):
        return getattr(self._get(), name)


conn = _ThreadLocalConnection(DB_PATH)

# every write from async code goes through this one thread, so writes never wait on each other
_writer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="db-writer")


async def write(fn, *args, **kwargs):
    """Run a store function that writes, off the event loop and one at a time."""
    return await asyncio.get_running_loop().run_in_executor(_writer, partial(fn, *args, **kwargs))


async def read(fn, *args, **kwargs):
    """Run a store function that only reads, off the event loop."""
    return await asyncio.to_thread(fn, *args, **kwargs)


def init_db():
    init_schema(conn)
