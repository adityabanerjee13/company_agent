from langchain_openai import ChatOpenAI

from apps.config import OPENROUTER_API_KEY, OPENROUTER_MODEL


def get_llm():
    return ChatOpenAI(model=OPENROUTER_MODEL, base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY)
