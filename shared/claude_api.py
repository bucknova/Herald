"""
claude_api.py — Claude API integration for AI-powered D&D content generation.

Features:
  - Item Forge: Generate homebrew items with descriptions, lore, and properties
  - Lore Builder: Generate locations, factions, NPCs, and historical lore
  - Rate limiting: Per-user cooldowns (configurable DM vs player limits)
"""

import os
import json
import time
import anthropic
from typing import Optional
from dataclasses import dataclass, field

# ─── Configuration ───────────────────────────────────────────────────────────

API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")

# Rate limits (requests per hour)
DM_RATE_LIMIT = int(os.getenv("DM_RATE_LIMIT", "60"))
PLAYER_RATE_LIMIT = int(os.getenv("PLAYER_RATE_LIMIT", "10"))

# ─── Rate Limiter ────────────────────────────────────────────────────────────


class RateLimiter:
    """Simple sliding-window rate limiter per user."""

    def __init__(self):
        self._requests: dict[int, list[float]] = {}

    def check(self, user_id: int, limit: int) -> tuple[bool, int]:
        """
        Check if a user can make a request.
        Returns (allowed, seconds_until_next_slot).
        """
        now = time.time()
        window = 3600  # 1 hour

        if user_id not in self._requests:
            self._requests[user_id] = []

        # Prune old entries
        self._requests[user_id] = [
            t for t in self._requests[user_id] if now - t < window
        ]

        if len(self._requests[user_id]) >= limit:
            oldest = self._requests[user_id][0]
            wait = int(oldest + window - now) + 1
            return False, wait

        return True, 0

    def record(self, user_id: int):
        """Record a request for rate limiting."""
        if user_id not in self._requests:
            self._requests[user_id] = []
        self._requests[user_id].append(time.time())

    def remaining(self, user_id: int, limit: int) -> int:
        """How many requests remain in the current window."""
        now = time.time()
        if user_id not in self._requests:
            return limit
        recent = [t for t in self._requests[user_id] if now - t < 3600]
        return max(0, limit - len(recent))


rate_limiter = RateLimiter()

# ─── Client ──────────────────────────────────────────────────────────────────

_client: Optional[anthropic.AsyncAnthropic] = None


def get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        if not API_KEY:
            raise RuntimeError(
                "ANTHROPIC_API_KEY not set. Add it to your .env file."
            )
        _client = anthropic.AsyncAnthropic(api_key=API_KEY)
    return _client


# ─── Prompt Templates ────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a seasoned Dungeon Master and D&D 5e content creator. You create vivid, \
flavorful, and mechanically sound content for tabletop RPG campaigns. Your tone is evocative and \
immersive — like reading from a well-crafted sourcebook.

When generating items, locations, factions, NPCs, or lore, follow these rules:
- Be specific and concrete, not generic
- Include sensory details (sight, sound, smell, texture)
- Make content feel like it belongs in a living world with history
- For items: include mechanical properties when appropriate (damage dice, AC, save DCs, charges)
- For locations: include hooks, secrets, and atmosphere
- For factions: include goals, methods, and internal tensions
- For NPCs: include personality quirks, motivations, and a secret
- Keep it concise but rich — aim for quality over quantity
- When campaign setting and character sheet context is provided, tailor your output to fit \
that world and those characters. Reference character abilities, backstories, and relationships \
when it makes the content more engaging. Make items that are tempting or useful for the specific \
party composition. Make NPCs that could interact meaningfully with the existing characters.

Always respond with valid JSON matching the requested schema. No markdown fences, no preamble."""

ITEM_PROMPT = """Create a D&D 5e homebrew item with the following parameters:

Name: {name}
Rarity: {rarity}
Type: {item_type}
{context_line}
{campaign_context}

Respond with ONLY a JSON object in this exact format:
{{
  "name": "the item name",
  "description": "2-3 paragraphs of rich lore and physical description",
  "rarity": "{rarity}",
  "item_type": "{item_type}",
  "properties": {{
    "damage": "damage dice if weapon (e.g., '2d6 radiant')",
    "ac_bonus": "AC bonus if armor/shield",
    "charges": "number of charges if applicable",
    "recharge": "recharge condition if applicable",
    "attunement": "yes/no and any requirements",
    "effects": "mechanical effects in clear rules language",
    "quirk": "a minor flavor quirk or personality trait of the item"
  }}
}}

Only include properties that are relevant to this item type. Omit irrelevant property keys entirely."""

ITEM_ENHANCE_PROMPT = """Enhance this existing D&D 5e homebrew item with richer lore, better description, \
and more detailed properties.

Current item:
Name: {name}
Rarity: {rarity}
Type: {item_type}
Current description: {description}
Current properties: {properties}
{context_line}
{campaign_context}

