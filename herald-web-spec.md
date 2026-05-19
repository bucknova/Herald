# Herald Web Portal — Build Specification

> **For Claude Code**: This is a complete specification for building a web companion portal to an existing Discord bot called Herald. Read this entire document before starting. The portal shares a SQLite database with the bot, so understanding the existing schema is critical.

---

## Project Context

### What is Herald?

Herald is a self-hosted Discord bot for D&D 5e campaign management, currently running in production on the user's Unraid server. It handles campaign scheduling, attendance tracking, homebrew inventory, language translation, character sheets, and AI-powered content generation (via Claude API and optional LocalAI backend).

**The existing bot lives at**: `https://github.com/bucknova/Herald-Bot`

### What is Herald Web?

A FastAPI + HTMX web companion that runs alongside the bot, sharing the same SQLite database. The portal complements Discord — Discord handles real-time interaction (pings, RSVPs, quick lookups), while the web portal handles deeper, more visual workflows (session prep, character sheet editing, browsing the item compendium, building campaign lore).

### Why Both?

- **Discord embeds are great for quick interactions, terrible for reviewing lots of data.** A DM prepping for a session shouldn't have to scroll through 50 messages to see the party's gear.
- **Players want a personal portal** to view their character, inventory, and stats without typing slash commands.
- **Visual workflows beat text commands** for things like editing a character sheet, browsing items by rarity, or organizing a wiki of NPCs and lore.
- **A web UI lets us add features that don't fit Discord** — a calendar, a wiki tree, drag-and-drop, image uploads.

---

## Architecture

```
┌──────────────────────┐    ┌──────────────────────┐
│  herald-bot          │    │  herald-web          │
│  (Python/discord.py) │    │  (FastAPI + HTMX)    │
│  Port: N/A (gateway) │    │  Port: 8088          │
└──────────┬───────────┘    └──────────┬───────────┘
           │                           │
           └────► data/scheduler.db ◄──┘
                  (SQLite, WAL mode)
                           │
                  Reverse proxy
                           │
                  herald.w0aez.com
```

**Key principle**: Both services read and write to the same database. SQLite WAL mode (already enabled) handles concurrent access safely. The web portal does NOT call a bot API — it queries the database directly.

**Deployment**: Second Docker container in the user's existing setup, exposed on port 8088, fronted by their existing reverse proxy at a subdomain like `herald.w0aez.com`.

---

## Tech Stack

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Backend | **FastAPI** | Async-native, fast, auto OpenAPI docs, plays well with discord.py's async patterns |
| Templates | **Jinja2** | Server-rendered HTML, no build step, simple |
| Interactivity | **HTMX** | Partial page swaps for dynamic UX without writing JavaScript framework code |
| Realtime | **WebSockets via FastAPI** | For dice roll log, live RSVP updates, combat tracker |
| Styling | **Tailwind CSS (via CDN initially, then build)** | Utility-first, fast iteration, dark fantasy aesthetic |
| DB | **SQLite (shared with bot)** | Already exists, no migration needed, WAL handles concurrency |
| ORM | **SQLAlchemy 2.0 (async)** OR **raw sqlite3** | Decide based on whether type-safety is worth the dependency. Raw queries match the existing bot's style. Recommend: raw sqlite3 with helper functions for consistency with `database.py` in the bot. |
| Auth | **Discord OAuth 2.0** | Players already have Discord accounts; no separate credentials |
| Sessions | **itsdangerous + signed cookies** OR **Redis** | Cookies fine for low scale, no Redis needed |
| Container | **Docker** with **uvicorn** | Same deployment pattern as the bot |

**No JS framework.** HTMX + Tailwind covers 95% of UX needs. For the dice roller and combat tracker (which need real-time updates), use HTMX's WebSocket extension.

---

## Existing Database Schema

The bot's `database.py` defines these tables. The web portal must read and write compatibly.

### Tables

