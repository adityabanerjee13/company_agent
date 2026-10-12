import asyncio
import logging

from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_bolt.async_app import AsyncApp
from slack_sdk.errors import SlackApiError

from apps import config, db
from apps.agent.orchestrator import run_turn
from apps.config import SLACK_APP_TOKEN, SLACK_BOT_TOKEN
from apps.slack import context
from apps.slack.sync import SlackSync
from apps.stores.channels import upsert_channel, upsert_conversation
from apps.stores.messages import apply_event, save_message

log = logging.getLogger(__name__)
app = AsyncApp(token=SLACK_BOT_TOKEN)

# the bot's own ids, so its posts are stored as user "bot"; set in start() before any event arrives
_me = {"user_id": None, "bot_id": None}
# keep a reference so the sync task is not garbage collected
_tasks = set()


async def respond(event, say):
    ctx = context.build(event)
    try:
        reply = await run_turn(ctx, context.clean_text(event))
    except Exception:
        log.exception("turn failed")
        reply = "Sorry, something went wrong while handling that."
    resp = await say(text=reply, thread_ts=ctx["thread_ts"])
    await db.write(save_message, resp["ts"], ctx["channel_id"], ctx["thread_ts"], "bot", reply)


@app.event("message")
async def on_message(event, say):
    # store every message event (new, edited, deleted, from people and bots) in every conversation the bot is in
    if event.get("channel_type"):
        await db.write(upsert_channel, event["channel"], event["channel_type"])
    await db.write(apply_event, event, _me["user_id"], _me["bot_id"])
    # reply only to plain user messages in DMs; in channels the bot only answers @mentions (app_mention)
    if event.get("bot_id") or event.get("subtype"):
        return
    if event.get("channel_type") == "im":
        await respond(event, say)


@app.event("app_mention")
async def on_mention(event, say):
    await respond(event, say)


async def _refresh_channel(client, channel_id):
    try:
        info = await client.conversations_info(channel=channel_id)
    except SlackApiError as e:
        log.warning("conversations.info %s: %s", channel_id, e.response.get("error"))
        return
    await db.write(upsert_conversation, info["channel"])


@app.event("channel_rename")
@app.event("group_rename")
async def on_rename(event, client):
    await _refresh_channel(client, event["channel"]["id"])


@app.event("channel_archive")
@app.event("channel_unarchive")
@app.event("group_archive")
@app.event("group_unarchive")
async def on_archive(event, client):
    await _refresh_channel(client, event["channel"])


@app.event("member_joined_channel")
async def on_member_joined(event, client):
    if event.get("user") == _me["user_id"]:  # the bot was added: record the channel now, not at the next sync
        await _refresh_channel(client, event["channel"])


async def start():
    me = await app.client.auth_test()
    _me.update(user_id=me.get("user_id"), bot_id=me.get("bot_id"))
    sync = SlackSync(SLACK_BOT_TOKEN, config.SLACK_USER_TOKEN, interval_s=config.SLACK_SYNC_INTERVAL_SECONDS,
                     lookback_hours=config.SLACK_SYNC_LOOKBACK_HOURS, prune_days=config.SLACK_PRUNE_DAYS,
                     prune_interval_hours=config.SLACK_PRUNE_INTERVAL_HOURS)
    task = asyncio.create_task(sync.run())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    await AsyncSocketModeHandler(app, SLACK_APP_TOKEN).start_async()