Respond with ONLY a JSON object in this exact format:
{{
  "description": "2-3 paragraphs of enhanced lore and physical description, building on the original",
  "properties": {{
    "damage": "damage dice if weapon",
    "ac_bonus": "AC bonus if armor/shield",
    "charges": "number of charges if applicable",
    "recharge": "recharge condition if applicable",
    "attunement": "yes/no and any requirements",
    "effects": "mechanical effects in clear rules language",
    "quirk": "a minor flavor quirk",
    "history": "a brief origin story for the item"
  }}
}}

Only include properties that are relevant. Omit irrelevant keys."""

LORE_PROMPTS = {
    "location": """Create a D&D 5e location with the following parameters:

Name: {name}
{context_line}
{campaign_context}

Respond with ONLY a JSON object:
{{
  "name": "location name",
  "type": "tavern/dungeon/city/wilderness/temple/etc.",
  "description": "2-3 paragraphs of vivid description with atmosphere and sensory details",
  "notable_features": ["3-4 interesting features or landmarks within"],
  "npcs": ["2-3 NPCs who can be found here with one-line descriptions"],
  "hooks": ["2-3 adventure hooks connected to this location"],
  "secret": "one hidden detail that players might discover",
  "mood": "one-line atmospheric summary for the DM"
}}""",

    "faction": """Create a D&D 5e faction/organization with the following parameters:

Name: {name}
{context_line}
{campaign_context}

Respond with ONLY a JSON object:
{{
  "name": "faction name",
  "type": "guild/cult/order/government/criminal/military/etc.",
  "description": "2-3 paragraphs covering their history, purpose, and methods",
  "leader": "name and brief description of the leader",
  "goals": ["2-3 current objectives"],
  "methods": "how they typically operate",
  "allies": "who they work with",
  "enemies": "who opposes them",
  "tension": "an internal conflict or schism within the faction",
  "symbol": "description of their emblem or identifying mark",
  "motto": "their motto or creed"
}}""",

    "npc": """Create a D&D 5e NPC with the following parameters:

Name: {name}
{context_line}
{campaign_context}

Respond with ONLY a JSON object:
{{
  "name": "NPC name",
  "race": "race",
  "class": "class or occupation",
  "description": "2-3 paragraphs covering appearance, personality, and background",
  "personality": ["2-3 defining personality traits"],
  "motivation": "what drives them",
  "flaw": "a significant character flaw",
  "secret": "something they're hiding",
  "voice": "a brief note on how to roleplay their speech pattern",
  "stat_block": "suggested CR range or class/level",
  "connection_hooks": ["2-3 ways to connect this NPC to the party"]
}}""",

    "history": """Create a piece of D&D world lore/history with the following parameters:

Topic: {name}
{context_line}
{campaign_context}

Respond with ONLY a JSON object:
{{
  "title": "lore title",
  "era": "when this took place or is relevant",
  "description": "3-4 paragraphs of rich historical lore written as if from a scholar's tome",
  "key_figures": ["2-3 historical figures involved with one-line descriptions"],
  "consequences": "how this history affects the present day",
  "evidence": "what physical traces or records remain",
  "mystery": "an unresolved question or lost detail about this history",
  "dm_notes": "suggestions for how to use this lore in a campaign"
}}""",
}


# ─── API Calls ───────────────────────────────────────────────────────────────

async def _call_claude(prompt: str, max_tokens: int = 2000) -> dict:
    """Make an API call to Claude and parse the JSON response."""
    client = get_client()

    message = await client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    text = message.content[0].text.strip()

    # Clean up potential markdown fences
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    if text.startswith("json"):
        text = text[4:]
    text = text.strip()

    return json.loads(text)


async def forge_item(
    name: str,
    rarity: str = "common",
    item_type: str = "wondrous item",
    context: str = "",
    campaign_context: str = "",
) -> dict:
    """Generate a complete homebrew item using Claude."""
    context_line = f"Additional context: {context}" if context else ""
    ctx_block = f"\n--- CAMPAIGN & PARTY CONTEXT ---\n{campaign_context}" if campaign_context else ""
    prompt = ITEM_PROMPT.format(
        name=name, rarity=rarity, item_type=item_type,
        context_line=context_line, campaign_context=ctx_block,
    )
    return await _call_claude(prompt)


async def enhance_item(
    name: str,
    rarity: str,
    item_type: str,
    description: str,
    properties: dict,
    context: str = "",
    campaign_context: str = "",
) -> dict:
    """Enhance an existing item with richer lore and properties."""
    context_line = f"Additional context: {context}" if context else ""
    ctx_block = f"\n--- CAMPAIGN & PARTY CONTEXT ---\n{campaign_context}" if campaign_context else ""
    prompt = ITEM_ENHANCE_PROMPT.format(
        name=name,
        rarity=rarity,
        item_type=item_type,
        description=description or "None yet",
        properties=json.dumps(properties) if properties else "None yet",
        context_line=context_line,
        campaign_context=ctx_block,
    )
    return await _call_claude(prompt)


async def generate_lore(
    lore_type: str,
    name: str,
    context: str = "",
    campaign_context: str = "",
) -> dict:
    """Generate a piece of world lore (location, faction, NPC, or history)."""
    if lore_type not in LORE_PROMPTS:
        raise ValueError(f"Unknown lore type: {lore_type}")

    context_line = f"Additional context/setting: {context}" if context else ""
    ctx_block = f"\n--- CAMPAIGN & PARTY CONTEXT ---\n{campaign_context}" if campaign_context else ""
    prompt = LORE_PROMPTS[lore_type].format(
        name=name, context_line=context_line, campaign_context=ctx_block,
    )
    return await _call_claude(prompt)


# ─── D&D Knowledge Assistant ────────────────────────────────────────────────

DND_ASSISTANT_PROMPT = """You are an expert D&D 5e rules advisor and lore encyclopedia. You provide \
accurate, concise answers about rules, spells, items, monsters, classes, races, mechanics, and \
official lore from the D&D 5th Edition core rulebooks (PHB, DMG, MM) and common supplements.