```sql
-- One row per campaign
campaigns (
    id INTEGER PRIMARY KEY,
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    dm_user_id INTEGER NOT NULL,
    schedule_day TEXT,                    -- 'monday', 'tuesday', ...
    schedule_time TEXT,                   -- '19:00'
    schedule_tz TEXT DEFAULT 'America/Denver',
    ping_days_before INTEGER DEFAULT 3,
    midweek_enabled INTEGER DEFAULT 1,
    followup_count INTEGER DEFAULT 1,
    followup_interval_hours INTEGER DEFAULT 24,
    reminder_hours INTEGER DEFAULT 4,
    auto_schedule INTEGER DEFAULT 0,
    repeat_frequency TEXT DEFAULT 'weekly',  -- 'weekly', 'biweekly', 'monthly'
    sessions_ahead INTEGER DEFAULT 1,
    schedule_start TEXT,                  -- ISO datetime
    ai_backend TEXT,                      -- 'claude', 'local', or NULL
    setting TEXT,                         -- Campaign world description for AI
    created_at TEXT
)

-- Party members with character sheets
players (
    id INTEGER PRIMARY KEY,
    campaign_id INTEGER REFERENCES campaigns(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL,             -- Discord user ID
    character_name TEXT,
    race TEXT,
    char_class TEXT,                      -- e.g. "Bard 8 (College of Lore)"
    level INTEGER,
    background TEXT,
    backstory TEXT,                       -- Narrative paragraph
    abilities TEXT,                       -- Class features, spells, feats
    details TEXT,                         -- AC, HP, ability scores, gear
    active INTEGER DEFAULT 1,
    added_at TEXT,
    UNIQUE(campaign_id, user_id)
)

-- Game sessions
sessions (
    id INTEGER PRIMARY KEY,
    campaign_id INTEGER REFERENCES campaigns(id) ON DELETE CASCADE,
    session_date TEXT NOT NULL,           -- ISO datetime with TZ offset
    title TEXT,
    notes TEXT,
    status TEXT DEFAULT 'scheduled',      -- 'scheduled', 'cancelled', 'completed'
    ping_sent INTEGER DEFAULT 0,
    midweek_sent INTEGER DEFAULT 0,
    reminders_sent INTEGER DEFAULT 0,
    last_reminder_at TEXT,
    final_reminder_sent INTEGER DEFAULT 0,
    created_at TEXT
)

-- Per-session attendance responses
rsvps (
    id INTEGER PRIMARY KEY,
    session_id INTEGER REFERENCES sessions(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL,
    response TEXT DEFAULT 'pending',      -- 'pending', 'yes', 'no', 'tentative'
    responded_at TEXT,
    UNIQUE(session_id, user_id)
)

-- Historical attendance (set when session is completed)
attendance_log (
    id INTEGER PRIMARY KEY,
    session_id INTEGER REFERENCES sessions(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL,
    attended INTEGER DEFAULT 0,
    logged_at TEXT,
    UNIQUE(session_id, user_id)
)

-- Homebrew item definitions
items (
    id INTEGER PRIMARY KEY,
    campaign_id INTEGER REFERENCES campaigns(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    rarity TEXT DEFAULT 'common',         -- 'common', 'uncommon', 'rare', 'very rare', 'legendary', 'artifact'
    item_type TEXT DEFAULT 'wondrous item',
    properties TEXT DEFAULT '{}',         -- JSON blob
    created_by INTEGER NOT NULL,
    created_at TEXT
)

-- Player inventories
player_inventory (
    id INTEGER PRIMARY KEY,
    campaign_id INTEGER REFERENCES campaigns(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL,
    item_id INTEGER REFERENCES items(id) ON DELETE CASCADE,
    quantity INTEGER DEFAULT 1,
    equipped INTEGER DEFAULT 0,
    notes TEXT,
    acquired_at TEXT,
    UNIQUE(campaign_id, user_id, item_id)
)
```

### Tables to ADD for the web portal

These will require schema migration. The bot uses an `_migrate()` helper for additive changes — follow that pattern.

