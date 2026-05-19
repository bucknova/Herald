# Contributing to Herald

Thanks for the interest! Herald is currently a personal/hobbyist project,
but issues and pull requests are welcome.

This document is short on purpose — it captures the working agreement, not
every possible policy.

---

## Before you start

1. **Read [ARCHITECTURE.md](./ARCHITECTURE.md)**. The decisions there are
   the source of truth — if your change goes against one of them, the PR
   needs to update ARCHITECTURE.md too.
2. **Read the section of [PLAN.md](./PLAN.md)** that covers what you're
   touching. Most work has a phase home.
3. **Open an issue first** for anything non-trivial. Saves us both time.

---

## Guardrails

Herald is a **brownfield** project — the bot is in production. A few hard
rules:

- **Don't modify existing Herald-Bot code** (`herald-bot/` and `shared/`)
  without explicit approval. If you think you need to, open an issue and
  we'll discuss.
- **The web portal adds new files and new database tables only.** Existing
  bot tables and columns are off-limits for modification.
- **Schema changes are additive forever.** No renames, no drops, no type
  changes on bot-owned tables.

---

## Code style

- **Python 3.12**, both services. Don't introduce older syntax or 3.13+
  features.
- **Plain SQL via `sqlite3`**. No ORM. Match the bot's existing style.
- **Module-level functions**, not classes for business logic.
- **A `_connect()` helper** that opens with WAL + foreign keys + `Row`
  factory, returns dict-rows, closes per query.
- **Don't catch exceptions broadly.** Let them propagate. FastAPI and
  discord.py both have decent default error handling.
- **No JavaScript framework** in the web portal. HTMX covers 95% of UX
  needs.

---

## Commits

- **Conventional commits**: `feat:`, `fix:`, `chore:`, `docs:`,
  `refactor:`, `test:`. Optional scope: `feat(auth): …`, `fix(scheduler): …`.
- **Every commit on `main` is deployable.** Broken code lives on
  feature branches.
- **Squash a noisy branch** before merging if it has cleanup or
  back-and-forth commits.

---

## Pull requests

Use the PR template — it's short. Cover:

- What the change does and why
- What's tested and how
- Any architecture decisions made (link to ARCHITECTURE.md updates)
- Screenshots for UI changes

CI isn't set up yet (early days). Manual testing on Unraid is the bar.

---

## Issues

Two templates: **bug report** and **feature request**. If your issue
doesn't fit either, just write a free-form description.

For bugs, the most useful things you can include:

- Which container the bug is in (bot or web)
- What you expected vs what happened
- Reproduction steps if possible
- Logs (`docker logs herald-bot` or `docker logs herald-web`)

---

## Asking before guessing

If the spec, ARCHITECTURE.md, or PLAN.md is ambiguous about something,
**ask before assuming**. Open a discussion or comment on the relevant
issue. Silent divergence from documented decisions is the one thing
guaranteed to cause rework.

---

## License

Currently TBD. Until a license is added, all rights reserved by the
maintainer. If you contribute, you're agreeing your contribution will
be released under whatever license is chosen.
