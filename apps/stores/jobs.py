import uuid
from datetime import datetime, timezone

from apps.db import conn


def _now():
    return datetime.now(timezone.utc).isoformat()


def create_job(user_id, repo, base_branch, task, issue_url, channel_id, thread_ts):
    job_id = uuid.uuid4().hex[:8]
    conn.execute(
        "INSERT INTO jobs (id, user_id, repo, base_branch, task, issue_url, status, channel_id, thread_ts, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?)",
        (job_id, user_id, repo, base_branch, task, issue_url, channel_id, thread_ts, _now()),
    )
    conn.commit()
    return job_id


def get_job(job_id):
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return dict(row) if row else None


def update_job(job_id, **fields):
    if fields.get("status") in ("succeeded", "failed"):
        fields["finished_at"] = _now()
    assignments = ", ".join(f"{name} = ?" for name in fields)
    conn.execute(f"UPDATE jobs SET {assignments} WHERE id = ?", (*fields.values(), job_id))
    conn.commit()
