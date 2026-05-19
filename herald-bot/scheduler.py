"""
scheduler.py — Background tasks that run on a loop to:
  1. Auto-create sessions based on each campaign's recurring schedule.
  2. Send initial attendance pings N days before a session.
  3. Send midweek status check-in (if enabled).
  4. Send configurable follow-up pings to non-responders on an interval.
  5. Send final reminder M hours before a session.
"""

import discord
from discord.ext import tasks, commands
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import asyncio

import database as db

# Map day names to weekday ints (Monday=0)
DAY_MAP = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}

RARITY_COLORS = {
    "common": 0x9D9D9D,
    "uncommon": 0x1EFF00,
    "rare": 0x0070DD,
    "very rare": 0xA335EE,
    "legendary": 0xFF8000,
    "artifact": 0xE6CC80,
}

EMOJI_MAP = {
    "yes": "✅",
    "no": "❌",
    "tentative": "❓",
    "pending": "⏳",
}


def build_rsvp_embed(session: dict, rsvps: list[dict], campaign_name: str, bot=None) -> discord.Embed:
    """Build a rich embed showing session info and RSVP status."""
    session_dt = datetime.fromisoformat(session["session_date"])
    unix_ts = int(session_dt.timestamp())

    embed = discord.Embed(
        title=f"⚔️  {session.get('title') or campaign_name} — Session #{session['id']}",
        description=f"📅 <t:{unix_ts}:F> (<t:{unix_ts}:R>)",
        color=0x7C3AED,
    )

    yes_list, no_list, tentative_list, pending_list = [], [], [], []
    for r in rsvps:
        user_mention = f"<@{r['user_id']}>"
        char = f" *({r['character_name']})*" if r.get("character_name") else ""
        entry = f"{user_mention}{char}"
        match r["response"]:
            case "yes":
                yes_list.append(entry)
            case "no":
                no_list.append(entry)
            case "tentative":
                tentative_list.append(entry)
            case _:
                pending_list.append(entry)

    if yes_list:
        embed.add_field(name="✅ Attending", value="\n".join(yes_list), inline=True)
    if no_list:
        embed.add_field(name="❌ Can't Make It", value="\n".join(no_list), inline=True)
    if tentative_list:
        embed.add_field(name="❓ Tentative", value="\n".join(tentative_list), inline=True)
    if pending_list:
        embed.add_field(name="⏳ Awaiting Response", value="\n".join(pending_list), inline=True)

    total = len(rsvps)
    confirmed = len(yes_list)
    embed.set_footer(text=f"{confirmed}/{total} confirmed  •  Use the buttons below to RSVP")
    return embed


