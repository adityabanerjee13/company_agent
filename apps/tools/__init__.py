from apps.tools.coding import start_coding_job
from apps.tools.github import ask_github
from apps.tools.knowledge import search_messages


def get_orchestrator_tools():
    return [search_messages, ask_github, start_coding_job]
