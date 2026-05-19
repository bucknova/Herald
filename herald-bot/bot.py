"""
bot.py — Main entry point for Herald, the DM's right hand.

Slash command groups:
  /campaign  – Create, list, schedule, delete campaigns
  /party     – Add, remove, rename players; view stats
  /session   – Create, list, ping, cancel, complete sessions
  /rsvp      – Quick RSVP shorthand
  /item      – Create, edit, delete, inspect homebrew items
  /inventory – Give, remove, transfer, equip items; view player bags
  /translate – Translate text between D&D languages
  /forge     – AI-powered homebrew item generation (Claude API)
  /lore      – AI-powered world-building generation (Claude API)
"""

import os
import json
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

import database as db
from scheduler import RSVPView, build_rsvp_embed, setup as setup_scheduler
from languages import translate, translate_to, translate_from, get_languages
import claude_api
import ai_backend
import pdf_parser

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN not set. Copy .env.example to .env and fill it in.")

# ─── Bot Setup ───────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.members = True
intents.message_content = False

bot = commands.Bot(command_prefix="!", intents=intents)


async def resolve_campaign_id(interaction: discord.Interaction, campaign_id: int = None) -> int | None:
    """
    Auto-resolve campaign_id. If None:
      - In a server: use the only campaign in that guild, or prompt if multiple.
      - In DMs: use the only campaign the user belongs to, or prompt if multiple.
    Returns the resolved ID or None (with an error message sent to the user).
    """
    if campaign_id is not None:
        return campaign_id

    # In a server — look up by guild
    if interaction.guild_id:
        campaigns = db.get_campaigns_for_guild(interaction.guild_id)
    else:
        # In DMs — look up by user (as DM or player)
        campaigns = db.get_campaigns_for_user(interaction.user.id)

    if len(campaigns) == 1:
        return campaigns[0]["id"]
    elif len(campaigns) == 0:
        if interaction.guild_id:
            await interaction.response.send_message(
                "No campaigns found. Create one with `/campaign create`.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "No campaigns found for your account. Use Herald in your server first to set up a campaign.",
                ephemeral=True,
            )
        return None
    else:
        names = "\n".join(f"• **{c['name']}** (ID: {c['id']})" for c in campaigns)
        await interaction.response.send_message(
            f"Multiple campaigns found — please specify `campaign_id`:\n{names}",
            ephemeral=True,
        )
        return None


@bot.event
async def on_ready():
    db.init_db()
    await setup_scheduler(bot)

    sessions = db.get_all_upcoming_sessions()
    for s in sessions:
        bot.add_view(RSVPView(s["id"]))

    synced = await bot.tree.sync()
    print(f"✅ {bot.user} is online — synced {len(synced)} commands.")


# ═════════════════════════════════════════════════════════════════════════════
#  CAMPAIGN COMMANDS
# ═════════════════════════════════════════════════════════════════════════════

campaign_group = app_commands.Group(name="campaign", description="Manage your D&D campaigns")


@campaign_group.command(name="create", description="Create a new campaign in this channel")
@app_commands.describe(name="Name of your campaign")
async def campaign_create(interaction: discord.Interaction, name: str):
    campaign_id = db.create_campaign(
        guild_id=interaction.guild_id,
        channel_id=interaction.channel_id,
        name=name,
        dm_user_id=interaction.user.id,
    )
    await interaction.response.send_message(
        f"🏰 **Campaign created!**\n\n"
        f"**{name}** (ID: `{campaign_id}`)\n"
        f"DM: {interaction.user.mention}\n"
        f"Channel: {interaction.channel.mention}\n\n"
        f"Next steps:\n"
        f"• `/party add {campaign_id} @player`\n"
        f"• `/campaign schedule {campaign_id} friday 19:00`"
    )


@campaign_group.command(name="list", description="List all campaigns in this server")
async def campaign_list(interaction: discord.Interaction):
    campaigns = db.get_campaigns_for_guild(interaction.guild_id)
    if not campaigns:
        await interaction.response.send_message("No campaigns yet. Create one with `/campaign create`!")
        return

    embed = discord.Embed(title="📜 Campaigns", color=0x7C3AED)
    for c in campaigns:
        players = db.get_players(c["id"])
        schedule = "Not set"
        if c["schedule_day"]:
            freq = c.get("repeat_frequency", "weekly")
            freq_label = {"weekly": "Weekly", "biweekly": "Biweekly", "monthly": "Monthly"}.get(freq, freq)
            schedule = f"{freq_label} — {c['schedule_day'].title()}s at {c['schedule_time']} ({c['schedule_tz']})"
            if c["auto_schedule"]:
                ahead = c.get("sessions_ahead", 1)
                schedule += f" 🔄 ({ahead} ahead)"

        ping_info = (
            f"Initial: {c['ping_days_before']}d before"
            f" | Midweek: {'✅' if c['midweek_enabled'] else '❌'}"
            f" | Follow-ups: {c['followup_count']}x every {c['followup_interval_hours']}h"
            f" | Final: {c['reminder_hours']}h before"
        )

        embed.add_field(
            name=f"{c['name']} (ID: {c['id']})",
            value=(
                f"DM: <@{c['dm_user_id']}>\n"
                f"Players: {len(players)}\n"
                f"Schedule: {schedule}\n"
                f"Pings: {ping_info}"
            ),
            inline=False,
        )

    await interaction.response.send_message(embed=embed)


@campaign_group.command(name="schedule", description="Set the recurring game schedule and ping timing")
@app_commands.describe(
    campaign_id="Campaign ID",
    day="Day of the week (e.g., friday)",
    time="Time in 24h format (e.g., 19:00)",
    timezone="Timezone (default: America/Denver)",
    repeat="How often sessions repeat (default: weekly)",
    sessions_ahead="How many future sessions to auto-create (default: 1)",
    start_date="First session date to anchor the schedule (e.g., 2026-04-24)",
    ping_days="Days before session to send first ping (default: 3)",
    midweek="Send a midweek status check-in (default: True)",
    followup_count="Number of follow-up pings to non-responders (default: 1)",
    followup_interval="Hours between follow-up pings (default: 24)",
    reminder_hours="Hours before session to send final reminder (default: 4)",
    auto="Automatically create sessions (default: True)",
)
@app_commands.choices(
    day=[
        app_commands.Choice(name=d.title(), value=d)
        for d in ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    ],
    repeat=[
        app_commands.Choice(name="Weekly", value="weekly"),
        app_commands.Choice(name="Biweekly (every 2 weeks)", value="biweekly"),
        app_commands.Choice(name="Monthly (same weekday each month)", value="monthly"),
    ],
)
async def campaign_schedule(
    interaction: discord.Interaction,
    campaign_id: int,
    day: str,
    time: str,
    timezone: str = "America/Denver",
    repeat: str = "weekly",
    sessions_ahead: int = 1,
    start_date: str = None,
    ping_days: int = 3,
    midweek: bool = True,
    followup_count: int = 1,
    followup_interval: int = 24,
    reminder_hours: int = 4,
    auto: bool = True,
):
    campaign = db.get_campaign(campaign_id)
    if not campaign:
        await interaction.response.send_message("Campaign not found.", ephemeral=True)
        return
    if campaign["dm_user_id"] != interaction.user.id:
        await interaction.response.send_message("Only the DM can change the schedule.", ephemeral=True)
        return

    try:
        ZoneInfo(timezone)
    except Exception:
        await interaction.response.send_message(f"Invalid timezone: `{timezone}`", ephemeral=True)
        return

    sessions_ahead = max(1, min(sessions_ahead, 8))  # Clamp to 1-8

    # Validate and parse start_date if provided
    parsed_start = None
    if start_date:
        try:
            tz_obj = ZoneInfo(timezone)
            parsed_start = datetime.strptime(start_date, "%Y-%m-%d").replace(
                hour=int(time.split(":")[0]),
                minute=int(time.split(":")[1]),
                tzinfo=tz_obj,
            )
            start_date_iso = parsed_start.isoformat()
        except ValueError:
            await interaction.response.send_message(
                "Invalid start date format. Use `YYYY-MM-DD` (e.g., `2026-04-24`).",
                ephemeral=True,
            )
            return
    else:
        start_date_iso = None

    db.update_campaign_schedule(
        campaign_id, day, time, timezone,
        ping_days, midweek, followup_count, followup_interval, reminder_hours, auto,
        repeat, sessions_ahead, start_date_iso,
    )

    freq_labels = {"weekly": "Every week", "biweekly": "Every 2 weeks", "monthly": "Monthly"}

    embed = discord.Embed(
        title=f"📅 Schedule Updated — {campaign['name']}",
        color=0x7C3AED,
    )
    embed.add_field(name="Game Day", value=f"**{day.title()}** at **{time}**", inline=True)
    embed.add_field(name="Repeat", value=freq_labels.get(repeat, repeat.title()), inline=True)
    embed.add_field(name="Timezone", value=timezone, inline=True)
    if parsed_start:
        unix_ts = int(parsed_start.timestamp())
        embed.add_field(name="Starting", value=f"<t:{unix_ts}:D>", inline=True)
    embed.add_field(name="Sessions Ahead", value=str(sessions_ahead), inline=True)
    embed.add_field(name="Auto-Schedule", value="🔄 Enabled" if auto else "Disabled", inline=True)
    embed.add_field(name="Initial Ping", value=f"{ping_days} days before", inline=True)
    embed.add_field(name="Midweek Check-in", value="✅ Enabled" if midweek else "❌ Disabled", inline=True)
    embed.add_field(
        name="Follow-up Pings",
        value=f"{followup_count}x, every {followup_interval}h",
        inline=True,
    )
    embed.add_field(name="Final Reminder", value=f"{reminder_hours} hours before", inline=True)

    await interaction.response.send_message(embed=embed)


