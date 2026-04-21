import logging
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands

from utils.checks import is_mod, is_admin, prefix_is_mod, prefix_is_admin
from utils.embeds import error_embed, success_embed, info_embed, build_embed, warning_embed

log = logging.getLogger("cypher.mod")

LOGS_PER_PAGE = 5


class Moderation(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @property
    def db(self):
        return self.bot.db

    # ─── Hierarchy checks ─────────────────────────────────────────────────────

    def _can_action(self, guild: discord.Guild, mod: discord.Member, target: discord.Member) -> str | None:
        if target.id == guild.owner_id:
            return "You cannot moderate the server owner."
        if target.top_role >= guild.me.top_role:
            return "I cannot moderate this user — their role is above mine."
        if mod.id != guild.owner_id and target.top_role >= mod.top_role:
            return "You cannot moderate this user — their role is above yours."
        return None

    async def _log_action(
        self,
        guild: discord.Guild,
        target: discord.Member | discord.Object,
        mod: discord.Member,
        action: str,
        reason: str,
        duration: int | None = None,
    ) -> int:
        log_id = await self.db.add_mod_log(guild.id, target.id, mod.id, action, reason, duration)
        log.info(f"[{action.upper()}] {target} by {mod} | Reason: {reason}")

        log_ch_id = await self.db.get_config(guild.id, "log_channel_id")
        if log_ch_id:
            ch = guild.get_channel(int(log_ch_id))
            if ch:
                fields = [
                    ("Action", action.upper(), True),
                    ("Target", f"{target.mention if hasattr(target, 'mention') else target.id}", True),
                    ("Moderator", mod.mention, True),
                    ("Reason", reason, False),
                ]
                if duration:
                    fields.append(("Duration", f"{duration // 60}m", True))
                embed = build_embed(
                    title=f"Mod Log #{log_id}",
                    color=0xD97706,
                    fields=fields,
                    footer=f"Log ID: {log_id}",
                )
                await ch.send(embed=embed)
        return log_id

    async def _auto_punish(self, guild: discord.Guild, target: discord.Member, warn_count: int):
        if warn_count == 3:
            try:
                until = discord.utils.utcnow() + timedelta(hours=1)
                await target.timeout(until, reason="Auto-timeout: 3 warnings reached")
                await self._log_action(guild, target, guild.me, "timeout", "Auto-timeout: 3 warnings", duration=3600)
            except Exception as e:
                log.warning(f"Auto-timeout failed: {e}")
        elif warn_count == 5:
            log_ch_id = await self.db.get_config(guild.id, "log_channel_id")
            if log_ch_id:
                ch = guild.get_channel(int(log_ch_id))
                if ch:
                    await ch.send(
                        embed=warning_embed(
                            f"{target.mention} has reached **5 warnings**. Consider banning this user.\nUse `/ban {target.id} <reason>`.",
                            title="⚠ Ban Threshold Reached",
                        )
                    )

    # ─── /ban ─────────────────────────────────────────────────────────────────

    @app_commands.command(name="ban", description="Ban a user from the server")
    @is_mod()
    @app_commands.describe(user="User to ban", reason="Reason (required)", delete_days="Days of messages to delete (0-7)")
    async def ban(self, interaction: discord.Interaction, user: discord.Member, reason: str, delete_days: int = 0):
        if not reason.strip():
            await interaction.response.send_message(embed=error_embed("A reason is required."), ephemeral=True)
            return
        err = self._can_action(interaction.guild, interaction.user, user)
        if err:
            await interaction.response.send_message(embed=error_embed(err), ephemeral=True)
            return

        try:
            await user.send(embed=warning_embed(f"You have been **banned** from **{interaction.guild.name}**.\nReason: {reason}"))
        except Exception:
            pass

        delete_days = max(0, min(7, delete_days))
        await interaction.guild.ban(user, reason=f"[{interaction.user}] {reason}", delete_message_days=delete_days)
        await self._log_action(interaction.guild, user, interaction.user, "ban", reason)
        await interaction.response.send_message(
            embed=success_embed(f"**{user}** has been banned.\nReason: {reason}", title="User Banned")
        )

    # ─── /kick ────────────────────────────────────────────────────────────────

    @app_commands.command(name="kick", description="Kick a user from the server")
    @is_mod()
    @app_commands.describe(user="User to kick", reason="Reason (required)")
    async def kick(self, interaction: discord.Interaction, user: discord.Member, reason: str):
        if not reason.strip():
            await interaction.response.send_message(embed=error_embed("A reason is required."), ephemeral=True)
            return
        err = self._can_action(interaction.guild, interaction.user, user)
        if err:
            await interaction.response.send_message(embed=error_embed(err), ephemeral=True)
            return

        try:
            await user.send(embed=warning_embed(f"You have been **kicked** from **{interaction.guild.name}**.\nReason: {reason}"))
        except Exception:
            pass

        await user.kick(reason=f"[{interaction.user}] {reason}")
        await self._log_action(interaction.guild, user, interaction.user, "kick", reason)
        await interaction.response.send_message(
            embed=success_embed(f"**{user}** has been kicked.\nReason: {reason}", title="User Kicked")
        )

    # ─── /timeout ─────────────────────────────────────────────────────────────

    @app_commands.command(name="timeout", description="Timeout a user")
    @is_mod()
    @app_commands.describe(user="User to timeout", minutes="Duration in minutes (max 40320)", reason="Reason")
    async def timeout(self, interaction: discord.Interaction, user: discord.Member, minutes: int, reason: str):
        if not reason.strip():
            await interaction.response.send_message(embed=error_embed("A reason is required."), ephemeral=True)
            return
        err = self._can_action(interaction.guild, interaction.user, user)
        if err:
            await interaction.response.send_message(embed=error_embed(err), ephemeral=True)
            return
        minutes = max(1, min(40320, minutes))
        until = discord.utils.utcnow() + timedelta(minutes=minutes)
        await user.timeout(until, reason=f"[{interaction.user}] {reason}")
        await self._log_action(interaction.guild, user, interaction.user, "timeout", reason, duration=minutes * 60)
        await interaction.response.send_message(
            embed=success_embed(f"**{user}** timed out for **{minutes}m**.\nReason: {reason}", title="User Timed Out")
        )

    # ─── /untimeout ───────────────────────────────────────────────────────────

    @app_commands.command(name="untimeout", description="Remove a user's timeout")
    @is_mod()
    @app_commands.describe(user="User to un-timeout", reason="Reason")
    async def untimeout(self, interaction: discord.Interaction, user: discord.Member, reason: str = "Timeout removed"):
        await user.timeout(None, reason=f"[{interaction.user}] {reason}")
        await self._log_action(interaction.guild, user, interaction.user, "untimeout", reason)
        await interaction.response.send_message(
            embed=success_embed(f"Timeout removed from **{user}**.", title="Timeout Removed")
        )

    # ─── /warn ────────────────────────────────────────────────────────────────

    @app_commands.command(name="warn", description="Issue a warning to a user")
    @is_mod()
    @app_commands.describe(user="User to warn", reason="Reason")
    async def warn(self, interaction: discord.Interaction, user: discord.Member, reason: str):
        if not reason.strip():
            await interaction.response.send_message(embed=error_embed("A reason is required."), ephemeral=True)
            return
        err = self._can_action(interaction.guild, interaction.user, user)
        if err:
            await interaction.response.send_message(embed=error_embed(err), ephemeral=True)
            return

        await self._log_action(interaction.guild, user, interaction.user, "warn", reason)
        warn_count = await self.db.get_warn_count(interaction.guild_id, user.id)

        try:
            await user.send(
                embed=warning_embed(f"You received a warning in **{interaction.guild.name}**.\nReason: {reason}\nTotal warnings: {warn_count}")
            )
        except Exception:
            pass

        await self._auto_punish(interaction.guild, user, warn_count)
        embed = success_embed(
            f"**{user}** warned. (**{warn_count}** total)\nReason: {reason}",
            title="Warning Issued",
        )
        if warn_count >= 3:
            embed.add_field(name="⚠ Auto-Action", value=f"{'1hr timeout applied' if warn_count == 3 else 'Admin notified (5 warns)'}", inline=False)
        await interaction.response.send_message(embed=embed)

    # ─── /warns ───────────────────────────────────────────────────────────────

    @app_commands.command(name="warns", description="View a user's warning history")
    @is_mod()
    @app_commands.describe(user="User to check", page="Page number")
    async def warns(self, interaction: discord.Interaction, user: discord.Member, page: int = 1):
        offset = (page - 1) * LOGS_PER_PAGE
        rows = await self.db.get_mod_logs(interaction.guild_id, user.id, limit=LOGS_PER_PAGE, offset=offset)
        warn_rows = [r for r in rows if r["action"] == "warn"]
        total = await self.db.get_warn_count(interaction.guild_id, user.id)

        if not warn_rows:
            await interaction.response.send_message(
                embed=info_embed(f"No warnings on record for {user.mention}.", title="Warnings"), ephemeral=True
            )
            return

        lines = []
        for row in warn_rows:
            mod = interaction.guild.get_member(row["mod_id"])
            mod_name = mod.display_name if mod else f"#{row['mod_id']}"
            lines.append(f"**Log #{row['log_id']}** — `{row['created_at'][:10]}`\nMod: {mod_name} | {row['reason']}")
        embed = build_embed(
            title=f"Warnings for {user.display_name} ({total} total)",
            description="\n\n".join(lines),
            color=0xD97706,
            footer=f"Page {page}",
        )
        await interaction.response.send_message(embed=embed)

    # ─── /delwarn ─────────────────────────────────────────────────────────────

    @app_commands.command(name="delwarn", description="Delete a warning by log ID")
    @is_admin()
    @app_commands.describe(log_id="Log ID to delete")
    async def delwarn(self, interaction: discord.Interaction, log_id: int):
        ok = await self.db.delete_mod_log(log_id, interaction.guild_id)
        if not ok:
            await interaction.response.send_message(
                embed=error_embed(f"Log `#{log_id}` not found in this guild."), ephemeral=True
            )
            return
        await interaction.response.send_message(
            embed=success_embed(f"Log `#{log_id}` deleted.", title="Warning Deleted"), ephemeral=True
        )

    # ─── /purge ───────────────────────────────────────────────────────────────

    @app_commands.command(name="purge", description="Bulk delete messages (up to 100)")
    @is_mod()
    @app_commands.describe(count="Number of messages to delete (1-100)", user="Filter to one user (optional)")
    async def purge(self, interaction: discord.Interaction, count: int, user: discord.Member | None = None):
        count = max(1, min(100, count))
        await interaction.response.defer(ephemeral=True)

        def check(msg: discord.Message) -> bool:
            return user is None or msg.author.id == user.id

        deleted = await interaction.channel.purge(limit=count, check=check)
        desc = f"Deleted **{len(deleted)}** message{'s' if len(deleted) != 1 else ''}"
        if user:
            desc += f" from {user.mention}"
        await self._log_action(interaction.guild, user or discord.Object(id=0), interaction.user, "purge", f"Purged {len(deleted)} messages")
        await interaction.followup.send(embed=success_embed(desc, title="Purge Complete"), ephemeral=True)

    # ─── /slowmode ────────────────────────────────────────────────────────────

    @app_commands.command(name="slowmode", description="Set channel slowmode (0 to disable, max 21600)")
    @is_mod()
    @app_commands.describe(seconds="Slowmode delay in seconds")
    async def slowmode(self, interaction: discord.Interaction, seconds: int):
        seconds = max(0, min(21600, seconds))
        await interaction.channel.edit(slowmode_delay=seconds)
        msg = f"Slowmode set to **{seconds}s**." if seconds > 0 else "Slowmode **disabled**."
        await interaction.response.send_message(embed=success_embed(msg))

    # ─── /lock & /unlock ──────────────────────────────────────────────────────

    @app_commands.command(name="lock", description="Lock a channel (deny @everyone from sending messages)")
    @is_mod()
    @app_commands.describe(channel="Channel to lock (defaults to current)", reason="Reason")
    async def lock(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel | None = None,
        reason: str = "Channel locked by moderator",
    ):
        ch = channel or interaction.channel
        overwrite = ch.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = False
        await ch.set_permissions(interaction.guild.default_role, overwrite=overwrite, reason=reason)
        await interaction.response.send_message(embed=success_embed(f"{ch.mention} has been **locked**.", title="Channel Locked"))

    @app_commands.command(name="unlock", description="Unlock a channel")
    @is_mod()
    @app_commands.describe(channel="Channel to unlock (defaults to current)", reason="Reason")
    async def unlock(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel | None = None,
        reason: str = "Channel unlocked by moderator",
    ):
        ch = channel or interaction.channel
        overwrite = ch.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = None
        await ch.set_permissions(interaction.guild.default_role, overwrite=overwrite, reason=reason)
        await interaction.response.send_message(embed=success_embed(f"{ch.mention} has been **unlocked**.", title="Channel Unlocked"))

    # ─── /unban ───────────────────────────────────────────────────────────────

    @app_commands.command(name="unban", description="Unban a user by their Discord ID")
    @is_admin()
    @app_commands.describe(user_id="User snowflake ID", reason="Reason")
    async def unban(self, interaction: discord.Interaction, user_id: str, reason: str = "Unbanned by admin"):
        try:
            uid = int(user_id)
        except ValueError:
            await interaction.response.send_message(embed=error_embed("Invalid user ID."), ephemeral=True)
            return
        try:
            await interaction.guild.unban(discord.Object(id=uid), reason=f"[{interaction.user}] {reason}")
        except discord.NotFound:
            await interaction.response.send_message(embed=error_embed(f"User `{uid}` is not banned."), ephemeral=True)
            return
        await self._log_action(interaction.guild, discord.Object(id=uid), interaction.user, "unban", reason)
        await interaction.response.send_message(
            embed=success_embed(f"User `{uid}` has been unbanned.\nReason: {reason}", title="User Unbanned")
        )

    # ─── /modlogs ─────────────────────────────────────────────────────────────

    @app_commands.command(name="modlogs", description="View a user's full moderation history")
    @is_mod()
    @app_commands.describe(user="Target user", page="Page number")
    async def modlogs(self, interaction: discord.Interaction, user: discord.Member, page: int = 1):
        offset = (page - 1) * LOGS_PER_PAGE
        rows = await self.db.get_mod_logs(interaction.guild_id, user.id, limit=LOGS_PER_PAGE, offset=offset)
        total = await self.db.count_mod_logs(interaction.guild_id, user.id)

        if not rows:
            await interaction.response.send_message(
                embed=info_embed(f"No mod history for {user.mention}.", title="Mod Logs"), ephemeral=True
            )
            return

        lines = []
        for row in rows:
            mod = interaction.guild.get_member(row["mod_id"])
            mod_name = mod.display_name if mod else f"#{row['mod_id']}"
            dur = f" ({row['duration']//60}m)" if row["duration"] else ""
            lines.append(
                f"**#{row['log_id']}** `{row['action'].upper()}{dur}` — `{row['created_at'][:10]}`\n"
                f"By: {mod_name} | {row['reason']}"
            )

        embed = build_embed(
            title=f"Mod History — {user.display_name} ({total} total)",
            description="\n\n".join(lines),
            color=0xD97706,
            footer=f"Page {page}",
        )
        view = _ModLogsView(self, interaction.guild_id, user.id, page, total)
        await interaction.response.send_message(embed=embed, view=view)

    # ─── Prefix equivalents ───────────────────────────────────────────────────

    @commands.command(name="ban")
    @prefix_is_mod()
    async def prefix_ban(self, ctx: commands.Context, user: discord.Member, *, reason: str):
        err = self._can_action(ctx.guild, ctx.author, user)
        if err:
            await ctx.send(embed=error_embed(err))
            return
        await ctx.guild.ban(user, reason=f"[{ctx.author}] {reason}")
        await self._log_action(ctx.guild, user, ctx.author, "ban", reason)
        await ctx.send(embed=success_embed(f"{user} banned. Reason: {reason}"))

    @commands.command(name="kick")
    @prefix_is_mod()
    async def prefix_kick(self, ctx: commands.Context, user: discord.Member, *, reason: str):
        err = self._can_action(ctx.guild, ctx.author, user)
        if err:
            await ctx.send(embed=error_embed(err))
            return
        await user.kick(reason=f"[{ctx.author}] {reason}")
        await self._log_action(ctx.guild, user, ctx.author, "kick", reason)
        await ctx.send(embed=success_embed(f"{user} kicked."))

    @commands.command(name="warn")
    @prefix_is_mod()
    async def prefix_warn(self, ctx: commands.Context, user: discord.Member, *, reason: str):
        await self._log_action(ctx.guild, user, ctx.author, "warn", reason)
        warn_count = await self.db.get_warn_count(ctx.guild.id, user.id)
        await self._auto_punish(ctx.guild, user, warn_count)
        await ctx.send(embed=success_embed(f"{user.display_name} warned ({warn_count} total). Reason: {reason}"))

    @commands.command(name="purge")
    @prefix_is_mod()
    async def prefix_purge(self, ctx: commands.Context, count: int, user: discord.Member | None = None):
        count = max(1, min(100, count))
        await ctx.message.delete()
        check = (lambda m: m.author.id == user.id) if user else None
        deleted = await ctx.channel.purge(limit=count, check=check)
        await ctx.send(embed=success_embed(f"Deleted {len(deleted)} messages."), delete_after=5)

    @commands.command(name="slowmode")
    @prefix_is_mod()
    async def prefix_slowmode(self, ctx: commands.Context, seconds: int):
        await ctx.channel.edit(slowmode_delay=max(0, min(21600, seconds)))
        await ctx.send(embed=success_embed(f"Slowmode set to {seconds}s."))

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CheckFailure):
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    embed=error_embed("You don't have permission to use this command."), ephemeral=True
                )
        else:
            log.error(f"Mod command error: {error}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message(embed=error_embed("An unexpected error occurred."), ephemeral=True)


class _ModLogsView(discord.ui.View):
    def __init__(self, cog: Moderation, guild_id: int, target_id: int, page: int, total: int):
        super().__init__(timeout=60)
        self.cog = cog
        self.guild_id = guild_id
        self.target_id = target_id
        self.page = page
        self.total = total

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
        offset = (self.page - 1) * LOGS_PER_PAGE
        rows = await self.cog.db.get_mod_logs(self.guild_id, self.target_id, limit=LOGS_PER_PAGE, offset=offset)
        if not rows:
            self.page = max(1, self.page - 1)
            await interaction.response.defer()
            return
        lines = []
        for row in rows:
            mod = interaction.guild.get_member(row["mod_id"])
            mod_name = mod.display_name if mod else f"#{row['mod_id']}"
            dur = f" ({row['duration']//60}m)" if row["duration"] else ""
            lines.append(
                f"**#{row['log_id']}** `{row['action'].upper()}{dur}` — `{row['created_at'][:10]}`\n"
                f"By: {mod_name} | {row['reason']}"
            )
        member = interaction.guild.get_member(self.target_id)
        name = member.display_name if member else f"User#{self.target_id}"
        embed = build_embed(
            title=f"Mod History — {name} ({self.total} total)",
            description="\n\n".join(lines),
            color=0xD97706,
            footer=f"Page {self.page}",
        )
        await interaction.response.edit_message(embed=embed, view=self)


async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
