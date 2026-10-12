from datetime import datetime, timezone

from langchain.agents import create_agent
from langgraph.checkpoint.memory import InMemorySaver

from apps import db
from apps.agent.llm import get_llm
from apps.agent.prompts import ORCHESTRATOR_PROMPT
from apps.config import HISTORY_PREFIX_LIMIT
from apps.stores.messages import recent_messages
from apps.tools import get_orchestrator_tools
from apps.traces import save_agent_trace

# the orchestrator's context is per Slack thread and lives in the checkpointer,
# separate from the raw Slack message log in the messages table
orchestrator = create_agent(
    get_llm(),
    tools=get_orchestrator_tools(),
    system_prompt=ORCHESTRATOR_PROMPT,
    checkpointer=InMemorySaver(),
)


def _history_prefix(ctx):
    # exclude the message being answered, it is sent as the user turn
    history = [m for m in recent_messages(ctx["channel_id"], HISTORY_PREFIX_LIMIT + 1) if m["ts"] != ctx["ts"]]
    if not history:
        return ""
    lines = [f"<@{m['user_id']}>: {m['text']}" if m["user_id"] != "bot" else f"you: {m['text']}" for m in history]
    return "[Earlier messages in this conversation]\n" + "\n".join(lines[-HISTORY_PREFIX_LIMIT:]) + "\n\n"


async def run_turn(ctx, text):
    config = {
        "configurable": {"thread_id": f"{ctx['channel_id']}:{ctx['thread_ts']}", "ctx": ctx},
        "recursion_limit": 25,
    }
    state = await orchestrator.aget_state(config)
    previous = len(state.values.get("messages", []))
    prompt = (await db.read(_history_prefix, ctx) if not previous else "") + f"<@{ctx['user_id']}>: {text}"
    started_at = datetime.now(timezone.utc)
    try:
        result = await orchestrator.ainvoke({"messages": [("user", prompt)]}, config)
    except Exception as e:
        # save whatever the checkpointer holds for this turn before re-raising
        state = await orchestrator.aget_state(config)
        save_agent_trace("orchestrator", ctx, prompt, state.values.get("messages", [])[previous:], started_at, repr(e))
        raise
    # only this turn's messages; earlier turns are already in earlier trace files
    save_agent_trace("orchestrator", ctx, prompt, result["messages"][previous:], started_at)
    return result["messages"][-1].text
