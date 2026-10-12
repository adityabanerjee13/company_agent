# Viewing the bot's database

The bot stores everything in one SQLite file, `agent.db`, in the project folder. Nothing extra needs installing: every command below uses the Python that comes with the project.

Run all commands from the `company_agent` folder in PowerShell. They work while the bot is running.

## Tables

| Table | What's in it |
|---|---|
| `messages` | Every Slack message the bot can read, plus its own replies (`user_id = 'bot'`). Deleted ones are kept with `deleted_at` set |
| `visible_messages` | A view of `messages` without deleted messages and without the `raw` column. Use it for reading |
| `channels` | Every channel and DM the bot can read |
| `sync_state` | The catch-up sync's bookkeeping, and `sync_status` (what the dashboard shows) |
| `users` | Users from `subscriptions.json`. **The `credential` column holds tokens: never select it.** |
| `jobs` | Coding jobs: repo, branch, status, PR link, error |

Columns of `messages`: `channel_id` and `ts` (Slack timestamp; together they are the ID, since a `ts` is only unique within a channel), `thread_ts`, `user_id`, `text`, `created_at`, `subtype`, `edited_at`, `files`, `deleted_at`, `raw` (the message JSON from Slack), `updated_at`.

The queries below read `messages`, so they include deleted messages. Replace `messages` with `visible_messages` to leave them out.

---

## Option 1: interactive SQL shell

```powershell
uv run python -m sqlite3 agent.db
```

At the `sqlite>` prompt, type any query ending in `;`:

```sql
SELECT created_at, channel_id, user_id, text FROM messages ORDER BY ts DESC LIMIT 20;
```

Type `.tables` to list the tables, `.schema messages` to see a table's columns, and `.quit` to exit.

To run a single query without opening the shell:

```powershell
"SELECT COUNT(*) FROM messages;" | uv run python -m sqlite3 agent.db
```

---

## Option 2: one-line commands

Each command prints one row per line. In the `LIMIT` and `substr(text,1,200)` parts, change the numbers to see more rows or longer text.

### Latest 20 messages, across all channels

```powershell
uv run python -c "import sqlite3; c=sqlite3.connect('agent.db'); [print(r) for r in c.execute('SELECT created_at, channel_id, user_id, substr(text,1,200) FROM messages ORDER BY ts DESC LIMIT 20')]"
```

### Message count per channel

```powershell
uv run python -c "import sqlite3; c=sqlite3.connect('agent.db'); [print(r) for r in c.execute('SELECT channel_id, COUNT(*) FROM messages GROUP BY channel_id')]"
```

### All messages in one channel or DM, oldest first

Replace `C0C944G2VJ4` with the channel ID from the count command above.

```powershell
uv run python -c "import sqlite3; c=sqlite3.connect('agent.db'); [print(r) for r in c.execute('SELECT created_at, user_id, text FROM messages WHERE channel_id = ? ORDER BY ts', ('C0C944G2VJ4',))]"
```

### One Slack thread

Replace the value with the thread's `ts`. A thread's ID is the `ts` of its first message.

```powershell
uv run python -c "import sqlite3; c=sqlite3.connect('agent.db'); [print(r) for r in c.execute('SELECT created_at, user_id, text FROM messages WHERE ts = ? OR thread_ts = ? ORDER BY ts', ('1791726635.943579','1791726635.943579'))]"
```

### Search message text

The search ignores case. Replace `svm` with any word.

```powershell
uv run python -c "import sqlite3; c=sqlite3.connect('agent.db'); [print(r) for r in c.execute('SELECT created_at, channel_id, user_id, substr(text,1,200) FROM messages WHERE text LIKE ? ORDER BY ts', ('%svm%',))]"
```

### Messages from one user

Replace the value with a Slack user ID, or use `bot` for the bot's replies.

```powershell
uv run python -c "import sqlite3; c=sqlite3.connect('agent.db'); [print(r) for r in c.execute('SELECT created_at, channel_id, substr(text,1,200) FROM messages WHERE user_id = ? ORDER BY ts', ('U0C944FS0HE',))]"
```

### Channels

```powershell
uv run python -c "import sqlite3; c=sqlite3.connect('agent.db'); [print(r) for r in c.execute('SELECT * FROM channels')]"
```

### Users, without their tokens

```powershell
uv run python -c "import sqlite3; c=sqlite3.connect('agent.db'); [print(r) for r in c.execute('SELECT slack_user_id, name, provider FROM users')]"
```

### Coding jobs, newest first

```powershell
uv run python -c "import sqlite3; c=sqlite3.connect('agent.db'); [print(r) for r in c.execute('SELECT id, repo, base_branch, status, created_at, finished_at, pr_url, substr(error,1,300) FROM jobs ORDER BY created_at DESC')]"
```

### Export all messages to a CSV file (opens in Excel)

```powershell
uv run python -c "import sqlite3, csv; c=sqlite3.connect('agent.db'); cur=c.execute('SELECT created_at, channel_id, thread_ts, user_id, text FROM messages ORDER BY ts'); w=csv.writer(open('messages_export.csv','w',newline='',encoding='utf-8-sig')); w.writerow([d[0] for d in cur.description]); w.writerows(cur)"
```

---

## Notes

- **Mangled characters** such as `→` or emoji: in PowerShell, run `$env:PYTHONIOENCODING = "utf-8"` first.
- **Times** (`created_at`) are in UTC.
- **What gets stored:** messages arrive live while the bot runs. The catch-up sync fills in history and anything sent while the bot was stopped, at startup and every 5 minutes.
- **Don't edit the data while the bot is running.** Reading is safe; editing could conflict with the bot's own writes.
