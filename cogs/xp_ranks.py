import asyncio
import logging
import secrets
from datetime import datetime, timezone, timedelta
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
from utils.checks import is_admin, is_mod, prefix_is_admin, prefix_is_mod
from utils.embeds import error_embed, success_embed, info_embed, build_embed

log = logging.getLogger("cypher.xp")

XP_COOLDOWN_SECS = 60
MIN_MSG_LEN = 5


class XPRanks(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # In-memory cooldown: {(user_id, guild_id): last_xp_time}
        self._cooldowns: dict[tuple[int, int], datetime] = {}
        self.voice_xp_task.start()

    def cog_unload(self):
        self.voice_xp_task.cancel()

    @property
    def db(self):
        return self.bot.db

    # ─── Background voice XP task ─────────────────────────────────────────────

    @tasks.loop(seconds=60)
    async def voice_xp_task(self):
        for guild in self.bot.guilds:
            bonus = await self._event_bonus(guild.id)
            for vc in guild.voice_channels:
                human_members = [m for m in vc.members if not m.bot]
                if len(human_members) < 2:
                    continue
                for member in human_members:
                    xp_gain = int(
                        (await self._get_cfg_int(guild.id, "voice_xp_rate", config.VOICE_XP_RATE))
                        * (2 if bonus else 1)
                    )
                    result = await self.db.update_xp(member.id, guild.id, xp_gain)
                    if result["leveled_up"]:
                        await self._on_level_up(member, result["level"], guild)

    @voice_xp_task.before_loop
    async def before_voice_xp(self):
        await self.bot.wait_until_ready()

    # ─── on_message XP ────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if len(message.content) < MIN_MSG_LEN:
            return

        key = (message.author.id, message.guild.id)
        now = datetime.now(timezone.utc)
        last = self._cooldowns.get(key)
        if last and (now - last).total_seconds() < XP_COOLDOWN_SECS:
            return

        self._cooldowns[key] = now
        await self.db.update_last_xp_msg(message.author.id, message.guild.id)

        bonus = await self._event_bonus(message.guild.id)
        xp_min = await self._get_cfg_int(message.guild.id, "msg_xp_min", config.MSG_XP_MIN)
        xp_max = await self._get_cfg_int(message.guild.id, "msg_xp_max", config.MSG_XP_MAX)
        xp_gain = secrets.randbelow(xp_max - xp_min + 1) + xp_min
        if bonus:
            xp_gain *= 2

        result = await self.db.update_xp(message.author.id, message.guild.id, xp_gain)
        if result["leveled_up"]:
            await self._on_level_up(message.author, result["level"], message.guild)

    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ):
        if member.bot:
            return
        if before.channel is None and after.channel is not None:
            # Joined voice
            await self.db.ensure_user(member.id, member.guild.id)
            await self.db.update_voice_joined(member.id, member.guild.id, datetime.now(timezone.utc))
        elif before.channel is not None and after.channel is None:
            # Left voice — clear voice_joined_at
            await self.db.update_voice_joined(member.id, member.guild.id, None)

    # ─── Level-up handler ─────────────────────────────────────────────────────

    async def _on_level_up(self, member: discord.Member, new_level: int, guild: discord.Guild):
        rank_name, _ = config.RANK_THRESHOLDS[new_level]
        log.info(f"{member} leveled up to {new_level} ({rank_name}) in {guild}")

        # Role swap
        for lvl, (_, _) in config.RANK_THRESHOLDS.items():
            role_id = await self.db.get_config(guild.id, f"rank_role_{lvl}")
            if not role_id:
                continue
            role = guild.get_role(int(role_id))
            if not role:
                continue
            if lvl == new_level:
                if role not in member.roles:
                    await member.add_roles(role, reason=f"Ranked up to level {new_level}")
            else:
                if role in member.roles:
                    await member.remove_roles(role, reason="Rank role replaced on level-up")

        # Announce
        rankup_id = await self.db.get_config(guild.id, "rankup_channel_id")
        if rankup_id:
            ch = guild.get_channel(int(rankup_id))
            if ch:
                embed = build_embed(
                    title="⚡ SIGNAL UPGRADED",
                    description=(
                        f"{member.mention} has reached **{rank_name}**!\n"
                        f"Level `{new_level}` unlocked."
                    ),
                    color=0x00B4CC,
                    thumbnail=member.display_avatar.url,
                )
                await ch.send(embed=embed)

    # ─── /rank ────────────────────────────────────────────────────────────────

    @app_commands.command(name="rank", description="Display your rank card")
    @app_commands.describe(user="User to check (defaults to you)")
    async def rank(self, interaction: discord.Interaction, user: discord.Member | None = None):
        await interaction.response.defer()
        target = user or interaction.user
        await self.db.ensure_user(target.id, interaction.guild_id)
        row = await self.db.get_user(target.id, interaction.guild_id)
        xp = row["xp"]
        level = row["level"]
        rank_pos = await self.db.get_xp_rank(target.id, interaction.guild_id)
        rank_name, _ = config.RANK_THRESHOLDS[level]

        xp_prev = config.RANK_THRESHOLDS[level][1]
        xp_next = config.RANK_THRESHOLDS.get(level + 1, (None, xp_prev + 1))[1]

        avatar_bytes: bytes | None = None
        try:
            avatar_bytes = await target.display_avatar.read()
        except Exception:
            pass

        from utils.rank_card import generate_rank_card
        buf = await asyncio.get_event_loop().run_in_executor(
            None,
            generate_rank_card,
            target.display_name,
            avatar_bytes,
            level,
            rank_name,
            xp,
            xp_next,
            xp_prev,
            rank_pos,
        )
        await interaction.followup.send(file=discord.File(buf, filename="rank.png"))

    # ─── /leaderboard ─────────────────────────────────────────────────────────

    @app_commands.command(name="leaderboard", description="Top 10 users by XP")
    @app_commands.describe(page="Page number")
    async def leaderboard(self, interaction: discord.Interaction, page: int = 1):
        await interaction.response.defer()
        if page < 1:
            page = 1
        offset = (page - 1) * 10
        rows = await self.db.get_xp_leaderboard(interaction.guild_id, limit=10, offset=offset)
        if not rows:
            await interaction.followup.send(
                embed=info_embed("No data yet. Start chatting!", title="Leaderboard"), ephemeral=True
            )
            return

        lines = []
        for i, row in enumerate(rows, start=offset + 1):
            try:
                member = interaction.guild.get_member(row["user_id"]) or await interaction.guild.fetch_member(row["user_id"])
                name = member.display_name
            except Exception:
                name = f"User#{row['user_id']}"
            rank_name, _ = config.RANK_THRESHOLDS[row["level"]]
            lines.append(f"`{i:>2}.` **{name}** — {row['xp']:,} XP · {rank_name}")

        embed = build_embed(
            title="⚡ XP Leaderboard",
            description="\n".join(lines),
            color=0x00B4CC,
            footer=f"Page {page}",
        )
        view = _LeaderboardView(self, interaction.guild_id, page)
        await interaction.followup.send(embed=embed, view=view)

    # ─── /rankinfo ────────────────────────────────────────────────────────────

    @app_commands.command(name="rankinfo", description="List all rank tiers")
    async def rankinfo(self, interaction: discord.Interaction):
        await interaction.response.defer()
        lines = []
        for lvl, (name, threshold) in config.RANK_THRESHOLDS.items():
            role_id = await self.db.get_config(interaction.guild_id, f"rank_role_{lvl}")
            role_str = f"<@&{role_id}>" if role_id else "_not configured_"
            lines.append(f"**{lvl+1:02d}. {name}** — `{threshold:,} XP` · {role_str}")
        embed = build_embed(
            title="⚡ Rank Tiers",
            description="\n".join(lines),
            color=0x00B4CC,
            footer="XP earned via chat, voice, and daily rewards",
        )
        await interaction.followup.send(embed=embed)

    # ─── /xp subcommands ──────────────────────────────────────────────────────

    xp_group = app_commands.Group(name="xp", description="XP management commands")

    @xp_group.command(name="add", description="Grant XP to a user")
    @is_admin()
    @app_commands.describe(user="Target user", amount="XP to add")
    async def xp_add(self, interaction: discord.Interaction, user: discord.Member, amount: int):
        await interaction.response.defer()
        if amount <= 0:
            await interaction.followup.send(embed=error_embed("Amount must be positive."), ephemeral=True)
            return
        result = await self.db.update_xp(user.id, interaction.guild_id, amount)
        await interaction.followup.send(
            embed=success_embed(
                f"Added **{amount:,} XP** to {user.mention}\nNew total: **{result['xp']:,} XP** (Level {result['level']})"
            )
        )
        if result["leveled_up"]:
            await self._on_level_up(user, result["level"], interaction.guild)

    @xp_group.command(name="remove", description="Remove XP from a user")
    @is_admin()
    @app_commands.describe(user="Target user", amount="XP to remove")
    async def xp_remove(self, interaction: discord.Interaction, user: discord.Member, amount: int):
        await interaction.response.defer()
        if amount <= 0:
            await interaction.followup.send(embed=error_embed("Amount must be positive."), ephemeral=True)
            return
        result = await self.db.update_xp(user.id, interaction.guild_id, -amount)
        await interaction.followup.send(
            embed=success_embed(
                f"Removed **{amount:,} XP** from {user.mention}\nNew total: **{result['xp']:,} XP** (Level {result['level']})"
            )
        )
        if result["leveled_down"]:
            await self._on_level_up(user, result["level"], interaction.guild)

    @xp_group.command(name="set", description="Set a user's XP to an exact value")
    @is_admin()
    @app_commands.describe(user="Target user", amount="XP value to set")
    async def xp_set(self, interaction: discord.Interaction, user: discord.Member, amount: int):
        await interaction.response.defer()
        if amount < 0:
            await interaction.followup.send(embed=error_embed("XP cannot be negative."), ephemeral=True)
            return
        result = await self.db.set_xp(user.id, interaction.guild_id, amount)
        await interaction.followup.send(
            embed=success_embed(
                f"Set {user.mention}'s XP to **{amount:,}** (Level {result['level']})"
            )
        )
        if result["leveled_up"] or result["leveled_down"]:
            await self._on_level_up(user, result["level"], interaction.guild)

    # ─── Prefix commands ──────────────────────────────────────────────────────

    @commands.command(name="rank")
    async def prefix_rank(self, ctx: commands.Context, user: discord.Member | None = None):
        target = user or ctx.author
        await self.db.ensure_user(target.id, ctx.guild.id)
        row = await self.db.get_user(target.id, ctx.guild.id)
        rank_name, _ = config.RANK_THRESHOLDS[row["level"]]
        rank_pos = await self.db.get_xp_rank(target.id, ctx.guild.id)
        embed = info_embed(
            f"**{target.display_name}** · Level {row['level']} · {rank_name}\n"
            f"XP: {row['xp']:,} · Rank: #{rank_pos}",
            title="Rank",
        )
        await ctx.send(embed=embed)

    @commands.command(name="leaderboard", aliases=["lb"])
    async def prefix_leaderboard(self, ctx: commands.Context, page: int = 1):
        offset = (page - 1) * 10
        rows = await self.db.get_xp_leaderboard(ctx.guild.id, limit=10, offset=offset)
        lines = []
        for i, row in enumerate(rows, start=offset + 1):
            m = ctx.guild.get_member(row["user_id"])
            name = m.display_name if m else f"User#{row['user_id']}"
            lines.append(f"`{i:>2}.` **{name}** — {row['xp']:,} XP")
        await ctx.send(embed=build_embed(title="⚡ XP Leaderboard", description="\n".join(lines) or "No data.", color=0x00B4CC))

    @commands.group(name="xp", invoke_without_command=True)
    async def prefix_xp(self, ctx: commands.Context):
        await ctx.send(embed=info_embed("Subcommands: `xp add`, `xp remove`, `xp set`"))

    @prefix_xp.command(name="add")
    @prefix_is_admin()
    async def prefix_xp_add(self, ctx: commands.Context, user: discord.Member, amount: int):
        result = await self.db.update_xp(user.id, ctx.guild.id, amount)
        await ctx.send(embed=success_embed(f"Added {amount:,} XP to {user.display_name}. Total: {result['xp']:,}"))
        if result["leveled_up"]:
            await self._on_level_up(user, result["level"], ctx.guild)

    @prefix_xp.command(name="remove")
    @prefix_is_admin()
    async def prefix_xp_remove(self, ctx: commands.Context, user: discord.Member, amount: int):
        result = await self.db.update_xp(user.id, ctx.guild.id, -amount)
        await ctx.send(embed=success_embed(f"Removed {amount:,} XP from {user.display_name}. Total: {result['xp']:,}"))

    @prefix_xp.command(name="set")
    @prefix_is_admin()
    async def prefix_xp_set(self, ctx: commands.Context, user: discord.Member, amount: int):
        result = await self.db.set_xp(user.id, ctx.guild.id, amount)
        await ctx.send(embed=success_embed(f"Set {user.display_name}'s XP to {amount:,} (Level {result['level']})"))

    # ─── Helpers ──────────────────────────────────────────────────────────────

    async def _event_bonus(self, guild_id: int) -> bool:
        val = await self.db.get_config(guild_id, "event_bonus_active")
        return val == "true"

    async def _get_cfg_int(self, guild_id: int, key: str, default: int) -> int:
        val = await self.db.get_config(guild_id, key)
        try:
            return int(val) if val else default
        except (ValueError, TypeError):
            return default

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CheckFailure):
            msg = error_embed("You don't have permission to use this command.")
        else:
            log.error(f"XP command error: {error}", exc_info=True)
            msg = error_embed("An unexpected error occurred.")

        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=msg, ephemeral=True)
            else:
                await interaction.response.send_message(embed=msg, ephemeral=True)
        except discord.NotFound:
            pass