```sql
-- Wiki-style page tree
wiki_pages (
    id INTEGER PRIMARY KEY,
    campaign_id INTEGER REFERENCES campaigns(id) ON DELETE CASCADE,
    parent_id INTEGER REFERENCES wiki_pages(id) ON DELETE CASCADE,
    category TEXT NOT NULL,               -- 'location', 'faction', 'npc', 'history', 'quest', 'session_recap', 'note'
    title TEXT NOT NULL,
    content TEXT DEFAULT '',              -- Markdown
    metadata TEXT DEFAULT '{}',           -- JSON for category-specific fields
    visibility TEXT DEFAULT 'party',      -- 'party' (everyone), 'dm' (DM only)
    created_by INTEGER NOT NULL,          -- Discord user ID
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
)

-- Dice roll history
dice_rolls (
    id INTEGER PRIMARY KEY,
    campaign_id INTEGER REFERENCES campaigns(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL,
    expression TEXT NOT NULL,             -- '2d6+3'
    result_total INTEGER NOT NULL,
    result_breakdown TEXT NOT NULL,       -- '[[3,4],"+",3]'
    label TEXT,                           -- 'Attack', 'Saving Throw', etc.
    rolled_at TEXT DEFAULT (datetime('now'))
)

-- Discord OAuth sessions (web auth)
web_sessions (
    session_id TEXT PRIMARY KEY,          -- Random UUID
    user_id INTEGER NOT NULL,
    username TEXT NOT NULL,
    avatar_hash TEXT,
    access_token TEXT,                    -- Discord OAuth token
    refresh_token TEXT,
    expires_at TEXT,
    created_at TEXT DEFAULT (datetime('now'))
)

-- Optional: notification preferences
notification_prefs (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    campaign_id INTEGER REFERENCES campaigns(id) ON DELETE CASCADE,
    web_notifications INTEGER DEFAULT 1,
    UNIQUE(user_id, campaign_id)
)
```

### IMPORTANT — Schema Migration Strategy

The bot uses this pattern in `database.py`:

```python
def _migrate(conn, table, column, col_type):
    """Add a column if it doesn't exist (safe for repeated runs)."""
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
    except sqlite3.OperationalError:
        pass  # Column already exists
```

The web portal should:
1. Add new tables with `CREATE TABLE IF NOT EXISTS`
2. NEVER alter existing bot tables in incompatible ways
3. NEVER rename or drop columns the bot depends on
4. Use a coordinated migration file that both services can run safely

---

## Project Structure

```
herald-web/
├── app/
│   ├── __init__.py
│   ├── main.py                  # FastAPI app, lifespan, middleware
│   ├── config.py                # Settings from env vars
│   ├── database.py              # SQLite connection, query helpers
│   ├── auth/
│   │   ├── __init__.py
│   │   ├── discord_oauth.py     # OAuth flow handlers
│   │   ├── dependencies.py      # FastAPI deps: current_user, require_dm
│   │   └── sessions.py          # Web session management
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── home.py              # Dashboard
│   │   ├── auth_routes.py       # /login, /callback, /logout
│   │   ├── schedule.py          # Calendar, session detail, RSVP
│   │   ├── party.py             # Roster, character sheets
│   │   ├── inventory.py         # Compendium, player bags
│   │   ├── lore.py              # Wiki pages
│   │   ├── ai_tools.py          # Forge, lore, ask UI
│   │   ├── dice.py              # Dice roller
│   │   └── admin.py             # DM-only campaign settings
│   ├── services/
│   │   ├── __init__.py
│   │   ├── ai_proxy.py          # Wrapper around bot's claude_api/local_api
│   │   ├── dice_engine.py       # Dice notation parser and roller
│   │   └── permissions.py       # is_dm, is_party_member, etc.
│   ├── models/                  # Pydantic models for forms/responses
│   ├── templates/
│   │   ├── base.html
│   │   ├── partials/            # HTMX fragments
│   │   ├── dashboard.html
│   │   ├── schedule/
│   │   ├── party/
│   │   ├── inventory/
│   │   ├── lore/
│   │   └── ai/
│   └── static/
│       ├── css/                 # Tailwind output
│       ├── js/                  # Minimal vanilla JS for HTMX extensions
│       ├── images/
│       └── icons/
├── data/                        # Symlinked or volume-mounted from bot
│   └── scheduler.db
├── tests/
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml OR requirements.txt
├── tailwind.config.js
├── .env.example
└── README.md
```

