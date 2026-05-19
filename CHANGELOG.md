# Changelog

All notable changes to Herald are recorded here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project uses semver-ish versioning where the bot and web portal
each track their own version under their respective heading.

---

## [Unreleased]

### Web Portal

- Working toward Phase 1 (Foundation): Discord OAuth login, sidebar
  layout, read-only dashboard, campaign JSON export. See
  [PLAN.md](./PLAN.md).

### Bot

- No changes in this cycle.

---

## [0.0.1] — 2026-05-19 — Web portal scaffold

### Added

- Monorepo layout: `herald-bot/`, `herald-web/`, `shared/`, `data/`.
- `herald-web/` empty FastAPI scaffold: builds, starts, serves
  `Herald Web` at `/`, `ok` at `/healthz`.
- Root `docker-compose.yml` defines both services with shared `./data`
  volume.
- Planning documents: `ARCHITECTURE.md`, `PLAN.md`, top-level `README.md`,
  `CONTRIBUTING.md`, `SECURITY.md`, GitHub issue/PR templates.

### Changed

- The Discord bot moved from a standalone layout into `herald-bot/`. The
  bot's Python code is unchanged; the Dockerfile was updated to use the
  repository root as build context (so the bot still imports modules from
  `shared/` at runtime via flat imports).

### Notes

- The web portal is **not** functional for daily use yet. Phase 1 is in
  progress.
- The bot's running behaviour is unchanged from its pre-monorepo state.

---

## Pre-monorepo bot history

The bot was developed and run as a standalone project before this
repository existed. Earlier features were not tracked in this changelog
but include:

- Recurring schedule + full configurable ping chain
- Interactive RSVP buttons + attendance logging
- Homebrew item compendium with rarity tiers
- 18 D&D language ciphers
- AI-powered item forge and lore builder (Claude + LocalAI)
- D&D Beyond PDF character sheet import via vision
- Per-campaign AI backend selection
- Per-campaign world/setting context for AI calls