@campaign_group.command(name="delete", description="Delete a campaign permanently (DM only)")
@app_commands.describe(
    campaign_id="Campaign ID to delete",
    confirm="Type the campaign name to confirm deletion",
)
async def campaign_delete(interaction: discord.Interaction, campaign_id: int, confirm: str):
    campaign = db.get_campaign(campaign_id)
    if not campaign:
        await interaction.response.send_message("Campaign not found.", ephemeral=True)
        return
    if campaign["dm_user_id"] != interaction.user.id:
        await interaction.response.send_message("Only the DM can delete a campaign.", ephemeral=True)
        return

    if confirm.strip() != campaign["name"]:
        await interaction.response.send_message(
            f"Confirmation didn't match. To delete this campaign, set `confirm` to the exact name: **{campaign['name']}**\n"
            f"This action is permanent — all sessions, RSVPs, items, inventory, and character sheets will be lost.",
            ephemeral=True,
        )
        return

    db.delete_campaign(campaign_id)
    await interaction.response.send_message(f"🗑️ Campaign **{campaign['name']}** has been deleted.")


@campaign_group.command(name="setting", description="Set your campaign's world/setting context for AI features")
@app_commands.describe(
    campaign_id="Campaign ID",
    setting="Describe your campaign world, themes, tone, house rules — anything the AI should know",
)
async def campaign_setting(interaction: discord.Interaction, campaign_id: int, setting: str):
    campaign = db.get_campaign(campaign_id)
    if not campaign:
        await interaction.response.send_message("Campaign not found.", ephemeral=True)
        return
    if campaign["dm_user_id"] != interaction.user.id:
        await interaction.response.send_message("Only the DM can set the campaign context.", ephemeral=True)
        return

    db.update_campaign_setting(campaign_id, setting)

    embed = discord.Embed(
        title=f"🌍 Setting Updated — {campaign['name']}",
        description=setting[:4000],
        color=0x7C3AED,
    )
    embed.set_footer(text="This context will be included in all /forge and /lore AI generations.")
    await interaction.response.send_message(embed=embed)


@campaign_group.command(name="setting_view", description="View the current campaign setting context")
@app_commands.describe(campaign_id="Campaign ID")
async def campaign_setting_view(interaction: discord.Interaction, campaign_id: int = None):
    campaign_id = await resolve_campaign_id(interaction, campaign_id)
    if campaign_id is None:
        return
    campaign = db.get_campaign(campaign_id)
    if not campaign:
        await interaction.response.send_message("Campaign not found.", ephemeral=True)
        return

    setting = campaign.get("setting")
    if not setting:
        await interaction.response.send_message(
            f"No setting configured for **{campaign['name']}** yet.\n"
            f"Use `/campaign setting {campaign_id}` to add one.",
        )
        return

    embed = discord.Embed(
        title=f"🌍 Setting — {campaign['name']}",
        description=setting[:4000],
        color=0x7C3AED,
    )
    await interaction.response.send_message(embed=embed)


@campaign_group.command(name="backend", description="Set the default AI backend for this campaign")
@app_commands.describe(
    campaign_id="Campaign ID (auto-detected if only one)",
    backend="AI backend to use as the default for this campaign",
)
@app_commands.choices(backend=[
    app_commands.Choice(name="☁️ Claude (cloud)", value="claude"),
    app_commands.Choice(name="🖥️ LocalAI (self-hosted)", value="local"),
    app_commands.Choice(name="System default", value="default"),
])
async def campaign_backend(interaction: discord.Interaction, backend: str, campaign_id: int = None):
    campaign_id = await resolve_campaign_id(interaction, campaign_id)
    if campaign_id is None:
        return

    campaign = db.get_campaign(campaign_id)
    if not campaign:
        await interaction.response.send_message("Campaign not found.", ephemeral=True)
        return
    if campaign["dm_user_id"] != interaction.user.id:
        await interaction.response.send_message("Only the DM can change the backend.", ephemeral=True)
        return

    # Validate the chosen backend is actually available
    if backend == "claude" and not claude_api.API_KEY:
        await interaction.response.send_message(
            "Claude is not configured. Set `ANTHROPIC_API_KEY` in your `.env` file.",
            ephemeral=True,
        )
        return
    if backend == "local" and not ai_backend.local_api.is_configured():
        await interaction.response.send_message(
            "LocalAI is not configured. Set `LOCALAI_BASE_URL` and `LOCALAI_MODEL` in your `.env` file.",
            ephemeral=True,
        )
        return

    # "default" stores NULL — falls back to system priority logic
    db_value = None if backend == "default" else backend
    db.update_campaign_backend(campaign_id, db_value)

    label = ai_backend.backend_label(backend) if backend != "default" else "System default"
    await interaction.response.send_message(
        f"🔧 AI backend for **{campaign['name']}** set to {label}.\n"
        f"Individual commands can still override with the `backend` parameter."
    )


bot.tree.add_command(campaign_group)


# ═════════════════════════════════════════════════════════════════════════════
#  PARTY COMMANDS
# ═════════════════════════════════════════════════════════════════════════════

party_group = app_commands.Group(name="party", description="Manage campaign party members")


@party_group.command(name="add", description="Add a player to the campaign")
@app_commands.describe(
    campaign_id="Campaign ID",
    player="The player to add",
    character_name="Their character's name (optional)",
)
async def party_add(
    interaction: discord.Interaction,
    campaign_id: int,
    player: discord.Member,
    character_name: str = None,
):
    campaign = db.get_campaign(campaign_id)
    if not campaign:
        await interaction.response.send_message("Campaign not found.", ephemeral=True)
        return
    if campaign["dm_user_id"] != interaction.user.id:
        await interaction.response.send_message("Only the DM can manage the party.", ephemeral=True)
        return

    db.add_player(campaign_id, player.id, character_name)
    char_text = f" as **{character_name}**" if character_name else ""
    await interaction.response.send_message(
        f"🗡️ {player.mention} has joined **{campaign['name']}**{char_text}!"
    )


@party_group.command(name="remove", description="Remove a player from the campaign")
@app_commands.describe(campaign_id="Campaign ID", player="The player to remove")
async def party_remove(interaction: discord.Interaction, campaign_id: int, player: discord.Member):
    campaign = db.get_campaign(campaign_id)
    if not campaign:
        await interaction.response.send_message("Campaign not found.", ephemeral=True)
        return
    if campaign["dm_user_id"] != interaction.user.id:
        await interaction.response.send_message("Only the DM can manage the party.", ephemeral=True)
        return

    db.remove_player(campaign_id, player.id)
    await interaction.response.send_message(f"👋 {player.mention} has left **{campaign['name']}**.")


@party_group.command(name="rename", description="Set or change a player's character name")
@app_commands.describe(campaign_id="Campaign ID", player="The player", character_name="New character name")
async def party_rename(
    interaction: discord.Interaction, campaign_id: int, player: discord.Member, character_name: str
):
    db.update_character_name(campaign_id, player.id, character_name)
    await interaction.response.send_message(f"📝 {player.mention} is now known as **{character_name}**.")


@party_group.command(name="list", description="Show all party members")
@app_commands.describe(campaign_id="Campaign ID")
async def party_list(interaction: discord.Interaction, campaign_id: int = None):
    campaign_id = await resolve_campaign_id(interaction, campaign_id)
    if campaign_id is None:
        return
    campaign = db.get_campaign(campaign_id)
    if not campaign:
        await interaction.response.send_message("Campaign not found.", ephemeral=True)
        return

    players = db.get_players(campaign_id)
    if not players:
        await interaction.response.send_message("No players yet. Add some with `/party add`!")
        return

    embed = discord.Embed(
        title=f"⚔️ Party — {campaign['name']}",
        description=f"DM: <@{campaign['dm_user_id']}>",
        color=0x7C3AED,
    )
    for i, p in enumerate(players, 1):
        char = p["character_name"] or "No character set"
        embed.add_field(name=f"{i}. <@{p['user_id']}>", value=char, inline=True)

    await interaction.response.send_message(embed=embed)


@party_group.command(name="stats", description="View a player's attendance stats")
@app_commands.describe(campaign_id="Campaign ID", player="The player")
async def party_stats(interaction: discord.Interaction, campaign_id: int, player: discord.Member):
    stats = db.get_player_stats(campaign_id, player.id)
    total = stats.get("total_sessions", 0)
    attended = stats.get("attended", 0) or 0
    rate = f"{(attended / total * 100):.0f}%" if total > 0 else "N/A"

    embed = discord.Embed(title=f"📊 {player.display_name} — Attendance", color=0x7C3AED)
    embed.add_field(name="Sessions Played", value=str(total), inline=True)
    embed.add_field(name="Attended", value=str(attended), inline=True)
    embed.add_field(name="Attendance Rate", value=rate, inline=True)
    embed.add_field(name="RSVP Yes", value=str(stats.get("rsvp_yes", 0) or 0), inline=True)
    embed.add_field(name="RSVP No", value=str(stats.get("rsvp_no", 0) or 0), inline=True)

    await interaction.response.send_message(embed=embed)


