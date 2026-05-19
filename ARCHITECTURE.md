# Herald Web Portal — Architecture & Decisions

> Source-of-truth document capturing the decisions made during planning.
> Every item here was explicitly agreed before this document was written.
> When the project starts, this lives in the repo root next to `README.md`.

---

## 1. Project Overview

**Herald** is an existing self-hosted Discord bot for D&D 5e campaign management
(scheduling, attendance, homebrew inventory, language translation, AI content
generation via Claude API and LocalAI). It runs in Docker on the maintainer's
Unraid server.

**Herald Web** is a web companion portal that runs alongside the bot, sharing
the same SQLite database. The split:

- **Discord** handles real-time interaction: pings, RSVP buttons, quick lookups.
- **Web** handles deeper visual workflows: session prep, character sheet
  editing, the item compendium, the campaign wiki, the dice roller, AI tools.

Both surfaces are first-class. A user shouldn't have to leave the web portal
to reach a feature, and the bot remains useful for anyone who prefers Discord.

---

## 2. Repository Structure

The bot does not currently live in a GitHub repo. As part of this project,
a single new GitHub repo will be created holding both the bot and the web
portal.

**The first commit** is the existing bot code (currently in `Docker Files/`)
imported verbatim into `herald-bot/` and the modules it shares into `shared/`.
Web work begins on the second commit. The bot's contents in this initial
import are treated as **read-only** from then on — see §14.

```
herald/
├── herald-bot/             # Existing bot — bot.py, scheduler.py (READ-ONLY)
├── herald-web/             # New FastAPI app
│   └── app/
│       └── db_init.py      # Web-owned schema (new tables, web-only)
├── shared/                 # Modules imported by both services (READ-ONLY)
│   ├── database.py         # Bot-owned schema, bot helper functions
│   ├── claude_api.py
│   ├── local_api.py
│   ├── ai_backend.py
│   ├── pdf_parser.py
│   └── languages.py
├── data/                   # SQLite DB lives here, git-ignored
│   ├── scheduler.db        # Production DB
│   └── scheduler-test.db   # Dev/test DB (seeded fake data)
├── docker-compose.yml      # Both services
├── README.md
└── ARCHITECTURE.md         # This file
```

**Why this layout**

- Side-by-side directories make the boundary between bot, web, and shared code
  obvious. Anyone reading the repo can answer "where does this run?" instantly.
- `shared/` holds the bot modules the web portal imports (read, never modify).
  No drift, no submodules, no copy-pasting.
- `herald-web/app/db_init.py` is owned by the web service and contains the
  schema for **new** web-only tables. The bot never touches it.
- `data/` is mounted as a Docker volume into both containers; SQLite WAL mode
  (already enabled in `shared/database.py`) handles concurrent access safely.

---

## 3. Technology Stack

Inherited from the spec, no deviations:

| Layer        | Choice                                |
| ------------ | ------------------------------------- |
| Language     | Python 3.12 (matches the bot exactly) |
| Backend      | FastAPI (async)                       |
| Templates    | Jinja2 (server-rendered)              |
| Interactive  | HTMX (partial swaps, no JS framework) |
| Realtime     | FastAPI WebSockets (dice log)         |
| Styling      | Tailwind CSS                          |
| DB           | SQLite (shared with bot, WAL mode)    |
| DB access    | Raw `sqlite3` via helper functions    |
| Auth         | Discord OAuth 2.0                     |
| Sessions     | Signed cookies (`itsdangerous`)       |
| Markdown     | `markdown` + `bleach` (server-side)   |
| Container    | Docker + uvicorn                      |

**Editor for markdown fields** is a plain `<textarea>` with server-rendered
preview. We will revisit a JS markdown editor (EasyMDE / Toast UI) only if
in-practice feedback shows the textarea is too rough.

---

## 4. Database Strategy

### 4.1 Shared database, independent schema ownership

