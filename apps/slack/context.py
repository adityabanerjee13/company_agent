import re

MENTION = re.compile(r"<@[A-Z0-9]+>")


def build(event):
    """The turn context passed to the orchestrator and its tools."""
    return {
        "user_id": event["user"],
        "channel_id": event["channel"],
        "channel_type": event.get("channel_type", "channel"),
        "ts": event["ts"],
        # replies always go in a thread
        "thread_ts": event.get("thread_ts") or event["ts"],
    }


def clean_text(event):
    """Message text with the bot's @mention removed."""
    return MENTION.sub("", event.get("text", "")).strip()
