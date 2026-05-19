"""
database.py — SQLite persistence layer for Herald.

Tables:
  campaigns        – one row per campaign (name, guild, channel, DM, schedule)
  players          – members of each campaign
  sessions         – individual game sessions (date/time)
  rsvps            – per-player attendance responses for each session
  attendance_log   – historical record of actual attendance
  items            – homebrew item definitions
  player_inventory – who has what items
"""

import sqlite3
import os
import json
from datetime import datetime, timezone
from typing import Optional

DB_PATH = os.getenv("DB_PATH", "data/scheduler.db")


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create tables if they don't exist."""
    conn = _connect()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS campaigns (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id                INTEGER NOT NULL,
            channel_id              INTEGER NOT NULL,
            name                    TEXT NOT NULL,
            dm_user_id              INTEGER NOT NULL,
            -- Recurring schedule
            schedule_day            TEXT DEFAULT NULL,
            schedule_time           TEXT DEFAULT NULL,
            schedule_tz             TEXT DEFAULT 'America/Denver',
            -- Ping configuration
            ping_days_before        INTEGER DEFAULT 3,
            midweek_enabled         INTEGER DEFAULT 1,
            followup_count          INTEGER DEFAULT 1,
            followup_interval_hours INTEGER DEFAULT 24,
            reminder_hours          INTEGER DEFAULT 4,
            -- Auto-scheduling
            auto_schedule           INTEGER DEFAULT 0,
            repeat_frequency        TEXT DEFAULT 'weekly',
            sessions_ahead          INTEGER DEFAULT 1,
            schedule_start          TEXT DEFAULT NULL,
            -- AI backend preference (claude, local, or NULL for system default)
            ai_backend              TEXT DEFAULT NULL,
            -- Campaign world context for AI features
            setting                 TEXT DEFAULT NULL,
            created_at              TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS players (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id     INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
            user_id         INTEGER NOT NULL,
            character_name  TEXT DEFAULT NULL,
            -- Character sheet fields
            race            TEXT DEFAULT NULL,
            char_class      TEXT DEFAULT NULL,
            level           INTEGER DEFAULT NULL,
            background      TEXT DEFAULT NULL,
            backstory       TEXT DEFAULT NULL,
            abilities       TEXT DEFAULT NULL,
            details         TEXT DEFAULT NULL,
            --
            active          INTEGER DEFAULT 1,
            added_at        TEXT DEFAULT (datetime('now')),
            UNIQUE(campaign_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS sessions (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id         INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
            session_date        TEXT NOT NULL,
            title               TEXT DEFAULT NULL,
            notes               TEXT DEFAULT NULL,
            status              TEXT DEFAULT 'scheduled',
            -- Ping tracking
            ping_sent           INTEGER DEFAULT 0,
            midweek_sent        INTEGER DEFAULT 0,
            reminders_sent      INTEGER DEFAULT 0,
            last_reminder_at    TEXT DEFAULT NULL,
            final_reminder_sent INTEGER DEFAULT 0,
            created_at          TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS rsvps (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id      INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            user_id         INTEGER NOT NULL,
            response        TEXT DEFAULT 'pending',
            responded_at    TEXT DEFAULT NULL,
            UNIQUE(session_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS attendance_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id      INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            user_id         INTEGER NOT NULL,
            attended        INTEGER DEFAULT 0,
            logged_at       TEXT DEFAULT (datetime('now')),
            UNIQUE(session_id, user_id)
        );

        -- ─── Homebrew Inventory ─────────────────────────────────────────

        CREATE TABLE IF NOT EXISTS items (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id     INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
            name            TEXT NOT NULL,
            description     TEXT DEFAULT '',
            rarity          TEXT DEFAULT 'common',
            item_type       TEXT DEFAULT 'wondrous item',
            properties      TEXT DEFAULT '{}',
            created_by      INTEGER NOT NULL,
            created_at      TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS player_inventory (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id     INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
            user_id         INTEGER NOT NULL,
            item_id         INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
            quantity        INTEGER DEFAULT 1,
            equipped        INTEGER DEFAULT 0,
            notes           TEXT DEFAULT NULL,
            acquired_at     TEXT DEFAULT (datetime('now')),
            UNIQUE(campaign_id, user_id, item_id)
        );
    """)

    # ── Migrations for existing databases ──
    # Add columns if upgrading from an older schema
    _migrate(conn, "campaigns", "setting", "TEXT DEFAULT NULL")
    _migrate(conn, "campaigns", "repeat_frequency", "TEXT DEFAULT 'weekly'")
    _migrate(conn, "campaigns", "sessions_ahead", "INTEGER DEFAULT 1")
    _migrate(conn, "campaigns", "schedule_start", "TEXT DEFAULT NULL")
    _migrate(conn, "campaigns", "ai_backend", "TEXT DEFAULT NULL")
    _migrate(conn, "players", "race", "TEXT DEFAULT NULL")
    _migrate(conn, "players", "char_class", "TEXT DEFAULT NULL")
    _migrate(conn, "players", "level", "INTEGER DEFAULT NULL")
    _migrate(conn, "players", "background", "TEXT DEFAULT NULL")
    _migrate(conn, "players", "backstory", "TEXT DEFAULT NULL")
    _migrate(conn, "players", "abilities", "TEXT DEFAULT NULL")
    _migrate(conn, "players", "details", "TEXT DEFAULT NULL")

    conn.commit()
    conn.close()


def _migrate(conn: sqlite3.Connection, table: str, column: str, col_type: str):
    """Add a column if it doesn't exist (safe for repeated runs)."""
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
    except sqlite3.OperationalError:
        pass  # Column already exists


# ─── Campaign CRUD ───────────────────────────────────────────────────────────

def create_campaign(guild_id: int, channel_id: int, name: str, dm_user_id: int) -> int:
    conn = _connect()
    cur = conn.execute(
        "INSERT INTO campaigns (guild_id, channel_id, name, dm_user_id) VALUES (?, ?, ?, ?)",
        (guild_id, channel_id, name, dm_user_id),
    )
    conn.commit()
    campaign_id = cur.lastrowid
    conn.close()
    return campaign_id


def get_campaign(campaign_id: int) -> Optional[dict]:
    conn = _connect()
    row = conn.execute("SELECT * FROM campaigns WHERE id = ?", (campaign_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_campaigns_for_guild(guild_id: int) -> list[dict]:
    conn = _connect()
    rows = conn.execute(
        "SELECT * FROM campaigns WHERE guild_id = ? ORDER BY name", (guild_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_campaigns_for_user(user_id: int) -> list[dict]:
    """Find all campaigns where this user is the DM or an active player."""
    conn = _connect()
    rows = conn.execute(
        """SELECT DISTINCT c.* FROM campaigns c
           LEFT JOIN players p ON c.id = p.campaign_id AND p.active = 1
           WHERE c.dm_user_id = ? OR p.user_id = ?
           ORDER BY c.name""",
        (user_id, user_id),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_campaign_schedule(
    campaign_id: int,
    day: str,
    time: str,
    tz: str = "America/Denver",
    ping_days: int = 3,
    midweek_enabled: bool = True,
    followup_count: int = 1,
    followup_interval_hours: int = 24,
    reminder_hours: int = 4,
    auto: bool = True,
    repeat_frequency: str = "weekly",
    sessions_ahead: int = 1,
    schedule_start: str = None,
):
    conn = _connect()
    conn.execute(
        """UPDATE campaigns
           SET schedule_day=?, schedule_time=?, schedule_tz=?,
               ping_days_before=?, midweek_enabled=?,
               followup_count=?, followup_interval_hours=?,
               reminder_hours=?, auto_schedule=?,
               repeat_frequency=?, sessions_ahead=?, schedule_start=?
           WHERE id=?""",
        (day, time, tz, ping_days, int(midweek_enabled),
         followup_count, followup_interval_hours,
         reminder_hours, int(auto),
         repeat_frequency, sessions_ahead, schedule_start, campaign_id),
    )
    conn.commit()
    conn.close()


def delete_campaign(campaign_id: int):
    conn = _connect()
    conn.execute("DELETE FROM campaigns WHERE id = ?", (campaign_id,))
    conn.commit()
    conn.close()


def update_campaign_setting(campaign_id: int, setting: str):
    conn = _connect()
    conn.execute("UPDATE campaigns SET setting = ? WHERE id = ?", (setting, campaign_id))
    conn.commit()
    conn.close()


def update_campaign_backend(campaign_id: int, backend: str | None):
    """Set the default AI backend for a campaign. None clears it."""
    conn = _connect()
    conn.execute("UPDATE campaigns SET ai_backend = ? WHERE id = ?", (backend, campaign_id))
    conn.commit()
    conn.close()


# ─── Player CRUD ─────────────────────────────────────────────────────────────

def add_player(campaign_id: int, user_id: int, character_name: Optional[str] = None) -> int:
    conn = _connect()
    cur = conn.execute(
        "INSERT OR IGNORE INTO players (campaign_id, user_id, character_name) VALUES (?, ?, ?)",
        (campaign_id, user_id, character_name),
    )
    conn.commit()
    pid = cur.lastrowid
    conn.close()
    return pid


def remove_player(campaign_id: int, user_id: int):
    conn = _connect()
    conn.execute(
        "UPDATE players SET active = 0 WHERE campaign_id = ? AND user_id = ?",
        (campaign_id, user_id),
    )
    conn.commit()
    conn.close()


def get_players(campaign_id: int, active_only: bool = True) -> list[dict]:
    conn = _connect()
    query = "SELECT * FROM players WHERE campaign_id = ?"
    if active_only:
        query += " AND active = 1"
    rows = conn.execute(query, (campaign_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_character_name(campaign_id: int, user_id: int, name: str):
    conn = _connect()
    conn.execute(
        "UPDATE players SET character_name = ? WHERE campaign_id = ? AND user_id = ?",
        (name, campaign_id, user_id),
    )
    conn.commit()
    conn.close()


def update_character_sheet(
    campaign_id: int,
    user_id: int,
    character_name: Optional[str] = None,
    race: Optional[str] = None,
    char_class: Optional[str] = None,
    level: Optional[int] = None,
    background: Optional[str] = None,
    backstory: Optional[str] = None,
    abilities: Optional[str] = None,
    details: Optional[str] = None,
):
    """Update character sheet fields. Only non-None values are changed."""
    conn = _connect()
    updates = {}
    if character_name is not None:
        updates["character_name"] = character_name
    if race is not None:
        updates["race"] = race
    if char_class is not None:
        updates["char_class"] = char_class
    if level is not None:
        updates["level"] = level
    if background is not None:
        updates["background"] = background
    if backstory is not None:
        updates["backstory"] = backstory
    if abilities is not None:
        updates["abilities"] = abilities
    if details is not None:
        updates["details"] = details

    if not updates:
        conn.close()
        return

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [campaign_id, user_id]
    conn.execute(
        f"UPDATE players SET {set_clause} WHERE campaign_id = ? AND user_id = ?",
        values,
    )
    conn.commit()
    conn.close()


def get_character_sheet(campaign_id: int, user_id: int) -> Optional[dict]:
    """Get full character sheet data for a player."""
    conn = _connect()
    row = conn.execute(
        "SELECT * FROM players WHERE campaign_id = ? AND user_id = ? AND active = 1",
        (campaign_id, user_id),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def build_ai_context(campaign_id: int) -> str:
    """
    Build a context string for Claude API calls that includes
    campaign setting and all active character sheets.
    """
    campaign = get_campaign(campaign_id)
    if not campaign:
        return ""

    parts = []

    # Campaign setting
    if campaign.get("setting"):
        parts.append(f"CAMPAIGN SETTING — {campaign['name']}:\n{campaign['setting']}")

    # Character sheets
    players = get_players(campaign_id)
    sheets = []
    for p in players:
        lines = []
        name = p.get("character_name") or "Unnamed"
        lines.append(f"  Name: {name}")
        if p.get("race"):
            lines.append(f"  Race: {p['race']}")
        if p.get("char_class"):
            lines.append(f"  Class: {p['char_class']}")
        if p.get("level"):
            lines.append(f"  Level: {p['level']}")
        if p.get("background"):
            lines.append(f"  Background: {p['background']}")
        if p.get("backstory"):
            lines.append(f"  Backstory: {p['backstory']}")
        if p.get("abilities"):
            lines.append(f"  Abilities/Spells: {p['abilities']}")
        if p.get("details"):
            lines.append(f"  Additional details: {p['details']}")

        # Include inventory summary
        inv = get_player_inventory(campaign_id, p["user_id"])
        if inv:
            item_names = [f"{i['name']} (x{i['quantity']})" for i in inv]
            lines.append(f"  Inventory: {', '.join(item_names)}")

        if len(lines) > 1:  # More than just the name
            sheets.append("\n".join(lines))

    if sheets:
        parts.append("PARTY MEMBERS:\n" + "\n\n".join(sheets))

    return "\n\n".join(parts)


# ─── Session CRUD ────────────────────────────────────────────────────────────

def create_session(campaign_id: int, session_date: str, title: Optional[str] = None) -> int:
    conn = _connect()
    cur = conn.execute(
        "INSERT INTO sessions (campaign_id, session_date, title) VALUES (?, ?, ?)",
        (campaign_id, session_date, title),
    )
    session_id = cur.lastrowid

    players = get_players(campaign_id)
    for p in players:
        conn.execute(
            "INSERT OR IGNORE INTO rsvps (session_id, user_id) VALUES (?, ?)",
            (session_id, p["user_id"]),
        )

    conn.commit()
    conn.close()
    return session_id


def get_session(session_id: int) -> Optional[dict]:
    conn = _connect()
    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_upcoming_sessions(campaign_id: int, limit: int = 5) -> list[dict]:
    """
    Get upcoming sessions for a campaign.
    Includes sessions starting within the last 12 hours (likely still ongoing).
    """
    conn = _connect()
    rows = conn.execute(
        """SELECT * FROM sessions
           WHERE campaign_id = ? AND status = 'scheduled'
             AND session_date >= datetime('now', '-12 hours')
           ORDER BY session_date LIMIT ?""",
        (campaign_id, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_upcoming_sessions() -> list[dict]:
    """
    Get all upcoming sessions with campaign config (for the scheduler).
    Includes sessions started within the last 12 hours so a final reminder
    or in-progress check still fires correctly across timezone boundaries.
    """
    conn = _connect()
    rows = conn.execute(
        """SELECT s.*,
                  c.channel_id, c.name as campaign_name,
                  c.ping_days_before, c.midweek_enabled,
                  c.followup_count, c.followup_interval_hours,
                  c.reminder_hours, c.schedule_day
           FROM sessions s
           JOIN campaigns c ON s.campaign_id = c.id
           WHERE s.status = 'scheduled' AND s.session_date >= datetime('now', '-12 hours')
           ORDER BY s.session_date"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_session_status(session_id: int, status: str):
    conn = _connect()
    conn.execute("UPDATE sessions SET status = ? WHERE id = ?", (status, session_id))
    conn.commit()
    conn.close()


def clear_sessions(campaign_id: int) -> int:
    """Delete all upcoming/scheduled sessions for a campaign. Returns count deleted."""
    conn = _connect()
    cur = conn.execute(
        "DELETE FROM sessions WHERE campaign_id = ? AND status = 'scheduled'",
        (campaign_id,),
    )
    count = cur.rowcount
    conn.commit()
    conn.close()
    return count


def mark_ping_sent(session_id: int):
    conn = _connect()
    conn.execute("UPDATE sessions SET ping_sent = 1 WHERE id = ?", (session_id,))
    conn.commit()
    conn.close()


def reset_ping_state(session_id: int):
    """Reset all ping flags so the scheduler treats this session as fresh."""
    conn = _connect()
    conn.execute(
        """UPDATE sessions SET
           ping_sent = 0, midweek_sent = 0, reminders_sent = 0,
           last_reminder_at = NULL, final_reminder_sent = 0
           WHERE id = ?""",
        (session_id,),
    )
    conn.commit()
    conn.close()


def mark_midweek_sent(session_id: int):
    conn = _connect()
    conn.execute("UPDATE sessions SET midweek_sent = 1 WHERE id = ?", (session_id,))
    conn.commit()
    conn.close()


def increment_reminders_sent(session_id: int):
    now = datetime.now(timezone.utc).isoformat()
    conn = _connect()
    conn.execute(
        "UPDATE sessions SET reminders_sent = reminders_sent + 1, last_reminder_at = ? WHERE id = ?",
        (now, session_id),
    )
    conn.commit()
    conn.close()


def mark_final_reminder_sent(session_id: int):
    conn = _connect()
    conn.execute("UPDATE sessions SET final_reminder_sent = 1 WHERE id = ?", (session_id,))
    conn.commit()
    conn.close()


# ─── RSVP Management ────────────────────────────────────────────────────────

def set_rsvp(session_id: int, user_id: int, response: str):
    conn = _connect()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO rsvps (session_id, user_id, response, responded_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(session_id, user_id)
           DO UPDATE SET response=excluded.response, responded_at=excluded.responded_at""",
        (session_id, user_id, response, now),
    )
    conn.commit()
    conn.close()


def get_rsvps(session_id: int) -> list[dict]:
    conn = _connect()
    rows = conn.execute(
        """SELECT r.*, p.character_name
           FROM rsvps r
           LEFT JOIN players p ON r.user_id = p.user_id
             AND p.campaign_id = (SELECT campaign_id FROM sessions WHERE id = r.session_id)
           WHERE r.session_id = ?""",
        (session_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_pending_rsvps(session_id: int) -> list[dict]:
    conn = _connect()
    rows = conn.execute(
        "SELECT * FROM rsvps WHERE session_id = ? AND response = 'pending'",
        (session_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─── Attendance Logging ──────────────────────────────────────────────────────

def log_attendance(session_id: int, user_id: int, attended: bool):
    conn = _connect()
    conn.execute(
        """INSERT INTO rsvps (session_id, user_id)
           VALUES (?, ?)
           ON CONFLICT DO NOTHING""",
        (session_id, user_id),
    )
    conn.execute(
        """INSERT INTO attendance_log (session_id, user_id, attended)
           VALUES (?, ?, ?)
           ON CONFLICT(session_id, user_id)
           DO UPDATE SET attended=excluded.attended""",
        (session_id, user_id, int(attended)),
    )
    conn.commit()
    conn.close()


def get_player_stats(campaign_id: int, user_id: int) -> dict:
    conn = _connect()
    row = conn.execute(
        """SELECT
             COUNT(*) as total_sessions,
             SUM(CASE WHEN a.attended = 1 THEN 1 ELSE 0 END) as attended,
             SUM(CASE WHEN r.response = 'yes' THEN 1 ELSE 0 END) as rsvp_yes,
             SUM(CASE WHEN r.response = 'no' THEN 1 ELSE 0 END) as rsvp_no
           FROM sessions s
           LEFT JOIN rsvps r ON s.id = r.session_id AND r.user_id = ?
           LEFT JOIN attendance_log a ON s.id = a.session_id AND a.user_id = ?
           WHERE s.campaign_id = ? AND s.status = 'completed'""",
        (user_id, user_id, campaign_id),
    ).fetchone()
    conn.close()
    return dict(row) if row else {}


# ─── Auto-Schedule Helpers ───────────────────────────────────────────────────

def get_auto_schedule_campaigns() -> list[dict]:
    conn = _connect()
    rows = conn.execute(
        "SELECT * FROM campaigns WHERE auto_schedule = 1 AND schedule_day IS NOT NULL"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─── Homebrew Item CRUD ──────────────────────────────────────────────────────

def create_item(
    campaign_id: int,
    name: str,
    created_by: int,
    description: str = "",
    rarity: str = "common",
    item_type: str = "wondrous item",
    properties: dict = None,
) -> int:
    conn = _connect()
    cur = conn.execute(
        """INSERT INTO items (campaign_id, name, description, rarity, item_type, properties, created_by)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (campaign_id, name, description, rarity, item_type,
         json.dumps(properties or {}), created_by),
    )
    conn.commit()
    item_id = cur.lastrowid
    conn.close()
    return item_id


def get_item(item_id: int) -> Optional[dict]:
    conn = _connect()
    row = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    conn.close()
    if row:
        d = dict(row)
        d["properties"] = json.loads(d["properties"]) if d["properties"] else {}
        return d
    return None


def get_items(campaign_id: int) -> list[dict]:
    conn = _connect()
    rows = conn.execute(
        "SELECT * FROM items WHERE campaign_id = ? ORDER BY rarity, name",
        (campaign_id,),
    ).fetchall()
    conn.close()
    results = []
    for r in rows:
        d = dict(r)
        d["properties"] = json.loads(d["properties"]) if d["properties"] else {}
        results.append(d)
    return results


def search_items(campaign_id: int, query: str) -> list[dict]:
    conn = _connect()
    rows = conn.execute(
        "SELECT * FROM items WHERE campaign_id = ? AND name LIKE ? ORDER BY name",
        (campaign_id, f"%{query}%"),
    ).fetchall()
    conn.close()
    results = []
    for r in rows:
        d = dict(r)
        d["properties"] = json.loads(d["properties"]) if d["properties"] else {}
        results.append(d)
    return results


def update_item(item_id: int, **kwargs):
    conn = _connect()
    allowed = {"name", "description", "rarity", "item_type", "properties"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if "properties" in updates and isinstance(updates["properties"], dict):
        updates["properties"] = json.dumps(updates["properties"])
    if not updates:
        conn.close()
        return
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [item_id]
    conn.execute(f"UPDATE items SET {set_clause} WHERE id = ?", values)
    conn.commit()
    conn.close()


def delete_item(item_id: int):
    conn = _connect()
    conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()


# ─── Inventory Management ────────────────────────────────────────────────────

def give_item(campaign_id: int, user_id: int, item_id: int, quantity: int = 1, notes: str = None):
    conn = _connect()
    conn.execute(
        """INSERT INTO player_inventory (campaign_id, user_id, item_id, quantity, notes)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(campaign_id, user_id, item_id)
           DO UPDATE SET quantity = quantity + ?, notes = COALESCE(?, notes)""",
        (campaign_id, user_id, item_id, quantity, notes, quantity, notes),
    )
    conn.commit()
    conn.close()


def remove_item_from_player(campaign_id: int, user_id: int, item_id: int, quantity: int = 1):
    conn = _connect()
    row = conn.execute(
        "SELECT quantity FROM player_inventory WHERE campaign_id=? AND user_id=? AND item_id=?",
        (campaign_id, user_id, item_id),
    ).fetchone()
    if row:
        new_qty = row["quantity"] - quantity
        if new_qty <= 0:
            conn.execute(
                "DELETE FROM player_inventory WHERE campaign_id=? AND user_id=? AND item_id=?",
                (campaign_id, user_id, item_id),
            )
        else:
            conn.execute(
                "UPDATE player_inventory SET quantity=? WHERE campaign_id=? AND user_id=? AND item_id=?",
                (new_qty, campaign_id, user_id, item_id),
            )
    conn.commit()
    conn.close()


def transfer_item(campaign_id: int, from_user: int, to_user: int, item_id: int, quantity: int = 1) -> bool:
    conn = _connect()
    row = conn.execute(
        "SELECT quantity FROM player_inventory WHERE campaign_id=? AND user_id=? AND item_id=?",
        (campaign_id, from_user, item_id),
    ).fetchone()
    if not row or row["quantity"] < quantity:
        conn.close()
        return False
    conn.close()
    remove_item_from_player(campaign_id, from_user, item_id, quantity)
    give_item(campaign_id, to_user, item_id, quantity)
    return True


def get_player_inventory(campaign_id: int, user_id: int) -> list[dict]:
    conn = _connect()
    rows = conn.execute(
        """SELECT pi.*, i.name, i.description, i.rarity, i.item_type, i.properties
           FROM player_inventory pi
           JOIN items i ON pi.item_id = i.id
           WHERE pi.campaign_id = ? AND pi.user_id = ?
           ORDER BY i.rarity, i.name""",
        (campaign_id, user_id),
    ).fetchall()
    conn.close()
    results = []
    for r in rows:
        d = dict(r)
        d["properties"] = json.loads(d["properties"]) if d["properties"] else {}
        results.append(d)
    return results


def get_item_holders(campaign_id: int, item_id: int) -> list[dict]:
    conn = _connect()
    rows = conn.execute(
        """SELECT pi.*, p.character_name
           FROM player_inventory pi
           LEFT JOIN players p ON pi.user_id = p.user_id AND pi.campaign_id = p.campaign_id
           WHERE pi.campaign_id = ? AND pi.item_id = ?""",
        (campaign_id, item_id),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def toggle_equipped(campaign_id: int, user_id: int, item_id: int) -> bool:
    conn = _connect()
    row = conn.execute(
        "SELECT equipped FROM player_inventory WHERE campaign_id=? AND user_id=? AND item_id=?",
        (campaign_id, user_id, item_id),
    ).fetchone()
    if not row:
        conn.close()
        return False
    new_val = 0 if row["equipped"] else 1
    conn.execute(
        "UPDATE player_inventory SET equipped=? WHERE campaign_id=? AND user_id=? AND item_id=?",
        (new_val, campaign_id, user_id, item_id),
    )
    conn.commit()
    conn.close()
    return bool(new_val)