@party_group.command(name="sheet", description="Set character sheet details for AI context")
@app_commands.describe(
    campaign_id="Campaign ID",
    player="The player (DM can set for anyone, players can set their own)",
    race="Character race (e.g., Half-Elf, Tiefling)",
    char_class="Character class (e.g., Warlock 5 / Sorcerer 3)",
    level="Character level",
    background="Background (e.g., Sage, Criminal)",
    backstory="Character backstory — as long as you want",
    abilities="Key abilities, feats, and spells",
    details="Anything else — personality traits, bonds, flaws, notable gear, etc.",
)
async def party_sheet(
    interaction: discord.Interaction,
    campaign_id: int,
    player: discord.Member,
    race: str = None,
    char_class: str = None,
    level: int = None,
    background: str = None,
    backstory: str = None,
    abilities: str = None,
    details: str = None,
):
    campaign = db.get_campaign(campaign_id)
    if not campaign:
        await interaction.response.send_message("Campaign not found.", ephemeral=True)
        return

    # Players can edit their own sheet; DM can edit anyone's
    is_dm = campaign["dm_user_id"] == interaction.user.id
    is_self = player.id == interaction.user.id
    if not is_dm and not is_self:
        await interaction.response.send_message(
            "You can only edit your own character sheet. The DM can edit anyone's.",
            ephemeral=True,
        )
        return

    db.update_character_sheet(
        campaign_id, player.id,
        race=race, char_class=char_class, level=level,
        background=background, backstory=backstory,
        abilities=abilities, details=details,
    )

    # Count what was updated
    updated = [k for k, v in {
        "race": race, "class": char_class, "level": level,
        "background": background, "backstory": backstory,
        "abilities": abilities, "details": details,
    }.items() if v is not None]

    await interaction.response.send_message(
        f"📝 Updated **{player.display_name}**'s character sheet: {', '.join(updated)}.\n"
        f"This info will now be included in `/forge` and `/lore` AI generations."
    )


@party_group.command(name="sheet_view", description="View a character's full sheet")
@app_commands.describe(campaign_id="Campaign ID", player="The player (defaults to yourself)")
async def party_sheet_view(
    interaction: discord.Interaction,
    player: discord.Member = None,
    campaign_id: int = None,
):
    campaign_id = await resolve_campaign_id(interaction, campaign_id)
    if campaign_id is None:
        return
    target = player or interaction.user
    sheet = db.get_character_sheet(campaign_id, target.id)
    if not sheet:
        await interaction.response.send_message(
            f"No character sheet found for {target.display_name} in this campaign.",
            ephemeral=True,
        )
        return

    campaign = db.get_campaign(campaign_id)
    char_name = sheet.get("character_name") or "Unnamed"

    embed = discord.Embed(
        title=f"📋 {char_name} — Character Sheet",
        description=f"Player: {target.mention} | Campaign: **{campaign['name']}**",
        color=0x7C3AED,
    )

    if sheet.get("race"):
        embed.add_field(name="Race", value=sheet["race"], inline=True)
    if sheet.get("char_class"):
        embed.add_field(name="Class", value=sheet["char_class"], inline=True)
    if sheet.get("level"):
        embed.add_field(name="Level", value=str(sheet["level"]), inline=True)
    if sheet.get("background"):
        embed.add_field(name="Background", value=sheet["background"], inline=True)
    if sheet.get("backstory"):
        embed.add_field(name="Backstory", value=sheet["backstory"][:1024], inline=False)
    if sheet.get("abilities"):
        embed.add_field(name="Abilities / Spells", value=sheet["abilities"][:1024], inline=False)
    if sheet.get("details"):
        embed.add_field(name="Additional Details", value=sheet["details"][:1024], inline=False)

    # Show inventory summary
    inventory = db.get_player_inventory(campaign_id, target.id)
    if inventory:
        inv_lines = []
        for item in inventory[:10]:
            emoji = RARITY_EMOJIS.get(item["rarity"], "⬜")
            eq = " 🔧" if item["equipped"] else ""
            qty = f" x{item['quantity']}" if item["quantity"] > 1 else ""
            inv_lines.append(f"{emoji} {item['name']}{qty}{eq}")
        if len(inventory) > 10:
            inv_lines.append(f"*...and {len(inventory) - 10} more*")
        embed.add_field(name="🎒 Inventory", value="\n".join(inv_lines), inline=False)

    # Check completeness
    fields = ["race", "char_class", "level", "background", "backstory", "abilities"]
    filled = sum(1 for f in fields if sheet.get(f))
    embed.set_footer(text=f"Sheet completeness: {filled}/{len(fields)} fields filled")

    await interaction.response.send_message(embed=embed)


