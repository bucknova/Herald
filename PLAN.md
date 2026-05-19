# Herald Web Portal — Phased Build Plan

> Companion to `ARCHITECTURE.md`. This document turns the eight phases from
> the spec into concrete, ordered tasks. Phase 1 is detailed; later phases
> are outlined and will be refined as we approach them.
>
> Rule: don't start Phase N+1 until Phase N's "Definition of Done" is met.

---

## Phase 0 — Repository Bootstrap

Goal: a fresh GitHub repo containing the existing bot, the planning docs,
and an empty web service scaffold that builds and runs.

### 0.1 Create the GitHub repo

- New repo on GitHub (private or public, your call). Suggested name: `Herald`.
- Clone locally.
- Add `.gitignore` covering Python (`__pycache__/`, `*.pyc`, `.env`,
  `data/`, `*.db`, `*.db-wal`, `*.db-shm`).

### 0.2 First commit — import the existing bot

Place the existing bot files into the repo:

```
herald/
├── herald-bot/             # bot.py, scheduler.py, Dockerfile, etc.
├── shared/                 # database.py, claude_api.py, local_api.py,
│                           # ai_backend.py, pdf_parser.py, languages.py
├── ARCHITECTURE.md
├── PLAN.md
└── README.md               # placeholder for now
```

The bot's `bot.py`, `scheduler.py`, and module-level files move into
`herald-bot/`; the modules that the web portal will import live in
`shared/`. The bot's import statements need their paths adjusted to point
to `shared/` instead of the current flat layout — this is the **only**
change to bot code in this commit and must be tested by running the bot
locally before committing.

Commit message: `chore: initial import of herald-bot into monorepo layout`

### 0.3 Second commit — herald-web scaffold

Create the empty web service that builds and serves a placeholder
response. No real routes yet.

```
herald-web/
├── Dockerfile
├── requirements.txt
├── .env.example
└── app/
    ├── __init__.py
    ├── main.py             # FastAPI app, returns "Herald Web" at /
    ├── config.py           # Settings loaded from env
    └── db_init.py          # Empty for now; tables added in Phase 1
```

Update `docker-compose.yml` at the repo root to include both services
sharing the `data/` volume.

Acceptance: `docker compose up --build` brings both containers up; the bot
connects to Discord as before, and `curl http://localhost:8088/` returns
"Herald Web".

Commit: `feat(web): scaffold empty FastAPI service`

---

## Phase 1 — Foundation (Auth + Layout + Dashboard)

Goal: a user can log in via Discord OAuth in a real browser against the
production Discord application, see their campaigns in the sidebar, view a
read-only dashboard, export a campaign as JSON, and log out.

### 1.1 Database access layer (web side)

File: `herald-web/app/database.py`

- `_connect()` helper matching the bot's pattern (WAL, foreign keys,
  `Row` factory).
- Read helpers for the bot's tables (just thin wrappers around queries
  the dashboard needs — campaigns for a user, next session, recent
  activity, attendance stats). We do not import `shared/database.py`'s
  helpers directly because the spec recommends staying lightweight, but
  we **read** the same tables.

File: `herald-web/app/db_init.py`

- `CREATE TABLE IF NOT EXISTS` for the five web-owned tables
  (`web_sessions`, `wiki_pages`, `dice_rolls`, `notification_prefs`,
  `ai_request_log`) plus `campaign_web_settings`.
- A local `_migrate()` helper for future additive changes.
- Called by FastAPI's lifespan event on startup.

Commit: `feat(db): web-owned schema initialization`

### 1.2 Configuration

File: `herald-web/app/config.py`

- Load env vars: `HERALD_WEB_HOST`, `HERALD_WEB_PORT`, `HERALD_WEB_BASE_URL`,
  `DB_PATH`, `SESSION_SECRET`, `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`,
  `DISCORD_REDIRECT_URI`, `ALLOWED_GUILD_ID` (optional), the AI keys.
- Validate required vars at startup; refuse to boot if any are missing.

File: `herald-web/.env.example`

- Same shape as the spec's `.env` block, with clear comments.

Commit: `feat(config): env-based settings with startup validation`

### 1.3 Auth — Discord OAuth flow

Files:
- `herald-web/app/auth/sessions.py` — create/read/delete `web_sessions`
  rows; sign and verify the session cookie via `itsdangerous`.
- `herald-web/app/auth/discord_oauth.py` — build the OAuth authorize URL,
  exchange `code` for tokens, fetch `/users/@me`, fetch
  `/users/@me/guilds`.
