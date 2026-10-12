"""Separate LangGraph agent for GitHub PRs, so its tool output never fills the orchestrator's context."""
from datetime import datetime, timezone

from langchain.agents import create_agent

from apps.agent.llm import get_llm
from apps.agent.prompts import GITHUB_AGENT_PROMPT
from apps.tools.github import PR_TOOLS
from apps.traces import save_agent_trace

github_agent = create_agent(get_llm(), tools=PR_TOOLS, system_prompt=GITHUB_AGENT_PROMPT)


async def run_github_agent(question, ctx=None):
    started_at = datetime.now(timezone.utc)
    messages = []
    try:
        # stream so the trace keeps every step even if the run fails midway
        async for chunk in github_agent.astream(
            {"messages": [("user", question)]}, {"recursion_limit": 25}, stream_mode="values"
        ):
            messages = chunk["messages"]
    except Exception as e:
        save_agent_trace("github_agent", ctx, question, messages, started_at, repr(e))
        raise
    save_agent_trace("github_agent", ctx, question, messages, started_at)
    return messages[-1].text
