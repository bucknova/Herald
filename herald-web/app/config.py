"""
config.py — Environment-driven configuration for Herald Web.

Phase 0 scaffold: just defines the names that will be loaded from the
environment. Real loading + validation lands in Phase 1.2.

Match the bot's style: module-level constants pulled from os.environ via
os.getenv with sensible defaults where defaults make sense, and no
default where the value is a required secret.
"""

import os

# ─── Network ────────────────────────────────────────────────
HERALD_WEB_HOST: str = os.getenv("HERALD_WEB_HOST", "0.0.0.0")
HERALD_WEB_PORT: int = int(os.getenv("HERALD_WEB_PORT", "8088"))
HERALD_WEB_BASE_URL: str = os.getenv("HERALD_WEB_BASE_URL", "http://localhost:8088")

# ─── Database ───────────────────────────────────────────────
DB_PATH: str = os.getenv("DB_PATH", "data/scheduler.db")

# ─── Session signing ────────────────────────────────────────
SESSION_SECRET: str = os.getenv("SESSION_SECRET", "")

# ─── Discord OAuth ──────────────────────────────────────────
DISCORD_CLIENT_ID: str = os.getenv("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET: str = os.getenv("DISCORD_CLIENT_SECRET", "")
DISCORD_REDIRECT_URI: str = os.getenv(
    "DISCORD_REDIRECT_URI",
    f"{HERALD_WEB_BASE_URL.rstrip('/')}/auth/callback",
)

# ─── AI (names match the bot's env vars) ────────────────────
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL: str = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")
LOCALAI_BASE_URL: str = os.getenv("LOCALAI_BASE_URL", "")
LOCALAI_MODEL: str = os.getenv("LOCALAI_MODEL", "")
LOCALAI_API_KEY: str = os.getenv("LOCALAI_API_KEY", "not-needed")

# ─── Optional guild lockdown ────────────────────────────────
ALLOWED_GUILD_ID: str = os.getenv("ALLOWED_GUILD_ID", "")