---

## Configuration (`.env`)

```bash
# ─── Required ────────────────────────────────────────────────
HERALD_WEB_HOST=0.0.0.0
HERALD_WEB_PORT=8088
HERALD_WEB_BASE_URL=https://herald.w0aez.com

# Database (must point at the same file the bot uses)
DB_PATH=data/scheduler.db

# Session signing key — generate with `python -c "import secrets; print(secrets.token_hex(32))"`
SESSION_SECRET=

# ─── Discord OAuth ──────────────────────────────────────────
DISCORD_CLIENT_ID=
DISCORD_CLIENT_SECRET=
DISCORD_REDIRECT_URI=https://herald.w0aez.com/auth/callback

# ─── AI (shared with bot — same env vars) ───────────────────
ANTHROPIC_API_KEY=
CLAUDE_MODEL=claude-sonnet-4-20250514
LOCALAI_BASE_URL=
LOCALAI_MODEL=
LOCALAI_API_KEY=not-needed

# ─── Optional: bot guild restriction ────────────────────────
# Only allow login from members of this Discord server
ALLOWED_GUILD_ID=
```

---

## Authentication Flow

1. User visits `/login` → redirected to Discord OAuth
2. Discord redirects back to `/auth/callback?code=...`
3. Server exchanges code for access token
4. Server fetches user info from Discord API: `GET https://discord.com/api/users/@me`
5. Optionally validate the user is in the configured guild: `GET https://discord.com/api/users/@me/guilds`
6. Create a `web_sessions` row, set a signed cookie with the session ID
7. Subsequent requests load the session via cookie

**Required scopes**: `identify` (and `guilds` if using `ALLOWED_GUILD_ID`)

**Permission model**:
- **Anonymous**: only `/login` and `/auth/*` routes
- **Authenticated**: can view their own player profile and any campaigns they're a member of
- **DM** (where `campaigns.dm_user_id == user_id`): full read/write access to their campaign(s)

Use FastAPI dependencies:

```python
async def current_user(session_id: str = Cookie(None)) -> User: ...
async def require_member(campaign_id: int, user: User = Depends(current_user)): ...
async def require_dm(campaign_id: int, user: User = Depends(current_user)): ...
```

---

## Visual Design

### Aesthetic
**Dark fantasy / DM screen**. Think rich dark backgrounds with parchment-cream text, deep purple primary, burnished gold accents. Reference the existing Herald bot logo (purple shield, gold trumpet, gold d20).

### Color Palette
```css
--bg-primary: #1a1025;        /* Deep purple-black */
--bg-secondary: #2a1f3d;      /* Slightly lifted panels */
--bg-card: #3a2f4d;           /* Card surfaces */
--text-primary: #f5e6d3;      /* Parchment cream */
--text-secondary: #c9b8a3;    /* Muted parchment */
--accent-purple: #8B5CF6;     /* Royal purple — primary actions */
--accent-purple-dark: #5B21B6;
--accent-gold: #FCD34D;       /* Gold — highlights, links */
--accent-gold-dark: #D97706;

/* Rarity colors (already in bot for items) */
--rarity-common: #9D9D9D;
--rarity-uncommon: #1EFF00;
--rarity-rare: #0070DD;
--rarity-very-rare: #A335EE;
--rarity-legendary: #FF8000;
--rarity-artifact: #E6CC80;
```

### Typography
- Headings: a serif display font like **Cinzel** or **EB Garamond** (Google Fonts) for that medieval feel
- Body: clean sans like **Inter** for readability
- Monospace: **JetBrains Mono** for dice expressions, item IDs, code