@party_group.command(name="import_sheet", description="Import a character sheet from a D&D Beyond PDF (URL or attachment)")
@app_commands.describe(
    campaign_id="Campaign ID",
    player="Player to import the sheet for",
    url="D&D Beyond PDF URL (e.g., dndbeyond.com/sheet-pdfs/username_12345.pdf)",
    attachment="Or attach the PDF file directly",
)
async def party_import(
    interaction: discord.Interaction,
    campaign_id: int,
    player: discord.Member,
    url: str = None,
    attachment: discord.Attachment = None,
    backend: str = None,
):
    campaign = db.get_campaign(campaign_id)
    if not campaign:
        await interaction.response.send_message("Campaign not found.", ephemeral=True)
        return

    # Permission check — DM can import for anyone, players can import their own
    is_dm = campaign["dm_user_id"] == interaction.user.id
    is_self = player.id == interaction.user.id
    if not is_dm and not is_self:
        await interaction.response.send_message(
            "You can only import your own sheet. The DM can import for anyone.",
            ephemeral=True,
        )
        return

    if not url and not attachment:
        await interaction.response.send_message(
            "Provide either a `url` or attach a PDF file.\n"
            "Example URL: `https://www.dndbeyond.com/sheet-pdfs/username_12345.pdf`",
            ephemeral=True,
        )
        return

    # Rate limit check
    limit = claude_api.DM_RATE_LIMIT if is_dm else claude_api.PLAYER_RATE_LIMIT
    allowed, wait = claude_api.rate_limiter.check(interaction.user.id, limit)
    if not allowed:
        await interaction.response.send_message(
            f"⏳ Rate limit reached. Try again in ~{wait // 60} minutes.",
            ephemeral=True,
        )
        return

    await interaction.response.defer(thinking=True)

    try:
        # ── Step 1: Render PDF pages as images ──
        if url:
            page_images = await pdf_parser.pdf_to_images_from_url(url)
        else:
            if not attachment.filename.lower().endswith(".pdf"):
                await interaction.followup.send("Attachment must be a PDF file.", ephemeral=True)
                return
            pdf_bytes = await attachment.read()
            page_images = await pdf_parser.pdf_to_images_from_bytes(pdf_bytes)

        if not page_images:
            await interaction.followup.send(
                "Couldn't render the PDF. Make sure it's a valid D&D Beyond character sheet export.",
                ephemeral=True,
            )
            return

        # ── Step 2: Send images to vision API for parsing ──
        backend_choice = ai_backend.resolve_backend(campaign_id, backend)
        result = await ai_backend.parse_character_pdf(page_images, backend=backend_choice)
        claude_api.rate_limiter.record(interaction.user.id)

        # ── Step 3: Save to database ──
        char_name = result.get("character_name")
        if char_name:
            db.update_character_name(campaign_id, player.id, char_name)

        db.update_character_sheet(
            campaign_id, player.id,
            character_name=result.get("character_name"),
            race=result.get("race"),
            char_class=result.get("char_class"),
            level=result.get("level"),
            background=result.get("background"),
            backstory=result.get("backstory"),
            abilities=result.get("abilities"),
            details=result.get("details"),
        )

        # ── Step 4: Show confirmation ──
        embed = discord.Embed(
            title=f"📥 Sheet Imported — {result.get('character_name', 'Unknown')}",
            color=0x7C3AED,
        )
        if result.get("race"):
            embed.add_field(name="Race", value=result["race"], inline=True)
        if result.get("char_class"):
            embed.add_field(name="Class", value=result["char_class"], inline=True)
        if result.get("level"):
            embed.add_field(name="Level", value=str(result["level"]), inline=True)
        if result.get("background"):
            embed.add_field(name="Background", value=result["background"], inline=True)
        if result.get("backstory"):
            preview = result["backstory"][:300]
            if len(result["backstory"]) > 300:
                preview += "..."
            embed.add_field(name="Backstory", value=preview, inline=False)
        if result.get("abilities"):
            preview = result["abilities"][:300]
            if len(result["abilities"]) > 300:
                preview += "..."
            embed.add_field(name="Abilities", value=preview, inline=False)
        if result.get("details"):
            preview = result["details"][:300]
            if len(result["details"]) > 300:
                preview += "..."
            embed.add_field(name="Details", value=preview, inline=False)

        embed.set_footer(
            text=f"Imported for {player.display_name} • Campaign: {campaign['name']} • "
                 f"Use /party sheet_view to see the full sheet"
        )

        await interaction.followup.send(
            f"✅ **{result.get('character_name', 'Character')}** imported successfully!",
            embed=embed,
        )

    except json.JSONDecodeError:
        await interaction.followup.send(
            "Claude couldn't parse the sheet into a clean format — try again or enter manually with `/party sheet`.",
            ephemeral=True,
        )
    except ValueError as e:
        await interaction.followup.send(f"PDF error: {str(e)[:300]}", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(
            f"Import failed: `{str(e)[:300]}`\n\nYou can still enter the sheet manually with `/party sheet`.",
            ephemeral=True,
        )


bot.tree.add_command(party_group)


# ═════════════════════════════════════════════════════════════════════════════
#  SESSION COMMANDS
# ═════════════════════════════════════════════════════════════════════════════

session_group = app_commands.Group(name="session", description="Manage game sessions")


@session_group.command(name="create", description="Manually create an upcoming session")
@app_commands.describe(
    campaign_id="Campaign ID",
    date="Date and time (e.g., 2026-04-18 19:00)",
    title="Optional title for this session",
)
async def session_create(
    interaction: discord.Interaction, campaign_id: int, date: str, title: str = None
):
    campaign = db.get_campaign(campaign_id)
    if not campaign:
        await interaction.response.send_message("Campaign not found.", ephemeral=True)
        return

    try:
        tz = ZoneInfo(campaign["schedule_tz"] or "America/Denver")
        dt = datetime.strptime(date, "%Y-%m-%d %H:%M").replace(tzinfo=tz)
    except ValueError:
        await interaction.response.send_message(
            "Invalid date format. Use `YYYY-MM-DD HH:MM` (e.g., `2026-04-18 19:00`)",
            ephemeral=True,
        )
        return

    # Reject sessions in the past
    if dt < datetime.now(tz):
        await interaction.response.send_message(
            f"That date is in the past. Please choose a future date.",
            ephemeral=True,
        )
        return

    session_id = db.create_session(campaign_id, dt.isoformat(), title)
    unix_ts = int(dt.timestamp())

    await interaction.response.send_message(
        f"📅 **Session #{session_id} created!**\n"
        f"Campaign: **{campaign['name']}**\n"
        f"When: <t:{unix_ts}:F> (<t:{unix_ts}:R>)\n"
        f"{f'Title: **{title}**' if title else ''}\n\n"
        f"Use `/session ping {session_id}` to send the attendance check now."
    )


@session_group.command(name="list", description="Show upcoming sessions")
@app_commands.describe(campaign_id="Campaign ID")
async def session_list(interaction: discord.Interaction, campaign_id: int = None):
    campaign_id = await resolve_campaign_id(interaction, campaign_id)
    if campaign_id is None:
        return
    campaign = db.get_campaign(campaign_id)
    if not campaign:
        await interaction.response.send_message("Campaign not found.", ephemeral=True)
        return

    sessions = db.get_upcoming_sessions(campaign_id)
    if not sessions:
        await interaction.response.send_message("No upcoming sessions.")
        return

    embed = discord.Embed(title=f"📅 Upcoming — {campaign['name']}", color=0x7C3AED)
    for s in sessions:
        dt = datetime.fromisoformat(s["session_date"])
        unix_ts = int(dt.timestamp())
        rsvps = db.get_rsvps(s["id"])
        confirmed = sum(1 for r in rsvps if r["response"] == "yes")
        total = len(rsvps)
        title_text = s["title"] or f"Session #{s['id']}"

        ping_status = "📭 Not pinged"
        if s["ping_sent"]:
            ping_status = f"📬 Pinged (follow-ups: {s['reminders_sent']})"
        if s["final_reminder_sent"]:
            ping_status = "✅ All pings sent"

        embed.add_field(
            name=f"{title_text} (ID: {s['id']})",
            value=f"<t:{unix_ts}:F>\n✅ {confirmed}/{total} confirmed | {ping_status}",
            inline=False,
        )

    await interaction.response.send_message(embed=embed)


@session_group.command(name="ping", description="Manually ping for attendance (or re-ping non-responders)")
@app_commands.describe(session_id="Session ID")
async def session_ping(interaction: discord.Interaction, session_id: int):
    session = db.get_session(session_id)
    if not session:
        await interaction.response.send_message("Session not found.", ephemeral=True)
        return

    campaign = db.get_campaign(session["campaign_id"])
    if campaign["dm_user_id"] != interaction.user.id:
        await interaction.response.send_message(
            "Only the DM can manually ping for attendance.", ephemeral=True,
        )
        return

    rsvps = db.get_rsvps(session_id)
    pending = db.get_pending_rsvps(session_id)

    embed = build_rsvp_embed(session, rsvps, campaign["name"], interaction.client)
    view = RSVPView(session_id)

    if pending:
        mentions = " ".join(f"<@{r['user_id']}>" for r in pending)
        await interaction.response.send_message(
            f"🎲 **Roll call, adventurers!** 🎲\n{mentions}\n\n"
            f"Your presence is requested — respond below!",
            embed=embed,
            view=view,
        )
    else:
        await interaction.response.send_message(
            "Everyone has responded! Here's the current status:",
            embed=embed,
            view=view,
        )
    db.mark_ping_sent(session_id)


@session_group.command(name="status", description="Check RSVP status for a session")
@app_commands.describe(session_id="Session ID")
async def session_status(interaction: discord.Interaction, session_id: int):
    session = db.get_session(session_id)
    if not session:
        await interaction.response.send_message("Session not found.", ephemeral=True)
        return

    campaign = db.get_campaign(session["campaign_id"])
    rsvps = db.get_rsvps(session_id)
    embed = build_rsvp_embed(session, rsvps, campaign["name"], interaction.client)
    await interaction.response.send_message(embed=embed)


@session_group.command(name="cancel", description="Cancel a session")
@app_commands.describe(session_id="Session ID")
async def session_cancel(interaction: discord.Interaction, session_id: int):
    session = db.get_session(session_id)
    if not session:
        await interaction.response.send_message("Session not found.", ephemeral=True)
        return

    campaign = db.get_campaign(session["campaign_id"])
    if campaign["dm_user_id"] != interaction.user.id:
        await interaction.response.send_message("Only the DM can cancel sessions.", ephemeral=True)
        return

    db.update_session_status(session_id, "cancelled")
    players = db.get_players(session["campaign_id"])
    mentions = " ".join(f"<@{p['user_id']}>" for p in players)

    await interaction.response.send_message(
        f"🚫 **Session #{session_id} has been cancelled.**\n{mentions}\n"
        f"The quest is postponed, adventurers. Rest up!"
    )


@session_group.command(name="complete", description="Mark a session as completed and log attendance")
@app_commands.describe(session_id="Session ID")
async def session_complete(interaction: discord.Interaction, session_id: int):
    session = db.get_session(session_id)
    if not session:
        await interaction.response.send_message("Session not found.", ephemeral=True)
        return

    campaign = db.get_campaign(session["campaign_id"])
    if campaign["dm_user_id"] != interaction.user.id:
        await interaction.response.send_message("Only the DM can complete sessions.", ephemeral=True)
        return

    db.update_session_status(session_id, "completed")
    rsvps = db.get_rsvps(session_id)
    for r in rsvps:
        db.log_attendance(session_id, r["user_id"], r["response"] == "yes")

    await interaction.response.send_message(
        f"✅ **Session #{session_id} marked as complete!**\n"
        f"Attendance has been logged based on RSVPs. "
        f"Use `/party stats` to view attendance records."
    )


@session_group.command(name="clear", description="Delete all upcoming sessions and start fresh (DM only)")
@app_commands.describe(campaign_id="Campaign ID (auto-detected if only one)")
async def session_clear(interaction: discord.Interaction, campaign_id: int = None):
    campaign_id = await resolve_campaign_id(interaction, campaign_id)
    if campaign_id is None:
        return

    campaign = db.get_campaign(campaign_id)
    if not campaign:
        await interaction.response.send_message("Campaign not found.", ephemeral=True)
        return
    if campaign["dm_user_id"] != interaction.user.id:
        await interaction.response.send_message("Only the DM can clear sessions.", ephemeral=True)
        return

    count = db.clear_sessions(campaign_id)
    await interaction.response.send_message(
        f"🗑️ Cleared **{count} upcoming session{'s' if count != 1 else ''}** from **{campaign['name']}**.\n"
        f"The scheduler will create new ones based on your current schedule within 15 minutes."
    )


bot.tree.add_command(session_group)


# ═════════════════════════════════════════════════════════════════════════════
#  QUICK RSVP
# ═════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="rsvp", description="Quickly RSVP to a session")
@app_commands.describe(session_id="Session ID", response="Your response")
@app_commands.choices(response=[
    app_commands.Choice(name="✅ Yes — I'll be there!", value="yes"),
    app_commands.Choice(name="❌ No — Can't make it", value="no"),
    app_commands.Choice(name="❓ Tentative — Maybe", value="tentative"),
])
async def rsvp_command(interaction: discord.Interaction, session_id: int, response: str):
    session = db.get_session(session_id)
    if not session:
        await interaction.response.send_message("Session not found.", ephemeral=True)
        return

    db.set_rsvp(session_id, interaction.user.id, response)
    labels = {"yes": "attending ⚔️", "no": "not attending 🛡️", "tentative": "tentative ❓"}
    await interaction.response.send_message(
        f"Got it — you're marked as **{labels[response]}** for session #{session_id}.",
        ephemeral=True,
    )


# ═════════════════════════════════════════════════════════════════════════════
#  HOMEBREW ITEM COMMANDS
# ═════════════════════════════════════════════════════════════════════════════

RARITY_EMOJIS = {
    "common": "⬜", "uncommon": "🟢", "rare": "🔵",
    "very rare": "🟣", "legendary": "🟠", "artifact": "🟡",
}

item_group = app_commands.Group(name="item", description="Manage homebrew items")


@item_group.command(name="create", description="Create a new homebrew item")
@app_commands.describe(
    campaign_id="Campaign ID",
    name="Item name",
    description="Item description / lore",
    rarity="Item rarity",
    item_type="Item type (weapon, armor, potion, wondrous item, etc.)",
)
@app_commands.choices(rarity=[
    app_commands.Choice(name=r.title(), value=r)
    for r in ["common", "uncommon", "rare", "very rare", "legendary", "artifact"]
])
async def item_create(
    interaction: discord.Interaction,
    campaign_id: int,
    name: str,
    description: str = "",
    rarity: str = "common",
    item_type: str = "wondrous item",
):
    campaign = db.get_campaign(campaign_id)
    if not campaign:
        await interaction.response.send_message("Campaign not found.", ephemeral=True)
        return
    if campaign["dm_user_id"] != interaction.user.id:
        await interaction.response.send_message("Only the DM can create items.", ephemeral=True)
        return

    item_id = db.create_item(campaign_id, name, interaction.user.id, description, rarity, item_type)
    emoji = RARITY_EMOJIS.get(rarity, "⬜")

    embed = discord.Embed(
        title=f"{emoji} {name}",
        description=description or "*No description yet*",
        color={"common": 0x9D9D9D, "uncommon": 0x1EFF00, "rare": 0x0070DD,
               "very rare": 0xA335EE, "legendary": 0xFF8000, "artifact": 0xE6CC80}.get(rarity, 0x9D9D9D),
    )
    embed.add_field(name="Type", value=item_type.title(), inline=True)
    embed.add_field(name="Rarity", value=rarity.title(), inline=True)
    embed.add_field(name="Item ID", value=str(item_id), inline=True)
    embed.set_footer(text=f"Campaign: {campaign['name']}")

    await interaction.response.send_message(f"✨ **New item created!**", embed=embed)


@item_group.command(name="list", description="List all homebrew items in a campaign")
@app_commands.describe(campaign_id="Campaign ID")
async def item_list(interaction: discord.Interaction, campaign_id: int = None):
    campaign_id = await resolve_campaign_id(interaction, campaign_id)
    if campaign_id is None:
        return
    campaign = db.get_campaign(campaign_id)
    if not campaign:
        await interaction.response.send_message("Campaign not found.", ephemeral=True)
        return

    items = db.get_items(campaign_id)
    if not items:
        await interaction.response.send_message("No items yet. Create some with `/item create`!")
        return

    embed = discord.Embed(title=f"🎒 Item Compendium — {campaign['name']}", color=0x7C3AED)
    for item in items[:25]:  # Discord embed field limit
        emoji = RARITY_EMOJIS.get(item["rarity"], "⬜")
        holders = db.get_item_holders(campaign_id, item["id"])
        holder_text = ", ".join(
            f"<@{h['user_id']}> (x{h['quantity']})" for h in holders
        ) if holders else "Unclaimed"

        desc_preview = (item["description"][:80] + "...") if len(item["description"]) > 80 else item["description"]
        embed.add_field(
            name=f"{emoji} {item['name']} (ID: {item['id']})",
            value=f"*{item['rarity'].title()} {item['item_type'].title()}*\n"
                  f"{desc_preview or 'No description'}\n"
                  f"Held by: {holder_text}",
            inline=False,
        )

    await interaction.response.send_message(embed=embed)


@item_group.command(name="inspect", description="View full details of an item")
@app_commands.describe(item_id="Item ID")
async def item_inspect(interaction: discord.Interaction, item_id: int):
    item = db.get_item(item_id)
    if not item:
        await interaction.response.send_message("Item not found.", ephemeral=True)
        return

    campaign = db.get_campaign(item["campaign_id"])
    emoji = RARITY_EMOJIS.get(item["rarity"], "⬜")

    embed = discord.Embed(
        title=f"{emoji} {item['name']}",
        description=item["description"] or "*No description*",
        color={"common": 0x9D9D9D, "uncommon": 0x1EFF00, "rare": 0x0070DD,
               "very rare": 0xA335EE, "legendary": 0xFF8000, "artifact": 0xE6CC80}.get(item["rarity"], 0x9D9D9D),
    )
    embed.add_field(name="Type", value=item["item_type"].title(), inline=True)
    embed.add_field(name="Rarity", value=item["rarity"].title(), inline=True)
    embed.add_field(name="Item ID", value=str(item["id"]), inline=True)

    if item["properties"]:
        props = "\n".join(f"**{k}:** {v}" for k, v in item["properties"].items())
        embed.add_field(name="Properties", value=props, inline=False)

    holders = db.get_item_holders(item["campaign_id"], item["id"])
    if holders:
        holder_lines = []
        for h in holders:
            char = f" ({h['character_name']})" if h.get("character_name") else ""
            equipped = " 🔧" if h.get("equipped") else ""
            holder_lines.append(f"<@{h['user_id']}>{char} — x{h['quantity']}{equipped}")
        embed.add_field(name="Held By", value="\n".join(holder_lines), inline=False)

    embed.set_footer(text=f"Campaign: {campaign['name']} | Created: {item['created_at']}")
    await interaction.response.send_message(embed=embed)


@item_group.command(name="edit", description="Edit an existing item (DM only)")
@app_commands.describe(
    item_id="Item ID",
    name="New name (leave empty to keep)",
    description="New description (leave empty to keep)",
    rarity="New rarity (leave empty to keep)",
    item_type="New type (leave empty to keep)",
)
@app_commands.choices(rarity=[
    app_commands.Choice(name=r.title(), value=r)
    for r in ["common", "uncommon", "rare", "very rare", "legendary", "artifact"]
])
async def item_edit(
    interaction: discord.Interaction,
    item_id: int,
    name: str = None,
    description: str = None,
    rarity: str = None,
    item_type: str = None,
):
    item = db.get_item(item_id)
    if not item:
        await interaction.response.send_message("Item not found.", ephemeral=True)
        return

    campaign = db.get_campaign(item["campaign_id"])
    if campaign["dm_user_id"] != interaction.user.id:
        await interaction.response.send_message("Only the DM can edit items.", ephemeral=True)
        return

    kwargs = {}
    if name is not None:
        kwargs["name"] = name
    if description is not None:
        kwargs["description"] = description
    if rarity is not None:
        kwargs["rarity"] = rarity
    if item_type is not None:
        kwargs["item_type"] = item_type

    if kwargs:
        db.update_item(item_id, **kwargs)

    await interaction.response.send_message(f"✏️ **{item['name']}** has been updated.")


@item_group.command(name="delete", description="Delete an item (DM only)")
@app_commands.describe(item_id="Item ID")
async def item_delete(interaction: discord.Interaction, item_id: int):
    item = db.get_item(item_id)
    if not item:
        await interaction.response.send_message("Item not found.", ephemeral=True)
        return

    campaign = db.get_campaign(item["campaign_id"])
    if campaign["dm_user_id"] != interaction.user.id:
        await interaction.response.send_message("Only the DM can delete items.", ephemeral=True)
        return

    db.delete_item(item_id)
    await interaction.response.send_message(f"🗑️ **{item['name']}** has been destroyed.")


@item_group.command(name="search", description="Search for items by name")
@app_commands.describe(campaign_id="Campaign ID", query="Search term (partial name match)")
async def item_search(interaction: discord.Interaction, campaign_id: int, query: str):
    campaign = db.get_campaign(campaign_id)
    if not campaign:
        await interaction.response.send_message("Campaign not found.", ephemeral=True)
        return

    results = db.search_items(campaign_id, query)
    if not results:
        await interaction.response.send_message(
            f"No items matching **\"{query}\"** in {campaign['name']}.",
            ephemeral=True,
        )
        return

    embed = discord.Embed(
        title=f"🔍 Search: \"{query}\" — {len(results)} found",
        color=0x7C3AED,
    )
    for item in results[:15]:
        emoji = RARITY_EMOJIS.get(item["rarity"], "⬜")
        holders = db.get_item_holders(campaign_id, item["id"])
        holder_text = ", ".join(
            f"<@{h['user_id']}>" for h in holders
        ) if holders else "Unclaimed"

        desc_preview = (item["description"][:80] + "...") if len(item["description"]) > 80 else item["description"]
        embed.add_field(
            name=f"{emoji} {item['name']} (ID: {item['id']})",
            value=f"*{item['rarity'].title()} {item['item_type'].title()}*\n"
                  f"{desc_preview or 'No description'}\n"
                  f"Held by: {holder_text}",
            inline=False,
        )

    if len(results) > 15:
        embed.set_footer(text=f"Showing 15 of {len(results)} results. Try a more specific query.")

    await interaction.response.send_message(embed=embed)


bot.tree.add_command(item_group)


# ═════════════════════════════════════════════════════════════════════════════
#  INVENTORY COMMANDS
# ═════════════════════════════════════════════════════════════════════════════

inv_group = app_commands.Group(name="inventory", description="Manage player inventories")


@inv_group.command(name="give", description="Give an item to a player (DM only)")
@app_commands.describe(
    campaign_id="Campaign ID",
    player="Player to receive the item",
    item_id="Item ID",
    quantity="How many (default: 1)",
)
async def inv_give(
    interaction: discord.Interaction,
    campaign_id: int,
    player: discord.Member,
    item_id: int,
    quantity: int = 1,
):
    campaign = db.get_campaign(campaign_id)
    if not campaign:
        await interaction.response.send_message("Campaign not found.", ephemeral=True)
        return
    if campaign["dm_user_id"] != interaction.user.id:
        await interaction.response.send_message("Only the DM can distribute items.", ephemeral=True)
        return

    item = db.get_item(item_id)
    if not item:
        await interaction.response.send_message("Item not found.", ephemeral=True)
        return

    db.give_item(campaign_id, player.id, item_id, quantity)
    emoji = RARITY_EMOJIS.get(item["rarity"], "⬜")
    qty_text = f" x{quantity}" if quantity > 1 else ""
    await interaction.response.send_message(
        f"{emoji} {player.mention} received **{item['name']}{qty_text}**!"
    )


@inv_group.command(name="remove", description="Remove an item from a player (DM only)")
@app_commands.describe(
    campaign_id="Campaign ID",
    player="Player to remove item from",
    item_id="Item ID",
    quantity="How many to remove (default: 1)",
)
async def inv_remove(
    interaction: discord.Interaction,
    campaign_id: int,
    player: discord.Member,
    item_id: int,
    quantity: int = 1,
):
    campaign = db.get_campaign(campaign_id)
    if not campaign:
        await interaction.response.send_message("Campaign not found.", ephemeral=True)
        return
    if campaign["dm_user_id"] != interaction.user.id:
        await interaction.response.send_message("Only the DM can remove items.", ephemeral=True)
        return

    item = db.get_item(item_id)
    if not item:
        await interaction.response.send_message("Item not found.", ephemeral=True)
        return

    db.remove_item_from_player(campaign_id, player.id, item_id, quantity)
    await interaction.response.send_message(f"📤 Removed **{item['name']}** x{quantity} from {player.mention}.")


@inv_group.command(name="transfer", description="Transfer an item to another player")
@app_commands.describe(
    campaign_id="Campaign ID",
    to_player="Player to give the item to",
    item_id="Item ID",
    quantity="How many (default: 1)",
)
async def inv_transfer(
    interaction: discord.Interaction,
    campaign_id: int,
    to_player: discord.Member,
    item_id: int,
    quantity: int = 1,
):
    item = db.get_item(item_id)
    if not item:
        await interaction.response.send_message("Item not found.", ephemeral=True)
        return

    success = db.transfer_item(campaign_id, interaction.user.id, to_player.id, item_id, quantity)
    if not success:
        await interaction.response.send_message(
            f"You don't have enough **{item['name']}** to transfer.", ephemeral=True
        )
        return

    qty_text = f" x{quantity}" if quantity > 1 else ""
    await interaction.response.send_message(
        f"🤝 {interaction.user.mention} gave **{item['name']}{qty_text}** to {to_player.mention}."
    )


@inv_group.command(name="show", description="View a player's inventory")
@app_commands.describe(campaign_id="Campaign ID", player="Player (defaults to yourself)")
async def inv_show(
    interaction: discord.Interaction,
    player: discord.Member = None,
    campaign_id: int = None,
):
    campaign_id = await resolve_campaign_id(interaction, campaign_id)
    if campaign_id is None:
        return
    target = player or interaction.user
    campaign = db.get_campaign(campaign_id)
    if not campaign:
        await interaction.response.send_message("Campaign not found.", ephemeral=True)
        return

    inventory = db.get_player_inventory(campaign_id, target.id)
    if not inventory:
        await interaction.response.send_message(
            f"{'Your' if target == interaction.user else target.display_name + chr(39) + 's'} inventory is empty."
        )
        return

    embed = discord.Embed(
        title=f"🎒 {target.display_name}'s Inventory",
        description=f"Campaign: **{campaign['name']}**",
        color=0x7C3AED,
    )

    for item in inventory:
        emoji = RARITY_EMOJIS.get(item["rarity"], "⬜")
        equipped = " 🔧 *equipped*" if item["equipped"] else ""
        qty = f" x{item['quantity']}" if item["quantity"] > 1 else ""
        desc_preview = (item["description"][:60] + "...") if len(item["description"]) > 60 else item["description"]

        embed.add_field(
            name=f"{emoji} {item['name']}{qty}{equipped}",
            value=f"*{item['rarity'].title()} {item['item_type'].title()}* (ID: {item['item_id']})\n"
                  f"{desc_preview or 'No description'}",
            inline=False,
        )

    await interaction.response.send_message(embed=embed)


@inv_group.command(name="equip", description="Toggle equip/unequip an item")
@app_commands.describe(campaign_id="Campaign ID", item_id="Item ID")
async def inv_equip(interaction: discord.Interaction, campaign_id: int, item_id: int):
    item = db.get_item(item_id)
    if not item:
        await interaction.response.send_message("Item not found.", ephemeral=True)
        return

    now_equipped = db.toggle_equipped(campaign_id, interaction.user.id, item_id)
    status = "equipped 🔧" if now_equipped else "unequipped"
    await interaction.response.send_message(
        f"**{item['name']}** is now **{status}**.", ephemeral=True
    )


bot.tree.add_command(inv_group)


# ═════════════════════════════════════════════════════════════════════════════
#  TRANSLATION COMMANDS
# ═════════════════════════════════════════════════════════════════════════════

translate_group = app_commands.Group(name="translate", description="Translate between D&D languages")

LANGUAGE_CHOICES = [
    app_commands.Choice(name=lang.title(), value=lang)
    for lang in get_languages()
]


@translate_group.command(name="to", description="Translate Common text into another language")
@app_commands.describe(language="Target language", text="Text to translate")
@app_commands.choices(language=LANGUAGE_CHOICES)
async def translate_to_cmd(interaction: discord.Interaction, language: str, text: str):
    result = translate_to(text, language)
    embed = discord.Embed(
        title=f"🌐 Common → {language.title()}",
        color=0x7C3AED,
    )
    embed.add_field(name="Original (Common)", value=text, inline=False)
    embed.add_field(name=f"Translated ({language.title()})", value=result, inline=False)
    await interaction.response.send_message(embed=embed)


@translate_group.command(name="from", description="Translate text from another language back to Common")
@app_commands.describe(language="Source language", text="Text to translate")
@app_commands.choices(language=LANGUAGE_CHOICES)
async def translate_from_cmd(interaction: discord.Interaction, language: str, text: str):
    result = translate_from(text, language)
    embed = discord.Embed(
        title=f"🌐 {language.title()} → Common",
        color=0x7C3AED,
    )
    embed.add_field(name=f"Original ({language.title()})", value=text, inline=False)
    embed.add_field(name="Translated (Common)", value=result, inline=False)
    await interaction.response.send_message(embed=embed)


@translate_group.command(name="between", description="Translate between any two D&D languages")
@app_commands.describe(from_lang="Source language", to_lang="Target language", text="Text to translate")
@app_commands.choices(from_lang=LANGUAGE_CHOICES, to_lang=LANGUAGE_CHOICES)
async def translate_between_cmd(
    interaction: discord.Interaction, from_lang: str, to_lang: str, text: str
):
    result = translate(text, from_lang, to_lang)
    embed = discord.Embed(
        title=f"🌐 {from_lang.title()} → {to_lang.title()}",
        color=0x7C3AED,
    )
    embed.add_field(name=f"Original ({from_lang.title()})", value=text, inline=False)
    embed.add_field(name=f"Translated ({to_lang.title()})", value=result, inline=False)
    await interaction.response.send_message(embed=embed)


@translate_group.command(name="languages", description="List all available D&D languages")
async def translate_languages_cmd(interaction: discord.Interaction):
    standard = ["Common", "Dwarvish", "Elvish", "Giant", "Gnomish", "Goblin", "Halfling", "Orc"]
    exotic = ["Abyssal", "Celestial", "Draconic", "Deep Speech", "Infernal", "Primordial",
              "Sylvan", "Undercommon"]
    secret = ["Druidic", "Thieves' Cant"]

    embed = discord.Embed(title="🌐 Available Languages", color=0x7C3AED)
    embed.add_field(name="Standard Languages", value="\n".join(standard), inline=True)
    embed.add_field(name="Exotic Languages", value="\n".join(exotic), inline=True)
    embed.add_field(name="Secret Languages", value="\n".join(secret), inline=True)
    embed.set_footer(text="Use /translate to Common, /translate from, or /translate between")

    await interaction.response.send_message(embed=embed)


bot.tree.add_command(translate_group)


# ═════════════════════════════════════════════════════════════════════════════
#  AI D&D KNOWLEDGE ASSISTANT (Claude API)
# ═════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="ask", description="Ask a D&D 5e rules question, look up items, spells, monsters, etc.")
@app_commands.describe(
    question="Your question (rules, spells, items, monsters, mechanics, lore, etc.)",
    campaign_id="Optional campaign ID — includes your party context for tailored answers",
)
async def ask_command(interaction: discord.Interaction, question: str, campaign_id: int = None, backend: str = None):
    # Auto-detect campaign if only one exists and none specified
    if campaign_id is None:
        if interaction.guild_id:
            campaigns = db.get_campaigns_for_guild(interaction.guild_id)
        else:
            campaigns = db.get_campaigns_for_user(interaction.user.id)
        if len(campaigns) == 1:
            campaign_id = campaigns[0]["id"]

    # Rate limit check — use campaign if resolved, otherwise just check player limit
    if campaign_id:
        campaign = db.get_campaign(campaign_id)
        if not campaign:
            await interaction.response.send_message("Campaign not found.", ephemeral=True)
            return
        is_dm = campaign["dm_user_id"] == interaction.user.id
    else:
        is_dm = False

    limit = claude_api.DM_RATE_LIMIT if is_dm else claude_api.PLAYER_RATE_LIMIT
    allowed, wait = claude_api.rate_limiter.check(interaction.user.id, limit)
    if not allowed:
        await interaction.response.send_message(
            f"⏳ Rate limit reached. Try again in ~{wait // 60} minutes.",
            ephemeral=True,
        )
        return

    await interaction.response.defer(thinking=True)

    try:
        campaign_ctx = db.build_ai_context(campaign_id) if campaign_id else ""
        backend_choice = ai_backend.resolve_backend(campaign_id, backend)
        answer = await ai_backend.ask_dnd(question, campaign_ctx, backend=backend_choice)
        claude_api.rate_limiter.record(interaction.user.id)

        embed = discord.Embed(
            title="📖 D&D 5e — Rules & Knowledge",
            color=0x7C3AED,
        )
        embed.add_field(name="Question", value=question[:1024], inline=False)

        # Split answer across fields if it's long (embed field limit is 1024)
        if len(answer) <= 1024:
            embed.add_field(name="Answer", value=answer, inline=False)
        else:
            # Split into chunks at sentence boundaries
            chunks = []
            current = ""
            for sentence in answer.replace("\n\n", "\n\n|SPLIT|").split("|SPLIT|"):
                if len(current) + len(sentence) > 1000:
                    if current:
                        chunks.append(current.strip())
                    current = sentence
                else:
                    current += sentence
            if current:
                chunks.append(current.strip())

            for i, chunk in enumerate(chunks[:4]):  # Max 4 chunks
                label = "Answer" if i == 0 else "​"  # Zero-width space for continuation
                embed.add_field(name=label, value=chunk[:1024], inline=False)

        remaining = claude_api.rate_limiter.remaining(interaction.user.id, limit)
        footer = f"{remaining} AI requests remaining this hour"
        if campaign_id:
            footer = f"Campaign-aware • {footer}"
        embed.set_footer(text=footer)

        await interaction.followup.send(embed=embed)

    except Exception as e:
        await interaction.followup.send(
            f"The sage's tome is unresponsive: `{str(e)[:200]}`",
            ephemeral=True,
        )


# ═════════════════════════════════════════════════════════════════════════════
#  AI FORGE COMMANDS (Claude API)
# ═════════════════════════════════════════════════════════════════════════════

forge_group = app_commands.Group(name="forge", description="AI-powered homebrew item creation")


async def _check_ai_rate_limit(interaction: discord.Interaction, campaign_id: int) -> bool:
    """Check rate limits — DMs get higher limits. Returns True if allowed."""
    campaign = db.get_campaign(campaign_id)
    if not campaign:
        await interaction.response.send_message("Campaign not found.", ephemeral=True)
        return False

    is_dm = campaign["dm_user_id"] == interaction.user.id
    limit = claude_api.DM_RATE_LIMIT if is_dm else claude_api.PLAYER_RATE_LIMIT

    allowed, wait = claude_api.rate_limiter.check(interaction.user.id, limit)
    if not allowed:
        remaining_min = wait // 60
        await interaction.response.send_message(
            f"⏳ Rate limit reached. You can use AI features again in ~{remaining_min} minutes.\n"
            f"{'DM limit' if is_dm else 'Player limit'}: {limit} requests/hour.",
            ephemeral=True,
        )
        return False
    return True


@forge_group.command(name="item", description="AI-generate a complete homebrew item")
@app_commands.describe(
    campaign_id="Campaign ID to add the item to",
    name="Item name or concept (e.g., 'Frostbite Dagger', 'a cursed crown')",
    rarity="Item rarity",
    item_type="Item type",
    context="Extra context for generation (setting, campaign theme, intended recipient, etc.)",
)
@app_commands.choices(rarity=[
    app_commands.Choice(name=r.title(), value=r)
    for r in ["common", "uncommon", "rare", "very rare", "legendary", "artifact"]
])
async def forge_item(
    interaction: discord.Interaction,
    name: str,
    rarity: str = "common",
    item_type: str = "wondrous item",
    context: str = "",
    campaign_id: int = None,
    backend: str = None,
):
    campaign_id = await resolve_campaign_id(interaction, campaign_id)
    if campaign_id is None:
        return
    if not await _check_ai_rate_limit(interaction, campaign_id):
        return

    await interaction.response.defer(thinking=True)

    try:
        campaign_ctx = db.build_ai_context(campaign_id)
        backend_choice = ai_backend.resolve_backend(campaign_id, backend)
        result = await ai_backend.forge_item(name, rarity, item_type, context, campaign_ctx, backend=backend_choice)
        claude_api.rate_limiter.record(interaction.user.id)

        # Save to database
        item_name = result.get("name", name)
        description = result.get("description", "")
        properties = result.get("properties", {})
        final_rarity = result.get("rarity", rarity)
        final_type = result.get("item_type", item_type)

        item_id = db.create_item(
            campaign_id, item_name, interaction.user.id,
            description, final_rarity, final_type, properties,
        )

        # Build embed
        emoji = RARITY_EMOJIS.get(final_rarity, "⬜")
        color = {"common": 0x9D9D9D, "uncommon": 0x1EFF00, "rare": 0x0070DD,
                 "very rare": 0xA335EE, "legendary": 0xFF8000, "artifact": 0xE6CC80}.get(final_rarity, 0x9D9D9D)

        embed = discord.Embed(
            title=f"{emoji} {item_name}",
            description=description[:4000],
            color=color,
        )
        embed.add_field(name="Type", value=final_type.title(), inline=True)
        embed.add_field(name="Rarity", value=final_rarity.title(), inline=True)
        embed.add_field(name="Item ID", value=str(item_id), inline=True)

        if properties:
            # Show relevant properties
            for key, value in properties.items():
                if value:
                    embed.add_field(
                        name=key.replace("_", " ").title(),
                        value=str(value)[:1024],
                        inline=True,
                    )

        campaign = db.get_campaign(campaign_id)
        remaining = claude_api.rate_limiter.remaining(
            interaction.user.id,
            claude_api.DM_RATE_LIMIT if campaign["dm_user_id"] == interaction.user.id else claude_api.PLAYER_RATE_LIMIT,
        )
        embed.set_footer(text=f"AI-generated • Campaign: {campaign['name']} • {remaining} AI requests remaining this hour")

        await interaction.followup.send(
            f"✨ **Item forged!** Added to the compendium as ID `{item_id}`.",
            embed=embed,
        )

    except json.JSONDecodeError:
        await interaction.followup.send(
            "The arcane forge misfired — Claude returned an unexpected format. Try again!",
            ephemeral=True,
        )
    except Exception as e:
        await interaction.followup.send(
            f"The forge encountered an error: `{str(e)[:200]}`",
            ephemeral=True,
        )


@forge_group.command(name="enhance", description="AI-enhance an existing item with richer lore and properties")
@app_commands.describe(
    item_id="Item ID to enhance",
    context="Extra context (e.g., 'this was found in a dragon's hoard', 'make it more sinister')",
)
async def forge_enhance(interaction: discord.Interaction, item_id: int, context: str = "", backend: str = None):
    item = db.get_item(item_id)
    if not item:
        await interaction.response.send_message("Item not found.", ephemeral=True)
        return

    if not await _check_ai_rate_limit(interaction, item["campaign_id"]):
        return

    await interaction.response.defer(thinking=True)

    try:
        campaign_ctx = db.build_ai_context(item["campaign_id"])
        backend_choice = ai_backend.resolve_backend(item["campaign_id"], backend)
        result = await ai_backend.enhance_item(
            item["name"], item["rarity"], item["item_type"],
            item["description"], item["properties"], context, campaign_ctx,
            backend=backend_choice,
        )
        claude_api.rate_limiter.record(interaction.user.id)

        # Update the item in the database
        new_desc = result.get("description", item["description"])
        new_props = result.get("properties", item["properties"])

        # Merge properties (keep old ones not in new, add new ones)
        merged_props = {**item["properties"], **new_props}
        # Remove empty values
        merged_props = {k: v for k, v in merged_props.items() if v}

        db.update_item(item_id, description=new_desc, properties=merged_props)

        # Build embed
        emoji = RARITY_EMOJIS.get(item["rarity"], "⬜")
        color = {"common": 0x9D9D9D, "uncommon": 0x1EFF00, "rare": 0x0070DD,
                 "very rare": 0xA335EE, "legendary": 0xFF8000, "artifact": 0xE6CC80}.get(item["rarity"], 0x9D9D9D)

        embed = discord.Embed(
            title=f"{emoji} {item['name']} — Enhanced",
            description=new_desc[:4000],
            color=color,
        )

        for key, value in merged_props.items():
            if value:
                embed.add_field(
                    name=key.replace("_", " ").title(),
                    value=str(value)[:1024],
                    inline=True,
                )

        embed.set_footer(text=f"AI-enhanced • Item ID: {item_id}")

        await interaction.followup.send(
            f"🔥 **{item['name']}** has been enhanced!", embed=embed
        )

    except json.JSONDecodeError:
        await interaction.followup.send(
            "The enhancement ritual fizzled — try again!", ephemeral=True
        )
    except Exception as e:
        await interaction.followup.send(
            f"Enhancement error: `{str(e)[:200]}`", ephemeral=True
        )


bot.tree.add_command(forge_group)


# ═════════════════════════════════════════════════════════════════════════════
#  AI LORE BUILDER COMMANDS (Claude API)
# ═════════════════════════════════════════════════════════════════════════════

lore_group = app_commands.Group(name="lore", description="AI-powered world-building and lore generation")


@lore_group.command(name="location", description="AI-generate a location with atmosphere, NPCs, and hooks")
@app_commands.describe(
    campaign_id="Campaign ID",
    name="Location name or concept (e.g., 'The Drowned Lantern', 'a cursed swamp village')",
    context="Setting details, campaign theme, or nearby landmarks",
)
async def lore_location(interaction: discord.Interaction, name: str, context: str = "", campaign_id: int = None, backend: str = None):
    campaign_id = await resolve_campaign_id(interaction, campaign_id)
    if campaign_id is None:
        return
    if not await _check_ai_rate_limit(interaction, campaign_id):
        return

    await interaction.response.defer(thinking=True)

    try:
        campaign_ctx = db.build_ai_context(campaign_id)
        backend_choice = ai_backend.resolve_backend(campaign_id, backend)
        result = await ai_backend.generate_lore("location", name, context, campaign_ctx, backend=backend_choice)
        claude_api.rate_limiter.record(interaction.user.id)

        embed = discord.Embed(
            title=f"🗺️ {result.get('name', name)}",
            description=result.get("description", "")[:4000],
            color=0x2D5016,
        )
        if result.get("type"):
            embed.add_field(name="Type", value=result["type"].title(), inline=True)
        if result.get("mood"):
            embed.add_field(name="Atmosphere", value=result["mood"], inline=True)
        if result.get("notable_features"):
            embed.add_field(
                name="Notable Features",
                value="\n".join(f"• {f}" for f in result["notable_features"]),
                inline=False,
            )
        if result.get("npcs"):
            embed.add_field(
                name="NPCs Found Here",
                value="\n".join(f"• {n}" for n in result["npcs"]),
                inline=False,
            )
        if result.get("hooks"):
            embed.add_field(
                name="🎣 Adventure Hooks",
                value="\n".join(f"• {h}" for h in result["hooks"]),
                inline=False,
            )
        if result.get("secret"):
            embed.add_field(name="🔒 Secret (DM Eyes Only)", value=f"||{result['secret']}||", inline=False)

        campaign = db.get_campaign(campaign_id)
        embed.set_footer(text=f"AI-generated • Campaign: {campaign['name']}")

        await interaction.followup.send(embed=embed)

    except Exception as e:
        await interaction.followup.send(f"Lore generation failed: `{str(e)[:200]}`", ephemeral=True)


@lore_group.command(name="faction", description="AI-generate a faction with goals, methods, and tensions")
@app_commands.describe(
    campaign_id="Campaign ID",
    name="Faction name or concept (e.g., 'The Ashen Compact', 'a thieves guild run by a lich')",
    context="Setting details, political landscape, or rival factions",
)
async def lore_faction(interaction: discord.Interaction, name: str, context: str = "", campaign_id: int = None, backend: str = None):
    campaign_id = await resolve_campaign_id(interaction, campaign_id)
    if campaign_id is None:
        return
    if not await _check_ai_rate_limit(interaction, campaign_id):
        return

    await interaction.response.defer(thinking=True)

    try:
        campaign_ctx = db.build_ai_context(campaign_id)
        backend_choice = ai_backend.resolve_backend(campaign_id, backend)
        result = await ai_backend.generate_lore("faction", name, context, campaign_ctx, backend=backend_choice)
        claude_api.rate_limiter.record(interaction.user.id)

        embed = discord.Embed(
            title=f"⚜️ {result.get('name', name)}",
            description=result.get("description", "")[:4000],
            color=0x8B0000,
        )
        if result.get("type"):
            embed.add_field(name="Type", value=result["type"].title(), inline=True)
        if result.get("leader"):
            embed.add_field(name="Leader", value=result["leader"], inline=True)
        if result.get("symbol"):
            embed.add_field(name="Symbol", value=result["symbol"], inline=True)
        if result.get("motto"):
            embed.add_field(name="Motto", value=f"*\"{result['motto']}\"*", inline=False)
        if result.get("goals"):
            embed.add_field(
                name="Goals",
                value="\n".join(f"• {g}" for g in result["goals"]),
                inline=False,
            )
        if result.get("methods"):
            embed.add_field(name="Methods", value=result["methods"], inline=False)
        if result.get("allies"):
            embed.add_field(name="Allies", value=result["allies"], inline=True)
        if result.get("enemies"):
            embed.add_field(name="Enemies", value=result["enemies"], inline=True)
        if result.get("tension"):
            embed.add_field(name="🔒 Internal Tension", value=f"||{result['tension']}||", inline=False)

        campaign = db.get_campaign(campaign_id)
        embed.set_footer(text=f"AI-generated • Campaign: {campaign['name']}")

        await interaction.followup.send(embed=embed)

    except Exception as e:
        await interaction.followup.send(f"Lore generation failed: `{str(e)[:200]}`", ephemeral=True)


@lore_group.command(name="npc", description="AI-generate an NPC with personality, secrets, and hooks")
@app_commands.describe(
    campaign_id="Campaign ID",
    name="NPC name or concept (e.g., 'Morwen the Blind', 'a paranoid alchemist')",
    context="Setting details, role in story, or relationship to party",
)
async def lore_npc(interaction: discord.Interaction, name: str, context: str = "", campaign_id: int = None, backend: str = None):
    campaign_id = await resolve_campaign_id(interaction, campaign_id)
    if campaign_id is None:
        return
    if not await _check_ai_rate_limit(interaction, campaign_id):
        return

    await interaction.response.defer(thinking=True)

    try:
        campaign_ctx = db.build_ai_context(campaign_id)
        backend_choice = ai_backend.resolve_backend(campaign_id, backend)
        result = await ai_backend.generate_lore("npc", name, context, campaign_ctx, backend=backend_choice)
        claude_api.rate_limiter.record(interaction.user.id)

        embed = discord.Embed(
            title=f"👤 {result.get('name', name)}",
            description=result.get("description", "")[:4000],
            color=0xDAA520,
        )
        if result.get("race"):
            embed.add_field(name="Race", value=result["race"], inline=True)
        if result.get("class"):
            embed.add_field(name="Class/Role", value=result["class"], inline=True)
        if result.get("stat_block"):
            embed.add_field(name="Stat Block", value=result["stat_block"], inline=True)
        if result.get("personality"):
            embed.add_field(
                name="Personality",
                value="\n".join(f"• {t}" for t in result["personality"]),
                inline=False,
            )
        if result.get("motivation"):
            embed.add_field(name="Motivation", value=result["motivation"], inline=True)
        if result.get("flaw"):
            embed.add_field(name="Flaw", value=result["flaw"], inline=True)
        if result.get("voice"):
            embed.add_field(name="🎭 Voice Notes", value=result["voice"], inline=False)
        if result.get("connection_hooks"):
            embed.add_field(
                name="🎣 Party Connections",
                value="\n".join(f"• {h}" for h in result["connection_hooks"]),
                inline=False,
            )
        if result.get("secret"):
            embed.add_field(name="🔒 Secret", value=f"||{result['secret']}||", inline=False)

        campaign = db.get_campaign(campaign_id)
        embed.set_footer(text=f"AI-generated • Campaign: {campaign['name']}")

        await interaction.followup.send(embed=embed)

    except Exception as e:
        await interaction.followup.send(f"Lore generation failed: `{str(e)[:200]}`", ephemeral=True)


@lore_group.command(name="history", description="AI-generate historical lore and world events")
@app_commands.describe(
    campaign_id="Campaign ID",
    topic="Topic or era (e.g., 'The Sundering of Kael', 'how dragons came to rule the north')",
    context="Setting details, timeline, or related events",
)
async def lore_history(interaction: discord.Interaction, topic: str, context: str = "", campaign_id: int = None, backend: str = None):
    campaign_id = await resolve_campaign_id(interaction, campaign_id)
    if campaign_id is None:
        return
    if not await _check_ai_rate_limit(interaction, campaign_id):
        return

    await interaction.response.defer(thinking=True)

    try:
        campaign_ctx = db.build_ai_context(campaign_id)
        backend_choice = ai_backend.resolve_backend(campaign_id, backend)
        result = await ai_backend.generate_lore("history", topic, context, campaign_ctx, backend=backend_choice)
        claude_api.rate_limiter.record(interaction.user.id)

        embed = discord.Embed(
            title=f"📜 {result.get('title', topic)}",
            description=result.get("description", "")[:4000],
            color=0x8B6914,
        )
        if result.get("era"):
            embed.add_field(name="Era", value=result["era"], inline=True)
        if result.get("key_figures"):
            embed.add_field(
                name="Key Figures",
                value="\n".join(f"• {f}" for f in result["key_figures"]),
                inline=False,
            )
        if result.get("consequences"):
            embed.add_field(name="Present-Day Impact", value=result["consequences"], inline=False)
        if result.get("evidence"):
            embed.add_field(name="Surviving Evidence", value=result["evidence"], inline=False)
        if result.get("mystery"):
            embed.add_field(name="🔒 Unresolved Mystery", value=f"||{result['mystery']}||", inline=False)
        if result.get("dm_notes"):
            embed.add_field(name="📝 DM Notes", value=f"||{result['dm_notes']}||", inline=False)

        campaign = db.get_campaign(campaign_id)
        embed.set_footer(text=f"AI-generated • Campaign: {campaign['name']}")

        await interaction.followup.send(embed=embed)

    except Exception as e:
        await interaction.followup.send(f"Lore generation failed: `{str(e)[:200]}`", ephemeral=True)


bot.tree.add_command(lore_group)


# ─── Run ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    bot.run(TOKEN)