- `herald-web/app/auth/dependencies.py` — FastAPI deps: `current_user`,
  `require_member(campaign_id)`, `require_dm(campaign_id)`.
- `herald-web/app/routes/auth_routes.py` — `GET /login`,
  `GET /auth/callback`, `POST /logout`.

Login flow:

1. `GET /login` builds the Discord authorize URL with `scope=identify+guilds`
   and redirects.
2. `GET /auth/callback?code=...` exchanges code, fetches user + guilds,
   intersects with the bot's guild list (or compares against
   `ALLOWED_GUILD_ID` if set). If the user shares no guild with the bot,
   show a styled 403 "you're not in any servers Herald is in" page.
3. On success: insert a `web_sessions` row keyed by a random UUID, set a
   signed cookie containing the UUID, redirect to `/`.
4. `POST /logout` deletes the row and clears the cookie.

Commit: `feat(auth): discord oauth login + signed cookie sessions`

### 1.4 Base template + sidebar layout

Files:
- `herald-web/app/templates/base.html` — Tailwind via CDN (we'll move to
  a build later), Cinzel + Inter + JetBrains Mono via Google Fonts,
  CSS variables for the palette from §9 of ARCHITECTURE.md.
- `herald-web/app/templates/partials/sidebar.html` — left nav with user
  avatar/name at the top, campaign selector dropdown (if >1), nav links
  for Dashboard / Schedule / Party / Inventory / Lore / AI Tools / Dice.
  Schedule/Party/Inventory/Lore/AI/Dice link to placeholder pages.
- `herald-web/app/templates/partials/toast.html` — toast slot for HTMX
  out-of-band swaps (not used in Phase 1 but lands in base).

Responsive: sidebar collapses to a hamburger drawer at mobile breakpoints.
Logo file goes in `herald-web/app/static/images/`.

Commit: `feat(ui): base template + responsive sidebar layout`

### 1.5 Dashboard

File: `herald-web/app/routes/home.py`

- `GET /` — requires `current_user`. Renders dashboard.

Dashboard contents (read-only):

- **Next session card**: next scheduled session for the currently
  selected campaign with date/time, countdown (HTMX `hx-trigger="load delay:30s"`
  to refresh the countdown), and the user's RSVP status. Link to session
  detail (placeholder route).
- **Recent activity feed** (last 10 events across the campaign): mix of
  RSVP responses, completed sessions, item grants. Pulled from
  `rsvps`, `sessions` (`status='completed'`), `player_inventory`
  (`acquired_at` desc).
- **Quick stats**: party size, total sessions played, the user's own
  attendance rate (computed from `attendance_log`).
- **Empty state**: if the user has no campaigns at all, show the
  friendly landing page from ARCHITECTURE §5.5.

Commit: `feat(dashboard): read-only dashboard with next session and stats`

### 1.6 Campaign export (Phase 1 bonus)

File: `herald-web/app/routes/home.py` (or new `export.py`)

- `GET /campaigns/{id}/export.json` — `require_dm`. Returns a single
  JSON document with: the campaign row, all players, all sessions, all
  RSVPs, all items, all `player_inventory` rows. No web-owned data
  yet (no wiki/dice in this campaign at Phase 1 anyway).

Add an "Export Campaign" button to the dashboard (DM-only, hidden for
players).

Commit: `feat(dashboard): DM-only campaign export to JSON`

### 1.7 Placeholder pages

Stubs so the sidebar nav doesn't 404:

- `GET /campaigns/{id}/schedule` → "Phase 2 — coming soon"
- `GET /campaigns/{id}/party` → "Phase 3 — coming soon"
- `GET /campaigns/{id}/inventory` → "Phase 4 — coming soon"
- `GET /campaigns/{id}/wiki` → "Phase 6 — coming soon"
- `GET /campaigns/{id}/ai` → "Phase 5 — coming soon"
- `GET /campaigns/{id}/dice` → "Phase 7 — coming soon"

Commit: `feat(nav): placeholder pages for later phases`

### 1.8 README — Discord OAuth setup guide

File: `README.md`

A step-by-step section walking a self-hoster through:

1. discord.com/developers/applications → select the existing Herald app
2. OAuth2 tab → add redirect URI(s) for their access pattern
3. Copy Client ID and reset/copy Client Secret into `.env`
4. Static IP / mDNS / reverse proxy callout from ARCHITECTURE §6.2
5. `docker compose up -d` and visit `/login`

