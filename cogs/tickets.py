import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

import config
from utils.checks import is_admin
from utils.embeds import error_embed, success_embed, info_embed, build_embed, warning_embed

log = logging.getLogger("cypher.tickets")

REPORT_QUESTIONS: list[str] = [
    "Who are you reporting? (Discord username and/or user ID)",
    "Which rule did they break?",
    "Describe what happened in as much detail as possible.",
    "Do you have any evidence? (message links, screenshot descriptions, IDs — type 'none' if not)",
]
REPORT_TIMEOUT = 180  # 3 minutes per question


# ─── Persistent Views ──────────────────────────────────────────────────────────

class TicketPanelView(discord.ui.View):
    def __init__(self, cog: "Tickets"):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="Open Ticket",
        emoji="🎫",
        style=discord.ButtonStyle.primary,
        custom_id="cypher:ticket_open",
    )
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.handle_open_ticket(interaction)


class TicketControlView(discord.ui.View):
    def __init__(self, cog: "Tickets"):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="Close Ticket",
        emoji="🔒",
        style=discord.ButtonStyle.danger,
        custom_id="cypher:ticket_close",
    )
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.handle_close_ticket(interaction)


class ReportPanelView(discord.ui.View):
    def __init__(self, cog: "Tickets"):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="Submit Report",
        emoji="🚨",
        style=discord.ButtonStyle.danger,
        custom_id="cypher:report_open",
    )
    async def open_report(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.handle_open_report(interaction)


# ─── Cog ───────────────────────────────────────────────────────────────────────

class Tickets(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._report_active: set[int] = set()
        bot.add_view(TicketPanelView(self))
        bot.add_view(TicketControlView(self))
        bot.add_view(ReportPanelView(self))

    @property
    def db(self):
        return self.bot.db

    # ─── Ticket: open ─────────────────────────────────────────────────────────

    async def handle_open_ticket(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        existing = await self.db.get_open_ticket_by_user(interaction.guild_id, interaction.user.id)
        if existing:
            ch = interaction.guild.get_channel(existing["channel_id"])
            if ch:
                await interaction.followup.send(
                    embed=warning_embed(
                        f"You already have an open ticket: {ch.mention}\n"
                        "Please continue there or close it first.",
                        title="Ticket Already Open",
                    ),
                    ephemeral=True,
                )
                return
            # channel was manually deleted without closing — mark it closed
            await self.db.close_ticket(existing["channel_id"], self.bot.user.id)

        cat_id = await self.db.get_config(interaction.guild_id, "ticket_category_id")
        category = interaction.guild.get_channel(int(cat_id)) if cat_id else None

        overwrites: dict = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True, attach_files=True
            ),
            interaction.guild.me: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, manage_channels=True, manage_messages=True
            ),
        }
        for key in ("mod_role_id", "admin_role_id"):
            role_id = await self.db.get_config(interaction.guild_id, key)
            if role_id:
                role = interaction.guild.get_role(int(role_id))
                if role:
                    overwrites[role] = discord.PermissionOverwrite(
                        view_channel=True, send_messages=True, read_message_history=True, manage_messages=True
                    )

        num = await self.db.next_ticket_number(interaction.guild_id)
        safe_name = interaction.user.name[:16].lower().replace(" ", "-")
        channel_name = f"ticket-{num:04d}-{safe_name}"

        try:
            channel = await interaction.guild.create_text_channel(
                name=channel_name,
                overwrites=overwrites,
                category=category,
                reason=f"Ticket #{num:04d} opened by {interaction.user}",
            )
        except discord.Forbidden:
            await interaction.followup.send(
                embed=error_embed("I don't have permission to create channels. Contact an admin."),
                ephemeral=True,
            )
            return

        await self.db.create_ticket(interaction.guild_id, interaction.user.id, channel.id)

        embed = build_embed(
            title=f"Ticket #{num:04d}",
            description=(
                f"Welcome, {interaction.user.mention}! Staff will be with you shortly.\n\n"
                "Please describe your issue in as much detail as possible.\n"
                "Click **Close Ticket** when your issue has been resolved."
            ),
            color=0x00B4CC,
            thumbnail=interaction.user.display_avatar.url,
            footer=f"Opened by {interaction.user} · #{num:04d}",
        )
        await channel.send(
            content=interaction.user.mention,
            embed=embed,
            view=TicketControlView(self),
        )

        await interaction.followup.send(
            embed=success_embed(f"Your ticket has been created: {channel.mention}", title="Ticket Opened"),
            ephemeral=True,
        )
        log.info(f"Ticket #{num:04d} opened by {interaction.user} ({interaction.user.id}) in guild {interaction.guild_id}")

    # ─── Ticket: close ────────────────────────────────────────────────────────

    async def handle_close_ticket(self, interaction: discord.Interaction):
        await interaction.response.defer()
        ticket = await self.db.get_ticket_by_channel(interaction.channel_id)
        if not ticket or ticket["closed_at"] is not None:
            await interaction.followup.send(
                embed=error_embed("This channel is not an active ticket."), ephemeral=True
            )
            return

        is_owner = interaction.user.id == ticket["user_id"]
        has_staff = (
            interaction.user.id in config.ADMIN_USER_IDS
            or interaction.user.id == interaction.guild.owner_id
        )
        if not has_staff:
            for key in ("mod_role_id", "admin_role_id"):
                role_id = await self.db.get_config(interaction.guild_id, key)
                if role_id:
                    role = interaction.guild.get_role(int(role_id))
                    if role and role in interaction.user.roles:
                        has_staff = True
                        break

        if not is_owner and not has_staff:
            await interaction.followup.send(
                embed=error_embed("Only the ticket owner or staff can close this ticket."),
                ephemeral=True,
            )
            return

        embed = build_embed(
            title="Ticket Closing",
            description=f"Closed by {interaction.user.mention}. This channel will be deleted in 5 seconds.",
            color=0xD97706,
        )
        await interaction.followup.send(embed=embed)

        log_ch_id = await self.db.get_config(interaction.guild_id, "ticket_log_channel_id")
        if log_ch_id:
            log_ch = interaction.guild.get_channel(int(log_ch_id))
            if log_ch:
                opener = interaction.guild.get_member(ticket["user_id"])
                opener_str = str(opener) if opener else f"ID:{ticket['user_id']}"
                log_embed = build_embed(
                    title="Ticket Closed",
                    color=0xD97706,
                    fields=[
                        ("Channel", interaction.channel.name, True),
                        ("Opened By", opener_str, True),
                        ("Closed By", str(interaction.user), True),
                    ],
                    footer=f"Internal ticket ID: {ticket['ticket_id']}",
                )
                await log_ch.send(embed=log_embed)

        await self.db.close_ticket(interaction.channel_id, interaction.user.id)
        await asyncio.sleep(5)
        try:
            await interaction.channel.delete(reason=f"Ticket closed by {interaction.user}")
        except discord.Forbidden:
            pass
        log.info(f"Ticket closed by {interaction.user} ({interaction.user.id}) in guild {interaction.guild_id}")

    # ─── Report: open ─────────────────────────────────────────────────────────

    async def handle_open_report(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if interaction.user.id in self._report_active:
            await interaction.followup.send(
                embed=warning_embed("You already have a report in progress. Check your DMs."),
                ephemeral=True,
            )
            return

        report_ch_id = await self.db.get_config(interaction.guild_id, "report_channel_id")
        if not report_ch_id:
            await interaction.followup.send(
                embed=error_embed("Reports are not configured yet. Ask an admin to run `/reportsetup setchannel`."),
                ephemeral=True,
            )
            return

        try:
            await interaction.user.send(
                embed=build_embed(
                    title="Submit a Report",
                    description=(
                        f"You are submitting a confidential report to **{interaction.guild.name}** staff.\n\n"
                        f"You will be asked **{len(REPORT_QUESTIONS)} questions**. "
                        "Please be as specific as possible.\n"
                        "Type `cancel` at any time to withdraw.\n\n"
                        "**Starting now:**"
                    ),
                    color=0xDC2626,
                    footer=f"You have {REPORT_TIMEOUT // 60} minutes per question.",
                )
            )
        except discord.Forbidden:
            await interaction.followup.send(
                embed=error_embed("I couldn't DM you. Please enable DMs from server members and try again."),
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            embed=success_embed("Check your DMs to complete your report.", title="Report Started"),
            ephemeral=True,
        )

        self._report_active.add(interaction.user.id)
        try:
            answers = await self._conduct_report(interaction.user)
        finally:
            self._report_active.discard(interaction.user.id)

        if answers is None:
            return
        await self._submit_report(interaction.user, interaction.guild, answers, int(report_ch_id))

    async def _conduct_report(self, user: discord.User) -> list[str] | None:
        answers: list[str] = []

        def dm_check(msg: discord.Message) -> bool:
            return msg.author.id == user.id and isinstance(msg.channel, discord.DMChannel)

        for i, question in enumerate(REPORT_QUESTIONS, start=1):
            embed = build_embed(
                title=f"Question {i} of {len(REPORT_QUESTIONS)}",
                description=question,
                color=0xDC2626,
                footer="Type 'cancel' to withdraw.",
            )
            try:
                await user.send(embed=embed)
            except discord.Forbidden:
                return None

            try:
                msg = await self.bot.wait_for("message", check=dm_check, timeout=REPORT_TIMEOUT)
            except asyncio.TimeoutError:
                try:
                    await user.send(embed=warning_embed("Your report timed out.", title="Report Timed Out"))
                except Exception:
                    pass
                return None

            if msg.content.strip().lower() == "cancel":
                try:
                    await user.send(
                        embed=info_embed("Your report has been withdrawn.", title="Report Cancelled")
                    )
                except Exception:
                    pass
                return None

            answers.append(msg.content.strip()[:1024])

        return answers

    async def _submit_report(
        self,
        user: discord.User,
        guild: discord.Guild,
        answers: list[str],
        report_ch_id: int,
    ):
        ch = guild.get_channel(report_ch_id)
        if not ch:
            try:
                await user.send(embed=error_embed("The report channel could not be found. Contact an admin."))
            except Exception:
                pass
            log.warning(f"Report channel {report_ch_id} not found for guild {guild.id}")
            return

        fields = [
            (f"Q{i}: {q}", a or "​", False)
            for i, (q, a) in enumerate(zip(REPORT_QUESTIONS, answers), start=1)
        ]
        embed = build_embed(
            title="New Report",
            description=f"**Reporter:** {user.mention} (`{user}` · ID: `{user.id}`)",
            color=0xDC2626,
            fields=fields,
            thumbnail=user.display_avatar.url,
            footer="Submitted via report panel.",
        )
        await ch.send(embed=embed)

        try:
            await user.send(
                embed=success_embed(
                    f"Your report has been submitted to **{guild.name}** staff. Thank you.",
                    title="Report Submitted",
                )
            )
        except Exception:
            pass
        log.info(f"Report submitted by {user} ({user.id}) in guild {guild.id}")

    # ─── /ticketsetup group ───────────────────────────────────────────────────

    ticketsetup_group = app_commands.Group(
        name="ticketsetup", description="Ticket system configuration"
    )

    @ticketsetup_group.command(name="panel", description="Post the ticket panel in a channel")
    @is_admin()
    @app_commands.describe(channel="Channel to post the panel in")
    async def ticketsetup_panel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await interaction.response.defer(ephemeral=True)
        embed = build_embed(
            title="Support Tickets",
            description=(
                "Need help from staff? Click the button below to open a private support ticket.\n\n"
                "A dedicated channel will be created just for you and the team."
            ),
            color=0x00B4CC,
            footer="One open ticket per user.",
        )
        await channel.send(embed=embed, view=TicketPanelView(self))
        await self.db.set_config(interaction.guild_id, "ticket_panel_channel_id", str(channel.id))
        await interaction.followup.send(
            embed=success_embed(f"Ticket panel posted in {channel.mention}.", title="Panel Created"),
            ephemeral=True,
        )
        log.info(f"Ticket panel posted in #{channel} by {interaction.user}")

    @ticketsetup_group.command(name="setcategory", description="Set the category where ticket channels are created")
    @is_admin()
    @app_commands.describe(category="Category for new ticket channels")
    async def ticketsetup_setcategory(
        self, interaction: discord.Interaction, category: discord.CategoryChannel
    ):
        await interaction.response.defer(ephemeral=True)
        await self.db.set_config(interaction.guild_id, "ticket_category_id", str(category.id))
        await interaction.followup.send(
            embed=success_embed(f"Ticket channels will be created under **{category.name}**.", title="Category Set"),
            ephemeral=True,
        )

    @ticketsetup_group.command(name="setlogchannel", description="Set the channel where closed tickets are logged")
    @is_admin()
    @app_commands.describe(channel="Staff channel to log ticket closures")
    async def ticketsetup_setlogchannel(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ):
        await interaction.response.defer(ephemeral=True)
        await self.db.set_config(interaction.guild_id, "ticket_log_channel_id", str(channel.id))
        await interaction.followup.send(
            embed=success_embed(f"Ticket close logs will be posted to {channel.mention}.", title="Log Channel Set"),
            ephemeral=True,
        )

    # ─── /reportsetup group ───────────────────────────────────────────────────

    reportsetup_group = app_commands.Group(
        name="reportsetup", description="Report system configuration"
    )

    @reportsetup_group.command(name="panel", description="Post the report panel in a channel")
    @is_admin()
    @app_commands.describe(channel="Channel to post the panel in")
    async def reportsetup_panel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await interaction.response.defer(ephemeral=True)
        embed = build_embed(
            title="Report a Member",
            description=(
                "Witnessed a rule violation? Click below to submit a confidential report to staff.\n\n"
                "Your report will be reviewed as soon as possible."
            ),
            color=0xDC2626,
            footer="All reports are confidential.",
        )
        await channel.send(embed=embed, view=ReportPanelView(self))
        await self.db.set_config(interaction.guild_id, "report_panel_channel_id", str(channel.id))
        await interaction.followup.send(
            embed=success_embed(f"Report panel posted in {channel.mention}.", title="Panel Created"),
            ephemeral=True,
        )
        log.info(f"Report panel posted in #{channel} by {interaction.user}")

    @reportsetup_group.command(name="setchannel", description="Set the channel where submitted reports are posted")
    @is_admin()
    @app_commands.describe(channel="Staff-only channel for incoming reports")
    async def reportsetup_setchannel(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ):
        await interaction.response.defer(ephemeral=True)
        await self.db.set_config(interaction.guild_id, "report_channel_id", str(channel.id))
        await interaction.followup.send(
            embed=success_embed(f"Submitted reports will be posted to {channel.mention}.", title="Report Channel Set"),
            ephemeral=True,
        )

    # ─── Error handler ────────────────────────────────────────────────────────

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ):
        if isinstance(error, app_commands.CheckFailure):
            msg = error_embed("You don't have permission to use this command.")
        else:
            log.error(f"Tickets command error: {error}", exc_info=True)
            msg = error_embed("An unexpected error occurred.")

        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=msg, ephemeral=True)
            else:
                await interaction.response.send_message(embed=msg, ephemeral=True)
        except discord.NotFound:
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(Tickets(bot))
