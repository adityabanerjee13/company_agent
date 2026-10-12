import os

from dotenv import load_dotenv

load_dotenv()


def _required(name):
    value = os.environ.get(name)
    if not value:
        raise ValueError(f"{name} must be set in the environment variables.")
    return value


SLACK_BOT_TOKEN = _required("SLACK_BOT_TOKEN")
SLACK_APP_TOKEN = _required("SLACK_APP_TOKEN")
OPENROUTER_API_KEY = _required("OPENROUTER_API_KEY")
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "x-ai/grok-4.6")

# a GitHub token used for PR reads, clone/push and PR creation
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

SANDBOX_IMAGE = os.environ.get("SANDBOX_IMAGE", "coding-agent-sandbox")
SANDBOX_TIMEOUT_SECONDS = int(os.environ.get("SANDBOX_TIMEOUT_SECONDS", "900"))

SUBSCRIPTIONS_FILE = os.environ.get("SUBSCRIPTIONS_FILE", "subscriptions.json")
DB_PATH = os.environ.get("DB_PATH", "agent.db")
TRACES_DIR = os.environ.get("TRACES_DIR", "traces")

HISTORY_PREFIX_LIMIT = 20

# catch-up sync (apps/slack/sync.py); a user token (xoxp) reads every conversation that user can see
SLACK_USER_TOKEN = os.environ.get("SLACK_USER_TOKEN") or None
SLACK_SYNC_INTERVAL_SECONDS = int(os.environ.get("SLACK_SYNC_INTERVAL_SECONDS", "300"))
SLACK_SYNC_LOOKBACK_HOURS = int(os.environ.get("SLACK_SYNC_LOOKBACK_HOURS", "24"))
SLACK_PRUNE_DAYS = int(os.environ.get("SLACK_PRUNE_DAYS", "30"))
SLACK_PRUNE_INTERVAL_HOURS = int(os.environ.get("SLACK_PRUNE_INTERVAL_HOURS", "24"))