Guidelines:
- Cite the relevant rulebook and page/section when possible (e.g., "PHB p.205")
- Be concise — aim for clear, direct answers, not essays
- If a rule is ambiguous or commonly debated, note the RAW (Rules As Written) interpretation \
and the common RAI (Rules As Intended) interpretation
- If asked about homebrew or house rules, clarify that the official rule differs
- For spells and abilities, include the key mechanical details (range, duration, components, etc.)
- When campaign context is provided, tailor your answer to the party's specific situation
- If you're not certain about something, say so rather than guessing

Always respond in plain text. Use bold (**text**) sparingly for emphasis on key terms."""


async def _call_claude_text(prompt: str, system: str = SYSTEM_PROMPT, max_tokens: int = 1500) -> str:
    """Make an API call to Claude and return the raw text response."""
    client = get_client()

    message = await client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )

    return message.content[0].text.strip()


async def ask_dnd(
    question: str,
    campaign_context: str = "",
) -> str:
    """Ask a D&D 5e rules/knowledge question."""
    prompt = question
    if campaign_context:
        prompt = (
            f"--- CAMPAIGN & PARTY CONTEXT ---\n{campaign_context}\n\n"
            f"--- QUESTION ---\n{question}"
        )
    return await _call_claude_text(prompt, system=DND_ASSISTANT_PROMPT)


# ─── Character Sheet PDF Import ─────────────────────────────────────────────

SHEET_VISION_PROMPT = """You are reading images of a D&D 5e character sheet exported from D&D Beyond. \
Read every page carefully and extract ALL character information into a structured JSON object.

Respond with ONLY a JSON object in this exact format:
{
  "character_name": "character name",
  "race": "species/race",
  "char_class": "class and level with subclass (e.g., 'Wizard 8 (Illusionist)')",
  "level": 8,
  "background": "background name",
  "backstory": "personality traits, ideals, bonds, flaws, physical description (gender, age, height, weight, skin, eyes, hair, alignment), and any written backstory — combined into a narrative paragraph",
  "abilities": "All class features, racial traits, feats with full descriptions, spellcasting info (ability, DC, attack bonus), and full spell list organized by level with slot counts. Include cantrips. Be thorough — include everything from features & traits pages.",
  "details": "AC, HP, Speed, Initiative, all six ability scores with modifiers, saving throw proficiencies with bonuses, skill proficiencies with bonuses (note expertise), tool proficiencies, languages, all equipment and magic items with quantities, potions, scrolls, weapons with hit/damage, and gold/currency amounts"
}

Be thorough. Include EVERY spell, EVERY item, EVERY feature, EVERY trait. Read ALL pages. Do not summarize or abbreviate. No markdown fences, no preamble."""


async def parse_character_pdf(page_images: list[str]) -> dict:
    """Parse character sheet by sending rendered page images to Claude's vision API."""
    client = get_client()

    # Build the message content with all page images
    content = []
    for i, b64_image in enumerate(page_images):
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": b64_image,
            },
        })
    content.append({
        "type": "text",
        "text": SHEET_VISION_PROMPT,
    })

    message = await client.messages.create(
        model=MODEL,
        max_tokens=4000,
        messages=[{"role": "user", "content": content}],
    )

    text = message.content[0].text.strip()

    # Clean up potential markdown fences
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    if text.startswith("json"):
        text = text[4:]
    text = text.strip()

    return json.loads(text)
