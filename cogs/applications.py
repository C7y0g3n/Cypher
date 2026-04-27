import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from utils.checks import is_admin
from utils.embeds import error_embed, success_embed, info_embed, build_embed, warning_embed

log = logging.getLogger("cypher.applications")

APPLICATION_QUESTIONS: list[str] = [
    "What is your Discord username and age?",
    "What timezone are you in?",
    "How long have you been a member of this server?",
    "How many hours per day are you typically active on Discord?",
    "Do you have any prior moderation or staff experience? If so, please describe it.",
    "Why do you want to become a moderator on this server?",
    "How would you handle a situation where a member is repeatedly breaking the rules?",
    "What would you do if you witnessed a heated argument between two members?",
    "Do you have any ongoing conflicts with current staff or members?",
    "Is there anything else you would like to add about yourself or your application?",
]

QUESTION_TIMEOUT = 300  # 5 minutes per question


class Applications(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._active: set[int] = set()

    @property
    def db(self):
        return self.bot.db

    # ─── /apply ───────────────────────────────────────────────────────────────

    @app_commands.command(name="apply", description="Apply to become a server moderator")
    async def apply(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if interaction.user.id in self._active:
            await interaction.followup.send(
                embed=warning_embed("You already have an active application in progress. Check your DMs."),
                ephemeral=True,
            )
            return

        app_ch_id = await self.db.get_config(interaction.guild_id, "app_channel_id")
        if not app_ch_id:
            await interaction.followup.send(
                embed=error_embed(
                    "Applications are not configured yet. Ask an admin to run `/appsetup setchannel`."
                ),
                ephemeral=True,
            )
            return

        try:
            await interaction.user.send(
                embed=build_embed(
                    title="Moderator Application",
                    description=(
                        f"Welcome to the **{interaction.guild.name}** moderator application!\n\n"
                        f"You will be asked **{len(APPLICATION_QUESTIONS)} questions**. "
                        "Please answer each one honestly and in full.\n"
                        "Type `cancel` at any time to withdraw your application.\n\n"
                        "**Let's get started — good luck!**"
                    ),
                    color=0x00B4CC,
                    footer=f"You have {QUESTION_TIMEOUT // 60} minutes per question.",
                )
            )
        except discord.Forbidden:
            await interaction.followup.send(
                embed=error_embed(
                    "I couldn't send you a DM. Please enable DMs from server members and try again."
                ),
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            embed=success_embed(
                "Check your DMs! Answer all 10 questions to submit your application.",
                title="Application Started",
            ),
            ephemeral=True,
        )

        self._active.add(interaction.user.id)
        try:
            answers = await self._conduct_interview(interaction.user)
        finally:
            self._active.discard(interaction.user.id)

        if answers is None:
            return

        await self._submit_application(interaction.user, interaction.guild, answers, int(app_ch_id))

    # ─── Interview flow ───────────────────────────────────────────────────────

    async def _conduct_interview(self, user: discord.User) -> list[str] | None:
        answers: list[str] = []

        def dm_check(msg: discord.Message) -> bool:
            return msg.author.id == user.id and isinstance(msg.channel, discord.DMChannel)

        for i, question in enumerate(APPLICATION_QUESTIONS, start=1):
            embed = build_embed(
                title=f"Question {i} of {len(APPLICATION_QUESTIONS)}",
                description=question,
                color=0x00B4CC,
                footer="Reply below — type 'cancel' to withdraw.",
            )
            try:
                await user.send(embed=embed)
            except discord.Forbidden:
                return None

            try:
                msg = await self.bot.wait_for("message", check=dm_check, timeout=QUESTION_TIMEOUT)
            except asyncio.TimeoutError:
                try:
                    await user.send(
                        embed=warning_embed(
                            f"Your application timed out after {QUESTION_TIMEOUT // 60} minutes of inactivity.",
                            title="Application Timed Out",
                        )
                    )
                except Exception:
                    pass
                return None

            if msg.content.strip().lower() == "cancel":
                try:
                    await user.send(
                        embed=info_embed(
                            "Your application has been withdrawn. You can start a new one anytime with `/apply`.",
                            title="Application Cancelled",
                        )
                    )
                except Exception:
                    pass
                return None

            answers.append(msg.content.strip()[:1024])

        return answers

    # ─── Submit to channel ────────────────────────────────────────────────────

    async def _submit_application(
        self,
        user: discord.User,
        guild: discord.Guild,
        answers: list[str],
        app_ch_id: int,
    ):
        ch = guild.get_channel(app_ch_id)
        if not ch:
            try:
                await user.send(
                    embed=error_embed(
                        "The application channel could not be found. Please contact an admin."
                    )
                )
            except Exception:
                pass
            log.warning(f"Application channel {app_ch_id} not found for guild {guild.id}")
            return

        fields = [
            (f"Q{i}: {q}", a or "​", False)
            for i, (q, a) in enumerate(zip(APPLICATION_QUESTIONS, answers), start=1)
        ]

        embed = build_embed(
            title="New Moderator Application",
            description=(
                f"**Applicant:** {user.mention}\n"
                f"**Tag:** `{user}` | **ID:** `{user.id}`"
            ),
            color=0x059669,
            fields=fields,
            thumbnail=user.display_avatar.url,
            footer="React or reply to review this application.",
        )
        await ch.send(embed=embed)

        try:
            await user.send(
                embed=success_embed(
                    f"Your application has been submitted to **{guild.name}**. "
                    "Staff will review it and get back to you shortly.",
                    title="Application Submitted",
                )
            )
        except Exception:
            pass

        log.info(f"Application submitted by {user} ({user.id}) in guild {guild.id}")

    # ─── /appsetup group ──────────────────────────────────────────────────────

    appsetup_group = app_commands.Group(
        name="appsetup", description="Moderator application configuration"
    )

    @appsetup_group.command(
        name="setchannel",
        description="Set the channel where completed applications are posted",
    )
    @is_admin()
    @app_commands.describe(channel="Text channel to receive applications")
    async def appsetup_setchannel(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ):
        await interaction.response.defer(ephemeral=True)
        await self.db.set_config(interaction.guild_id, "app_channel_id", str(channel.id))
        log.info(f"Application channel set to #{channel} ({channel.id}) by {interaction.user}")
        await interaction.followup.send(
            embed=success_embed(
                f"Completed applications will now be posted to {channel.mention}.",
                title="Application Channel Set",
            ),
            ephemeral=True,
        )

    @appsetup_group.command(
        name="status", description="Check the current application channel configuration"
    )
    @is_admin()
    async def appsetup_status(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        app_ch_id = await self.db.get_config(interaction.guild_id, "app_channel_id")
        if not app_ch_id:
            await interaction.followup.send(
                embed=info_embed(
                    "No application channel configured. Use `/appsetup setchannel` to set one.",
                    title="Application Setup",
                ),
                ephemeral=True,
            )
            return
        ch = interaction.guild.get_channel(int(app_ch_id))
        ch_ref = ch.mention if ch else f"`{app_ch_id}` *(channel not found)*"
        await interaction.followup.send(
            embed=info_embed(
                f"Applications are currently posting to {ch_ref}.",
                title="Application Setup",
            ),
            ephemeral=True,
        )

    # ─── Error handler ────────────────────────────────────────────────────────

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ):
        if isinstance(error, app_commands.CheckFailure):
            msg = error_embed("You don't have permission to use this command.")
        else:
            log.error(f"Applications command error: {error}", exc_info=True)
            msg = error_embed("An unexpected error occurred.")

        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=msg, ephemeral=True)
            else:
                await interaction.response.send_message(embed=msg, ephemeral=True)
        except discord.NotFound:
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(Applications(bot))
