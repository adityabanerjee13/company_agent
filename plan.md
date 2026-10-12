# Handoff: Slack AI agent — implementation plan

This document is the complete brief for implementing the Slack AI agent. Build exactly what is described here. Do not add features, services, dashboards or abstractions that are not listed. If something is ambiguous, stop and ask rather than invent.

---

## 1. What we are building

A Slack bot used by a changing set of company users. Each user is registered by an admin and linked to a Claude or Codex **subscription token**. The bot is a LangGraph agent with five capabilities:

1. **GitHub PRs**: read PRs, read PR comments and reviews, post review comments. Nothing else on GitHub.
2. **Knowledge base**: per-user knowledge (configured off) and message history, plus per-channel (group chat) knowledge (configured off) and message history. Stored in MongoDB.
3. **Skills**: per-user saved workflows. Users can create, update, delete, list and run them. A skill is created either from a description, or from a task the user just performed in the conversation.
4. **To-dos**: set and track to-dos for all users.
5. **Coding job**: given a repo, a branch and an issue (a Slack description, a GitHub issue link, or both), start a Docker sandbox. In it, run Claude Code or Codex on the requesting user's subscription to resolve the issue, then raise a PR. The coding job is a **fixed, linear workflow**, not a LangGraph graph.

## 2. Fixed decisions

| Topic | Decision |
|---|---|
| Language | Python 3.12, all backend code under `./apps` |
| Database | MongoDB, using the PyMongo async API (`pymongo.AsyncMongoClient`). Do not use Motor. |
| Orchestration | LangGraph `StateGraph` (explicit graph, not a prebuilt agent) |
| Slack | `slack_bolt` async app in **Socket Mode** |
| User credentials | Subscription tokens. Claude: OAuth token from `claude setup-token`. Codex: the `auth.json` produced by `codex login`. |
| GitHub identity | A single company **GitHub App**. All reviews, comments, pushes and PRs appear as the bot. |
| Sandbox | Docker on one host, driven by the `docker` Python SDK, one container per job |
| Coding-job input | A Slack description, a GitHub issue URL, or both |
| Job queue | The MongoDB `jobs` collection. Do not add Redis, Celery or similar. |
| Secrets at rest | User credentials encrypted with Fernet (`cryptography`) under the `MASTER_KEY` env var |
| KB retrieval | MongoDB text index (`$text`). Do not add embeddings or a vector DB. |

### Assumption to confirm before milestone 3

Subscription tokens are supported by the Claude Code CLI and the Codex CLI. They are **not** supported by chat-model API clients such as LangChain's `ChatAnthropic` or `ChatOpenAI`. Because of this:

- **The LangGraph orchestrator uses one company API key**, configured via `ORCHESTRATOR_MODEL` and the provider's API key env var. It is loaded through `langchain.chat_models.init_chat_model`.
- **Each user's subscription token is used only inside that user's coding-job sandbox.**

Also confirm with the owner that each provider's terms allow subscription tokens to be used in this automated, server-side way.

## 3. Repository structure

