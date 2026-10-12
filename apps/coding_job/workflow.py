"""The coding job: a fixed, linear sequence of steps (no graph).

Every job leaves a trace folder at traces/coding_jobs/<job_id>/:
  prompt.txt          the prompt given to the coding agent
  steps.json          every workflow step: command, timing, output, error
  agent_output.jsonl  the coding agent's event stream (each tool call / message)
  agent_session/      the agent's own session files copied out of the container
  summary.txt         the agent's final summary
  job.json            the final jobs row
"""
import asyncio
import json
import logging
import os
from datetime import datetime, timezone

from slack_sdk.web.async_client import AsyncWebClient

from apps import db, github_client, traces
from apps.coding_job import sandbox
from apps.coding_job.prompt import build_prompt
from apps.config import GITHUB_TOKEN, SANDBOX_TIMEOUT_SECONDS, SLACK_BOT_TOKEN
from apps.stores.jobs import get_job, update_job
from apps.stores.users import get_user

log = logging.getLogger(__name__)
slack = AsyncWebClient(token=SLACK_BOT_TOKEN)

REPO_DIR = "/work/repo"
# only the transcript folders are copied out; never ~/.claude or ~/.codex as a whole (they hold credentials)
SESSION_DIRS = {"claude": "/home/agent/.claude/projects", "codex": "/home/agent/.codex/sessions"}


async def _post(job, text):
    await slack.chat_postMessage(channel=job["channel_id"], thread_ts=job["thread_ts"], text=text)


def _claude_summary(output):
    """Final answer from Claude Code's stream-json output (the "result" event)."""
    for line in reversed(output.splitlines()):
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("type") == "result":
            return event.get("result") or ""
    return output.strip()[-3000:]


async def run_coding_job(job_id):
    job = await db.read(get_job, job_id)
    await db.write(update_job, job_id, status="running")
    container = None
    steps = []

    async def step(name, cmd, env=None, workdir="/work"):
        """Run one sandbox command and record it. Env values are never recorded (they hold tokens)."""
        record = {"step": name, "cmd": cmd, "env_keys": sorted(env or {}), "started_at": datetime.now(timezone.utc).isoformat()}
        steps.append(record)
        try:
            output = await sandbox.exec(container, cmd, env=env, workdir=workdir)
            record["output"] = output
            return output
        except sandbox.SandboxError as e:
            record["output"], record["error"] = e.output, str(e)
            raise
        finally:
            record["finished_at"] = datetime.now(timezone.utc).isoformat()
            traces.write_job_file(job_id, "steps.json", steps)

    try:
        # 1. load the user and resolve the task text
        user = await db.read(get_user, job["user_id"])
        task = job["task"] or ""
        title = task.strip().splitlines()[0][:72] if task.strip() else ""
        issue = None
        if job["issue_url"]:
            issue = await github_client.get_issue(job["issue_url"])
            title = issue["title"][:72]
            task = f"GitHub issue #{issue['number']}: {issue['title']}\n\n{issue['body']}\n\n{task}".strip()

        # 2. start the container
        container = await sandbox.start()

        # 3. clone; the GitHub token only lives in this exec's environment
        branch = f"agent/{job_id}"
        await step(
            "clone",
            f"git clone --branch {job['base_branch']} https://x-access-token:$GITHUB_TOKEN@github.com/{job['repo']}.git repo"
            f" && cd repo && git remote set-url origin https://github.com/{job['repo']}.git && git checkout -b {branch}",
            env={"GITHUB_TOKEN": GITHUB_TOKEN},
        )

        # 4 + 5. run the user's coding agent on their own subscription
        prompt = build_prompt(task)
        traces.write_job_file(job_id, "prompt.txt", prompt)
        env = {"PROMPT": prompt}
        if user["provider"] == "codex":
            await sandbox.put_file(container, "/home/agent/.codex/auth.json", user["credential"])
            cmd = 'codex exec --json --dangerously-bypass-approvals-and-sandbox --output-last-message /work/summary.txt "$PROMPT"'
        else:
            env["CLAUDE_CODE_OAUTH_TOKEN"] = user["credential"]
            cmd = 'claude -p "$PROMPT" --dangerously-skip-permissions --output-format stream-json --verbose'
        try:
            output = await asyncio.wait_for(step("agent", cmd, env=env, workdir=REPO_DIR), SANDBOX_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            raise sandbox.SandboxError(f"the coding agent timed out after {SANDBOX_TIMEOUT_SECONDS}s")
        finally:
            if steps and steps[-1]["step"] == "agent":
                traces.write_job_file(job_id, "agent_output.jsonl", steps[-1].get("output", ""))
        if user["provider"] == "codex":
            summary = await step("read summary", "cat /work/summary.txt")
        else:
            summary = _claude_summary(output)
        summary = summary.strip()[-3000:]
        traces.write_job_file(job_id, "summary.txt", summary)

        # 6. commit and push
        if not (await step("check changes", "git status --porcelain", workdir=REPO_DIR)).strip():
            raise sandbox.SandboxError(f"the coding agent made no changes. Its output:\n{summary}")
        await step(
            "commit", 'git add -A && git commit -q -m "$MESSAGE"', env={"MESSAGE": f"{title} (job {job_id})"}, workdir=REPO_DIR
        )
        await step(
            "push",
            f"git push -q https://x-access-token:$GITHUB_TOKEN@github.com/{job['repo']}.git HEAD",
            env={"GITHUB_TOKEN": GITHUB_TOKEN},
            workdir=REPO_DIR,
        )

        # 7. open the PR and report back
        body = summary
        if issue:
            body += f"\n\nCloses #{issue['number']}"
        body += f"\n\nRequested by {user['name'] or job['user_id']} via Slack"
        pr_url = await github_client.create_pull_request(job["repo"], branch, job["base_branch"], title, body)
        await db.write(update_job, job_id, status="succeeded", pr_url=pr_url)
        await _post(job, f"Coding job {job_id} finished: {pr_url}\n\n{summary}")
    except Exception as e:
        log.exception("coding job %s failed", job_id)
        await db.write(update_job, job_id, status="failed", error=str(e))
        await _post(job, f"Coding job {job_id} failed: {e}")
    finally:
        if container is not None:
            # copy the agent's own session transcript out before the container is removed
            try:
                provider = ((await db.read(get_user, job["user_id"])) or {}).get("provider", "claude")
                await sandbox.fetch_dir(
                    container, SESSION_DIRS[provider], os.path.join(traces.job_dir(job_id), "agent_session")
                )
            except Exception:
                log.exception("could not fetch agent session files for job %s", job_id)
            await sandbox.remove(container)
        traces.write_job_file(job_id, "job.json", await db.read(get_job, job_id))
