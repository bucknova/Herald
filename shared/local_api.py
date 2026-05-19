"""
local_api.py — LocalAI integration for Herald.

https://github.com/bucknova/Herald-Bot

LocalAI is OpenAI-compatible, so this module uses the OpenAI client
pointed at a self-hosted LocalAI server. Mirrors the claude_api.py
interface so the bot can call either backend transparently.

Configuration via environment variables:
  LOCALAI_BASE_URL  — e.g. http://192.168.1.50:8080/v1
  LOCALAI_MODEL     — model name as configured in LocalAI
  LOCALAI_API_KEY   — optional, often unused for local servers

Note: PDF vision import (parse_character_pdf) requires a vision-capable
model. If your local model doesn't support vision, that command will
fail and you should fall back to Claude.
"""

import os
import json
import base64
from openai import AsyncOpenAI

# ─── Configuration ───────────────────────────────────────────────────────────

BASE_URL = os.getenv("LOCALAI_BASE_URL", "")
MODEL = os.getenv("LOCALAI_MODEL", "")
API_KEY = os.getenv("LOCALAI_API_KEY", "not-needed")

# ─── Client ──────────────────────────────────────────────────────────────────

_client: AsyncOpenAI | None = None


def is_configured() -> bool:
    """Return True if LocalAI is configured and ready to use."""
    return bool(BASE_URL and MODEL)


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        if not is_configured():
            raise RuntimeError(
                "LocalAI not configured. Set LOCALAI_BASE_URL and LOCALAI_MODEL in .env."
            )
        _client = AsyncOpenAI(base_url=BASE_URL, api_key=API_KEY)
    return _client


# ─── Prompt Templates (shared with Claude — kept simple for local models) ───

SYSTEM_PROMPT = """You are a seasoned Dungeon Master and D&D 5e content creator. You create vivid, \
flavorful, and mechanically sound content for tabletop RPG campaigns. Your tone is evocative and \
immersive. Always respond with valid JSON matching the requested schema. No markdown fences, no preamble."""

DND_ASSISTANT_PROMPT = """You are an expert D&D 5e rules advisor. Provide accurate, concise answers \
about rules, spells, items, monsters, classes, and mechanics. Cite the rulebook when possible. \
Respond in plain text. Use bold sparingly for emphasis."""


# ─── Core API Calls ─────────────────────────────────────────────────────────

async def _call_json(prompt: str, system: str = SYSTEM_PROMPT, max_tokens: int = 2000) -> dict:
    """Make a chat completion call expecting JSON output."""
    client = get_client()

    response = await client.chat.completions.create(
        model=MODEL,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
    )

    text = response.choices[0].message.content.strip()

    # Clean up potential markdown fences (local models often add them)
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    if text.startswith("json"):
        text = text[4:]
    text = text.strip()

    return json.loads(text)


async def _call_text(prompt: str, system: str, max_tokens: int = 1500) -> str:
    """Make a chat completion call expecting plain text output."""
    client = get_client()

    response = await client.chat.completions.create(
        model=MODEL,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
    )

    return response.choices[0].message.content.strip()


# ─── Item Forge ─────────────────────────────────────────────────────────────

async def forge_item(
    name: str,
    rarity: str = "common",
    item_type: str = "wondrous item",
    context: str = "",
    campaign_context: str = "",
) -> dict:
    """Generate a complete homebrew item using LocalAI."""
    context_line = f"Additional context: {context}" if context else ""
    ctx_block = f"\n\nCAMPAIGN & PARTY CONTEXT:\n{campaign_context}" if campaign_context else ""

    prompt = f"""Create a D&D 5e homebrew item.

Name: {name}
Rarity: {rarity}
Type: {item_type}
{context_line}{ctx_block}

Respond with ONLY a JSON object:
{{
  "name": "the item name",
  "description": "2-3 paragraphs of rich lore and physical description",
  "rarity": "{rarity}",
  "item_type": "{item_type}",
  "properties": {{
    "damage": "damage dice if weapon",
    "ac_bonus": "AC bonus if armor",
    "charges": "charges if applicable",
    "attunement": "yes/no and requirements",
    "effects": "mechanical effects in clear rules language",
    "quirk": "a flavor quirk or personality trait"
  }}
}}

Only include relevant properties. Omit irrelevant keys."""

    return await _call_json(prompt)


async def enhance_item(
    name: str,
    rarity: str,
    item_type: str,
    description: str,
    properties: dict,
    context: str = "",
    campaign_context: str = "",
) -> dict:
    """Enhance an existing item with richer lore."""
    context_line = f"Additional context: {context}" if context else ""
    ctx_block = f"\n\nCAMPAIGN & PARTY CONTEXT:\n{campaign_context}" if campaign_context else ""

    prompt = f"""Enhance this D&D 5e item with richer lore and properties.

Name: {name}
Rarity: {rarity}
Type: {item_type}
Current description: {description or 'None yet'}
Current properties: {json.dumps(properties) if properties else 'None yet'}
{context_line}{ctx_block}

Respond with ONLY a JSON object:
{{
  "description": "2-3 paragraphs of enhanced lore",
  "properties": {{
    "damage": "...",
    "effects": "...",
    "quirk": "...",
    "history": "brief origin story"
  }}
}}

Only include relevant keys."""

    return await _call_json(prompt)


