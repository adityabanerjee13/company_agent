from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from apps import github_client

MAX_DIFF_CHARS = 60_000


# --- read-only PR tools, used only by the GitHub sub-agent ---

@tool
async def search_pull_requests(query: str) -> str:
    """Search pull requests visible to the bot. `query` uses GitHub search syntax,
    e.g. "repo:owner/name is:open", "author:alice", "fix login"."""
    data = await github_client.get("/search/issues", {"q": f"is:pr {query}", "per_page": 20})
    if not data["items"]:
        return "No pull requests found."
    return "\n".join(
        f"{item['repository_url'].split('/repos/')[1]}#{item['number']} [{item['state']}] {item['title']} "
        f"by {item['user']['login']} - {item['html_url']}"
        for item in data["items"]
    )


@tool
async def get_pull_request(repo: str, number: int) -> str:
    """Get a pull request's details. `repo` is "owner/name"."""
    pr = await github_client.get(f"/repos/{repo}/pulls/{number}")
    return (
        f"{repo}#{number}: {pr['title']}\n"
        f"state: {pr['state']}{' (merged)' if pr.get('merged') else ''}, author: {pr['user']['login']}\n"
        f"{pr['head']['ref']} -> {pr['base']['ref']}, +{pr['additions']}/-{pr['deletions']} in {pr['changed_files']} files\n"
        f"url: {pr['html_url']}\n\n{pr.get('body') or '(no description)'}"
    )


@tool
async def get_pr_diff(repo: str, number: int) -> str:
    """Get a pull request's unified diff. `repo` is "owner/name"."""
    diff = await github_client.get(f"/repos/{repo}/pulls/{number}", accept="application/vnd.github.diff")
    if len(diff) > MAX_DIFF_CHARS:
        return diff[:MAX_DIFF_CHARS] + f"\n... (diff truncated, {len(diff)} chars total)"
    return diff


@tool
async def get_pr_discussion(repo: str, number: int) -> str:
    """Get a pull request's conversation comments, reviews and inline review comments, oldest first."""
    comments = await github_client.get(f"/repos/{repo}/issues/{number}/comments", {"per_page": 100})
    reviews = await github_client.get(f"/repos/{repo}/pulls/{number}/reviews", {"per_page": 100})
    review_comments = await github_client.get(f"/repos/{repo}/pulls/{number}/comments", {"per_page": 100})
    entries = (
        [(c["created_at"], f"comment by {c['user']['login']}: {c['body']}") for c in comments]
        + [(r["submitted_at"] or "", f"review ({r['state']}) by {r['user']['login']}: {r['body'] or ''}") for r in reviews]
        + [(c["created_at"], f"inline comment by {c['user']['login']} on {c['path']}: {c['body']}") for c in review_comments]
    )
    if not entries:
        return "No comments or reviews."
    return "\n\n".join(f"[{when[:16]}] {text}" for when, text in sorted(entries))


PR_TOOLS = [search_pull_requests, get_pull_request, get_pr_diff, get_pr_discussion]


# --- orchestrator tool ---

@tool
async def ask_github(question: str, config: RunnableConfig) -> str:
    """Ask the GitHub assistant a question about pull requests: finding PRs, their details, diffs,
    comments and reviews. Include the repo and PR number in the question when known."""
    from apps.agent.github_agent import run_github_agent  # imported here to avoid a circular import

    return await run_github_agent(question, config["configurable"].get("ctx"))
