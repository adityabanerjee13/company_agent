# company-agent

A Slack AI coworker (demo). It:

- **stores every Slack message** it can see (DMs and channels it has joined) in SQLite, and can **search them with BM25**;
- **GitHub Agent**: answers questions about **GitHub pull requests** (details, diffs, comments, reviews) through a separate, read-only GitHub agent;
- **Coding Jobs**: runs **coding jobs**: Claude Code or Codex, on the requesting user's own subscription, in a local Docker container, then opens a PR and posts the link in the Slack thread.
- **Orchestrator**: called for every mention of AI-coworker in slack. It has tool to search_messages for the user, call github_agent or call coding_agent.

## Quick start

Needs Python 3.13 with [uv](https://docs.astral.sh/uv/), Docker, and Node (for the dashboard). Create the Slack app and GitHub token first (see [Setup](#setup)).

Install uv if you don't have it, then open a new terminal so it is on your `PATH`:

```powershell
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Or `pip install uv`. uv fetches Python 3.13 itself if it isn't installed (the version is pinned in `.python-version`).

```powershell
uv sync
cp .env.example .env                                  # fill in Slack, OpenRouter and GitHub tokens
cp subscriptions.example.json subscriptions.json      # add Claude/Codex tokens per Slack user
```

add Claude/Codex tokens per Slack user in the `subscriptions.json`. This will give access to the coding agent and help run coding jobs.

```powershell
docker build -t coding-agent-sandbox sandbox/         # image for coding jobs

uv run python -m apps.main                            # start the bot
```

### Getting the Claude and Codex credentials

Coding jobs run on the requesting user's own subscription, so each user who wants them needs an entry in `subscriptions.json`. The key is their Slack member ID: in Slack, open their profile, click **⋮** (More), then **Copy member ID** (it looks like `U0123ABCD`).

**Claude** (needs a Claude Pro or Max plan). On any machine:

```powershell
npm install -g @anthropic-ai/claude-code
claude setup-token
```

It opens a browser to sign in, then prints a long-lived token starting with `sk-ant-oat01-`. Put it in `token`:

```json
"U0123ABCD": { "name": "Asha", "provider": "claude", "token": "sk-ant-oat01-..." }
```

**Codex** (needs a ChatGPT plan that includes Codex). On any machine:

```powershell
npm install -g @openai/codex
codex login
Get-Content $HOME\.codex\auth.json      # macOS / Linux: cat ~/.codex/auth.json
```

`codex login` opens a browser to sign in with ChatGPT and writes `auth.json`. Paste that file's whole JSON object, unchanged, as `auth_json`. It must be an object, not a string:

```json
"U0456EFGH": { "name": "Ravi", "provider": "codex", "auth_json": { "OPENAI_API_KEY": null, "tokens": { "...": "..." }, "last_refresh": "..." } }
```

Both are credentials for the user's account: treat them like passwords and don't commit `subscriptions.json` (it is gitignored). The bot reads the file only at startup, so restart it after editing. If a user's jobs start failing with an authentication error, have them run the command again and replace their entry. A Codex login can expire after its tokens are refreshed elsewhere.

Then @mention the bot in a channel it has joined, or DM it. To view messages and traces, in a second terminal:

```powershell
cd dashboard/web; npm install; npm run build; cd ../..
uv run python -m dashboard                            # http://127.0.0.1:8787
```

## Demo

Asking the bot in a channel to add a Decision Tree option to a repo's CLI starts a coding job:

![Coding job started from a Slack mention](demo/Screenshot%202026-10-12%20151054.png)

When the job finishes, the bot posts the PR link and a summary of the change and its test runs in the thread:

![Coding job finished with PR link and summary](demo/Screenshot%202026-10-12%20151448.png)

The PR the job opened (#3) on GitHub:

![Pull requests opened by coding jobs](demo/Screenshot%202026-10-12%20151509.png)

Traces visualization in the dashboard: [demo recording (Google Drive)](https://drive.google.com/file/d/19E7yr3bexCCgpU6lSsUBOdaOnU2QwQIM/view?usp=drive_link)

## Layout

```
apps/
  main.py            entrypoint: python -m apps.main
  config.py          env vars
  db.py              SQLite connection + schema
  github_client.py   GitHub REST helpers
  slack/             Bolt app (event handlers) + turn context
  stores/            data access, one file per table: users, channels, messages, jobs
  agent/             LLM, prompts, orchestrator agent, GitHub sub-agent
  tools/             LLM-facing tools: knowledge (BM25), github, coding
  coding_job/        linear coding-job workflow, Docker sandbox, prompt
sandbox/Dockerfile   image the coding jobs run in
```

To add a capability: add a tool in `tools/` and register it in `tools/__init__.py`. New data gets a file in `stores/` and a table in `db.py`.

**Keeping the Slack log current.** The bot is the only process that writes to `agent.db`. Live Slack events store new messages, edits and deletes as they happen. A catch-up sync in the bot (`apps/slack/sync.py`) runs at startup and every 5 minutes to fill in whatever the events missed while the bot was stopped or reconnecting. Once a day it also checks the last 30 days for messages deleted in Slack. Deleted messages are kept but hidden (`deleted_at`).

**Two kinds of history.** The `messages` table is the raw Slack log, reachable through the `search_messages` tool. The orchestrator's own context is per Slack thread and kept in memory by the LangGraph checkpointer. The first turn in a thread also sees the last 20 messages of that channel or DM. The checkpointer is in memory, so thread context resets when the bot restarts. The Slack log persists.

## Traces

Every agent run is saved locally under `traces/` (gitignored):

```
traces/
  orchestrator/<channel>_<thread_ts>/<time>.json   one per Slack turn: input, every model call, tool call
                                                   and tool result in that turn, token usage, timing, error
  github_agent/<channel>_<thread_ts>/<time>.json   one per ask_github call, same format
  coding_jobs/<job_id>/
    prompt.txt           prompt given to Claude Code / Codex
    steps.json           every workflow step: command, timing, output, error (env values never saved)
    agent_output.jsonl   the agent's event stream: each message and tool use
    agent_session/       the agent's own session transcript, copied out of the container before removal
    summary.txt          the agent's final summary
    job.json             the final jobs row
```

The orchestrator and GitHub folders share the Slack thread name, so you can line up one conversation across both.

## Setup

1. **Slack app** (api.slack.com/apps):
   - Turn on Socket Mode. Create an app-level token with `connections:write` (`SLACK_APP_TOKEN`).
   - Bot token scopes: `app_mentions:read`, `chat:write`, `channels:history`, `groups:history`, `im:history`, `mpim:history`, `channels:read`, `groups:read`, `im:read`, `mpim:read`, `users:read`.
   - Event subscriptions (bot events): `app_mention`, `message.channels`, `message.groups`, `message.im`, `channel_rename`, `channel_archive`, `channel_unarchive`, `group_rename`, `group_archive`, `group_unarchive`, `member_joined_channel`.
   - App Home: enable the Messages tab so users can DM the bot.
   - Install the app and copy the bot token (`SLACK_BOT_TOKEN`). Invite the bot to the channels it should read.
2. **GitHub token** (`GITHUB_TOKEN`): a fine-grained PAT with Pull requests R/W, Contents R/W and Issues R on the repos the bot should see.
3. **Environment:** `cp .env.example .env` and fill it in. Optional: `SLACK_USER_TOKEN` (an xoxp token, so the sync can read every conversation that user can see), `SLACK_SYNC_INTERVAL_SECONDS` (300), `SLACK_SYNC_LOOKBACK_HOURS` (24, how far back each pass re-reads to catch edits), `SLACK_PRUNE_DAYS` (30) and `SLACK_PRUNE_INTERVAL_HOURS` (24) for the deleted-message check.
4. **Subscriptions:** `cp subscriptions.example.json subscriptions.json`, then add one entry per Slack user ID. Claude users need the token from `claude setup-token`. Codex users need the contents of `~/.codex/auth.json` after `codex login`. See [Getting the Claude and Codex credentials](#getting-the-claude-and-codex-credentials) for the steps. The file is loaded into the `users` table at startup.
5. **Sandbox image:** `docker build -t coding-agent-sandbox sandbox/`. Docker must be running on the bot's host.
6. **Run:** `uv sync` then `uv run python -m apps.main`. The first start after updating from a version where `messages` was keyed on `ts` alone migrates the table to `(channel_id, ts)`: stop the bot and copy `agent.db` first.
7. **Tests:** `uv run pytest`.

## Using it

- DM the bot, or @mention it in a channel. It replies in a thread.
- "What did we decide about the release date?" uses message search.
- "Summarise owner/repo#42 and its review comments" goes to the GitHub agent.
- "Fix the typo in the README of owner/repo on main" or "Implement https://github.com/owner/repo/issues/7 on main" starts a coding job. It works only for users listed in `subscriptions.json`.

Check that each provider's terms allow subscription tokens to be used this way before relying on it.

## Running the bot

After [Setup](#setup), from the project root:

```powershell
uv sync                         # install dependencies
uv run python -m apps.main      # start the bot
```

On startup it:

1. creates `agent.db` (or `DB_PATH`) and its tables if they don't exist, migrating older schemas;
2. loads `subscriptions.json` into the `users` table and prints `loaded N user subscriptions`;
3. connects to Slack over Socket Mode, so no public URL or port is needed;
4. starts the background Slack sync, which catches up on messages missed while it was off.

It needs `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN` and `OPENROUTER_API_KEY` in `.env` and exits with an error if any is missing. Coding jobs also need Docker running and the `coding-agent-sandbox` image built. Stop it with Ctrl+C. Thread context is kept in memory and lost on restart; stored messages and traces persist. Run only one instance at a time, since it is the only writer to the database.

## Dashboard

A read-only web view over `agent.db` and `traces/`:

```powershell
uv run python -m dashboard            # http://127.0.0.1:8787  (--port to change)
```

- **Slack**: channels, DMs and threads as Slack shows them. The user picker filters to one person's conversations and messages.
- **Messages that @mention the bot** link to the orchestrator trace for that turn (matched on the message `ts`). Mentions from before tracing was added show "no trace recorded".
- **Orchestrator run**: the prompt (with the thread history collapsed), each model call with its text and token usage, and every tool call, expandable to show its arguments and result. `ask_github` calls open the GitHub agent run, and `start_coding_job` calls open the coding job.
- **Coding job**: the task, the prompt given to Claude, each workflow step run in the Docker sandbox (command, output, errors) and the parsed Claude session from inside the sandbox.

It reads `DB_PATH` and `TRACES_DIR` from the environment (defaults `agent.db`, `traces`). It opens the database read-only and never writes, so it is safe to run while the bot runs. The sync status in the sidebar is the one the bot saves; it shows an error until the bot has started. Deleted Slack messages are hidden. It never reads `users.credential`.
