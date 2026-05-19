# ⚔️ Herald

A self-hosted Discord bot — the DM's right hand. Campaign scheduling, homebrew inventory, language translation, and AI-powered world-building. Like Apollo, but free, self-hosted, and built for tabletop RPGs.

## Features

### 📅 Scheduling & Attendance
- **Recurring schedules** — Set your game day/time and the bot auto-creates sessions weekly
- **Configurable ping chain** — Full control over how and when players get pinged:
  - **Initial ping** — N days before (default: 3)
  - **Midweek check-in** — Status update halfway between ping and game day
  - **Follow-up pings** — Configurable count and interval for non-responders
  - **Final reminder** — M hours before game time (default: 4)
- **Interactive RSVP** — Big buttons: ⚔️ I'm In / 🛡️ Can't Make It / ❓ Tentative
- **Attendance tracking** — Historical stats per player across completed sessions
- **D&D-themed messages** — Rotating flavor text for follow-up pings

### 🎒 Homebrew Inventory
- **Create items** — Define homebrew items with name, description, rarity, and type
- **Rarity tiers** — Common through Artifact with color-coded embeds (WoW-style)
- **Give / Remove / Transfer** — DM distributes loot; players can trade between each other
- **Equip tracking** — Players can mark items as equipped
- **Item compendium** — Browse all items in a campaign with holder info

### 🌐 Language Translation
- **18 D&D languages** — Common, Dwarvish, Elvish, Draconic, Infernal, and more
- **Cipher-based** — Each language has a unique character mapping for visual flavor
- **Decorative markers** — Translated text is wrapped with thematic symbols
- **Bidirectional** — Translate to, from, or between any two languages

### 🤖 AI-Powered Content (Claude API)
- **Item Forge** — Describe an item concept and Claude generates full lore, description, and mechanical properties, then auto-saves it to your compendium
- **Enhance existing items** — Take a bare-bones item and flesh it out with AI
- **Lore Builder** — Generate locations (with NPCs, hooks, and secrets), factions (with goals, tensions, and mottos), NPCs (with personality, voice notes, and secrets), and historical lore (with key figures and mysteries)
- **Spoiler-tagged secrets** — DM-sensitive info (secrets, DM notes) is wrapped in Discord spoiler tags
- **Rate limiting** — Players get 10 AI requests/hour, DMs get 60/hour (configurable)
- **Fully optional** — Leave `ANTHROPIC_API_KEY` blank and everything else still works

## Discord Developer Portal Setup