Both bot and web read and write the same `data/scheduler.db`. **The bot owns
its schema and the web owns its schema** — they live in separate files and
are managed independently:

- **Bot schema** lives in `shared/database.py` (the existing file). The
  web service may **read** from this file (importing query helpers) but
  **must not modify it**. Bot-owned tables and columns are off-limits to
  the web service.
- **Web schema** lives in `herald-web/app/db_init.py`. Only the web service
  creates and writes these tables. The bot does not import this module.

Each service initializes its own tables on startup. Both use
`CREATE TABLE IF NOT EXISTS`, so repeated runs are safe. There is no
coordination required at runtime — the bot starts first in `docker-compose`
(`depends_on`), but the order doesn't matter because each service's `init_db()`
is independent and idempotent.

This is stricter than putting all schema in one file. The trade-off: a small
duplication of the "open a sqlite connection with WAL mode" boilerplate, in
exchange for a hard guarantee that the bot's code is untouched. Given the
bot is in production, that guarantee is worth more than the saved
boilerplate.

### 4.2 New tables (web-owned, in `herald-web/app/db_init.py`)

```sql
wiki_pages              -- Campaign wiki: locations, factions, NPCs,
                        -- history, quests, recaps, notes. Markdown
                        -- content, parent_id for tree, visibility =
                        -- party | dm.

dice_rolls              -- Every roll made through the web portal:
                        -- expression, result, breakdown, optional
                        -- label, who rolled it.

web_sessions            -- Discord OAuth session storage. Random
                        -- session_id is the value of the signed cookie;
                        -- row holds user info, access/refresh tokens,
                        -- expiry.

notification_prefs      -- Per-user, per-campaign web notification toggle.

ai_request_log          -- Audit trail of every AI call from the web
                        -- portal: who, when, which backend, request
                        -- type, success/error. Bot AI calls are not
                        -- logged here (bot code is untouched); if a
                        -- unified log becomes useful later, the bot
                        -- can opt in by adding writes to this table.

campaign_web_settings   -- Web-only per-campaign settings, keyed on
                        -- campaign_id (FK to campaigns.id). Currently
                        -- holds the optional Discord webhook URL for
                        -- cross-posting. Future web-only campaign
                        -- settings go here instead of new columns on
                        -- the bot's campaigns table.
```

### 4.3 No new columns on existing bot tables

The web portal **does not** add columns to `campaigns`, `players`,
`sessions`, `rsvps`, `items`, `player_inventory`, or `attendance_log`.
Any per-campaign or per-player web settings live in a sibling table
keyed on the existing primary key (e.g., `campaign_web_settings`).

This is the practical expression of "do not modify existing bot code":
the bot's `database.py`, including its CREATE TABLE statements and
`_migrate()` calls, is exactly what it is today.

### 4.4 Migration strategy

For web-owned tables only (the bot manages its own):

- New tables: `CREATE TABLE IF NOT EXISTS` in `herald-web/app/db_init.py`
- New columns on web tables: a web-local `_migrate(conn, table, column, type)`
  helper that mirrors the bot's pattern (swallows "duplicate column" errors)

Schema changes are additive forever.

---

## 5. Authentication & Authorization

### 5.1 Identity: Discord OAuth 2.0

A user is the same identity in the web portal and in the bot — both keyed on
the Discord `user_id`. No separate accounts, no passwords stored.

**OAuth scopes:** `identify` and `guilds`.

### 5.2 Login eligibility

A user can log in if **they share at least one Discord guild with the bot**.
At callback we call `GET /users/@me/guilds`, intersect with the bot's guild
list, and reject if empty.

This is the natural fit for Herald's deployment style: the web portal exists
because someone runs the bot in their server, and only people in that server
should be able to log in. No deployment-specific allowlists needed.

`ALLOWED_GUILD_ID` remains available as an *optional* stricter override if a
maintainer wants to lock the portal to one specific guild even though the bot
is in several.

### 5.3 Permission tiers