class _LeaderboardView(discord.ui.View):
    def __init__(self, cog: XPRanks, guild_id: int, page: int):
        super().__init__(timeout=60)
        self.cog = cog
        self.guild_id = guild_id
        self.page = page

    @discord.ui.button(label="◀ Previous", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page <= 1:
            await interaction.response.defer()
            return
        self.page -= 1
        await self._update(interaction)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page += 1
        await self._update(interaction)

    async def _update(self, interaction: discord.Interaction):
        offset = (self.page - 1) * 10
        rows = await self.cog.db.get_xp_leaderboard(self.guild_id, limit=10, offset=offset)
        if not rows:
            self.page = max(1, self.page - 1)
            await interaction.response.defer()
            return
        lines = []
        for i, row in enumerate(rows, start=offset + 1):
            m = interaction.guild.get_member(row["user_id"])
            name = m.display_name if m else f"User#{row['user_id']}"
            rank_name, _ = config.RANK_THRESHOLDS[row["level"]]
            lines.append(f"`{i:>2}.` **{name}** — {row['xp']:,} XP · {rank_name}")
        embed = build_embed(
            title="⚡ XP Leaderboard",
            description="\n".join(lines),
            color=0x00B4CC,
            footer=f"Page {self.page}",
        )
        await interaction.response.edit_message(embed=embed, view=self)


async def setup(bot: commands.Bot):
    await bot.add_cog(XPRanks(bot))
