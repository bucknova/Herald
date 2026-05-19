"""
ai_backend.py — Routes AI calls to Claude or LocalAI.

https://github.com/bucknova/Herald-Bot

Backend selection priority:
  1. Explicit override on the command (e.g., backend="local")
  2. Campaign default (set via /campaign backend)
  3. System default (claude if API key set, else local if configured)

If the chosen backend isn't available, falls back to whatever IS available
and logs a warning. If neither is available, raises an error.
"""

import claude_api
import local_api
import database as db


def resolve_backend(campaign_id: int = None, override: str = None) -> str:
    """
    Determine which backend to use.
    Returns 'claude', 'local', or raises if neither available.
    """
    # 1. Explicit per-command override
    if override:
        choice = override.lower()
        if choice == "claude" and claude_api.API_KEY:
            return "claude"
        if choice == "local" and local_api.is_configured():
            return "local"
        # Override requested but not available — fall through to defaults

    # 2. Campaign default
    if campaign_id:
        campaign = db.get_campaign(campaign_id)
        if campaign:
            preferred = campaign.get("ai_backend") or ""
            if preferred == "claude" and claude_api.API_KEY:
                return "claude"
            if preferred == "local" and local_api.is_configured():
                return "local"

    # 3. System default — Claude first if configured, else LocalAI
    if claude_api.API_KEY:
        return "claude"
    if local_api.is_configured():
        return "local"

    raise RuntimeError(
        "No AI backend available. Set ANTHROPIC_API_KEY or LOCALAI_BASE_URL+LOCALAI_MODEL."
    )


def get_backend_module(backend: str):
    """Return the module for a given backend name."""
    if backend == "local":
        return local_api
    return claude_api


def backend_label(backend: str) -> str:
    """Human-readable label for a backend."""
    if backend == "local":
        model = local_api.MODEL or "local"
        return f"🖥️ LocalAI ({model})"
    return "☁️ Claude"


# ─── Unified entry points ────────────────────────────────────────────────────
# Each function dispatches to the appropriate backend's implementation.

async def forge_item(name, rarity="common", item_type="wondrous item",
                     context="", campaign_context="", backend="claude"):
    mod = get_backend_module(backend)
    return await mod.forge_item(name, rarity, item_type, context, campaign_context)


async def enhance_item(name, rarity, item_type, description, properties,
                       context="", campaign_context="", backend="claude"):
    mod = get_backend_module(backend)
    return await mod.enhance_item(name, rarity, item_type, description, properties,
                                   context, campaign_context)


async def generate_lore(lore_type, name, context="", campaign_context="", backend="claude"):
    mod = get_backend_module(backend)
    return await mod.generate_lore(lore_type, name, context, campaign_context)


async def ask_dnd(question, campaign_context="", backend="claude"):
    mod = get_backend_module(backend)
    return await mod.ask_dnd(question, campaign_context)


async def parse_character_pdf(page_images, backend="claude"):
    mod = get_backend_module(backend)
    return await mod.parse_character_pdf(page_images)