| Tier              | Definition                                | Can do                                                                  |
| ----------------- | ----------------------------------------- | ----------------------------------------------------------------------- |
| Anonymous         | No session                                | `/login` and `/auth/*` only                                             |
| Authenticated     | Valid session, no campaigns               | Friendly empty-state page with login info and instructions              |
| Player            | Listed in `players` for a campaign        | View campaign, RSVP, edit own character sheet, manage own inventory     |
| DM                | `campaigns.dm_user_id == user_id`         | All player actions plus full read/write on campaign, items, wiki, AI    |

Authorization is enforced server-side via FastAPI dependencies (`current_user`,
`require_member`, `require_dm`). The client is never trusted on permission
claims — `dm_user_id` is checked against the session's `user_id` for every
DM-gated route.

### 5.4 Character sheet ownership

The owner of a sheet (the player whose `user_id` matches) has **full edit
control** over every field on their own sheet, including stats, level, and
inventory. The DM has full edit control over any sheet in their campaigns.
Group social contract handles agreements about leveling, etc. — the portal
does not enforce it.

### 5.5 Empty state — logged-in user with no campaigns

A friendly landing page: "You're logged in, but you're not in any campaigns
yet. Ask a DM to add you with `/party add` in Discord, or create your own
campaign with `/campaign create`." Plus a logout link. Not a 403.

---

## 6. Deployment & Access

### 6.1 Docker

Two services in one `docker-compose.yml`. Both mount the same `data/` volume.

```
herald-bot   → existing bot, unchanged interface
herald-web   → FastAPI + uvicorn on port 8088
```

Both services build from the same repo and import from `shared/`.

### 6.2 Network access

The portal listens on port 8088. How users *reach* it depends on their
network setup, and the README will document this clearly with strong
guidance.

**Recommended (loud README callout):**
- Set a **static IP / DHCP reservation** on the device running Herald.
  If the host's IP changes, the Discord OAuth redirect URI breaks and
  nobody can log in.

**Working access patterns:**
1. Static IP — `http://192.168.x.x:8088`
2. mDNS — `http://<host>.local:8088` (e.g. `http://tower.local:8088`)
3. Reverse proxy with a domain — `https://herald.example.com`

The Docker container does not publish its own `.local` hostname; resolution
depends on the deployer's network (mDNS, router DNS, Pi-hole, hosts file,
or a reverse proxy).

### 6.3 Discord OAuth setup

Each self-hoster registers their own Discord OAuth application and adds
their access URL(s) as redirect URIs:

- `http://<their-static-ip>:8088/auth/callback`
- `http://<host>.local:8088/auth/callback` (optional, if mDNS works)
- `https://<their-domain>/auth/callback` (optional, if behind a reverse proxy)

Discord allows multiple redirect URIs per app, so dev + prod can coexist.

The README will include a step-by-step guide for the OAuth setup (Developer
Portal → OAuth2 tab → add redirect URI(s) → copy Client ID & Client Secret
into `.env`).

---

## 7. AI Integration

### 7.1 Backends

Herald supports two AI backends via `shared/ai_backend.py`:

- **Claude API** (cloud, `claude_api.py`)
- **LocalAI** (self-hosted, OpenAI-compatible, `local_api.py`)

Per-campaign default backend is already supported on the bot side via
`campaigns.ai_backend`. The web portal inherits this and exposes the same
override in its AI tools UI.

The maintainer's reference deployment runs Claude API as the active backend
with LocalAI (Gemma 4 26B) available as a tested fallback. Both must work
in the web portal from Phase 5 onward.

### 7.2 Rate limiting

The bot's existing per-user, per-process, in-memory rate limiter
(10/hour player, 60/hour DM) is preserved. The web portal runs the same
limiter, in its own process, with its own pool. A user determined to use
both surfaces gets up to 2× the limit; this is acceptable given the cost
profile and trust model.

If this ever matters, we move to a shared DB-backed limiter — and the
data we need is already being captured (see 7.3).

