"""Local trace files for later analysis. Everything lands under TRACES_DIR:

  orchestrator/<channel>_<thread_ts>/<time>.json   one file per Slack turn
  github_agent/<channel>_<thread_ts>/<time>.json   one file per ask_github call
  coding_jobs/<job_id>/                            prompt, workflow steps, agent transcript + session files
"""
import json
import os
from datetime import datetime, timezone

from langchain_core.messages import messages_to_dict

from apps.config import TRACES_DIR


def _now():
    return datetime.now(timezone.utc)


def _thread_dir(kind, ctx):
    if ctx:
        name = f"{ctx['channel_id']}_{ctx['thread_ts']}"
    else:
        name = "no_thread"
    path = os.path.join(TRACES_DIR, kind, name)
    os.makedirs(path, exist_ok=True)
    return path


def save_agent_trace(kind, ctx, input_text, messages, started_at, error=None):
    """One agent run: the input, every message produced (model calls, tool calls, tool results), timing."""
    finished_at = _now()
    record = {
        "agent": kind,
        "ctx": ctx,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_s": round((finished_at - started_at).total_seconds(), 2),
        "input": input_text,
        "error": error,
        "messages": messages_to_dict(messages),
    }
    path = os.path.join(_thread_dir(kind, ctx), finished_at.strftime("%Y%m%dT%H%M%S_%f") + ".json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, ensure_ascii=False, default=str)
    return path


def job_dir(job_id):
    path = os.path.join(TRACES_DIR, "coding_jobs", job_id)
    os.makedirs(path, exist_ok=True)
    return path


def write_job_file(job_id, name, content):
    path = os.path.join(job_dir(job_id), name)
    with open(path, "w", encoding="utf-8") as f:
        if isinstance(content, str):
            f.write(content)
        else:
            json.dump(content, f, indent=2, ensure_ascii=False, default=str)
    return path