```
.
├── apps/
│   ├── __init__.py
│   ├── main.py                 # entrypoint: `python -m apps.main bot|worker`
│   ├── config.py               # pydantic-settings; all env vars
│   ├── db.py                   # Mongo client, collection handles, index creation
│   ├── crypto.py               # Fernet encrypt/decrypt for credentials
│   ├── admin.py                # CLI: add-user, update-credential, remove-user, list-users
│   ├── github_app.py           # GitHub App JWT -> installation token; issue fetch; PR create
│   ├── slack/
│   │   ├── __init__.py
│   │   ├── app.py              # Bolt app + event handlers
│   │   └── context.py          # resolve user + scope (DM vs channel) for an event
│   ├── stores/                 # plain data-access functions, one file per collection
│   │   ├── __init__.py
│   │   ├── users.py
│   │   ├── channels.py
│   │   ├── messages.py
│   │   ├── knowledge.py
│   │   ├── skills.py
│   │   ├── todos.py
│   │   └── jobs.py
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── state.py            # AgentState TypedDict
│   │   ├── llm.py              # init_chat_model from config
│   │   ├── prompts.py          # system prompt template
│   │   ├── graph.py            # StateGraph build + run_turn()
│   │   └── memory.py           # KB fact extraction (user + channel)
│   ├── tools/                  # every LLM-facing tool and the GitHub MCP client
│   │   ├── __init__.py         # get_tools(config) -> list of tools
│   │   ├── github_mcp.py
│   │   ├── knowledge.py
│   │   ├── skills.py
│   │   ├── todos.py
│   │   └── coding.py           # start_coding_job tool (enqueues only)
│   └── coding_job/
│       ├── __init__.py
│       ├── worker.py           # polls jobs collection, runs workflow
│       ├── workflow.py         # linear steps, no graph
│       ├── sandbox.py          # Docker container lifecycle + exec with timeout
│       └── prompt.py           # prompt template sent to Claude Code / Codex
├── sandbox/
│   └── Dockerfile              # image used for coding jobs
├── tests/
├── Dockerfile                  # image for bot + worker
├── docker-compose.yml          # mongo, bot, worker
├── pyproject.toml
├── .env.example
└── README.md
```

Rules:
- `tools/` contains only LLM-facing tool definitions and the MCP client. They call `stores/`, and must never touch Mongo directly.
- `stores/` functions are plain `async def` functions that take and return dicts. Do not build a repository-class hierarchy or an ORM.

## 4. Configuration (`apps/config.py`, `.env.example`)

```
MONGO_URI=mongodb://mongo:27017
MONGO_DB=slack_agent
MASTER_KEY=                      # Fernet key

SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...         # Socket Mode, connections:write

ORCHESTRATOR_MODEL=anthropic:<model-id>   # passed to init_chat_model
ANTHROPIC_API_KEY=               # or OPENAI_API_KEY, matching ORCHESTRATOR_MODEL

GITHUB_APP_ID=
GITHUB_APP_PRIVATE_KEY_PATH=
GITHUB_APP_INSTALLATION_ID=
GITHUB_MCP_COMMAND=github-mcp-server     # binary path for stdio mode
GITHUB_MCP_TOOL_ALLOWLIST=               # comma-separated, see §8.1

HISTORY_LIMIT=30                 # messages loaded into context per turn
CHANNEL_EXTRACT_EVERY=20         # new channel messages between KB extractions

SANDBOX_IMAGE=slack-agent-sandbox:latest
SANDBOX_TIMEOUT_SECONDS=2700
SANDBOX_MEM_LIMIT=4g
SANDBOX_CPUS=2
MAX_CONCURRENT_JOBS=4            # global; per-user limit is fixed at 1
```

## 5. MongoDB data model (`apps/db.py` creates the indexes on startup)

**users**
```
{ _id, slack_user_id, display_name,
  provider: "claude" | "codex",
  credential_enc: <bytes>,       # claude: oauth token; codex: auth.json contents
  active: bool, created_at, updated_at }
index: slack_user_id unique
```

**channels**
```
{ _id, slack_channel_id, name, msgs_since_extract: int, created_at }
index: slack_channel_id unique
```

**messages**: message history for DMs and group channels.
```
{ _id, scope_type: "dm" | "channel",
  scope_id,                      # dm: users._id ; channel: slack_channel_id
  slack_ts, thread_ts | null,
  author_slack_id,               # "bot" for bot messages
  text,
  tool_calls: [{ name, args, result_summary }],   # bot messages only; used for "skill from task"
  created_at }
indexes: (scope_type, scope_id, created_at), (scope_id, thread_ts, created_at), slack_ts unique
```

**knowledge**
```
{ _id, scope_type: "user" | "channel", scope_id,
  content: str,                  # one fact / note per document
  source: "extracted" | "explicit",
  source_ts,                     # slack ts it came from
  created_at, updated_at }
indexes: (scope_type, scope_id), text index on content
```

**skills**
```
{ _id, owner_user_id, name, description, instructions,   # instructions = markdown steps
  created_from: "description" | "task",
  created_at, updated_at }
index: (owner_user_id, name) unique
```