### 7.3 AI request audit log

Every AI call from either bot or web writes a row to `ai_request_log`:

```
campaign_id, user_id, backend, request_type, source ('bot'|'web'),
success, error, requested_at
```

This gives us:
- An audit trail (who generated what, when, on which backend)
- The data needed to switch to a shared DB-backed limiter later
- The data needed for a future "AI usage this month" DM dashboard

### 7.4 Web AI surface is first class

Phase 5 (AI tools) gets full polish: clean forms, generation history,
"save to compendium / wiki" flows, backend selection, campaign-context
auto-injection. The principle is: if a user is in the web portal, they
should never need to switch to Discord to use Herald's AI features.

---

## 8. Discord Cross-Posting

For Phase 7+ features that benefit from posting back to Discord (dice roll
broadcasts, "Alice equipped Sunsword" notices, AI-generated session recaps),
the web portal uses **per-campaign Discord webhook URLs**.

- The DM creates a webhook on the Discord channel and pastes its URL into
  campaign settings.
- The web portal POSTs to the webhook for cross-posts. No bot-side coupling
  required, no new IPC layer.
- The schema is ready now — the webhook URL lives in the web-owned
  `campaign_web_settings` table (see §4.2), not as a new column on the bot's
  `campaigns` table. The *feature* lands when the relevant phase does.

---

## 9. UI/UX Principles

### 9.1 Responsive strategy

The portal is fully responsive from day one. Tailwind utilities are used
throughout — there is no "mobile.css" added later as an afterthought.

- **Player flows** (RSVP, character sheet view, inventory, wiki reading)
  are designed mobile-first and scale up cleanly to desktop.
- **DM flows** (calendar, AI tools, wiki tree, admin) are designed
  desktop-first but stay usable on tablet — DMs at the game table run the
  portal on a tablet next to their screen.

### 9.2 Visual identity

Inherited from the spec: dark fantasy aesthetic. Deep purple-black
backgrounds, parchment-cream text, royal purple primary, burnished gold
accents. Cinzel/EB Garamond display, Inter body, JetBrains Mono for
code. Item rarity colors as already used in the bot's embeds.

The maintainer provides logo files (the existing Herald shield/trumpet/d20
mark) and we generate the favicon set from them.

### 9.3 No JS framework

HTMX for partial swaps, vanilla JS only where strictly needed (HTMX
WebSocket extension for the dice log). No React/Vue/Svelte build pipeline.

---

## 10. Phasing & Scope

The 8 phases from the spec are kept verbatim. We ship Phase 1 first and
iterate; we don't try to build everything before deploying.

| Phase | Scope                                 | Mutations |
| ----- | ------------------------------------- | --------- |
| 1     | Auth, layout, dashboard, JSON export  | None — read-only |
| 2     | Calendar, session detail, RSVP        | RSVP, session edits |
| 3     | Party + character sheets              | Sheet edits, PDF re-import |
| 4     | Inventory: compendium + bags          | Item create/edit, distribute, equip |
| 5     | AI tools (Forge, Lore, Ask)           | AI generation, save-to-compendium/wiki |
| 6     | Lore / campaign wiki                  | Wiki page CRUD |
| 7     | Dice roller (real-time WS)            | Dice rolls, optional Discord cross-post |
| 8     | Stretch: combat tracker, recap gen,   | TBD when we get there |
|       | quests, maps, calendar export, PWA    |           |

### Phase 1 — Definition of Done

A user can log in via Discord OAuth, see their campaigns in the sidebar,
view a dashboard (next session card, recent activity, quick stats), navigate
to placeholder pages for later phases, and log out. Nothing in Phase 1
mutates the database except writing/clearing the `web_sessions` row.

**Hard gate**: Phase 1 is not done until login has been completed in a
**real browser** against the **production Discord OAuth application**
(not a mock, not a placeholder). Auth is the foundation — every later
phase depends on it working end-to-end against the real Discord API.