Plus a top-level project README that explains the two services.

Commit: `docs: discord oauth setup guide and readme`

### 1.9 The Phase 1 gate — real login test

This is **not** a code task. Before Phase 1 closes:

- Create / configure the production Discord OAuth app (you + me together)
- Deploy the web container on your Unraid box pointed at
  `data/scheduler-test.db`
- Open `/login` in a real browser, complete the Discord OAuth dance,
  end up on the dashboard with your real campaigns visible

Until this is green, Phase 2 doesn't start.

### Phase 1 — Definition of Done checklist

- [ ] User logs in via Discord OAuth in a real browser against the
      production Discord app
- [ ] Sidebar shows user avatar/name and campaign selector
- [ ] Dashboard shows next session, recent activity, quick stats
- [ ] Placeholder pages for Schedule / Party / Inventory / Lore / AI /
      Dice are reachable from the sidebar
- [ ] "Export Campaign" returns a complete JSON for a DM's campaign
- [ ] Empty state landing for users with no campaigns
- [ ] Logout clears the session and returns to a logged-out state
- [ ] Web container builds and runs alongside the bot on Unraid
- [ ] No bot code or bot schema was modified

---

## Phase 2 — Schedule (Outline)

Goal: month-grid calendar + session detail panel with RSVP + DM-only
session management.

High-level tasks:
- Calendar route + month-grid template
- Session detail panel (HTMX swap, not a separate page)
- RSVP buttons for players → `POST /campaigns/{id}/sessions/{sid}/rsvp`
- DM-only session actions: edit notes, cancel, complete, re-ping,
  manual ping reset
- "Create Session" modal (DM only)
- Schedule settings page (DM only): friendly form for
  `ping_days_before`, `repeat_frequency`, etc.

To be refined when Phase 1 ships.

---

## Phase 3 — Party / Character Sheets (Outline)

- Roster page with character names, classes, levels, attendance rates
- Character sheet view → edit form (owner or DM)
- Markdown editor (plain textarea + server-side preview)
- "Re-import from D&D Beyond" → reuse `shared/pdf_parser.py` and
  `shared/ai_backend.parse_character_pdf`
- Per-player attendance sparkline
- Inline inventory view

---

## Phase 4 — Inventory (Outline)

- Compendium table with sort + filter + search
- Item detail modal (markdown render of description, properties block)
- Player bag grid view + equip/unequip
- DM-only create / edit / distribute / transfer flows

---

## Phase 5 — AI Tools Panel (Outline)

- AI tools landing with sub-tabs: Forge, Locations, Factions, NPCs,
  History, Ask
- Forms wrapping the bot's existing `ai_backend` functions
- Backend selector (Claude / LocalAI)
- "Save to Compendium" / "Save to Wiki" flows
- Per-user generation history (last 20 rows from `ai_request_log`)

---

## Phase 6 — Lore / Campaign Wiki (Outline)

- Tree-organized wiki by category
- Markdown rendering with category-specific metadata blocks
- New page form (DM only initially)
- Cross-linking with `[[Page Title]]` syntax
- Search across wiki content

---

## Phase 7 — Dice Roller (Outline)

- Dice tray UI with notation input + quick-roll buttons
- Advantage / disadvantage toggle for d20
- Shared roll log via FastAPI WebSocket
- Roll history per player
- Optional Discord cross-post via the per-campaign
  `campaign_web_settings.discord_webhook_url`

---

## Phase 8 — Stretch (Sketch only)

Designed compatible from earlier phases but built only when desired:
combat tracker, session recap generator, quest tracker, map embeds,
iCal export, mobile PWA shell.

---

## Cross-Cutting — Always Apply

- **Conventional commits** on every change.
- **Every `main` commit is deployable** — broken work lives on branches.
- **Match the bot's style** — plain SQL, module-level functions,
  thin connection helpers.
- **Ask before guessing** — if anything's ambiguous, surface it.
- **Test environment is Unraid** with `scheduler-test.db`. Production
  DB is only pointed to after a feature is verified.
- **The bot's files are read-only** — if a need to change them appears,
  stop and ask first.

---

## Right Now — Next Three Steps

1. **You**: create the GitHub repo (private to start is fine).
2. **You + me**: walk through Phase 0 (import the bot, scaffold the
   empty web service, push the first two commits). Done when
   `docker compose up --build` brings both services up on Unraid.
3. **Me**: start Phase 1.1 (database access layer + web schema init).

Once you say go, we begin Step 1.