**todos**
```
{ _id, created_by_user_id, assignee_user_id, title, notes,
  status: "open" | "done", due_date | null,
  slack_channel_id, slack_thread_ts,
  created_at, updated_at, completed_at | null }
indexes: (assignee_user_id, status), (created_by_user_id, status)
```

**jobs**
```
{ _id, requested_by_user_id, provider,
  repo: "owner/name", base_branch, instructions | null, issue_url | null,
  status: "queued" | "running" | "succeeded" | "failed",
  slack_channel_id, slack_thread_ts,
  head_branch | null, pr_url | null, error | null, log_tail | null,
  created_at, started_at | null, finished_at | null }
indexes: (status, created_at), (requested_by_user_id, status)
```

## 6. User lifecycle (`apps/admin.py`)

This is an argparse CLI, run as `python -m apps.admin <cmd>`:

- `add-user --slack-id U123 --name "Asha" --provider claude --credential-file token.txt`
- `add-user ... --provider codex --credential-file ~/.codex/auth.json`
- `update-credential --slack-id U123 --credential-file ...`
- `remove-user --slack-id U123 [--purge]`: sets `active=false`. With `--purge`, it also deletes the user's knowledge, DM messages, skills and to-dos. Jobs are kept for audit.
- `list-users`

Credentials are always encrypted before they are written, and are never logged or echoed back.

## 7. Slack gateway (`apps/slack/`)

**App scopes**: `app_mentions:read`, `chat:write`, `channels:history`, `groups:history`, `im:history`, `im:read`, `users:read`.
**Events**: `app_mention`, `message.im`, `message.channels`, `message.groups`.

Handler behaviour:
1. Ignore bot messages, message edits and deletes, and any subtypes other than plain messages.
2. **Store every message.** This means all DMs to the bot, and every message in channels the bot is a member of. Store it in `messages` (upsert by `slack_ts`) and upsert the `channels` doc.
3. For channel messages, increment `msgs_since_extract`. When it reaches `CHANNEL_EXTRACT_EVERY`, schedule `memory.extract_channel(channel_id)` as a background task and reset the counter.
4. **Respond only** to DMs and to `app_mention` events in channels.
5. `context.py` resolves the sender to an active `users` doc. If there isn't one, reply in the thread "You are not registered with this bot. Ask an admin to add you." and stop.
6. Build the scope:
   - DM: `{type: "dm", user, channel_id, thread_ts}`
   - Channel: `{type: "channel", user, channel_id, thread_ts}`. Replies always go in a thread, so `thread_ts` is the event's `thread_ts`, or its `ts` if there is none.
7. Call `agent.graph.run_turn(scope, text)` in an `asyncio` task, so the Bolt `ack` is immediate. Post the final text in the thread. Store the bot reply in `messages`, including `tool_calls`.
8. On an exception, post a short error message in the thread and log the traceback.

## 8. LangGraph orchestrator (`apps/agent/`)

### State (`state.py`)
```python
class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    scope: dict            # from slack/context.py
    context_block: str     # rendered history + KB + skills list
```

### Graph (`graph.py`)
```
START -> load_context -> agent --(tool calls?)--> tools -> agent
                              \--(no tool calls)--> END
```
- **`load_context`**: builds `context_block` from:
  - History: the current Slack thread's messages first, then the last `HISTORY_LIMIT` messages of the scope (DM or channel).
  - KB hits: a `$text` search on the incoming message. In a DM, search the user's KB. In a channel, search the channel KB **and** the requesting user's KB.
  - The user's skills, as a list of `name — description` lines.
- **`agent`**: `llm.bind_tools(tools)`, called with the system prompt (`prompts.py`, which includes `context_block`) plus `messages`.
- **`tools`**: LangGraph `ToolNode`.
- **Recursion limit**: 25.
- **No checkpointer.** History is rebuilt from MongoDB on every turn.
- **Tool runtime context**: tools receive `user_id`, `scope` and the Slack channel/thread through `RunnableConfig["configurable"]`, read via an injected `config: RunnableConfig` parameter. The LLM never supplies these as arguments.
- **`run_turn(scope, text)`**: builds the graph once at module level. It invokes the graph and returns `(final_text, tool_call_summaries)`. It then schedules `memory.extract_user(...)` for DMs as a background task.