### Components
- **Cards**: subtle border (1px) + slight shadow, rounded corners (rounded-lg / 8px)
- **Buttons**: filled purple primary, outlined gold secondary, ghost for tertiary
- **Item cards**: left border colored by rarity (4px solid)
- **Avatars**: pull Discord avatars via `https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.png`
- **Backgrounds**: subtle parchment texture or gradient as page bg, not too busy

### Layout
- Persistent left sidebar (~240px) with nav, collapsible to icons-only on tablet
- Main content area with max-width container
- Mobile: sidebar becomes a hamburger drawer

---

## Feature Specifications

> Build in the order listed. Each phase should be independently deployable.

### Phase 1: Foundation
**Auth + Layout + Dashboard**

- Discord OAuth login flow
- Session management with signed cookies
- Base template with sidebar navigation
- Dashboard route showing:
  - User's name and avatar in sidebar header
  - Campaign selector (if user is in multiple campaigns)
  - "Next session" card with countdown, RSVP status, button to open detail
  - Recent activity feed (last 10 RSVPs, item grants, completed sessions)
  - Quick stats: party size, total sessions played, attendance rate
- Logout

**Acceptance**: A logged-in DM sees their dashboard for "Hord of the Dragon Queen" with the next session card showing "May 10, 2026 — 1/5 confirmed".

### Phase 2: Schedule
**Calendar + Session Management**

- Month-grid calendar view of all sessions in the active campaign
  - Past sessions: greyed out
  - Scheduled: purple
  - Cancelled: red strikethrough
  - Completed: green check
- Click a date to see session detail panel (HTMX swap):
  - Date/time, title, notes (editable by DM)
  - RSVP grid: avatars + status icons + character names
  - Action buttons (DM only): Edit, Cancel, Complete, Re-ping, Manual ping reset
  - Action buttons (player): RSVP (Yes/No/Tentative)
- "Create Session" button (DM only) — modal form
- Schedule settings page (DM only) — friendly UI for `ping_days_before`, `repeat_frequency`, etc., replacing the slash command parameters

**Acceptance**: DM clicks May 10, sees Venna confirmed and four pending players, can change Kerrigan to "Tentative" with one click.

### Phase 3: Party / Character Sheets
**Roster + Editable Sheets**

- Party page listing all players with character names, classes, levels, attendance rate
- Click a player → full character sheet view
- DM (or sheet owner) can click "Edit" → form with all fields:
  - Race, class, level, background
  - Backstory (markdown editor)
  - Abilities (markdown editor)
  - Details (markdown editor)
- "Re-import from D&D Beyond" button → URL input or file upload → calls existing PDF import logic via `ai_backend.parse_character_pdf`
- Per-player attendance heatmap (sparkline showing attended/missed over last N sessions)
- View this player's inventory inline

**Acceptance**: DM opens Kerrigan's sheet, scrolls down to see the full backstory, edits the "Details" field to update HP from 51 to 57 after a level up.

### Phase 4: Inventory
**Compendium + Player Bags**

- Item compendium page (table view):
  - Sortable columns: name, rarity (color-coded), type, holder, created date
  - Search bar (uses existing `db.search_items`)
  - Filter dropdowns: rarity, type, "unclaimed only"
  - Click row → item detail modal
- Item detail page:
  - Full description (markdown rendered)
  - Properties listed cleanly (damage, AC, charges, attunement, effects, quirks)
  - "Held by" section with avatars
  - Edit/delete buttons (DM only)
- Player bag view:
  - Cards-style grid of items the player has
  - Equipped items have a "🔧 Equipped" badge
  - Player can: equip/unequip, request transfer, view full item
- DM-only "Create Item" form OR "Forge with AI" (jumps to AI tools)
- DM-only "Distribute Item" — pick item, pick player, set quantity → calls `db.give_item`

**Acceptance**: DM filters to "Legendary" items, drags "Sunsword" to Alice's bag (or uses a dropdown), Alice now has it.

### Phase 5: AI Tools Panel
**Web UI for Forge, Lore, Ask**

