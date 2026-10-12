"""Read-only loaders for agent.db and traces/, normalized for the dashboard.

Nothing here imports apps.config: that module requires Slack/OpenRouter secrets, and the
dashboard only needs the two paths below. The dashboard never writes: the bot is the only writer,
including the Slack sync. Messages are read through the visible_messages view, which hides deleted ones.

Links between the pieces:
  Slack message ts         == orchestrator trace ctx.ts
  orchestrator ask_github  -> github_agent trace in the same <channel>_<thread_ts> dir, input == args.question
  start_coding_job result  -> "Job <id> started" -> traces/coding_jobs/<id> and the jobs row
"""
import glob
import json
import os
import re
import sqlite3
from collections import Counter
from datetime import datetime

DB_PATH = os.environ.get("DB_PATH", "agent.db")
TRACES_DIR = os.environ.get("TRACES_DIR", "traces")
AGENTS = ("orchestrator", "github_agent")
MAX_TEXT = 20_000
SUBAGENT_TOOLS = {"ask_github": "github", "start_coding_job": "job"}
JOB_ID_RE = re.compile(r"Job (\w+) started")
MENTION_RE = re.compile(r"<@(U\w+)>")
SAFE_NAME_RE = re.compile(r"^[\w.\-]+$")
JOB_FILES = ("job.json", "prompt.txt", "steps.json", "agent_output.jsonl", "summary.txt")


# ---------- helpers ----------

def _rows(sql, params=()):
    """Query agent.db read-only; an absent database or a table not created yet reads as empty."""
    if not os.path.exists(DB_PATH):
        return []
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql, params)]
    except sqlite3.OperationalError as e:
        if "no such" in str(e):
            return []
        raise
    finally:
        conn.close()


def _state(key):
    rows = _rows("SELECT value FROM sync_state WHERE key = ?", (key,))
    return rows[0]["value"] if rows else None


NO_SYNC_STATUS = {"state": "error", "error": "No sync status yet. Start the bot: it runs the Slack sync."}


def sync_status():
    """The bot's Slack sync status, as it last saved it."""
    try:
        return json.loads(_state("sync_status") or "null") or NO_SYNC_STATUS
    except ValueError:
        return NO_SYNC_STATUS


def _clip(value, limit=MAX_TEXT):
    """Long strings are cut so the page stays responsive; the raw file is still reachable."""
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + f"\n\n… [truncated, {len(value) - limit:,} more characters]"
    return value