### System prompt rules (`prompts.py`)
- Say which user is speaking, and whether this is a DM or channel `#name`.
- In channels, do not reveal the user's personal KB unless it is directly needed to answer them.
- Before saving, updating or deleting a skill, show the draft or summary and wait for the user's confirmation in the next message. Apply the same rule before deleting a to-do.
- Before posting a GitHub review comment, show the comment text and wait for confirmation.
- When a skill applies, or the user asks to run one, call `get_skill` and follow its instructions using the available tools.

### Memory extraction (`memory.py`)
- `extract_user(user_id, recent_messages)` and `extract_channel(channel_id)` (which uses messages since the last extraction).
- One LLM call with structured output, returning `{facts: [{content, replaces_id | null}]}`. The input is the recent messages plus the existing KB docs for that scope, as top `$text` matches. This step:
  - inserts new facts with `source: "extracted"`
  - updates facts where `replaces_id` is set
  - extracts only durable information (who the person is, their role, projects, preferences, decisions, recurring context), not chit-chat.

### 8.1 GitHub MCP tools (`tools/github_mcp.py`)
- Use `langchain-mcp-adapters` (`MultiServerMCPClient`) to start the official `github-mcp-server` in **stdio** mode. Pin its version, and set these env vars:
  - `GITHUB_PERSONAL_ACCESS_TOKEN=<installation token from github_app.py>`
  - `GITHUB_TOOLSETS=pull_requests`
- Load the tools, then **filter by name** against `GITHUB_MCP_TOOL_ALLOWLIST`. Drop everything else.
- The allowlist must cover only the following, and nothing that merges, closes, creates or updates PRs or branches:
  - get PR details
  - get PR diff and files
  - list PR comments, review comments and reviews
  - create or submit a review with comments
  - add a comment to a PR
- **Tool names differ between `github-mcp-server` versions.** At startup, log the full tool list of the pinned version, then set the allowlist from it.
- Installation tokens expire after about one hour. `github_app.get_installation_token()` caches the token and refreshes it after 50 minutes. The MCP client is created per turn with the current token.
- GitHub App permissions: Pull requests R/W, Contents R/W (needed for coding-job pushes), Issues R, Metadata R.

### 8.2 Knowledge tools (`tools/knowledge.py`)
- `search_knowledge(query)`: searches the current scope's KB. In a channel this covers the channel KB plus the requester's KB.
- `save_knowledge(content, target: "me" | "channel")`: an explicit "remember this". `target="channel"` is allowed only in channels.

### 8.3 Skill tools (`tools/skills.py`)

All skill tools act on the requesting user's own skills only:
- `list_skills()`
- `get_skill(name)`: returns the instructions.
- `create_skill(name, description, instructions, created_from)`
- `update_skill(name, new_name?, description?, instructions?)`
- `delete_skill(name)`
- `get_recent_task_trace(limit=20)`: returns this thread's recent messages, including bot `tool_calls`.

The two creation paths both go through `create_skill`; only the drafting step differs:
- **From a description**: the LLM drafts name, description and step-by-step instructions from what the user described. It shows the draft, and calls `create_skill(created_from="description")` once the user confirms.
- **From the task just performed**: the user says something like "save what we just did as a skill". The LLM calls `get_recent_task_trace`, generalises the steps and tool calls into reusable instructions with placeholders for anything task-specific, shows the draft, and calls `create_skill(created_from="task")` once the user confirms.

### 8.4 To-do tools (`tools/todos.py`)
- `create_todo(title, notes?, due_date?, assignee_slack_id?)`: the assignee defaults to the requester and must be a registered user. The tool records the channel and thread.
- `list_todos(filter: "mine" | "assigned_by_me" | "user", user_slack_id?, status?)`: `"user"` lists another registered user's to-dos.
- `update_todo(todo_id, title?, notes?, due_date?, assignee_slack_id?)`
- `complete_todo(todo_id)`, `reopen_todo(todo_id)`, `delete_todo(todo_id)`
- Only the creator or the assignee may modify a to-do.
- There are **no** scheduled reminders. To-dos are tracked by asking the bot.

