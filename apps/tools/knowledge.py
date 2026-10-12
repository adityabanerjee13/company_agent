import re

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from rank_bm25 import BM25Plus

from apps.stores.messages import all_in_channel


def _tokenize(text):
    return re.findall(r"\w+", text.lower())


@tool
def search_messages(query: str, config: RunnableConfig, k: int = 8) -> str:
    """Keyword search over past Slack messages in the current channel or DM. Returns the best matches."""
    ctx = config["configurable"]["ctx"]
    messages = all_in_channel(ctx["channel_id"])
    if not messages:
        return "No messages stored for this conversation yet."
    # BM25Plus keeps idf positive, so it also works on small conversations
    docs = [_tokenize(m["text"]) for m in messages]
    query_tokens = _tokenize(query)
    scores = BM25Plus(docs).get_scores(query_tokens)
    ranked = sorted(zip(scores, docs, messages), key=lambda item: item[0], reverse=True)
    hits = [m for _, doc, m in ranked if set(query_tokens) & set(doc)][:k]
    if not hits:
        return "No matching messages."
    return "\n".join(f"[<@{m['user_id']}> @ {m['created_at'][:16]}] {m['text']}" for m in hits)
