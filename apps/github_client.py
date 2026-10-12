"""Thin wrapper over the GitHub REST API, shared by the PR tools and the coding job."""
import httpx

from apps.config import GITHUB_TOKEN

API = "https://api.github.com"


def _headers(accept="application/vnd.github+json"):
    headers = {"Accept": accept, "X-GitHub-Api-Version": "2022-11-28"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return headers


async def get(path, params=None, accept="application/vnd.github+json"):
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{API}{path}", params=params, headers=_headers(accept))
        resp.raise_for_status()
        return resp.text if accept.endswith("diff") else resp.json()


async def post(path, payload):
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{API}{path}", json=payload, headers=_headers())
        resp.raise_for_status()
        return resp.json()


def parse_issue_url(url):
    """https://github.com/owner/repo/issues/12 -> ("owner/repo", 12)"""
    parts = url.rstrip("/").split("/")
    return f"{parts[-4]}/{parts[-3]}", int(parts[-1])


async def get_default_branch(repo):
    return (await get(f"/repos/{repo}"))["default_branch"]


async def list_branches(repo):
    return [b["name"] for b in await get(f"/repos/{repo}/branches", {"per_page": 100})]


async def get_issue(url):
    repo, number = parse_issue_url(url)
    issue = await get(f"/repos/{repo}/issues/{number}")
    return {"number": number, "title": issue["title"], "body": issue.get("body") or ""}


async def create_pull_request(repo, head, base, title, body):
    pr = await post(f"/repos/{repo}/pulls", {"head": head, "base": base, "title": title, "body": body})
    return pr["html_url"]
