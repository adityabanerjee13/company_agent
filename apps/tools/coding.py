import asyncio

import httpx
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from apps import db, github_client
from apps.coding_job.workflow import run_coding_job
from apps.stores.jobs import create_job
from apps.stores.users import get_user

# keep references so running jobs are not garbage collected
_running = set()


@tool
async def start_coding_job(repo: str, config: RunnableConfig, base_branch: str = "", task: str = "", issue_url: str = "") -> str:
    """Start a coding agent that resolves a task in a GitHub repository and opens a pull request.
    `repo` is "owner/name". Leave `base_branch` empty unless the user named one; the repo's default
    branch is used. Give a `task` description, a GitHub `issue_url`, or both."""
    ctx = config["configurable"]["ctx"]
    if not task and not issue_url:
        return "Need a task description or a GitHub issue URL."
    if not await db.read(get_user, ctx["user_id"]):
        return "This user has no coding subscription on file, so a coding job can't be started for them."
    try:
        if not base_branch:
            base_branch = await github_client.get_default_branch(repo)
        branches = await github_client.list_branches(repo)
    except httpx.HTTPStatusError:
        return f"Can't access the repository {repo}. Check the name and that the bot's GitHub token can see it."
    if base_branch not in branches:
        return f"Branch '{base_branch}' doesn't exist in {repo}. Existing branches: {', '.join(branches)}."
    job_id = await db.write(create_job, ctx["user_id"], repo, base_branch, task, issue_url or None, ctx["channel_id"], ctx["thread_ts"])
    job = asyncio.get_running_loop().create_task(run_coding_job(job_id))
    _running.add(job)
    job.add_done_callback(_running.discard)
    return f"Job {job_id} started on {repo}@{base_branch}; the PR link will be posted in this thread when it's done."
