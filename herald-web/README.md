# herald-web

FastAPI + HTMX web companion to the Herald Discord bot.

> See the [root README](../README.md) for the full Herald project overview
> and [ARCHITECTURE.md](../ARCHITECTURE.md) for design decisions.

---

## Status

**Phase 0** — empty scaffold. The container builds, uvicorn starts, and
`GET /` returns `Herald Web`. No real routes yet.

**Phase 1** (next) — Discord OAuth login, sidebar layout, read-only
dashboard, campaign JSON export.

See [`PLAN.md`](../PLAN.md) for the full phased build plan.

---

## Stack

| Layer | Choice |
| ----- | ------ |
| Language | Python 3.12 |
| Backend | FastAPI (async) |
| Templates | Jinja2 (server-rendered) |
| Interactive | HTMX (no JS framework) |
| Realtime | FastAPI WebSockets (Phase 7) |
| Styling | Tailwind CSS |
| DB | SQLite, shared with bot, WAL mode |
| DB access | Raw `sqlite3` via helper functions |
| Auth | Discord OAuth 2.0 + signed cookie sessions |
| Markdown | `markdown` + `bleach` (server-side rendering) |
| Container | Docker + uvicorn |

No build step. No JS framework. Tailwind via CDN initially, build pipeline
when it actually matters.

---

## Local development

The web service is built and run via the **root** `docker-compose.yml`:

```bash
# From the repo root
docker compose up herald-web --build
```

Or run it directly without Docker if you have Python 3.12 and want a
faster iteration loop:

```bash
cd herald-web
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env       # then edit
uvicorn app.main:app --reload --host 0.0.0.0 --port 8088
```

---

## Layout

```
herald-web/
├── Dockerfile              build context = repo root
├── requirements.txt
├── .env.example            full env shape
└── app/
    ├── __init__.py
    ├── main.py             FastAPI app
    ├── config.py           env-driven settings
    ├── db_init.py          web-owned schema (web tables only)
    ├── auth/               (Phase 1) OAuth + session helpers
    ├── routes/             (Phase 1+) route modules
    ├── services/           (Phase 1+) permissions, dice engine, AI proxy
    ├── templates/          (Phase 1+) Jinja2 templates
    │   └── partials/       HTMX fragments
    └── static/             (Phase 1+) CSS, JS, images, icons
```

---

## Database

The web portal **reads** the bot's tables and **owns** its own tables.

| Owner | Where | Tables |
| ----- | ----- | ------ |
| Bot   | `shared/database.py` | `campaigns`, `players`, `sessions`, `rsvps`, `attendance_log`, `items`, `player_inventory` |
| Web   | `herald-web/app/db_init.py` (Phase 1.1) | `web_sessions`, `wiki_pages`, `dice_rolls`, `notification_prefs`, `ai_request_log`, `campaign_web_settings` |

Each service runs its own idempotent init on startup. The web service
does not modify the bot's schema.

---

## Configuration

All settings are environment variables loaded by `app/config.py`. See
`.env.example` for the full template. Phase 1.2 adds startup validation
that refuses to boot if required vars are missing.

Required at runtime (Phase 1+):
`HERALD_WEB_BASE_URL`, `DB_PATH`, `SESSION_SECRET`,
`DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`, `DISCORD_REDIRECT_URI`.

Optional:
`ALLOWED_GUILD_ID`, `ANTHROPIC_API_KEY`, `LOCALAI_BASE_URL`,
`LOCALAI_MODEL`, `CLAUDE_MODEL`.

---

## Code style

Match the bot's conventions:

- Plain SQL via `sqlite3`, no ORM
- Module-level helper functions, not classes for business logic
- A `_connect()` helper that opens with WAL + foreign keys + `Row` factory,
  returns dict-rows, closes per query
- Don't catch exceptions broadly — let them propagate to FastAPI's
  default error handler

---

## Phase 1 — Definition of Done

- [ ] User logs in via Discord OAuth in a real browser against the
      production Discord app
- [ ] Sidebar shows user avatar/name and a campaign selector
- [ ] Dashboard shows next session, recent activity, quick stats
- [ ] Placeholder pages for Schedule / Party / Inventory / Lore / AI /
      Dice are reachable from the sidebar
- [ ] "Export Campaign" returns a complete JSON for a DM's campaign
- [ ] Empty state landing for users with no campaigns
- [ ] Logout clears the session and returns to a logged-out state
- [ ] Container builds and runs alongside the bot on Unraid
- [ ] No bot code or bot schema was modified