- AI tools sidebar with sub-tabs: Forge, Locations, Factions, NPCs, History, Ask
- Each tool is a clean form, not a slash command:
  - Forge: name, rarity dropdown, type dropdown, context textarea, backend selector (Claude/Local), "Generate" button
  - Lore variants: name/topic + context + backend
  - Ask: question textarea + campaign context auto-included + backend
- Generated output rendered in a card with full styling
- For items/lore: "Save to Compendium" or "Save to Wiki" button
- Generation history list per user (last 20)
- Reuses existing `claude_api.py`, `local_api.py`, `ai_backend.py` from the bot — IMPORT them, don't reimplement.

**Implementation note**: The web service should be deployed in a way that it can import from the bot's source. Options:
- Symlink the bot's Python files into the web container
- Publish the bot's helpers as a shared package
- Or just COPY the AI modules into the web image (simplest for v1)

**Acceptance**: DM picks "Generate NPC", types "Morwen the Blind", clicks Generate, sees a beautifully formatted NPC profile with personality, voice notes, and a spoiler-tagged secret. Hits "Save to Wiki" and it appears in the wiki under NPCs.

### Phase 6: Lore / Campaign Wiki
**Pages + Tree + Linking**

- Wiki page tree on the left, organized by category (Locations, Factions, NPCs, History, Quests, Session Recaps, Notes)
- Click a page → markdown rendered with category-specific metadata fields (e.g., NPCs show personality/motivation/secret as styled blocks)
- "New Page" button (DM only initially) → category selector + form
- Markdown editor with toolbar
- Page metadata: visibility (DM-only / Party-visible), category, tags
- Cross-linking: when you write `[[Morwen the Blind]]` in a page, it auto-links to that NPC's wiki page
- Search across all wiki content
- AI generation auto-saves: when a player generates a location via the AI panel, it can be saved as a wiki page

**Acceptance**: DM browses to "NPCs → Morwen the Blind", sees the AI-generated profile, edits it to add post-encounter notes, hits save. The "Strahd" page links to her with `[[Morwen the Blind]]` and shows up as a hyperlink.

### Phase 7: Dice Roller
**Real-time Shared Dice Log**

- Dice tray UI: input field with dice notation (`2d6+3`, `d20`, `4d6kh3` for stat rolling)
- Quick-roll buttons: d4, d6, d8, d10, d12, d20, d100
- Advantage / Disadvantage toggle for d20 rolls
- Results appear in a shared roll log panel (WebSocket-driven)
- Each roll shows: roller's avatar, expression, result (with breakdown of individual dice), optional label
- Bot integration: dice rolls in the web optionally cross-post to the campaign's Discord channel
- Roll history per player

**Implementation**: Use a Python dice library like `dice` or `d20`, OR implement a simple parser. Store every roll in `dice_rolls` table.

### Phase 8: Future / Stretch

These are explicitly **out of scope** for the initial build but should be designed compatible:

- **Combat tracker**: initiative order, HP, conditions, turn timer
- **Session recap generator**: DM dumps notes → AI generates polished recap → posted to Discord + saved to wiki
- **Quest tracker**: active/completed quests with objectives
- **Map embeds**: image uploads with simple pin/annotation overlay
- **Calendar export**: iCal feed of sessions
- **Mobile PWA**: installable, offline-capable for player views
- **Discord webhook integration**: web actions trigger Discord messages (e.g., "Alice equipped Sunsword" posts to the channel)

---

## API Conventions

