# Security Policy

Herald is a self-hosted hobby project. There is no commercial support
behind it, but security issues are still taken seriously.

---

## Reporting a vulnerability

**Do not** open a public GitHub issue for a security vulnerability.

Instead, email the maintainer directly via the address on
[github.com/bucknova](https://github.com/bucknova) or use GitHub's
**private vulnerability reporting** if it's enabled on this repo.

Include:

- A clear description of the issue
- Steps to reproduce
- The impact (what an attacker could do)
- Any suggested remediation

You should receive an acknowledgement within a week. Real-world fix
timelines depend on the severity and the maintainer's availability.

---

## Scope

Things in scope:

- **Authentication bypass** — anything that lets a user impersonate
  another Discord identity or escalate from player → DM
- **SQL injection** or other input-handling bugs
- **Stored XSS / template injection** via user-controlled content
  (wiki pages, character sheets, item descriptions)
- **Session hijacking** — cookie signing weaknesses, CSRF
- **Credential leakage** — Discord tokens, OAuth secrets, webhook URLs
  exposed to the client or logs

Things **out of scope** for this project (but still welcome as
discussions):

- Denial of service against your own self-hosted instance
- Discord API rate limiting
- Anything that requires already-compromised host access

---

## Self-hosting safety checklist

If you're running Herald yourself:

1. **Never commit `.env` files.** Both `herald-bot/.env` and
   `herald-web/.env` contain secrets (Discord tokens, OAuth secrets,
   API keys). The `.gitignore` covers them by default.
2. **Use HTTPS** if the portal is reachable from the internet. Don't
   send Discord OAuth tokens over plaintext HTTP across the public web.
3. **Rotate `SESSION_SECRET`** if you ever suspect it leaked. This
   invalidates all existing web sessions but is otherwise harmless.
4. **Back up `data/scheduler.db`** regularly.
5. **Keep base images current.** Rebuild containers when you update
   Python or system packages.

---

## Known non-issues

- The Discord bot rate limiter is in-memory and per-process. The web
  portal has its own pool. A determined user could in theory get up to
  2× the rate limit by using both surfaces. See ARCHITECTURE.md §7 for
  the trade-off rationale.
- Discord avatar URLs cached at login can go stale if the user changes
  their avatar between logins. Re-login refreshes them.