### 8.5 Coding tool (`tools/coding.py`)
- `start_coding_job(repo, base_branch, instructions?, issue_url?)`:
  - At least one of `instructions` and `issue_url` is required.
  - It checks via `github_app` that the repo is in the installation and that the branch exists.
  - It inserts a `jobs` doc with `status: "queued"` and the requester's provider, then returns the job id.
- The agent replies that the job is queued and that the result will be posted in this thread.

## 9. Coding job (`apps/coding_job/`): a workflow, not a graph

### Worker (`worker.py`)
- `python -m apps.main worker` runs a loop that polls every 3 seconds.
- An `asyncio.Semaphore(MAX_CONCURRENT_JOBS)` limits concurrency.
- It claims a job atomically with `find_one_and_update({status: "queued", requested_by_user_id: {$nin: <users with a running job>}}, {$set: {status: "running", started_at}}, sort created_at)`. This enforces a limit of one running job per user.
- On startup, it marks any `running` jobs left from a crash as `failed` with the error `"worker restarted"`, and posts that to Slack.

### Workflow (`workflow.py`)

These are plain sequential `async` steps. Any step can fail: on failure, set `status=failed` and `error`, post to the Slack thread, then run step 10 cleanup.

1. **Load** the job and the user. Decrypt the user's credential.
2. **Resolve the issue.** If `issue_url` is set, fetch the issue title, body and comments via `github_app`. Combine them with `instructions` into the task text.
3. **Mint** an installation token for this repo.
4. **Start the container** from `SANDBOX_IMAGE`:
   - Limits: memory and CPU from config, no privileged mode, auto-remove off (so it can be inspected on failure).
   - Container env holds only the provider credential:
     - Claude: `CLAUDE_CODE_OAUTH_TOKEN=<token>`
     - Codex: write `auth.json` to `/home/agent/.codex/auth.json` via `put_archive`.
5. **Clone** with an exec that gets the GitHub token only in that exec's environment, not the container's:
   - `git clone --branch <base> https://x-access-token:$TOKEN@github.com/<repo>.git /work/repo`
   - Then `git remote set-url origin https://github.com/<repo>.git`, so the token is not left in the repo.
   - `git checkout -b agent/<job_id[:8]>`
6. **Run the agent** in `/work/repo` with the prompt from `prompt.py`, wrapped in `asyncio.wait_for(SANDBOX_TIMEOUT_SECONDS)`:
   - Claude: `claude -p "<prompt>" --dangerously-skip-permissions --output-format json`
   - Codex: `codex exec --dangerously-bypass-approvals-and-sandbox --output-last-message /work/summary.txt "<prompt>"`
   - **Verify both commands' flags against the CLI versions pinned in `sandbox/Dockerfile`.** The container is the sandbox, which is why the CLIs' own permission prompts are disabled.
   - Capture the final summary and the last 200 lines of output into `log_tail`.
7. **Codex only**: copy `auth.json` back out of the container. If it changed (token refresh), re-encrypt it and update `users.credential_enc`.
8. **Commit and push.**
   - If `git status --porcelain` is empty, fail with the agent's summary as the error.
   - Otherwise run `git add -A`, then commit as the bot identity with the message `"<short title>"` plus the job id.
   - Push with a token exec: `git push https://x-access-token:$TOKEN@github.com/<repo>.git HEAD`.
9. **Create the PR** via the GitHub REST API (as the App):
   - Base is `base_branch`, head is `agent/<id>`.
   - Title: the issue title, or the first line of the instructions (up to 72 characters).
   - Body: the agent summary, "Closes #N" if an issue URL was given, and "Requested by <name> via Slack".
   - Set `pr_url` and `status=succeeded`, and post the PR link in the Slack thread.
10. **Cleanup** (always runs): stop and remove the container, and set `finished_at`.