### URL Structure
```
GET  /                              → Dashboard
GET  /login                         → Discord OAuth start
GET  /auth/callback                 → OAuth callback
POST /logout                        → Clear session

GET  /campaigns/{id}                → Campaign dashboard
GET  /campaigns/{id}/schedule       → Calendar
GET  /campaigns/{id}/sessions/{sid} → Session detail (HTMX-friendly)
POST /campaigns/{id}/sessions/{sid}/rsvp     → RSVP action
POST /campaigns/{id}/sessions/{sid}/cancel   → DM only

GET  /campaigns/{id}/party          → Roster
GET  /campaigns/{id}/players/{uid}  → Character sheet
POST /campaigns/{id}/players/{uid}  → Update sheet
POST /campaigns/{id}/players/{uid}/import   → Re-import PDF

GET  /campaigns/{id}/items          → Compendium
GET  /campaigns/{id}/items/{iid}    → Item detail
POST /campaigns/{id}/items          → Create item (DM)
POST /campaigns/{id}/inventory/give → Distribute item (DM)
POST /campaigns/{id}/inventory/transfer → Player-to-player

GET  /campaigns/{id}/wiki                    → Wiki home
GET  /campaigns/{id}/wiki/{category}/{slug}  → Page detail
POST /campaigns/{id}/wiki                    → New page

GET  /campaigns/{id}/ai              → AI tools landing
POST /campaigns/{id}/ai/forge        → Generate item
POST /campaigns/{id}/ai/lore         → Generate lore
POST /campaigns/{id}/ai/ask          → Ask question

GET  /campaigns/{id}/dice            → Dice tray
POST /campaigns/{id}/dice/roll       → Submit roll
WS   /campaigns/{id}/dice/feed       → Live roll updates
```

### HTMX Patterns
- Forms POST and return HTML fragments to swap into the page
- Use `hx-target` and `hx-swap` for partial updates
- Use `hx-trigger="load delay:30s"` for the next-session countdown
- Modals: `<dialog>` element + HTMX swap

### Response Conventions
- Form validation errors: re-render the form fragment with error messages inline
- Success: swap the affected component, show a toast notification (HTMX out-of-band swap into `#toast-area`)
- Auth failures: redirect to `/login`
- Permission failures: 403 with a styled error page

---

## Code Style & Conventions

Follow the existing bot's style. From `database.py`:
- Plain SQL, no ORM
- Helper functions like `get_campaign(id)`, `get_players(campaign_id)`, etc.
- Connection helper that opens, runs, returns dict-row results, closes
- WAL mode pragma on connect
- Don't catch exceptions broadly — let them propagate to FastAPI's error handler

```python
def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn
```

The bot uses simple module-level functions, NOT classes. Match that.

For async DB access, use `aiosqlite` if you want true async, OR run sync queries in a thread pool with `asyncio.to_thread()`. Either is fine — SQLite isn't the bottleneck.

---

## Deployment

### `Dockerfile`

```dockerfile
FROM python:3.12-slim

LABEL maintainer="bucknova"
LABEL description="Herald Web — D&D 5e campaign portal"

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8088
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8088"]
```

### `docker-compose.yml` (extended from the bot's compose)

```yaml
services:
  herald-bot:
    build: ./herald-bot
    container_name: herald-bot
    restart: unless-stopped
    env_file: ./herald-bot/.env
    volumes:
      - ./shared-data:/app/data

  herald-web:
    build: ./herald-web
    container_name: herald-web
    restart: unless-stopped
    env_file: ./herald-web/.env
    ports:
      - "8088:8088"
    volumes:
      - ./shared-data:/app/data
    depends_on:
      - herald-bot
```

Both services mount the same `./shared-data` directory containing `scheduler.db`. SQLite WAL mode handles concurrent access.

---

## Testing Strategy

- **Unit tests** for the dice engine and any non-trivial helpers
- **Integration tests** that spin up a fresh SQLite DB, seed test data, and hit endpoints with FastAPI's `TestClient`
- **No need for E2E browser tests** in v1 — manual testing in dev is fine
- Test users: create fixtures for a "DM user" and "Player user" with bypass auth in test mode

---

## Things to Watch Out For

1. **Concurrent writes between bot and web**. SQLite WAL handles this, but avoid long transactions on either side. Don't hold a connection open across requests.

2. **Session date formatting**. The bot stores dates as ISO strings WITH timezone offset (e.g., `2026-04-26T15:00:00-06:00`). Always parse with `datetime.fromisoformat()` and respect the offset. Don't assume UTC.

3. **Discord avatars expire**. The avatar hash from OAuth is stable, but if the user changes their avatar, the cached URL stops working. Refresh on login.