1. Go to [discord.com/developers/applications](https://discord.com/developers/applications)
2. Click **New Application**, name it "Herald"
3. Go to the **Bot** tab:
   - Click **Reset Token** and copy it — this is your `DISCORD_TOKEN`
   - Enable **Server Members Intent** (under Privileged Gateway Intents)
   - Disable **Public Bot** if you only want it on your server
4. Go to the **OAuth2** tab:
   - Under **Scopes**, check `bot` and `applications.commands`
   - Under **Bot Permissions**, check:
     - Send Messages
     - Embed Links
     - Use Slash Commands
     - Mention Everyone
     - Read Message History
   - Copy the generated URL and open it to invite the bot to your server

## Claude API Setup (optional — for /forge and /lore)

1. Go to [console.anthropic.com/settings/keys](https://console.anthropic.com/settings/keys)
2. Create an API key and add it to your `.env` as `ANTHROPIC_API_KEY`
3. The bot uses `claude-sonnet-4-20250514` by default (good balance of quality and cost). You can change this to any model via the `CLAUDE_MODEL` env var.
4. Typical cost: a `/forge item` or `/lore npc` call runs ~$0.003-0.01 per generation.

If you don't set `ANTHROPIC_API_KEY`, all scheduling, inventory, and translation features still work — only `/forge` and `/lore` commands will error.

## Deployment on Unraid

### Option A: Docker Compose (recommended)

```bash
mkdir -p /mnt/user/appdata/herald-bot
# Copy all project files there

cd /mnt/user/appdata/herald-bot
cp .env.example .env
nano .env   # Paste your DISCORD_TOKEN and optionally ANTHROPIC_API_KEY

docker compose up -d
```

### Option B: Manual Docker

```bash
cd /mnt/user/appdata/herald-bot
docker build -t herald-bot .
docker run -d \
  --name herald-bot \
  --restart unless-stopped \
  --env-file .env \
  -v ./data:/app/data \
  herald-bot
```

## Command Reference

### `/campaign` — Campaign Management

| Command | Description |
|---------|-------------|
| `create <name>` | Create a campaign in the current channel |
| `list` | List all campaigns in this server |
| `schedule <id> <day> <time> [options]` | Set recurring schedule and ping timing |
| `setting <id> <text>` | Set campaign world/setting context for AI features |
| `setting_view <id>` | View the current campaign setting |
| `delete <id>` | Delete a campaign (DM only) |

**Schedule options:**
| Option | Default | Description |
|--------|---------|-------------|
| `timezone` | America/Denver | Timezone for scheduling |
| `ping_days` | 3 | Days before session for initial ping |
| `midweek` | True | Send midweek status check-in |
| `followup_count` | 1 | Number of follow-up pings to non-responders |
| `followup_interval` | 24 | Hours between follow-up pings |
| `reminder_hours` | 4 | Hours before session for final reminder |
| `auto` | True | Auto-create sessions each week |

### `/party` — Party Management

| Command | Description |
|---------|-------------|
| `add <campaign_id> @player [character_name]` | Add a player |
| `remove <campaign_id> @player` | Remove a player |
| `rename <campaign_id> @player <name>` | Set character name |
| `list <campaign_id>` | Show the party roster |
| `stats <campaign_id> @player` | View attendance stats |
| `sheet <campaign_id> @player [race] [class] [level] ...` | Set character sheet for AI context |
| `sheet_view <campaign_id> [@player]` | View full character sheet + inventory |

### `/session` — Session Management

| Command | Description |
|---------|-------------|
| `create <campaign_id> <date> [title]` | Manually create a session |
| `list <campaign_id>` | Show upcoming sessions |
| `ping <session_id>` | Manually ping for attendance |
| `status <session_id>` | View current RSVP status |
| `cancel <session_id>` | Cancel a session (DM only) |
| `complete <session_id>` | Mark complete + log attendance (DM only) |

### `/rsvp` — Quick RSVP

| Command | Description |
|---------|-------------|
| `<session_id> <yes\|no\|tentative>` | Quick RSVP via slash command |

### `/item` — Homebrew Items (DM only for create/edit/delete)

| Command | Description |
|---------|-------------|
| `create <campaign_id> <name> [description] [rarity] [type]` | Create an item |
| `list <campaign_id>` | Browse the item compendium |
| `inspect <item_id>` | View full item details + who holds it |
| `edit <item_id> [name] [description] [rarity] [type]` | Edit an item |
| `delete <item_id>` | Delete an item |

### `/inventory` — Player Inventory

| Command | Description |
|---------|-------------|
| `give <campaign_id> @player <item_id> [qty]` | Give item to player (DM only) |
| `remove <campaign_id> @player <item_id> [qty]` | Remove item from player (DM only) |
| `transfer <campaign_id> @player <item_id> [qty]` | Trade item to another player |
| `show <campaign_id> [@player]` | View inventory (defaults to self) |
| `equip <campaign_id> <item_id>` | Toggle equip/unequip |

### `/translate` — D&D Languages

| Command | Description |
|---------|-------------|
| `to <language> <text>` | Common → target language |
| `from <language> <text>` | Source language → Common |
| `between <from> <to> <text>` | Translate between any two languages |
| `languages` | List all 18 available languages |

**Available languages:** Common, Dwarvish, Elvish, Giant, Gnomish, Goblin, Halfling, Orc, Abyssal, Celestial, Draconic, Deep Speech, Infernal, Primordial, Sylvan, Undercommon, Druidic, Thieves' Cant

### `/forge` — AI Item Forge (Claude API)

| Command | Description |
|---------|-------------|
| `item <campaign_id> <name> [rarity] [type] [context]` | AI-generate a full homebrew item and add it to the compendium |
| `enhance <item_id> [context]` | AI-enhance an existing item with richer lore and properties |

Players can use these (rate-limited to 10/hour). DMs get 60/hour. Both limits are configurable in `.env`.

### `/lore` — AI Lore Builder (Claude API)

| Command | Description |
|---------|-------------|
| `location <campaign_id> <name> [context]` | Generate a location with NPCs, hooks, and a secret |
| `faction <campaign_id> <name> [context]` | Generate a faction with goals, tensions, and a motto |
| `npc <campaign_id> <name> [context]` | Generate an NPC with personality, voice notes, and a secret |
| `history <campaign_id> <topic> [context]` | Generate historical lore with key figures and mysteries |

All lore outputs use Discord spoiler tags (`||hidden||`) for secrets and DM notes so players don't see them unless they choose to.

## Ping Chain Flow

Example: Friday game at 7 PM, configured with defaults + 2 follow-ups every 12 hours:

```
Tuesday    → 📬 Initial ping (3 days before) — pings all players
Wednesday  → 📋 Midweek check-in — status update + nudges non-responders
Thursday   → 🔔 Follow-up #1 (if non-responders remain)
Thursday   → 🔔 Follow-up #2 (12 hours later, if still pending)
Friday 3PM → ⏰ Final reminder (4 hours before) — last call
Friday 7PM → 🎲 Game time!
```

## Typical Workflow

```
1.  /campaign create "Curse of Strahd"
2.  /party add 1 @Alice character_name:Elara
3.  /party add 1 @Bob character_name:Grimjaw
4.  /campaign schedule 1 friday 19:00 followup_count:2 followup_interval:12
5.  → Bot auto-creates sessions and runs the full ping chain weekly
6.  Players click ⚔️ or 🛡️ on ping messages
7.  /forge item 1 "Sunsword" rarity:legendary item_type:weapon context:"sentient blade that hates undead"
    → Claude generates full item with description, properties, quirks — auto-saved to compendium
8.  /inventory give 1 @Alice 7
9.  /lore location 1 "The Drowned Lantern" context:"a tavern in Barovia that caters to Vistani travelers"
    → Claude generates atmosphere, NPCs, adventure hooks, and a secret (spoiler-tagged)
10. /lore npc 1 "Morwen the Blind" context:"an old woman who knows too much about Strahd's past"
11. /translate to draconic "The dragon awakens"
12. /session complete 1
```

## Project Structure

```
├── bot.py           # Slash commands (all command groups)
├── database.py      # SQLite persistence layer
├── scheduler.py     # Background ping chain + auto-session creation
├── languages.py     # D&D language cipher translation engine
├── claude_api.py    # Claude API integration (forge + lore generation)
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── .env.example
```

## Data

All data lives in `data/scheduler.db` (SQLite with WAL mode). Back it up if you care about attendance history and item compendiums.

## Future Ideas

- Web dashboard for viewing stats and inventory
- Poll for best day/time when scheduling
- Voice channel detection for auto-attendance
- Session notes / recap storage
- XP / milestone tracking
- Party loot pool (unassigned treasure)
- Custom language cipher editor
- Item property templates (damage dice, AC bonus, etc.)