def _text(content):
    """LangChain / Anthropic content can be a string or a list of blocks."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, dict):
                parts.append(json.dumps(block, ensure_ascii=False))
        return "\n".join(parts)
    return "" if content is None else str(content)


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _read_text(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def _parse_jsonl(text):
    events = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except ValueError:
            continue  # partial last line of a job that was killed mid-write
    return events


def _ts(iso):
    try:
        return datetime.fromisoformat(iso).timestamp()
    except (TypeError, ValueError):
        return None


def safe_name(name):
    return bool(name) and bool(SAFE_NAME_RE.match(name)) and name not in (".", "..")


# ---------- Slack data ----------

def bot_user_id():
    """The bot's Slack user id: recorded by the Slack sync, else BOT_USER_ID, else inferred from the
    mentions in messages that started orchestrator runs."""
    known = _state("bot_user_id") or os.environ.get("BOT_USER_ID")
    if known:
        return known
    triggers = {r["ctx"].get("ts") for r in trace_index() if r["agent"] == "orchestrator"}
    counts = Counter()
    for m in _rows("SELECT ts, text FROM visible_messages"):
        if m["ts"] in triggers:
            counts.update(MENTION_RE.findall(m["text"]))
    return counts.most_common(1)[0][0] if counts else None


def _display_name(row):
    return row.get("display_name") or row.get("real_name") or row.get("name") or row["user_id"]


def list_users():
    """Slack members (from the sync), subscribed users and anyone seen in messages or traces.
    Never selects users.credential."""
    users = {}
    for r in _rows("SELECT user_id, name, real_name, display_name, is_bot, deleted, avatar FROM slack_users"):
        users[r["user_id"]] = {"id": r["user_id"], "name": _display_name(r), "handle": r["name"],
                               "is_bot": bool(r["is_bot"]), "deleted": bool(r["deleted"]),
                               "avatar": r["avatar"], "subscribed": False}
    for r in _rows("SELECT slack_user_id, name, provider FROM users"):
        u = users.setdefault(r["slack_user_id"], {"id": r["slack_user_id"], "name": r["name"] or r["slack_user_id"]})
        u.update(provider=r["provider"], subscribed=True)
    for r in _rows("SELECT user_id, COUNT(*) AS n FROM visible_messages GROUP BY user_id"):
        u = users.setdefault(r["user_id"], {"id": r["user_id"], "name": r["user_id"], "subscribed": False})
        u["message_count"] = r["n"]
    for run in trace_index():
        uid = run["ctx"].get("user_id")
        if uid:
            users.setdefault(uid, {"id": uid, "name": uid, "subscribed": False})

    # the bot stores its own messages as "bot"; its Slack user id is an alias of that entry
    bot = bot_user_id()
    bot_name = users.get(bot, {}).get("name") if bot else None
    if bot_name == bot:
        bot_name = None
    entry = users.setdefault("bot", {"id": "bot", "subscribed": False})
    entry.update(name=bot_name or "AI Coworker", is_bot=True, is_app=True, slack_id=bot,
                 avatar=users.get(bot, {}).get("avatar"))
    if bot:
        users.setdefault(bot, {"id": bot, "subscribed": False})
        users[bot].update(name=entry["name"], is_bot=True, alias_of="bot")
    for u in users.values():
        u.setdefault("message_count", 0)
        u.setdefault("is_bot", False)
    return sorted(users.values(), key=lambda u: (u["is_bot"], u.get("deleted", False), u["name"].lower()))


def list_conversations(user_id=None):
    """Channels and DMs from the sync (with names) plus any channel seen only in messages."""
    rows = _rows("""
        SELECT c.*, COUNT(m.ts) AS message_count, MAX(m.created_at) AS last_at,
               GROUP_CONCAT(DISTINCT m.user_id) AS members
        FROM channels c LEFT JOIN visible_messages m ON m.channel_id = c.channel_id
        GROUP BY c.channel_id""")
    rows += _rows("""
        SELECT m.channel_id, NULL AS type, COUNT(*) AS message_count, MAX(m.created_at) AS last_at,
               GROUP_CONCAT(DISTINCT m.user_id) AS members
        FROM visible_messages m WHERE m.channel_id NOT IN (SELECT channel_id FROM channels)
        GROUP BY m.channel_id""")
    convs = []
    for r in rows:
        members = [m for m in (r["members"] or "").split(",") if m]
        if r.get("dm_user_id") and r["dm_user_id"] not in members:
            members.append(r["dm_user_id"])
        if user_id and user_id not in members:
            continue
        kind = r["type"] or ("im" if r["channel_id"].startswith("D") else "channel")
        convs.append({
            "id": r["channel_id"], "type": kind, "is_dm": kind in ("im", "mpim"),
            "name": r.get("name"), "dm_user_id": r.get("dm_user_id"), "topic": r.get("topic"),
            "is_member": None if r.get("is_member") is None else bool(r["is_member"]),
            "is_private": bool(r.get("is_private")),
            "message_count": r["message_count"], "last_at": r["last_at"], "members": members,
        })
    return sorted(convs, key=lambda c: (c["last_at"] or "", c["name"] or ""), reverse=True)


def channel_info(channel_id):
    return next((c for c in list_conversations() if c["id"] == channel_id), {"id": channel_id, "type": "channel"})


def _decorate(messages):
    """Mark messages that mention the bot and link them (and the bot's replies) to orchestrator runs."""
    bot = bot_user_id()
    runs = [r for r in trace_index() if r["agent"] == "orchestrator"]
    by_trigger = {(r["ctx"].get("channel_id"), r["ctx"].get("ts")): r for r in runs}
    for m in messages:
        if isinstance(m.get("files"), str):
            try:
                m["files"] = json.loads(m["files"])
            except ValueError:
                m["files"] = None
        m["mentions_bot"] = bool(bot) and f"<@{bot}>" in (m["text"] or "")
        run = by_trigger.get((m["channel_id"], m["ts"]))
        if run:
            m["run"] = run["ref"]
        elif m["user_id"] == "bot":
            # the reply a run posted lands shortly after the run finishes
            t = _ts(m["created_at"])
            for r in runs:
                if (r["ctx"].get("channel_id") == m["channel_id"] and t
                        and r["started_ts"] <= t <= r["finished_ts"] + 15):
                    m["produced_by"] = r["ref"]
                    break
    return messages


def channel_messages(channel_id):
    """Top-level messages of a channel/DM, each with its reply count, like Slack's channel view."""
    rows = _rows("""
        SELECT m.*, (SELECT COUNT(*) FROM visible_messages r WHERE r.channel_id = m.channel_id AND r.thread_ts = m.ts AND r.ts != m.ts) AS reply_count,
               (SELECT MAX(r.created_at) FROM visible_messages r WHERE r.channel_id = m.channel_id AND r.thread_ts = m.ts AND r.ts != m.ts) AS last_reply_at,
               (SELECT GROUP_CONCAT(DISTINCT r.user_id) FROM visible_messages r WHERE r.channel_id = m.channel_id AND r.thread_ts = m.ts AND r.ts != m.ts) AS repliers
        FROM visible_messages m
        WHERE m.channel_id = ? AND (m.thread_ts IS NULL OR m.thread_ts = m.ts)
        ORDER BY m.ts""", (channel_id,))
    # replies whose root was never stored (bot started after the root was posted): show the thread anyway
    orphans = _rows("""
        SELECT thread_ts, MIN(ts) AS first_ts, COUNT(*) AS n, MAX(created_at) AS last_reply_at,
               GROUP_CONCAT(DISTINCT user_id) AS repliers
        FROM visible_messages
        WHERE channel_id = ? AND thread_ts IS NOT NULL AND thread_ts != ts
          AND thread_ts NOT IN (SELECT ts FROM visible_messages WHERE channel_id = ?)
        GROUP BY thread_ts""", (channel_id, channel_id))
    for o in orphans:
        rows.append({"ts": o["thread_ts"], "channel_id": channel_id, "thread_ts": o["thread_ts"],
                     "user_id": None, "text": "", "created_at": None, "missing_root": True,
                     "reply_count": o["n"], "last_reply_at": o["last_reply_at"], "repliers": o["repliers"]})
    for r in rows:
        r["repliers"] = [u for u in (r.get("repliers") or "").split(",") if u]
    rows.sort(key=lambda r: float(r["ts"]))
    return _decorate([r for r in rows if not r.get("missing_root")]) + [r for r in rows if r.get("missing_root")]


def thread(channel_id, thread_ts):
    msgs = _rows("""SELECT * FROM visible_messages WHERE channel_id = ? AND (ts = ? OR thread_ts = ?) ORDER BY ts""",
                 (channel_id, thread_ts, thread_ts))
    msgs = _decorate(msgs)
    jobs = _rows("SELECT id, status, repo, pr_url, created_at FROM jobs WHERE channel_id = ? AND thread_ts = ?",
                 (channel_id, thread_ts))
    runs = [r for r in trace_index() if r["ctx"].get("channel_id") == channel_id
            and r["ctx"].get("thread_ts") == thread_ts]
    return {"channel_id": channel_id, "thread_ts": thread_ts, "messages": msgs, "jobs": jobs,
            "runs": [_summary(r) for r in runs]}


def user_detail(user_id):
    msgs = _decorate(_rows("SELECT * FROM visible_messages WHERE user_id = ? ORDER BY ts", (user_id,)))
    user = next((u for u in list_users() if u["id"] == user_id), {"id": user_id, "name": user_id})
    runs = [_summary(r) for r in trace_index() if r["ctx"].get("user_id") == user_id]
    jobs = _rows("SELECT id, repo, base_branch, status, pr_url, created_at, finished_at FROM jobs "
                 "WHERE user_id = ? ORDER BY created_at DESC", (user_id,))
    return {"user": user, "messages": msgs, "conversations": list_conversations(user_id),
            "runs": runs, "jobs": jobs}


# ---------- orchestrator / github_agent traces ----------

def trace_index():
    """Every saved agent run, light-weight: what's needed to list and link them."""
    runs = []
    for agent in AGENTS:
        for path in sorted(glob.glob(os.path.join(TRACES_DIR, agent, "*", "*.json"))):
            rec = _read_json(path)
            if not isinstance(rec, dict):
                continue
            folder = os.path.basename(os.path.dirname(path))
            ctx = rec.get("ctx") or {}
            started, finished = _ts(rec.get("started_at")), _ts(rec.get("finished_at"))
            runs.append({
                "agent": agent, "dir": folder, "file": os.path.basename(path),
                "ref": {"agent": agent, "dir": folder, "file": os.path.basename(path)},
                "ctx": ctx, "started_at": rec.get("started_at"), "finished_at": rec.get("finished_at"),
                "started_ts": started or 0, "finished_ts": finished or started or 0,
                "duration_s": rec.get("duration_s"), "error": rec.get("error"),
                "input": rec.get("input") or "", "_messages": rec.get("messages") or [],
            })
    return runs


def _tool_calls(messages):
    calls = []
    for m in messages:
        if m.get("type") == "ai":
            calls.extend((m.get("data") or {}).get("tool_calls") or [])
    return calls


def _usage(messages):
    total = Counter()
    model = None
    for m in messages:
        data = m.get("data") or {}
        if m.get("type") != "ai":
            continue
        u = data.get("usage_metadata") or {}
        total["input"] += u.get("input_tokens") or 0
        total["output"] += u.get("output_tokens") or 0
        total["reasoning"] += (u.get("output_token_details") or {}).get("reasoning") or 0
        total["cache_read"] += (u.get("input_token_details") or {}).get("cache_read") or 0
        model = model or (data.get("response_metadata") or {}).get("model_name")
    return dict(total), model


def _summary(run):
    calls = _tool_calls(run["_messages"])
    usage, model = _usage(run["_messages"])
    return {
        "ref": run["ref"], "agent": run["agent"], "ctx": run["ctx"],
        "started_at": run["started_at"], "finished_at": run["finished_at"],
        "duration_s": run["duration_s"], "error": run["error"], "model": model,
        "tool_calls": len(calls), "tools": Counter(c.get("name") for c in calls),
        "usage": usage, "input_preview": _preview(_last_turn(run["input"])),
    }


def _preview(text, limit=240):
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def _last_turn(prompt):
    """The orchestrator prompt starts with the thread history; the new message is the last block."""
    if prompt.startswith("[Earlier messages in this conversation]"):
        head, sep, tail = prompt.rpartition("\n\n")
        if sep:
            return tail
    return prompt


def list_runs(agent=None):
    return [_summary(r) for r in trace_index() if not agent or r["agent"] == agent]


def normalize_langchain(messages):
    """LangChain messages -> steps: prompt, assistant text, tool calls paired with their results, final reply."""
    results = {}
    for m in messages:
        if m.get("type") == "tool":
            d = m.get("data") or {}
            results[d.get("tool_call_id")] = d
    steps = []
    ai_turns = [i for i, m in enumerate(messages) if m.get("type") == "ai"]
    last_ai = ai_turns[-1] if ai_turns else None
    for i, m in enumerate(messages):
        d = m.get("data") or {}
        kind = m.get("type")
        if kind == "human":
            steps.append({"kind": "prompt", "text": _clip(_text(d.get("content")))})
        elif kind == "ai":
            u = d.get("usage_metadata") or {}
            calls = d.get("tool_calls") or []
            turn = {
                "kind": "final" if i == last_ai and not calls else "turn",
                "text": _clip(_text(d.get("content"))),
                "model": (d.get("response_metadata") or {}).get("model_name"),
                "usage": {"input": u.get("input_tokens"), "output": u.get("output_tokens"),
                          "reasoning": (u.get("output_token_details") or {}).get("reasoning"),
                          "cache_read": (u.get("input_token_details") or {}).get("cache_read")},
                "tool_calls": [],
            }
            for c in calls:
                res = results.get(c.get("id")) or {}
                turn["tool_calls"].append({
                    "id": c.get("id"), "name": c.get("name"), "args": c.get("args") or {},
                    "result": _clip(_text(res.get("content"))) if res else None,
                    "status": res.get("status") if res else "missing",
                })
            steps.append(turn)
    return steps


def find_run(agent, folder, file):
    for r in trace_index():
        if r["agent"] == agent and r["dir"] == folder and r["file"] == file:
            return r
    return None


def run_detail(agent, folder, file):
    run = find_run(agent, folder, file)
    if not run:
        return None
    detail = _summary(run)
    detail["input"] = _clip(run["input"])
    detail["steps"] = normalize_langchain(run["_messages"])
    ctx = run["ctx"]
    trigger = _rows("SELECT * FROM visible_messages WHERE channel_id = ? AND ts = ?",
                    (ctx.get("channel_id"), ctx.get("ts")))
    detail["trigger_message"] = trigger[0] if trigger else None

    if agent == "orchestrator":
        siblings = [r for r in trace_index() if r["agent"] == "github_agent" and r["dir"] == folder]
        for step in detail["steps"]:
            for call in step.get("tool_calls", []):
                if call["name"] == "ask_github":
                    sub = _match_github(run, call, siblings)
                    if sub:
                        call["link"] = {"type": "github", "ref": sub["ref"]}
                elif call["name"] == "start_coding_job":
                    match = JOB_ID_RE.search(call.get("result") or "")
                    if match:
                        job = _rows("SELECT id, status, pr_url FROM jobs WHERE id = ?", (match.group(1),))
                        call["link"] = {"type": "job", "id": match.group(1),
                                        "status": job[0]["status"] if job else None}
    else:
        parent = _github_parent(run)
        if parent:
            detail["parent"] = parent
    return detail


def _match_github(orch, call, candidates):
    question = (call.get("args") or {}).get("question", "").strip()
    for c in candidates:
        if c["input"].strip() == question:
            return c
    for c in candidates:
        if orch["started_ts"] <= c["started_ts"] <= orch["finished_ts"]:
            return c
    return None


def _github_parent(gh_run):
    for r in trace_index():
        if r["agent"] != "orchestrator" or r["dir"] != gh_run["dir"]:
            continue
        for c in _tool_calls(r["_messages"]):
            if c.get("name") == "ask_github" and _match_github(r, c, [gh_run]):
                return {"ref": r["ref"], "tool_call_id": c.get("id")}
    return None


# ---------- coding jobs ----------

def _job_dir(job_id):
    return os.path.join(TRACES_DIR, "coding_jobs", job_id)


def list_jobs():
    jobs = {r["id"]: r for r in _rows("SELECT * FROM jobs")}
    for path in glob.glob(os.path.join(TRACES_DIR, "coding_jobs", "*")):
        job_id = os.path.basename(path)
        if job_id not in jobs and os.path.isdir(path):
            jobs[job_id] = _read_json(os.path.join(path, "job.json")) or {"id": job_id, "status": "unknown"}
    for job in jobs.values():
        folder = _job_dir(job["id"])
        job["files"] = [f for f in JOB_FILES if os.path.exists(os.path.join(folder, f))]
        job["has_session"] = bool(glob.glob(os.path.join(folder, "agent_session", "**", "*.jsonl"), recursive=True))
    return sorted(jobs.values(), key=lambda j: j.get("created_at") or "", reverse=True)


def normalize_claude_stream(events):
    """Claude Code stream-json (or session jsonl) -> init info, conversation steps, usage, noise counts."""
    results, init, steps, noise = {}, None, [], Counter()
    for e in events:
        if e.get("type") == "user":
            content = (e.get("message") or {}).get("content")
            if isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        results[b.get("tool_use_id")] = b
    seen_ids = set()
    usage_total = Counter()
    for e in events:
        etype = e.get("type")
        if etype == "system" and e.get("subtype") == "init":
            init = {k: e.get(k) for k in ("model", "cwd", "tools", "permissionMode", "claude_code_version", "session_id")}
            continue
        if etype == "result":
            steps.append({"kind": "result", "text": _clip(_text(e.get("result"))), "is_error": e.get("is_error"),
                          "duration_ms": e.get("duration_ms"), "cost_usd": e.get("total_cost_usd"),
                          "num_turns": e.get("num_turns")})
            continue
        if etype == "system" and e.get("subtype") in ("task_started", "task_notification"):
            noise[f"system/{e.get('subtype')}"] += 1
            steps.append({"kind": "event", "subtype": e.get("subtype"),
                          "text": _clip(e.get("description") or e.get("summary") or e.get("status") or "", 400),
                          "ts": e.get("timestamp")})
            continue
        if etype != "assistant":
            if etype != "user":
                noise[etype + (f"/{e['subtype']}" if e.get("subtype") else "")] += 1
            continue
        msg = e.get("message") or {}
        u = msg.get("usage") or {}
        # streamed output repeats usage per content block of the same message id: count once
        if msg.get("id") not in seen_ids:
            seen_ids.add(msg.get("id"))
            usage_total["input"] += u.get("input_tokens") or 0
            usage_total["output"] += u.get("output_tokens") or 0
            usage_total["cache_read"] += u.get("cache_read_input_tokens") or 0
            usage_total["cache_creation"] += u.get("cache_creation_input_tokens") or 0
        for b in msg.get("content") or []:
            btype = b.get("type")
            base = {"ts": e.get("timestamp"), "subagent": bool(e.get("parent_tool_use_id"))}
            if btype == "text":
                steps.append({**base, "kind": "text", "text": _clip(b.get("text", ""))})
            elif btype == "thinking":
                steps.append({**base, "kind": "thinking", "text": _clip(b.get("thinking") or ""),
                              "redacted": not b.get("thinking"), "duration_ms": e.get("thinking_duration_ms")})
            elif btype == "tool_use":
                res = results.get(b.get("id"))
                steps.append({**base, "kind": "tool_call", "id": b.get("id"), "name": b.get("name"),
                              "args": b.get("input") or {},
                              "result": _clip(_text(res.get("content"))) if res else None,
                              "status": ("error" if res.get("is_error") else "success") if res else "missing"})
    return {"init": init, "steps": steps, "usage": dict(usage_total), "noise": dict(noise)}


def load_job(job_id):
    if not safe_name(job_id):
        return None
    folder = _job_dir(job_id)
    row = _rows("SELECT * FROM jobs WHERE id = ?", (job_id,))
    job = row[0] if row else _read_json(os.path.join(folder, "job.json"))
    if not job and not os.path.isdir(folder):
        return None
    job = dict(job or {"id": job_id, "status": "unknown"})

    steps = _read_json(os.path.join(folder, "steps.json")) or []
    for s in steps:
        s["duration_s"] = (round(_ts(s["finished_at"]) - _ts(s["started_at"]), 2)
                           if _ts(s.get("finished_at")) and _ts(s.get("started_at")) else None)
        s["output_length"] = len(s.get("output") or "")
        if s.get("step") == "agent":
            s["output"] = None  # it's the raw stream-json; shown parsed as the session instead
        else:
            s["output"] = _clip(s.get("output"))
        s["error"] = _clip(s.get("error"), 4000)

    # sandbox Claude session: agent_output.jsonl, else the agent step's captured output, else the session file
    source, events = None, []
    raw = _read_text(os.path.join(folder, "agent_output.jsonl"))
    if raw:
        source, events = "agent_output.jsonl", _parse_jsonl(raw)
    if not events:
        for s in _read_json(os.path.join(folder, "steps.json")) or []:
            if s.get("step") == "agent" and s.get("output"):
                source, events = "steps.json (agent step output)", _parse_jsonl(s["output"])
    if not events:
        for path in glob.glob(os.path.join(folder, "agent_session", "**", "*.jsonl"), recursive=True):
            source, events = "agent_session", _parse_jsonl(_read_text(path))

    return {
        "job": job,
        "prompt": _read_text(os.path.join(folder, "prompt.txt")),
        "summary": _read_text(os.path.join(folder, "summary.txt")),
        "steps": steps,
        "session": {**normalize_claude_stream(events), "source": source, "event_count": len(events)} if events else None,
        "files": [f for f in JOB_FILES if os.path.exists(os.path.join(folder, f))],
        "parent": _job_parent(job_id, job),
    }


def _job_parent(job_id, job):
    for r in trace_index():
        if r["agent"] != "orchestrator":
            continue
        for m in r["_messages"]:
            if m.get("type") == "tool" and (m.get("data") or {}).get("name") == "start_coding_job":
                match = JOB_ID_RE.search(_text((m.get("data") or {}).get("content")))
                if match and match.group(1) == job_id:
                    return {"ref": r["ref"], "tool_call_id": m["data"].get("tool_call_id")}
    return None


def job_raw_file(job_id, name):
    if not safe_name(job_id) or name not in JOB_FILES:
        return None
    return _read_text(os.path.join(_job_dir(job_id), name))


# ---------- overview ----------

def _interaction(run, jobs_by_id, github_runs, messages_by_ts):
    """One user -> agent interaction (an orchestrator run), with everything that went wrong in it."""
    summary = _summary(run)
    trigger = messages_by_ts.get((run["ctx"].get("channel_id"), run["ctx"].get("ts")))
    tools, problems, job_refs, github_refs = [], [], [], []
    results = {}
    for m in run["_messages"]:
        if m.get("type") == "tool":
            d = m.get("data") or {}
            results[d.get("tool_call_id")] = d
    siblings = [g for g in github_runs if g["dir"] == run["dir"]]
    for call in _tool_calls(run["_messages"]):
        res = results.get(call.get("id"))
        status = (res or {}).get("status") or "missing"
        entry = {"name": call.get("name"), "status": status}
        if status != "success":
            problems.append(f"{call.get('name')} {'returned an error' if status == 'error' else 'never returned'}")
        if call.get("name") == "ask_github":
            sub = _match_github(run, call, siblings)
            if sub:
                entry["link"] = {"type": "github", "ref": sub["ref"]}
                github_refs.append(sub["ref"])
                if sub["error"]:
                    problems.append("GitHub agent crashed")
        elif call.get("name") == "start_coding_job":
            match = JOB_ID_RE.search(_text((res or {}).get("content")))
            if match:
                job = jobs_by_id.get(match.group(1), {"id": match.group(1)})
                entry["link"] = {"type": "job", "id": job["id"], "status": job.get("status")}
                job_refs.append({"id": job["id"], "status": job.get("status"), "error": _preview(job.get("error") or "", 160)})
                if job.get("status") == "failed":
                    problems.append(f"coding job {job['id']} failed")
            elif res:
                problems.append("coding job did not start")
        tools.append(entry)
    if run["error"]:
        problems.insert(0, "run crashed")
    if problems:
        outcome = "failed"
    elif any(j["status"] in ("running", "queued") for j in job_refs):
        outcome = "running"
    else:
        outcome = "succeeded"
    return {
        **summary,
        "message": trigger["text"] if trigger else _last_turn(run["input"]),
        "message_found": bool(trigger),
        "tool_list": tools, "jobs": job_refs, "github": github_refs,
        "problems": problems, "outcome": outcome,
    }


def _unanswered_mentions():
    """Messages that @mention the bot with no bot reply after them in the same thread."""
    bot = bot_user_id()
    if not bot:
        return []
    rows = _rows("""
        SELECT m.* FROM visible_messages m
        WHERE m.text LIKE ? AND m.user_id != 'bot'
          AND NOT EXISTS (SELECT 1 FROM visible_messages r WHERE r.user_id = 'bot' AND r.channel_id = m.channel_id
                          AND COALESCE(r.thread_ts, r.ts) = COALESCE(m.thread_ts, m.ts) AND CAST(r.ts AS REAL) > CAST(m.ts AS REAL))
        ORDER BY m.ts DESC""", (f"%<@{bot}>%",))
    return rows


def overview():
    index = trace_index()
    orchestrator = [r for r in index if r["agent"] == "orchestrator"]
    github_runs = [r for r in index if r["agent"] == "github_agent"]
    jobs = list_jobs()
    jobs_by_id = {j["id"]: j for j in jobs}
    triggers = [r["ctx"].get("ts") for r in orchestrator if r["ctx"].get("ts")]
    messages_by_ts = {}
    if triggers:
        marks = ",".join("?" * len(triggers))
        messages_by_ts = {(m["channel_id"], m["ts"]): m
                          for m in _rows(f"SELECT * FROM visible_messages WHERE ts IN ({marks})", triggers)}

    interactions = sorted((_interaction(r, jobs_by_id, github_runs, messages_by_ts) for r in orchestrator),
                          key=lambda i: i["started_at"] or "", reverse=True)
    linked_jobs = {j["id"] for i in interactions for j in i["jobs"]}

    issues = []
    for i in interactions:
        if i["outcome"] == "failed":
            issues.append({
                "kind": "interaction", "at": i["started_at"], "title": "; ".join(i["problems"]).capitalize(),
                "detail": i["error"] or next((j["error"] for j in i["jobs"] if j["status"] == "failed" and j["error"]), None),
                "message": _preview(i["message"], 140), "user_id": i["ctx"].get("user_id"), "ref": i["ref"],
            })
    for j in jobs:
        if j.get("status") == "failed" and j["id"] not in linked_jobs:
            issues.append({"kind": "job", "at": j.get("finished_at") or j.get("created_at"),
                           "title": f"Coding job {j['id']} failed", "detail": _preview(j.get("error") or "", 300),
                           "user_id": j.get("user_id"), "job_id": j["id"]})
    traced = {(r["ctx"].get("channel_id"), r["ctx"].get("ts")) for r in orchestrator}
    unanswered = [m for m in _unanswered_mentions() if (m["channel_id"], m["ts"]) not in traced]
    for m in unanswered:
        issues.append({"kind": "unanswered", "at": m["created_at"], "title": "Mention got no reply",
                       "detail": None, "message": _preview(m["text"], 140), "user_id": m["user_id"],
                       "channel_id": m["channel_id"], "thread_ts": m["thread_ts"] or m["ts"], "ts": m["ts"]})
    issues.sort(key=lambda x: x["at"] or "", reverse=True)

    usage = Counter()
    for i in interactions:
        usage.update(i["usage"])
    durations = sorted(i["duration_s"] for i in interactions if i["duration_s"] is not None)
    return {
        "counts": {
            "interactions": len(interactions),
            "failed": sum(i["outcome"] == "failed" for i in interactions),
            "running": sum(i["outcome"] == "running" for i in interactions),
            "jobs": len(jobs),
            "jobs_failed": sum(j.get("status") == "failed" for j in jobs),
            "jobs_running": sum(j.get("status") in ("running", "queued") for j in jobs),
            "unanswered": len(unanswered),
            "tool_calls": sum(len(i["tool_list"]) for i in interactions),
            "tool_errors": sum(t["status"] != "success" for i in interactions for t in i["tool_list"]),
        },
        "median_duration_s": durations[len(durations) // 2] if durations else None,
        "usage": dict(usage),
        "issues": issues,
        "interactions": interactions,
        "bot_user_id": bot_user_id(),
    }
