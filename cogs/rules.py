import logging

import discord
from discord import app_commands
from discord.ext import commands

from utils.checks import is_admin
from utils.embeds import error_embed, success_embed, info_embed, build_embed

log = logging.getLogger("cypher.rules")

DEFAULT_TITLE = "Server Rules"
DEFAULT_DESCRIPTION = (
    "By clicking **Accept Rules** below you confirm that you have read and agree "
    "to abide by all server rules.\n\n"
    "Violations may result in warnings, timeouts, or a permanent ban."
)


# ─── Persistent View ───────────────────────────────────────────────────────────

class RulesAcceptView(discord.ui.View):
    def __init__(self, cog: "Rules"):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="Accept Rules",
        emoji="✅",
        style=discord.ButtonStyle.success,
        custom_id="cypher:rules_accept",
    )
    async def accept_rules(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.handle_accept(interaction)


# ─── Cog ───────────────────────────────────────────────────────────────────────

class Rules(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        bot.add_view(RulesAcceptView(self))

    @property
    def db(self):
        return self.bot.db

    # ─── Accept handler ───────────────────────────────────────────────────────

    async def handle_accept(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        role_id = await self.db.get_config(interaction.guild_id, "rules_role_id")
        if not role_id:
            await interaction.followup.send(
                embed=error_embed(
                    "No role is configured for rule acceptance. Ask an admin to run `/rulessetup setrole`."
                ),
                ephemeral=True,
            )
            return

        role = interaction.guild.get_role(int(role_id))
        if not role:
            await interaction.followup.send(
                embed=error_embed("The configured role no longer exists. Contact an admin."),
                ephemeral=True,
            )
            return

        if role in interaction.user.roles:
            await interaction.followup.send(
                embed=info_embed("You have already accepted the rules.", title="Already Accepted"),
                ephemeral=True,
            )
            return

        try:
            await interaction.user.add_roles(role, reason="Accepted server rules via panel")
        except discord.Forbidden:
            await interaction.followup.send(
                embed=error_embed("I don't have permission to assign that role. Contact an admin."),
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            embed=success_embed(
                f"You've been given the **{role.name}** role. Welcome to the server!",
                title="Rules Accepted",
            ),
            ephemeral=True,
        )
        log.info(f"{interaction.user} ({interaction.user.id}) accepted rules and received role '{role.name}' in guild {interaction.guild_id}")

    # ─── /rulessetup group ────────────────────────────────────────────────────

    rulessetup_group = app_commands.Group(
        name="rulessetup", description="Rules acceptance panel configuration"
    )

    @rulessetup_group.command(name="setrole", description="Set the role granted when a member accepts the rules")
    @is_admin()
    @app_commands.describe(role="Role to assign on acceptance")
    async def rulessetup_setrole(self, interaction: discord.Interaction, role: discord.Role):
        await interaction.response.defer(ephemeral=True)
        if role >= interaction.guild.me.top_role:
            await interaction.followup.send(
                embed=error_embed(
                    f"**{role.name}** is above my highest role — I can't assign it. "
                    "Move the bot's role above it and try again."
                ),
                ephemeral=True,
            )
            return

        await self.db.set_config(interaction.guild_id, "rules_role_id", str(role.id))
        log.info(f"Rules role set to '{role.name}' ({role.id}) by {interaction.user}")
        await interaction.followup.send(
            embed=success_embed(
                f"Members will receive **{role.name}** after accepting the rules.",
                title="Role Set",
            ),
            ephemeral=True,
        )

    @rulessetup_group.command(name="panel", description="Post the rules acceptance panel in a channel")
    @is_admin()
    @app_commands.describe(
        channel="Channel to post the panel in",
        title="Embed title (optional)",
        description="Rules text shown in the embed (optional)",
    )
    async def rulessetup_panel(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        title: str = DEFAULT_TITLE,
        description: str = DEFAULT_DESCRIPTION,
    ):
        await interaction.response.defer(ephemeral=True)
        role_id = await self.db.get_config(interaction.guild_id, "rules_role_id")
        if not role_id:
            await interaction.followup.send(
                embed=error_embed(
                    "Set a role first with `/rulessetup setrole <role>` before posting the panel."
                ),
                ephemeral=True,
            )
            return

        role = interaction.guild.get_role(int(role_id))
        role_name = role.name if role else f"ID:{role_id}"

        embed = build_embed(
            title=title,
            description=description,
            color=0x00B4CC,
            footer=f"Accepting grants the '{role_name}' role.",
        )
        await channel.send(embed=embed, view=RulesAcceptView(self))
        await self.db.set_config(interaction.guild_id, "rules_panel_channel_id", str(channel.id))

        log.info(f"Rules panel posted in #{channel} by {interaction.user}")
        await interaction.followup.send(
            embed=success_embed(f"Rules panel posted in {channel.mention}.", title="Panel Created"),
            ephemeral=True,
        )

    @rulessetup_group.command(name="status", description="Check the current rules panel configuration")
    @is_admin()
    async def rulessetup_status(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        role_id = await self.db.get_config(interaction.guild_id, "rules_role_id")
        panel_ch_id = await self.db.get_config(interaction.guild_id, "rules_panel_channel_id")

        role_str = "Not set"
        if role_id:
            role = interaction.guild.get_role(int(role_id))
            role_str = role.mention if role else f"`{role_id}` *(role not found)*"

        ch_str = "Not set"
        if panel_ch_id:
            ch = interaction.guild.get_channel(int(panel_ch_id))
            ch_str = ch.mention if ch else f"`{panel_ch_id}` *(channel not found)*"

        embed = build_embed(
            title="Rules Panel Status",
            color=0x00B4CC,
            fields=[
                ("Acceptance Role", role_str, True),
                ("Panel Channel", ch_str, True),
            ],
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ─── Error handler ────────────────────────────────────────────────────────

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ):
        if isinstance(error, app_commands.CheckFailure):
            msg = error_embed("You don't have permission to use this command.")
        else:
            log.error(f"Rules command error: {error}", exc_info=True)
            msg = error_embed("An unexpected error occurred.")

        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=msg, ephemeral=True)
            else:
                await interaction.response.send_message(embed=msg, ephemeral=True)
        except discord.NotFound:
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(Rules(bot))