**Bonus feature (Phase 1)**: a dashboard "Export Campaign" button that
returns the entire campaign as a single JSON document — campaigns,
players, sessions, RSVPs, items, inventory. Three purposes:
1. Manual backup separate from the SQLite file
2. End-to-end smoke test that the DB access layer reads correctly
3. Foundation for future import/sharing features

Read-only, DM-only, no schema changes.

---

## 11. Testing & Dev Environment

The maintainer's Unraid server is the test environment. Iteration loop:
push to GitHub → pull on Unraid → test.

To avoid risking real campaign data while building mutating features
(Phase 2+), the web container takes a `DB_PATH` env override pointing at
`data/scheduler-test.db`. A `seed_dev.py` script populates that DB with
one fake campaign, a DM, a few players, items, and a session. Once a
feature is verified there, the web container is pointed at the real
`scheduler.db`.

Optional later: a small `tests/` suite using FastAPI's `TestClient`
against an in-memory or temp-file SQLite DB. Not required for Phase 1.

---

## 11a. Working Practices

These are how the project is built, not what is built. Same weight as the
rest of this document.

### Python version

Python 3.12. Matches the bot exactly (`python:3.12-slim` in the bot's
Dockerfile). Do not default to an older version or upgrade to a newer one
without revisiting this document.

### Commit discipline

- Use conventional commit messages: `feat:`, `fix:`, `refactor:`, `docs:`,
  `chore:`, `test:`.
- The **first commit** is the project skeleton: the existing bot files
  imported into `herald-bot/` + `shared/`, plus this `ARCHITECTURE.md` and
  the initial `README.md`. No web code yet.
- Every commit on `main` is a **working, deployable state**. Broken code
  does not land on `main`. Work-in-progress lives on feature branches.
- Commit at each phase milestone with a meaningful message
  (e.g., `feat(phase-1): discord oauth login + dashboard`).

### Ask before guessing

If the spec or this document is ambiguous, or appears to conflict with
existing bot code, **stop and ask**. Do not silently diverge from the bot's
patterns. The codebase has a consistent voice — plain SQL, module-level
functions, no over-engineering — and we keep it.

### Match the bot's style

- Plain SQL, no ORM.
- Module-level helper functions, not classes for business logic.
- A `_connect()` helper that opens with WAL + foreign keys, returns
  `sqlite3.Row` results, and closes per query.
- Don't catch exceptions broadly — let them propagate to FastAPI's
  error handler.

### Phase gates are real

Phase N+1 doesn't start until Phase N's Definition of Done is met. Phase 1
specifically requires a successful real-browser Discord OAuth login against
the production Discord app — see §10.

---

## 12. Configuration (`.env`)

```bash
# ─── Required ────────────────────────────────────────────────
HERALD_WEB_HOST=0.0.0.0
HERALD_WEB_PORT=8088
HERALD_WEB_BASE_URL=http://<your-static-ip>:8088   # or domain

DB_PATH=data/scheduler.db                          # or scheduler-test.db

SESSION_SECRET=                                    # python -c "import secrets; print(secrets.token_hex(32))"

# ─── Discord OAuth ──────────────────────────────────────────
DISCORD_CLIENT_ID=
DISCORD_CLIENT_SECRET=
DISCORD_REDIRECT_URI=http://<your-static-ip>:8088/auth/callback

# ─── AI (shared with bot — same env vars) ───────────────────
ANTHROPIC_API_KEY=
CLAUDE_MODEL=claude-sonnet-4-20250514
LOCALAI_BASE_URL=
LOCALAI_MODEL=
LOCALAI_API_KEY=not-needed

# ─── Optional ───────────────────────────────────────────────
ALLOWED_GUILD_ID=                                  # lock portal to one guild
```

The bot's existing `.env` continues to drive bot behaviour. The web service
has its own `.env` but the AI keys are intentionally the same names so a
self-hoster can use a single `.env` if they like.