# ─── Lore Builder ───────────────────────────────────────────────────────────

LORE_PROMPTS = {
    "location": """Create a D&D 5e location.

Name: {name}
{context_line}{ctx_block}

Respond with ONLY a JSON object:
{{
  "name": "...",
  "type": "tavern/dungeon/city/etc.",
  "description": "2-3 paragraphs",
  "notable_features": ["3-4 features"],
  "npcs": ["2-3 NPCs"],
  "hooks": ["2-3 adventure hooks"],
  "secret": "one hidden detail",
  "mood": "atmospheric summary"
}}""",

    "faction": """Create a D&D 5e faction.

Name: {name}
{context_line}{ctx_block}

Respond with ONLY a JSON object:
{{
  "name": "...",
  "type": "guild/cult/order/etc.",
  "description": "2-3 paragraphs",
  "leader": "name and description",
  "goals": ["2-3 objectives"],
  "methods": "how they operate",
  "allies": "...",
  "enemies": "...",
  "tension": "internal conflict",
  "symbol": "their emblem",
  "motto": "their creed"
}}""",

    "npc": """Create a D&D 5e NPC.

Name: {name}
{context_line}{ctx_block}

Respond with ONLY a JSON object:
{{
  "name": "...",
  "race": "...",
  "class": "class or occupation",
  "description": "2-3 paragraphs",
  "personality": ["2-3 traits"],
  "motivation": "what drives them",
  "flaw": "character flaw",
  "secret": "hidden truth",
  "voice": "speech pattern note",
  "stat_block": "CR or class/level",
  "connection_hooks": ["2-3 ways to connect to party"]
}}""",

    "history": """Create D&D world history/lore.

Topic: {name}
{context_line}{ctx_block}

Respond with ONLY a JSON object:
{{
  "title": "...",
  "era": "when this took place",
  "description": "3-4 paragraphs as if from a scholar's tome",
  "key_figures": ["2-3 historical figures"],
  "consequences": "present-day impact",
  "evidence": "physical traces remaining",
  "mystery": "unresolved question",
  "dm_notes": "campaign usage suggestions"
}}""",
}


async def generate_lore(lore_type: str, name: str, context: str = "", campaign_context: str = "") -> dict:
    """Generate world lore (location, faction, NPC, or history)."""
    if lore_type not in LORE_PROMPTS:
        raise ValueError(f"Unknown lore type: {lore_type}")

    context_line = f"Additional context: {context}" if context else ""
    ctx_block = f"\n\nCAMPAIGN & PARTY CONTEXT:\n{campaign_context}" if campaign_context else ""

    prompt = LORE_PROMPTS[lore_type].format(
        name=name, context_line=context_line, ctx_block=ctx_block
    )
    return await _call_json(prompt)


# ─── Rules Advisor ──────────────────────────────────────────────────────────

async def ask_dnd(question: str, campaign_context: str = "") -> str:
    """Answer a D&D 5e rules/knowledge question."""
    prompt = question
    if campaign_context:
        prompt = f"CAMPAIGN & PARTY CONTEXT:\n{campaign_context}\n\nQUESTION:\n{question}"
    return await _call_text(prompt, system=DND_ASSISTANT_PROMPT)


# ─── Character Sheet Vision Import ──────────────────────────────────────────

async def parse_character_pdf(page_images: list[str]) -> dict:
    """Parse character sheet via vision. Requires a vision-capable local model."""
    client = get_client()

    content = []
    for b64_image in page_images:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{b64_image}"},
        })
    content.append({
        "type": "text",
        "text": """Read every page of this D&D 5e character sheet and extract ALL information into JSON.

Respond with ONLY a JSON object:
{
  "character_name": "...",
  "race": "...",
  "char_class": "class and level with subclass",
  "level": 0,
  "background": "...",
  "backstory": "personality, ideals, bonds, flaws, physical description, and backstory combined",
  "abilities": "All class features, racial traits, feats, spellcasting info, and full spell list",
  "details": "AC, HP, Speed, Initiative, ability scores, saves, skills, equipment, currency"
}

Be thorough. Include every spell, item, and feature. No markdown fences."""
    })

    response = await client.chat.completions.create(
        model=MODEL,
        max_tokens=4000,
        messages=[{"role": "user", "content": content}],
    )

    text = response.choices[0].message.content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    if text.startswith("json"):
        text = text[4:]
    text = text.strip()

    return json.loads(text)
