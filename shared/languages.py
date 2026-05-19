"""
languages.py — D&D language translation using unique cipher systems.

Each language has a distinct character mapping and optional transformation rules
to give it a unique visual flavor. These are meant to be fun and thematic, not
cryptographically secure — players can use /translate to encode messages in-game
for flavor.

Supported languages:
  Common, Dwarvish, Elvish, Giant, Gnomish, Goblin, Halfling, Orc,
  Abyssal, Celestial, Draconic, Deep Speech, Infernal, Primordial,
  Sylvan, Undercommon, Druidic, Thieves' Cant
"""

# Each language maps lowercase a-z to a shuffled alphabet.
# Uppercase is handled by case-matching the output.
# Non-alpha characters pass through unchanged.

LANGUAGE_CIPHERS: dict[str, str] = {
    # ── Standard Languages ───────────────────────────────────
    "common":       "abcdefghijklmnopqrstuvwxyz",   # Identity — Common IS English
    "dwarvish":     "qvwrtzuiopasdfghjklyxcbenm",   # Germanic / runic feel
    "elvish":       "leynasiuwkgmdofpqrthvbxczj",   # Flowing, vowel-heavy output
    "giant":        "zuritobvswaxedcmfyghjklnpq",   # Harsh, heavy consonants
    "gnomish":      "nopqrstuvwxyzabcdefghijklm",   # ROT-13 — the tinker's cipher
    "goblin":       "gkrzdnoubthwijxycpqefvlsam",   # Guttural, sharp
    "halfling":     "bmaclndoepfqgrhsitjukvwxyz",   # Gentle interleave
    "orc":          "xrkdoezbguhsiwntjcpqfvlyam",   # Brutal, heavy

    # ── Exotic Languages ────────────────────────────────────
    "abyssal":      "zyxwvutsrqponmlkjihgfedcba",   # Reversed — everything inverted
    "celestial":    "aelioubcdsfghjkmnpqrtvwxyz",    # Vowels promoted forward
    "draconic":     "draconisbtufghejklmpqvwxyz",    # "DRACONIS" leads the cipher
    "deep speech":  "thfwgxhyizjakblcmdneofpqrs",    # Alien, disorienting shifts
    "infernal":     "inferalsbcdghjkmopqtuvwxyz",    # "INFERAL" leads the cipher
    "primordial":   "primodalbcefghjknqstuvwxyz",    # "PRIMODAL" leads the cipher
    "sylvan":       "sylvanbcdefghijkmoprqtuwxz",    # "SYLVAN" leads, soft
    "undercommon":  "uxdercombfghijklnpqstvwayz",    # "UXDERCOM" leads, dark
    "druidic":      "druicabefghjklmnopqstvwxyz",    # "DRUIC" leads, natural
    "thieves' cant":"thievscanbdfgjklmopqruwxyz",    # "THIEVSCAN" leads, street
}

# Decorative markers that wrap translated text for flavor
LANGUAGE_DECORATORS: dict[str, tuple[str, str]] = {
    "common":       ("", ""),
    "dwarvish":     ("᚛ ", " ᚜"),
    "elvish":       ("⊹ ", " ⊹"),
    "giant":        ("ᚦ ", " ᚦ"),
    "gnomish":      ("⚙ ", " ⚙"),
    "goblin":       ("☠ ", " ☠"),
    "halfling":     ("🌿 ", " 🌿"),
    "orc":          ("⚔ ", " ⚔"),
    "abyssal":      ("🜏 ", " 🜏"),
    "celestial":    ("✦ ", " ✦"),
    "draconic":     ("🐉 ", " 🐉"),
    "deep speech":  ("◯̸ ", " ◯̸"),
    "infernal":     ("🔥 ", " 🔥"),
    "primordial":   ("🌊 ", " 🌊"),
    "sylvan":       ("🌸 ", " 🌸"),
    "undercommon":  ("🕷 ", " 🕷"),
    "druidic":      ("🌳 ", " 🌳"),
    "thieves' cant":("🗡 ", " 🗡"),
}

COMMON_ALPHA = "abcdefghijklmnopqrstuvwxyz"


def get_languages() -> list[str]:
    """Return all available language names."""
    return list(LANGUAGE_CIPHERS.keys())


def translate(text: str, from_lang: str, to_lang: str) -> str:
    """
    Translate text between D&D languages.

    The approach: decode from source language back to a neutral form,
    then encode into the target language.
    """
    from_lang = from_lang.lower().strip()
    to_lang = to_lang.lower().strip()

    if from_lang not in LANGUAGE_CIPHERS:
        return f"Unknown language: {from_lang}"
    if to_lang not in LANGUAGE_CIPHERS:
        return f"Unknown language: {to_lang}"

    from_cipher = LANGUAGE_CIPHERS[from_lang]
    to_cipher = LANGUAGE_CIPHERS[to_lang]

    result = []
    for ch in text:
        if ch.lower() in from_cipher:
            idx = from_cipher.index(ch.lower())
            new_ch = to_cipher[idx]
            result.append(new_ch.upper() if ch.isupper() else new_ch)
        else:
            result.append(ch)

    prefix, suffix = LANGUAGE_DECORATORS.get(to_lang, ("", ""))
    return f"{prefix}{''.join(result)}{suffix}"


def translate_to(text: str, to_lang: str) -> str:
    """Shorthand: translate from Common to another language."""
    return translate(text, "common", to_lang)


def translate_from(text: str, from_lang: str) -> str:
    """Shorthand: translate from another language back to Common."""
    return translate(text, from_lang, "common")
