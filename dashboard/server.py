"""FastAPI app: the JSON API, a server-sent event stream for live updates, and the built React UI."""
import asyncio
import contextlib
import json
import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from dashboard import data, live

WEB_DIST = os.path.join(os.path.dirname(__file__), "web", "dist")

broadcaster = live.Broadcaster()


@contextlib.asynccontextmanager
async def lifespan(app):
    tasks = [asyncio.create_task(live.watch(data.DB_PATH, data.TRACES_DIR, broadcaster.publish))]
    yield
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(title="Agent dashboard", lifespan=lifespan)


def _require(value, what):
    if value is None:
        raise HTTPException(404, f"{what} not found")
    return value


def _safe(*names):
    if not all(data.safe_name(n) for n in names):
        raise HTTPException(404, "not found")


# ---------- live ----------

@app.get("/api/events")
async def events(request: Request):
    """Server-sent events: the bot's sync status, db and trace changes."""
    q = broadcaster.subscribe()

    async def stream():
        try:
            status = await asyncio.to_thread(data.sync_status)
            yield f"data: {json.dumps({'type': 'sync', 'status': status})}\n\n"
            while not await request.is_disconnected():
                try:
                    event = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {json.dumps(event, default=str)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            broadcaster.unsubscribe(q)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/sync")
def sync_status():
    return data.sync_status()


# ---------- data ----------

@app.get("/api/overview")
def overview():
    return {**data.overview(), "sync": data.sync_status()}


@app.get("/api/users")
def users():
    return data.list_users()


@app.get("/api/conversations")
def conversations(user: str | None = None):
    return data.list_conversations(user or None)


@app.get("/api/channel/{ch}")
def channel(ch: str):
    _safe(ch)
    return {"channel": data.channel_info(ch), "messages": data.channel_messages(ch)}


@app.get("/api/thread/{ch}/{ts}")
def thread(ch: str, ts: str):
    _safe(ch, ts)
    return data.thread(ch, ts)


@app.get("/api/user/{user_id}")
def user(user_id: str):
    _safe(user_id)
    return data.user_detail(user_id)


@app.get("/api/runs")
def runs(agent: str | None = None):
    return data.list_runs(agent or None)


@app.get("/api/run/{agent}/{folder}/{file}")
def run(agent: str, folder: str, file: str):
    if agent not in data.AGENTS:
        raise HTTPException(404, "run not found")
    _safe(folder, file)
    return _require(data.run_detail(agent, folder, file), "run")


@app.get("/api/jobs")
def jobs():
    return data.list_jobs()


@app.get("/api/job/{job_id}")
def job(job_id: str):
    _safe(job_id)
    return _require(data.load_job(job_id), "job")


@app.get("/api/job/{job_id}/raw/{name}", response_class=PlainTextResponse)
def job_raw(job_id: str, name: str):
    return _require(data.job_raw_file(job_id, name), "file")


# ---------- UI ----------

if os.path.isdir(WEB_DIST):
    app.mount("/assets", StaticFiles(directory=os.path.join(WEB_DIST, "assets")), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        # hash routing: every non-API path serves the app shell
        candidate = os.path.join(WEB_DIST, path)
        if path and os.path.isfile(candidate) and os.path.commonpath([candidate, WEB_DIST]) == WEB_DIST:
            return FileResponse(candidate)
        return FileResponse(os.path.join(WEB_DIST, "index.html"))
else:
    @app.get("/", include_in_schema=False, response_class=PlainTextResponse)
    def no_ui():
        return ("The React UI is not built yet. Run:\n\n  cd dashboard/web\n  npm install\n  npm run build\n\n"
                "or `npm run dev` there for live-reloading development on http://localhost:5173.")
