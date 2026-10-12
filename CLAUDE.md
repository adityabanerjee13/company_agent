# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Slack AI coworker (demo): keeps a SQLite copy of every Slack message it can see, including edits and deletes, and searches them with BM25, answers GitHub PR questions via a read-only sub-agent, and runs coding jobs (Claude Code or Codex on the requesting user's own subscription, inside a Docker container) that end in a PR. See [README.md](README.md) for Slack/GitHub app setup.

## Commands

Python 3.13, managed with `uv`. Developed on Windows/PowerShell.

```powershell
uv sync                                           # install deps
uv run python -m apps.main                        # run the bot (Socket Mode; needs .env)
uv run python -m dashboard                        # read-only web UI on http://127.0.0.1:8787 (--port, --host)
docker build -t coding-agent-sandbox sandbox/     # image coding jobs run in; Docker must be running
uv run python -m sqlite3 agent.db                 # inspect the DB (see DB_QUERIES.md)
```

Tests: `uv run pytest` (`tests/`: message normalization and the schema migration; no Slack or `.env` needed). There is no linter or formatter configured.

## Architecture

**Request flow.** `apps/slack/app.py` (Bolt, Socket Mode) stores every `message` event, of any subtype and from people or bots, through `slack/normalize.py`: new messages are upserted, `message_changed` updates the row, `message_deleted` and `tombstone` set `deleted_at`. It replies only to plain user messages in DMs and to `app_mention` in channels, always in a thread. Channel rename/archive/join events refresh the `channels` row. `slack/context.py` builds the turn `ctx` dict (`user_id`, `channel_id`, `channel_type`, `ts`, `thread_ts`), which `run_turn` passes to tools through `config["configurable"]["ctx"]`. Tools read it from a `config: RunnableConfig` parameter. That is how a tool knows the current user and channel.

**Orchestrator** (`apps/agent/orchestrator.py`): a LangChain `create_agent` with an `InMemorySaver` checkpointer, keyed on `thread_id = "<channel>:<thread_ts>"`. On the first turn of a thread it prepends the last `HISTORY_PREFIX_LIMIT` (20) channel messages. Thread context is lost on restart. The `messages` table persists. All LLM calls go through OpenRouter via `ChatOpenAI` (`apps/agent/llm.py`, model from `OPENROUTER_MODEL`).

**Tools** (`apps/tools/`, registered in `tools/__init__.py:get_orchestrator_tools`):
- `search_messages`: BM25Plus over all stored messages of the *current* channel or DM only.
- `ask_github`: delegates to a separate agent (`agent/github_agent.py`) with the read-only `PR_TOOLS`, so diffs and comments never enter the orchestrator's context. It is imported lazily inside the tool to avoid a circular import.
- `start_coding_job`: validates the user has a subscription and that the branch exists, inserts a `jobs` row, and fires `run_coding_job` as a background asyncio task (references kept in `_running`).

**Coding job** (`apps/coding_job/workflow.py`): a fixed, linear sequence of steps, not a graph. It starts a container (`sandbox.py`, docker SDK wrapped in `asyncio.to_thread`), clones with the token passed only via exec env, runs `claude -p ... --dangerously-skip-permissions` or `codex exec ...` as user `agent` (uid 1001), then commits, pushes `agent/<job_id>`, opens a PR via `github_client.py`, and posts to the Slack thread. Every `step()` is recorded to `traces/coding_jobs/<job_id>/steps.json`. Env *values* are never recorded, only keys. Only the agent's session transcript dirs are copied out of the container, never all of `~/.claude` or `~/.codex`, because those hold credentials.

**Slack sync** (`apps/slack/sync.py`): a background task in the bot that re-reads Slack through the Web API at startup and every `SLACK_SYNC_INTERVAL_SECONDS` (300) to fill in what live events missed. Per-channel cursor plus a lookback window, threads re-read when `latest_reply` moves, older active threads rescanned at startup and daily, and a daily pass that marks top-level messages missing from Slack as deleted. It writes its status to `sync_state['sync_status']` for the dashboard. It polls rather than opening a second Socket Mode connection, which would take events from the bot.

**Data** (`apps/db.py`, `apps/schema.py`): one `sqlite3` connection per thread, WAL mode, `busy_timeout` 5s. **The bot is the only writer.** Async code must not call store functions directly: use `await db.write(fn, ...)` (one dedicated writer thread, so writes never contend) or `await db.read(fn, ...)` (`asyncio.to_thread`). Sync LangChain tools already run in executor threads and call stores directly. Tables: `users`, `channels`, `messages` (key `(channel_id, ts)`; a Slack `ts` is unique only per channel), `jobs`, `slack_users`, `sync_state`. Readers use the `visible_messages` view, which hides deleted messages and the `raw` JSON. `stores/` has one file of plain functions per table. `users` is upserted from `subscriptions.json` at startup (`stores/users.py:sync_from_file`). `users.credential` holds plaintext tokens: never select or log it.

**Traces** (`apps/traces.py`): every orchestrator turn and GitHub-agent run is written to `traces/<agent>/<channel>_<thread_ts>/<time>.json`, including on failure. Keep this behaviour when changing agent code: the dashboard depends on it.

**Dashboard** (`dashboard/`): FastAPI plus a React UI (`dashboard/web`, build with `npm run build`; `dist/` is gitignored). It opens `agent.db` read-only, never writes, and reads `traces/`. `live.py` checks `PRAGMA data_version` every 1.5s to push changes over SSE. It deliberately does **not** import `apps.config`, because that module raises if Slack/OpenRouter secrets are missing. `dashboard/data.py` links the pieces: a Slack message `ts` equals the orchestrator trace `ctx.ts`, and the `"Job <id> started"` tool result maps to `traces/coding_jobs/<id>`.

## Conventions

- New capability: add a `@tool` in `apps/tools/` and register it in `tools/__init__.py`. New persisted data: a file in `stores/` plus a table in `schema.py` (schema is `CREATE TABLE IF NOT EXISTS`, new columns go through `_add_columns`, and key changes need a copy-table migration like `_migrate_messages`).
- Anything that stores Slack messages goes through `apps/slack/normalize.py`, so live events and the sync store them the same way.
- `apps/config.py` reads env at import time and requires `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`, `OPENROUTER_API_KEY`. Importing almost anything under `apps/` therefore needs a populated `.env`.
- `plan.md` is the original brief and is **out of date**: it specifies MongoDB, an explicit `StateGraph`, Fernet encryption, a GitHub App, skills and to-dos. None of these were built. Treat the code and README as the source of truth.
- `.env`, `subscriptions.json`, `*.db` and `traces/` are gitignored and contain secrets or user data.