---

## 13. Open / Deferred Decisions

These were intentionally not decided during this planning round and will
be revisited when the relevant phase begins:

- **Markdown editor upgrade.** Plain textarea + preview is the starting
  point. Move to EasyMDE / Toast UI only if in-practice feedback shows
  the textarea is too rough for non-technical users.
- **Shared DB-backed AI rate limiter.** Stays per-process for now. Move
  to shared only if abuse / cost proves it matters; data is already
  captured.
- **Image uploads** (item art, map images). Phase 8 stretch. Will live
  in a volume-mounted directory, not in SQLite.
- **iCal export, mobile PWA, voice channel detection.** Phase 8 stretch.
- **Combat tracker schema.** Designed compatible (initiative order, HP,
  conditions) but not built; schema lands when Phase 8 lands.

---

## 14. Things We Will Not Do

Documenting the negative space so we don't drift:

- We will **not modify the existing Herald-Bot code**. The contents of
  `herald-bot/` and `shared/` are read-only from the web portal's
  perspective. If we think we need to change a bot file, we stop and
  ask first.
- We will **not add columns to existing bot tables**. Per-campaign or
  per-player web settings go in sibling tables (e.g.,
  `campaign_web_settings`).
- We will not alter, rename, or drop anything the bot depends on.
  Schema changes are additive forever and live in web-owned files only.
- We will not introduce a JavaScript framework (React/Vue/Svelte).
- We will not call a bot HTTP API. The web portal reads and writes the
  database directly. The bot is not a service the web depends on at
  runtime.
- We will not store passwords or any non-Discord identity. Discord
  OAuth is the only identity surface.
- We will not expose Discord webhook URLs to the client. They are
  secrets — held server-side, never echoed to the browser.
- We will not ship Phase 2+ before Phase 1 is deployed and used.
- We will not silently guess when the spec is ambiguous. Open
  questions get asked, decided, and recorded in this file.

---

## 15. Decision Log Summary

For quick reference, the decisions that produced this document:

1. Single GitHub repo holding bot, web, and shared modules. First commit
   imports the existing bot; web work begins on commit two.
2. Layout: `herald-bot/`, `herald-web/`, `shared/`, `data/`. The bot and
   `shared/` directories are read-only from the web's perspective.
3. **Independent schema ownership**: bot schema stays in `shared/database.py`
   (untouched); web schema lives in `herald-web/app/db_init.py`. No new
   columns on existing bot tables — sibling tables (e.g.,
   `campaign_web_settings`) hold web-only per-campaign settings.
4. Auth: Discord OAuth 2.0; login requires sharing a guild with the bot.
5. Access: static-IP-first; mDNS and reverse-proxy documented as
   alternatives; user registers their own redirect URIs.
6. Phase 1 = read-only, with a hard gate: real-browser login against the
   production Discord OAuth app must work end-to-end.
7. Phase 1 bonus: dashboard "Export Campaign" JSON button (DM-only,
   read-only).
8. Test environment: Unraid, with separate `scheduler-test.db`.
9. AI rate limiting: per-process for now; web AI calls audited in DB for
   future. Bot AI calls remain unlogged in v1 (bot code is untouched).
10. Discord cross-posting: per-campaign webhook URLs stored in
    `campaign_web_settings.discord_webhook_url`.
11. Branding: maintainer-provided logo files.
12. Character sheets: full self-edit for owner; full edit for DM.
13. Responsive: player mobile-first; DM desktop-first.
14. Markdown: plain textarea + server-side preview to start.
15. AI backends: both Claude and LocalAI (Gemma 4 26B); web is first class.
16. Empty state: friendly landing for users with no campaigns.
17. Working practices: Python 3.12, conventional commits, every `main`
    commit deployable, ask before guessing, match the bot's style.

---

*Update this document any time a decision changes. The first PR after
this is finalized should reference it; subsequent PRs that change
architecture should update it in the same commit.*
