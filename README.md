# ⚔️ Herald

> A self-hosted D&D 5e campaign assistant — a Discord bot and a web portal that share one database. Like Apollo, but free, self-hosted, and built for tabletop RPGs.

![Python](https://img.shields.io/badge/python-3.12-blue.svg)
![Docker](https://img.shields.io/badge/docker-ready-2496ED.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-async-009688.svg)
![discord.py](https://img.shields.io/badge/discord.py-2.3+-5865F2.svg)
![Status](https://img.shields.io/badge/web%20portal-Phase%200-orange.svg)
![License](https://img.shields.io/badge/license-TBD-lightgrey.svg)

Herald is the DM's right hand. The Discord bot handles real-time party
interactions — pings, RSVPs, quick lookups, AI-generated loot — while the
web portal (in development) brings the same data into a richer interface
for session prep, character sheet editing, the campaign wiki, and visual
workflows that don't fit in a Discord embed.

Both surfaces are first-class. Use whichever fits the moment.

---

## ✨ Features

### 🤖 Discord Bot — **production**

| Area | What it does |
| ---- | ------------ |
| 📅 **Scheduling** | Recurring schedules, configurable ping chain (initial → midweek → follow-ups → final reminder), auto-created sessions |
| ⚔️ **Attendance** | Interactive RSVP buttons, historical attendance stats per player, completed-session logging |
| 🎒 **Homebrew Inventory** | Create / edit / distribute / trade items with rarity tiers (Common → Artifact) and color-coded embeds |
| 📜 **Character Sheets** | Per-player sheets feed AI context; PDF import from D&D Beyond via vision-capable models |
| 🌐 **Languages** | 18 D&D languages with unique cipher mappings (Common, Dwarvish, Elvish, Draconic, Infernal, Thieves' Cant, …) |
| 🔥 **Item Forge (AI)** | Describe an item — Claude or LocalAI generates full lore, mechanics, and properties, auto-saved to the compendium |
| 📚 **Lore Builder (AI)** | Generate locations, factions, NPCs, and historical lore with spoiler-tagged secrets |
| 💬 **D&D Q&A (AI)** | Ask 5e rules questions with campaign context auto-injected |

### 🌐 Web Portal — **in development**

| Phase | Focus | Status |
| ----- | ----- | ------ |
| 0 | Repo bootstrap + scaffolds | ✅ Done |
| 1 | Discord OAuth, sidebar layout, read-only dashboard, campaign JSON export | 🚧 Next |
| 2 | Calendar + session detail + RSVP from the web | ⏳ Planned |
| 3 | Party roster + editable character sheets + PDF re-import | ⏳ Planned |
| 4 | Item compendium + player bags + DM distribute flows | ⏳ Planned |
| 5 | Web-native AI tools (Forge / Lore / Ask) with save-to-compendium | ⏳ Planned |
| 6 | Campaign wiki — pages, tree, cross-linking, search | ⏳ Planned |
| 7 | Real-time shared dice roller with optional Discord cross-post | ⏳ Planned |
| 8 | Stretch — combat tracker, session recap AI, quests, maps, iCal, PWA | 💭 Future |

See [PLAN.md](./PLAN.md) for the full phased build plan.

---

## 🏗️ Architecture

```
 ┌──────────────────────┐    ┌──────────────────────┐
 │  herald-bot          │    │  herald-web          │
 │  (Python/discord.py) │    │  (FastAPI + HTMX)    │
 │  Gateway connection  │    │  Port: 8088          │
 └──────────┬───────────┘    └──────────┬───────────┘
            │                           │
            └────► data/scheduler.db ◄──┘
                   (SQLite, WAL mode)
                            │
                  optional reverse proxy
                            │
                  herald.your-domain.com
```

**Key idea:** both services read and write the same SQLite file. There is
no bot HTTP API — the web portal queries the database directly. SQLite WAL
mode handles concurrent access safely.

**Auth model:** Discord OAuth 2.0. A user is the same identity in the bot
(via Discord `user_id`) and in the web portal. No separate accounts. Login
is restricted to users who share a Discord guild with the bot.

**Schema ownership:** the bot owns its tables in `shared/database.py`. The
web portal owns its own tables in `herald-web/app/db_init.py`. Neither
service touches the other's schema. See [ARCHITECTURE.md](./ARCHITECTURE.md)
for the full rationale.

---

## 🚀 Quick Start

### Prerequisites

- Docker and Docker Compose (tested on Unraid; works on any Linux/macOS host)
- A Discord Bot Token ([create one](https://discord.com/developers/applications))
- _Optional:_ an Anthropic API key for Claude-powered AI features
- _Optional:_ a LocalAI / Ollama / OpenAI-compatible server for local AI

### 1. Clone

```bash
git clone https://github.com/bucknova/Herald.git
cd Herald
```

### 2. Configure the bot

```bash
# Create herald-bot/.env from the bot's existing template
# (see herald-bot/README.md for the full setup walkthrough)
# At minimum set DISCORD_TOKEN
```

See [herald-bot/README.md](./herald-bot/README.md) for the full bot setup
walkthrough (Discord Developer Portal, OAuth invite URL, optional AI
configuration).

### 3. (Web portal — Phase 1+) Configure the web

```bash
cp herald-web/.env.example herald-web/.env
# Edit herald-web/.env — fill in DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET,
# SESSION_SECRET, HERALD_WEB_BASE_URL
```

The web portal will be functional after Phase 1 ships. Today it serves a
placeholder at `/`.

### 4. Run

```bash
docker compose up -d
```

- **Bot** — connects to Discord and starts processing slash commands.
- **Web** — listens on `http://localhost:8088`.
- **Data** — persisted to `./data/scheduler.db`.

---

## 📊 Project Status

| Component   | Version | Status                                                |
| ----------- | ------- | ----------------------------------------------------- |
| `herald-bot`| Production | Running on the maintainer's Unraid box             |
| `herald-web`| 0.0.1   | Phase 0 scaffold — empty FastAPI service that builds  |
| `shared/`   | —       | Stable; bot owns it, web reads from it                |

The web portal is being built in phases (see roadmap above). Phase 1 is
not deployable for daily use yet — it lands when Discord OAuth login
works end-to-end in a real browser.

---

## 🗂️ Project Structure

```
Herald/
├── herald-bot/                 Discord bot (production)
│   ├── bot.py
│   ├── scheduler.py
│   ├── Dockerfile
│   ├── requirements.txt
│   └── README.md               Bot-specific docs
│
├── herald-web/                 Web portal (in development)
│   ├── app/
│   │   ├── main.py             FastAPI entry point
│   │   ├── config.py           Env-driven settings
│   │   ├── db_init.py          Web-owned schema (web tables only)
│   │   └── (auth/, routes/, templates/, services/ in Phase 1+)
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── .env.example
│   └── README.md
│
├── shared/                     Modules both services import
│   ├── database.py             Bot-owned schema + query helpers
│   ├── claude_api.py           Claude API integration
│   ├── local_api.py            LocalAI / OpenAI-compatible integration
│   ├── ai_backend.py           Backend dispatcher
│   ├── pdf_parser.py           D&D Beyond PDF rendering
│   └── languages.py            18 D&D language ciphers
│
├── data/                       Runtime data (git-ignored)
│   └── scheduler.db            SQLite database, WAL mode
│
├── .github/                    Issue templates, PR template
├── docker-compose.yml          Both services
├── ARCHITECTURE.md             Decisions, schema strategy, auth, deployment
├── PLAN.md                     Phased build plan with concrete tasks
├── herald-web-spec.md          Original web portal spec (reference)
├── CONTRIBUTING.md             How to contribute
├── CHANGELOG.md                Notable changes
├── SECURITY.md                 Security policy
└── README.md                   This file
```

---

## 📖 Documentation

- **[ARCHITECTURE.md](./ARCHITECTURE.md)** — every architectural decision and the reasoning behind it. Read this before contributing to the web portal.
- **[PLAN.md](./PLAN.md)** — phased build plan turning the architecture into concrete tasks.
- **[herald-bot/README.md](./herald-bot/README.md)** — full bot command reference, setup, and ping-chain flow.
- **[herald-web/README.md](./herald-web/README.md)** — web subproject orientation.
- **[herald-web-spec.md](./herald-web-spec.md)** — the original web portal specification.
- **[CONTRIBUTING.md](./CONTRIBUTING.md)** — how PRs and issues work here.

---

## ⚙️ Configuration

Both services read configuration from environment variables (loaded from
`.env` files via Docker Compose).

### Bot (`herald-bot/.env`)

| Var | Required | Notes |
| --- | -------- | ----- |
| `DISCORD_TOKEN` | Yes | Bot token from the Discord Developer Portal |
| `ANTHROPIC_API_KEY` | No | Enables Claude-powered `/forge` and `/lore` |
| `CLAUDE_MODEL` | No | Defaults to `claude-sonnet-4-20250514` |
| `LOCALAI_BASE_URL` | No | OpenAI-compatible local server, e.g. `http://192.168.1.50:8080/v1` |
| `LOCALAI_MODEL` | No | Model name as configured in your LocalAI |
| `DM_RATE_LIMIT` | No | Per-DM AI calls per hour. Default: 60 |
| `PLAYER_RATE_LIMIT` | No | Per-player AI calls per hour. Default: 10 |

### Web (`herald-web/.env`) — Phase 1+

| Var | Required | Notes |
| --- | -------- | ----- |
| `HERALD_WEB_BASE_URL` | Yes | Public-facing URL (used to build the OAuth redirect URI) |
| `DB_PATH` | Yes | Path to the SQLite DB. Same file the bot uses. |
| `SESSION_SECRET` | Yes | Random 64-char hex string for signing cookies |
| `DISCORD_CLIENT_ID` | Yes | From the Discord Developer Portal → OAuth2 tab |
| `DISCORD_CLIENT_SECRET` | Yes | From the same tab |
| `DISCORD_REDIRECT_URI` | Yes | Must match a redirect URI registered with Discord |
| `ALLOWED_GUILD_ID` | No | Optional — lock the portal to a single Discord server |
| `ANTHROPIC_API_KEY` | No | Same keys as the bot |
| `LOCALAI_BASE_URL` | No | Same as the bot |

See `herald-web/.env.example` for the full template.

---

## 🌐 Network Setup

The web portal listens on port `8088`. How users actually reach it depends
on your network. **Set a static IP / DHCP reservation on the host** — if
the IP changes, your Discord OAuth redirect URI breaks and nobody can log in.

Three working access patterns:

1. **Static IP** — `http://192.168.x.x:8088`
2. **mDNS** — `http://<host>.local:8088` (e.g. `http://tower.local:8088`) if your network supports it
3. **Reverse proxy with a domain** — `https://herald.your-domain.com`

Discord allows multiple redirect URIs per OAuth app, so dev and prod can
coexist. The full Discord OAuth setup walkthrough lands with Phase 1.

---

## 💾 Data & Backups

All persistent state lives in `data/scheduler.db` (SQLite with WAL mode).
Three artefacts you'll see in `data/`:

- `scheduler.db` — main database
- `scheduler.db-wal` — write-ahead log
- `scheduler.db-shm` — shared memory file

Back up the whole `data/` directory if you care about attendance history,
character sheets, the item compendium, and (once Phase 6 ships) the
campaign wiki.

The web portal's Phase 1 "Export Campaign" button gives you a per-campaign
JSON dump as an additional manual backup path.

---

## 🛠️ Development

This is a **brownfield project** — the bot is in production. Read the
guardrails before contributing:

- The bot's existing code is treated as **read-only** unless changes are
  explicitly approved.
- The web portal adds **new files and new database tables only**.
- Existing bot tables and columns are off-limits for modification.

See [CONTRIBUTING.md](./CONTRIBUTING.md) for the full working agreement.

### Code style

- Python 3.12 across both services
- Plain SQL, no ORM (matches the bot's existing pattern)
- Module-level functions, not classes for business logic
- Conventional commit messages (`feat:`, `fix:`, `chore:`, `docs:`, …)
- Every commit on `main` is a working, deployable state

---

## 🗺️ Roadmap

See [PLAN.md](./PLAN.md) for the granular task breakdown. The macro view:

- **Now** — Phase 1: auth, layout, read-only dashboard, campaign export
- **Soon** — Phases 2–4: web mutations (RSVP, sheets, inventory)
- **Then** — Phases 5–7: AI tools, wiki, dice roller
- **Eventually** — Phase 8: combat tracker, session recaps, maps, PWA

---

## 🤝 Contributing

This is currently a personal/hobbyist project. Issues and PRs are welcome,
but the maintainer may not be quick to respond.

If you're submitting a PR, read [CONTRIBUTING.md](./CONTRIBUTING.md) first.

---

## 📄 License

License TBD. The codebase is being prepared for an open-source license
decision.

---

## 🙏 Acknowledgments

- The [Apollo](https://apollo-bot.com/) Discord bot for showing what good
  campaign scheduling looks like
- [discord.py](https://discordpy.readthedocs.io/) for the bot framework
- [FastAPI](https://fastapi.tiangolo.com/) and [HTMX](https://htmx.org/)
  for making the web portal possible without a JS framework
- [Anthropic Claude](https://www.anthropic.com/) for AI-powered content
  generation
- The D&D 5e community — every campaign, every character sheet, every
  improvised tavern name is what this is built for

---

*Built by [@bucknova](https://github.com/bucknova). For DMs who'd rather
prep than fight with tooling.*