4. **Markdown sanitization**. User input goes into wiki pages, character backstories, and item descriptions. Render markdown safely (use `markdown` + `bleach`, or `mistune` with a strict renderer). Don't allow raw HTML.

5. **The bot's AI rate limiter is in-memory**. If both the bot and web service make AI calls, they have separate rate limit pools. This is fine for now (web is mostly DM use, bot is mostly player use), but consider a shared limiter later if it matters.

6. **Schema migrations are SHARED**. Don't add columns the bot doesn't know about and then have the bot crash on `SELECT *`. Coordinate the migration so both services run compatible code.

7. **`dm_user_id` is the source of truth for permissions**. Never trust the client about who's a DM. Always check `campaigns.dm_user_id == session_user_id`.

8. **Don't break the bot**. The web portal is additive. Adding tables is fine. Modifying or dropping existing columns is not — the bot will crash.

9. **Image uploads**. If you add item art or map images later, store them in a volume-mounted directory, not in the database. SQLite is for structured data.

10. **AI content is user input**. Players can ask the AI anything. Pipe campaign context (which includes character sheets) but don't let players inject prompts that exfiltrate other campaigns' data. Always scope AI calls to the current campaign's context.

---

## Reference: Existing Bot Modules to Reuse

The web portal should import these from the bot rather than reimplementing:

- `database.py` — All the existing `get_*`, `create_*`, `update_*` functions
- `claude_api.py` — `forge_item`, `enhance_item`, `generate_lore`, `ask_dnd`, `parse_character_pdf`
- `local_api.py` — Same interface, LocalAI backend
- `ai_backend.py` — Dispatcher (`resolve_backend`, unified call functions)
- `pdf_parser.py` — PDF rendering and download
- `languages.py` — Cipher translation (could be a fun web feature: "translate as Draconic" for chat in the wiki)

Decide early how to share these. **Recommended for v1**: copy them into the web image at build time (`COPY ../herald-bot/{claude_api,local_api,ai_backend,pdf_parser,database,languages}.py ./app/shared/`). Later, refactor into a shared package.

---

## Definition of Done (Phase 1)

The first release is complete when:

- [ ] User can log in via Discord OAuth
- [ ] User sees their campaign(s) in the sidebar
- [ ] Dashboard shows next session, recent activity, party stats
- [ ] Sidebar nav links to placeholder pages for Schedule / Party / Inventory / Lore / AI Tools
- [ ] Logout works
- [ ] Container builds and runs alongside the bot
- [ ] Reverse proxy serves it at the chosen subdomain
- [ ] All bot data is visible (read-only is fine for Phase 1)

After Phase 1, ship and iterate. Don't try to build everything before deploying.

---

## Open Questions for the Builder

- **Markdown editor**: roll your own with a `<textarea>` and preview, OR pull in something like EasyMDE/Toast UI Editor? Recommend simple textarea + server-side preview for Phase 6.
- **Session signing key rotation**: not needed for v1; document the manual process.
- **Mobile-first or desktop-first?** Recommend desktop-first since it's a DM/prep tool, mobile responsive layer added later.
- **Multi-server support?** The bot supports being in multiple Discord servers with multiple campaigns. The web portal should too — design the campaign selector with this in mind from the start.

---

## What "Done" Looks Like (the whole project)

A DM running their session can:
1. Open the portal on a tablet next to their DM screen
2. See the party's character sheets in tabs across the top
3. Track initiative and HP in the combat tracker
4. Roll dice that show in both the web and Discord
5. Click on the location their party just entered to see the AI-generated lore
6. Hand out a magic item with two clicks
7. Take session notes that auto-generate a recap when the session ends

A player on a phone can:
1. Get a Discord notification of an upcoming session
2. Tap the notification → opens the portal → RSVPs in two clicks
3. Check their character's inventory and equip a new item
4. Read the wiki entry on the NPC they met last week

That's the goal. Build toward it iteratively.

---

*This spec is a living document. As the project evolves, update it. The first PR should include any clarifications or decisions made during initial scaffolding.*