### Prompt (`prompt.py`)
The prompt tells the agent to:
- resolve the task described below in this repository
- make the minimal correct change and follow existing conventions
- run the repo's relevant tests if any exist
- **not** commit, push or open PRs (the workflow does that)
- finish with a short plain-text summary of what changed and why

The prompt ends with the task text.

### Sandbox image (`sandbox/Dockerfile`)
- Debian slim base, with git, Python 3, Node LTS, and build-essential.
- Claude Code CLI and Codex CLI installed via npm, **with pinned versions**.
- A non-root user `agent`. Claude Code refuses the skip-permissions flag when run as root.
- Workdir `/work`, and the default command `sleep infinity` (the workflow uses `exec`).

## 10. Runtime (`docker-compose.yml`, `Dockerfile`)
- **Services**:
  - `mongo` (mongo:8, with a volume)
  - `bot` (`python -m apps.main bot`)
  - `worker` (`python -m apps.main worker`, mounts `/var/run/docker.sock`)
- `bot` and `worker` use the same image. The sandbox image is built separately: `docker build -t slack-agent-sandbox sandbox/`.
- **Dependencies** (`pyproject.toml`): `slack-bolt`, `slack-sdk`, `aiohttp`, `pymongo`, `langgraph`, `langchain`, `langchain-anthropic`, `langchain-openai`, `langchain-mcp-adapters`, `pydantic-settings`, `cryptography`, `docker`, `httpx`, `pyjwt`. Dev dependencies: `pytest`, `pytest-asyncio`.

## 11. Milestones (build in order; each must pass its checks before moving on)

| # | Scope | Done when |
|---|---|---|
| 1 | Scaffold, `config.py`, `db.py` (indexes), `crypto.py`, compose with mongo | `python -m apps.main bot` connects to Mongo and creates indexes |
| 2 | `stores/users.py`, `admin.py` | add, list, update and remove users works, and the credential is stored encrypted |
| 3 | Slack gateway + `stores/messages.py`, `channels.py` + graph with **no tools** | A DM or @mention gets an LLM reply in the thread; all DM and channel messages are stored; unregistered users get the refusal |
| 4 | Knowledge tools + `memory.py` | "remember X" saves; facts are extracted after DMs and every N channel messages; KB hits appear in context; channel and user scopes never mix on write |
| 5 | To-do tools | create, list, update, complete, reopen and delete work; assigning to another user works; permission rule enforced |
| 6 | Skill tools | Create from a description, and create from the just-performed task, both work with confirmation; update, delete, list and run work |
| 7 | GitHub MCP | Bot summarises a PR, lists its comments, and posts a confirmed review comment; no non-allowlisted tool is loaded |
| 8 | Coding job (tool, worker, workflow, sandbox image) | A Slack description, and separately an issue link, each produce a PR from the bot and the link in the thread; failures are reported; per-user limit holds; Codex `auth.json` refresh is persisted |
| 9 | README | Covers Slack app setup, GitHub App setup, `.env`, building both images, admin commands |

## 12. Tests (`tests/`)
- Store functions run against the compose MongoDB, using a separate test database.
- Tool permission rules: skill ownership, to-do creator/assignee rule, KB scope on write.
- GitHub tool allowlist filtering.
- The coding workflow is tested with a fake `sandbox` module, covering: the success path, no-changes failure, timeout, and Codex credential write-back.
- Do not write end-to-end Slack tests.

## 13. Out of scope: do not build
Web UI or admin dashboard; to-do reminders and schedules; skill sharing between users; document or file upload into the KB; embeddings or vector search; any GitHub action beyond PR read and review/comment (except the coding job's own branch push and PR creation); a job-status tool; multi-host or Kubernetes sandboxes; Redis or Celery; analytics or metrics.

## 14. Open items (ask the owner; do not guess)
1. Confirm the orchestrator runs on one company API key (§2), and the subscription-terms check.
2. Confirm the KB is built only from chat (extracted + explicit "remember"), with no document uploads.
3. Confirm channel knowledge: is storing **all** messages in channels the bot has joined acceptable, or only messages in threads where the bot was mentioned?
4. Should users be able to view or delete their own KB entries from Slack? This is currently not included.