class RSVPView(discord.ui.View):
    """Persistent buttons for RSVP responses."""

    def __init__(self, session_id: int):
        super().__init__(timeout=None)
        self.session_id = session_id

    @discord.ui.button(label="I'm In!", style=discord.ButtonStyle.green, emoji="⚔️", custom_id="rsvp_yes")
    async def rsvp_yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_rsvp(interaction, "yes")

    @discord.ui.button(label="Can't Make It", style=discord.ButtonStyle.red, emoji="🛡️", custom_id="rsvp_no")
    async def rsvp_no(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_rsvp(interaction, "no")

    @discord.ui.button(label="Tentative", style=discord.ButtonStyle.grey, emoji="❓", custom_id="rsvp_tentative")
    async def rsvp_tentative(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_rsvp(interaction, "tentative")

    async def _handle_rsvp(self, interaction: discord.Interaction, response: str):
        session = db.get_session(self.session_id)
        if not session:
            await interaction.response.send_message("Session not found.", ephemeral=True)
            return

        players = db.get_players(session["campaign_id"])
        player_ids = [p["user_id"] for p in players]
        if interaction.user.id not in player_ids:
            await interaction.response.send_message(
                "You're not in this campaign's party. Ask the DM to add you!", ephemeral=True
            )
            return

        db.set_rsvp(self.session_id, interaction.user.id, response)

        labels = {"yes": "attending", "no": "not attending", "tentative": "tentative"}
        await interaction.response.send_message(
            f"{EMOJI_MAP[response]} Got it — you're marked as **{labels[response]}**.",
            ephemeral=True,
        )

        # Update the embed with new RSVP state
        rsvps = db.get_rsvps(self.session_id)
        campaign = db.get_campaign(session["campaign_id"])
        embed = build_rsvp_embed(session, rsvps, campaign["name"], interaction.client)
        await interaction.message.edit(embed=embed, view=self)


# ─── Background Loop ────────────────────────────────────────────────────────

def _next_monthly(current: datetime, target_weekday: int, hour: int, minute: int, tz) -> datetime:
    """
    Find the same weekday occurrence in the next month.
    E.g., if current is the 2nd Friday of April, return the 2nd Friday of May.
    """
    import calendar

    # Determine which occurrence of the weekday this is (1st, 2nd, 3rd, 4th)
    occurrence = (current.day - 1) // 7 + 1

    # Move to next month
    if current.month == 12:
        next_month, next_year = 1, current.year + 1
    else:
        next_month, next_year = current.month + 1, current.year

    # Find the Nth occurrence of target_weekday in that month
    cal = calendar.monthcalendar(next_year, next_month)
    count = 0
    for week in cal:
        if week[target_weekday] != 0:
            count += 1
            if count == occurrence:
                day = week[target_weekday]
                return datetime(next_year, next_month, day, hour, minute, tzinfo=tz)

    # If the month doesn't have that many occurrences (e.g., 5th Friday),
    # use the last occurrence
    for week in reversed(cal):
        if week[target_weekday] != 0:
            day = week[target_weekday]
            return datetime(next_year, next_month, day, hour, minute, tzinfo=tz)

    # Fallback — shouldn't happen
    return current + timedelta(days=28)


class SchedulerCog(commands.Cog):
    """Background tasks for auto-scheduling and pinging."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._tick_lock = asyncio.Lock()
        self.scheduler_loop.start()

    def cog_unload(self):
        self.scheduler_loop.cancel()

    @tasks.loop(minutes=15)
    async def scheduler_loop(self):
        """Runs every 15 minutes to check for work."""
        if self._tick_lock.locked():
            print("Scheduler tick still running from previous cycle, skipping")
            return

        async with self._tick_lock:
            try:
                await self._auto_create_sessions()
                await self._send_initial_pings()
                await self._send_midweek_checkins()
                await self._send_followup_pings()
                await self._send_final_reminders()
            except Exception as e:
                # Log but don't let one bad iteration kill the loop
                print(f"Scheduler tick error: {type(e).__name__}: {e}")

    @scheduler_loop.before_loop
    async def before_scheduler(self):
        await self.bot.wait_until_ready()

    # ── 1. Auto-create sessions ──────────────────────────────────────────

    async def _auto_create_sessions(self):
        """Create upcoming sessions based on repeat frequency and sessions_ahead count."""
        campaigns = db.get_auto_schedule_campaigns()
        for c in campaigns:
            try:
                tz = ZoneInfo(c["schedule_tz"])
            except Exception:
                tz = ZoneInfo("America/Denver")

            now = datetime.now(tz)
            target_weekday = DAY_MAP.get(c["schedule_day"].lower())
            if target_weekday is None:
                continue

            try:
                hour, minute = map(int, c["schedule_time"].split(":"))
            except Exception:
                continue

            frequency = c.get("repeat_frequency", "weekly")
            sessions_ahead = max(1, c.get("sessions_ahead", 1))

            # Determine the interval in days between sessions
            if frequency == "biweekly":
                interval_days = 14
            elif frequency == "monthly":
                interval_days = None  # Handled specially
            else:
                interval_days = 7  # weekly (default)

            # Find the anchor date for generating sessions
            schedule_start = c.get("schedule_start")

            if schedule_start:
                # Use the explicit start date as the anchor
                try:
                    start_dt = datetime.fromisoformat(schedule_start)
                    if start_dt.tzinfo is None:
                        start_dt = start_dt.replace(tzinfo=tz)
                except Exception:
                    start_dt = None

                if start_dt:
                    # Walk forward from start_dt in increments until we pass now
                    anchor = start_dt
                    if frequency == "monthly":
                        while anchor < now:
                            anchor = _next_monthly(anchor, target_weekday, hour, minute, tz)
                    else:
                        while anchor < now:
                            anchor += timedelta(days=interval_days)
                        # Step back one if we overshot, then check if it's still upcoming
                        candidate_back = anchor - timedelta(days=interval_days)
                        candidate_back_end = candidate_back.replace(hour=hour, minute=minute, second=0, microsecond=0)
                        if candidate_back_end > now:
                            anchor = candidate_back_end
                else:
                    # Fallback if start date is malformed
                    schedule_start = None

            if not schedule_start:
                # No start date — find the next occurrence of the target day
                days_to_next = (target_weekday - now.weekday()) % 7
                if days_to_next == 0:
                    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                    if now > candidate:
                        days_to_next = interval_days or 7
                next_date = now + timedelta(days=days_to_next)
                anchor = next_date.replace(hour=hour, minute=minute, second=0, microsecond=0)

                # For biweekly without a start date: align to existing sessions
                if frequency == "biweekly":
                    upcoming = db.get_upcoming_sessions(c["id"], limit=1)
                    if upcoming:
                        last_dt = datetime.fromisoformat(upcoming[0]["session_date"])
                        if last_dt.tzinfo is None:
                            last_dt = last_dt.replace(tzinfo=tz)
                        diff = abs((anchor - last_dt).days)
                        if diff % 14 != 0 and diff > 0:
                            anchor += timedelta(days=7)

            # Get all existing upcoming sessions for duplicate checking
            existing = db.get_upcoming_sessions(c["id"], limit=20)
            existing_timestamps = [
                datetime.fromisoformat(s["session_date"]).timestamp()
                for s in existing
            ]

            # Generate sessions_ahead future dates
            created = 0
            candidate_dt = anchor
            attempts = 0
            while created < sessions_ahead and attempts < sessions_ahead + 10:
                attempts += 1

                # Skip candidates in the past
                if candidate_dt < now:
                    if frequency == "monthly":
                        # Jump to next month, same weekday occurrence
                        candidate_dt = _next_monthly(candidate_dt, target_weekday, hour, minute, tz)
                    else:
                        candidate_dt += timedelta(days=interval_days)
                    continue

                # Check if this session already exists (within 1 hour tolerance)
                already_exists = any(
                    abs(ts - candidate_dt.timestamp()) < 3600
                    for ts in existing_timestamps
                )

                if not already_exists:
                    db.create_session(c["id"], candidate_dt.isoformat())
                    existing_timestamps.append(candidate_dt.timestamp())
                    created += 1

                # Advance to next occurrence
                if frequency == "monthly":
                    candidate_dt = _next_monthly(candidate_dt, target_weekday, hour, minute, tz)
                else:
                    candidate_dt += timedelta(days=interval_days)

    # ── 2. Initial ping ─────────────────────────────────────────────────

    async def _send_initial_pings(self):
        """Send first attendance check N days before session."""
        sessions = db.get_all_upcoming_sessions()
        now = datetime.now(ZoneInfo("UTC"))

        for s in sessions:
            if s["ping_sent"]:
                continue

            session_dt = datetime.fromisoformat(s["session_date"])
            if session_dt.tzinfo is None:
                session_dt = session_dt.replace(tzinfo=ZoneInfo("UTC"))

            days_until = (session_dt - now).total_seconds() / 86400

            # Skip past sessions (defensive — shouldn't happen but possible
            # with timezone edge cases or malformed dates)
            if days_until < 0:
                continue

            if days_until <= s["ping_days_before"]:
                channel = self.bot.get_channel(s["channel_id"])
                if not channel:
                    continue

                rsvps = db.get_rsvps(s["id"])
                embed = build_rsvp_embed(s, rsvps, s["campaign_name"], self.bot)
                view = RSVPView(s["id"])

                players = db.get_players(s["campaign_id"])
                mentions = " ".join(f"<@{p['user_id']}>" for p in players)

                try:
                    await channel.send(
                        f"🎲 **Roll call, adventurers!** 🎲\n{mentions}\n\n"
                        f"An upcoming session approaches — confirm your attendance below!",
                        embed=embed,
                        view=view,
                    )
                    db.mark_ping_sent(s["id"])
                except discord.HTTPException as e:
                    print(f"Failed to send initial ping for session #{s['id']}: {e}")
                    # Don't mark as sent — will retry next tick

    # ── 3. Midweek check-in ─────────────────────────────────────────────

    async def _send_midweek_checkins(self):
        """Send a midweek status update + nudge non-responders."""
        sessions = db.get_all_upcoming_sessions()
        now = datetime.now(ZoneInfo("UTC"))

        for s in sessions:
            if not s["ping_sent"] or s["midweek_sent"] or not s["midweek_enabled"]:
                continue

            session_dt = datetime.fromisoformat(s["session_date"])
            if session_dt.tzinfo is None:
                session_dt = session_dt.replace(tzinfo=ZoneInfo("UTC"))

            days_until = (session_dt - now).total_seconds() / 86400

            # Defensive: skip past or far-future sessions even if ping_sent
            # somehow got set (e.g., manual /session ping on wrong session)
            if days_until < 0 or days_until > s["ping_days_before"]:
                continue

            # Send midweek if we're roughly halfway between initial ping and session
            midweek_window = s["ping_days_before"] / 2.0
            if 1.0 < days_until <= midweek_window + 0.5:
                channel = self.bot.get_channel(s["channel_id"])
                if not channel:
                    continue

                pending = db.get_pending_rsvps(s["id"])
                rsvps = db.get_rsvps(s["id"])
                embed = build_rsvp_embed(s, rsvps, s["campaign_name"], self.bot)
                view = RSVPView(s["id"])

                confirmed = sum(1 for r in rsvps if r["response"] == "yes")
                total = len(rsvps)

                try:
                    if pending:
                        mentions = " ".join(f"<@{r['user_id']}>" for r in pending)
                        await channel.send(
                            f"📋 **Midweek check-in!** {confirmed}/{total} confirmed so far.\n\n"
                            f"{mentions} — the party awaits your response!",
                            embed=embed,
                            view=view,
                        )
                    else:
                        await channel.send(
                            f"📋 **Midweek check-in!** All {total} adventurers have responded. "
                            f"Looking good for game day!",
                            embed=embed,
                        )
                    db.mark_midweek_sent(s["id"])
                except discord.HTTPException as e:
                    print(f"Failed to send midweek for session #{s['id']}: {e}")

    # ── 4. Follow-up pings ──────────────────────────────────────────────

    async def _send_followup_pings(self):
        """Send configurable follow-up pings to non-responders on an interval."""
        sessions = db.get_all_upcoming_sessions()
        now = datetime.now(ZoneInfo("UTC"))

        for s in sessions:
            if not s["ping_sent"]:
                continue
            if s["reminders_sent"] >= s["followup_count"]:
                continue

            session_dt = datetime.fromisoformat(s["session_date"])
            if session_dt.tzinfo is None:
                session_dt = session_dt.replace(tzinfo=ZoneInfo("UTC"))

            hours_until = (session_dt - now).total_seconds() / 3600
            days_until = hours_until / 24

            # Defensive: only follow up for sessions that are actually within
            # the initial ping window. Prevents runaway pings if ping_sent got
            # set on a far-future session by manual command or stale state.
            if days_until < 0 or days_until > s["ping_days_before"]:
                continue

            # Don't send follow-ups if we're within the final reminder window
            if hours_until <= s["reminder_hours"]:
                continue

            # Check if enough time has passed since last reminder/ping
            if s["last_reminder_at"]:
                last_reminder = datetime.fromisoformat(s["last_reminder_at"])
                if last_reminder.tzinfo is None:
                    last_reminder = last_reminder.replace(tzinfo=ZoneInfo("UTC"))
                hours_since_last = (now - last_reminder).total_seconds() / 3600
                if hours_since_last < s["followup_interval_hours"]:
                    continue
            else:
                # No follow-ups sent yet — check time since initial ping
                ping_threshold = s["ping_days_before"] * 24 - hours_until
                if ping_threshold < s["followup_interval_hours"]:
                    continue

            pending = db.get_pending_rsvps(s["id"])
            if not pending:
                continue

            channel = self.bot.get_channel(s["channel_id"])
            if not channel:
                continue

            mentions = " ".join(f"<@{r['user_id']}>" for r in pending)
            reminder_num = s["reminders_sent"] + 1

            rsvps = db.get_rsvps(s["id"])
            embed = build_rsvp_embed(s, rsvps, s["campaign_name"], self.bot)
            view = RSVPView(s["id"])

            nudge_messages = [
                "The tavern keeper is asking for a headcount...",
                "Your fellow adventurers need to know if you're coming!",
                "The quest board awaits your commitment, adventurer.",
                "A carrier pigeon has been dispatched for your response.",
                "The DM's planning hand grows restless...",
            ]
            nudge = nudge_messages[(reminder_num - 1) % len(nudge_messages)]

            try:
                await channel.send(
                    f"🔔 **Follow-up #{reminder_num}** — {nudge}\n\n"
                    f"{mentions}\n"
                    f"Please respond so the party can plan!",
                    embed=embed,
                    view=view,
                )
                db.increment_reminders_sent(s["id"])
            except discord.HTTPException as e:
                print(f"Failed to send follow-up for session #{s['id']}: {e}")

    # ── 5. Final reminder ───────────────────────────────────────────────

    async def _send_final_reminders(self):
        """Send final reminder M hours before session to non-responders."""
        sessions = db.get_all_upcoming_sessions()
        now = datetime.now(ZoneInfo("UTC"))

        for s in sessions:
            if s["final_reminder_sent"] or not s["ping_sent"]:
                continue

            session_dt = datetime.fromisoformat(s["session_date"])
            if session_dt.tzinfo is None:
                session_dt = session_dt.replace(tzinfo=ZoneInfo("UTC"))

            hours_until = (session_dt - now).total_seconds() / 3600

            # Skip past sessions defensively
            if hours_until < 0:
                continue

            if hours_until <= s["reminder_hours"]:
                pending = db.get_pending_rsvps(s["id"])
                channel = self.bot.get_channel(s["channel_id"])
                if not channel:
                    continue

                rsvps = db.get_rsvps(s["id"])
                embed = build_rsvp_embed(s, rsvps, s["campaign_name"], self.bot)
                view = RSVPView(s["id"])
                unix_ts = int(session_dt.timestamp())

                try:
                    if pending:
                        mentions = " ".join(f"<@{r['user_id']}>" for r in pending)
                        await channel.send(
                            f"⏰ **Final call!** The quest begins <t:{unix_ts}:R>.\n\n"
                            f"{mentions}\n"
                            f"Last chance to confirm — the portal is opening!",
                            embed=embed,
                            view=view,
                        )
                    else:
                        confirmed = sum(1 for r in rsvps if r["response"] == "yes")
                        await channel.send(
                            f"⏰ **Game time approaches!** Starting <t:{unix_ts}:R>.\n\n"
                            f"All RSVPs are in — **{confirmed} adventurers** ready for action!",
                            embed=embed,
                        )
                    db.mark_final_reminder_sent(s["id"])
                except discord.HTTPException as e:
                    print(f"Failed to send final reminder for session #{s['id']}: {e}")


async def setup(bot: commands.Bot):
    await bot.add_cog(SchedulerCog(bot))
