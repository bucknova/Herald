"""
db_init.py — Web-owned schema initialization.

Phase 0: this file is intentionally empty. The web portal does not yet
read from or write to the database.

Phase 1 will add:
  - A _connect() helper matching the bot's pattern (WAL + foreign keys
    + Row factory).
  - init_web_db() that creates the web-owned tables with
    CREATE TABLE IF NOT EXISTS:
      web_sessions, wiki_pages, dice_rolls, notification_prefs,
      ai_request_log, campaign_web_settings
  - A _migrate(conn, table, column, type) helper mirroring the bot's
    additive-migration pattern.

The bot's schema in shared/database.py is read-only from this module's
perspective. We never modify bot-owned tables. See ARCHITECTURE.md §4.
"""
