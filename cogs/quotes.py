import asyncio
import logging
from datetime import timezone

import discord
from discord import app_commands
from discord.ext import commands

from utils.checks import is_admin
from utils.embeds import error_embed, info_embed, success_embed
from utils.quote_card import generate_quote_card

log = logging.getLogger("cypher.quotes")


class Quotes(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.ctx_menu = app_commands.ContextMenu(
            name="Quote this",
            callback=self.quote_message,
        )
        self.bot.tree.add_command(self.ctx_menu)

    async def cog_unload(self):
        self.bot.tree.remove_command(self.ctx_menu.name, type=self.ctx_menu.type)

    @property
    def db(self):
        return self.bot.db

    # ─── Context menu ─────────────────────────────────────────────────────────

    async def quote_message(self, interaction: discord.Interaction, message: discord.Message):
        await interaction.response.defer(ephemeral=True, thinking=True)

        ch_id = await self.db.get_config(interaction.guild_id, "quotes_channel_id")
        if not ch_id:
            await interaction.followup.send(
                embed=error_embed(
                    "No quotes channel is set. Ask an admin to run `/quotesetup setchannel`."
                ),
                ephemeral=True,
            )
            return

        quotes_ch = interaction.guild.get_channel(int(ch_id))
        if not quotes_ch:
            await interaction.followup.send(
                embed=error_embed("The configured quotes channel no longer exists. Contact an admin."),
                ephemeral=True,
            )
            return

        content = message.clean_content.strip()
        if not content:
            if message.attachments:
                content = f"[{message.attachments[0].filename}]"
            elif message.embeds:
                content = "[embed]"
            else:
                await interaction.followup.send(
                    embed=error_embed("That message has no text content to quote."),
                    ephemeral=True,
                )
                return

        avatar_bytes: bytes | None = None
        try:
            avatar_bytes = await message.author.display_avatar.read()
        except Exception:
            pass

        timestamp = message.created_at.replace(tzinfo=timezone.utc).strftime("%b %d, %Y")

        loop = asyncio.get_event_loop()
        buf = await loop.run_in_executor(
            None,
            generate_quote_card,
            content,
            message.author.display_name,
            interaction.user.display_name,
            interaction.guild.name,
            avatar_bytes,
            timestamp,
        )

        await quotes_ch.send(file=discord.File(buf, filename="quote.png"))
        await interaction.followup.send(
            embed=success_embed(f"Quote posted to {quotes_ch.mention}.", title="Quoted"),
            ephemeral=True,
        )
        log.info(
            f"{interaction.user} quoted {message.author} (msg {message.id}) "
            f"→ #{quotes_ch} in guild {interaction.guild_id}"
        )

    # ─── /quotesetup group ────────────────────────────────────────────────────

    quotesetup_group = app_commands.Group(
        name="quotesetup", description="Quote channel configuration"
    )

    @quotesetup_group.command(
        name="setchannel",
        description="Set the channel where quoted messages are posted",
    )
    @is_admin()
    @app_commands.describe(channel="Text channel to receive quotes")
    async def quotesetup_setchannel(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ):
        await self.db.set_config(interaction.guild_id, "quotes_channel_id", str(channel.id))
        log.info(f"Quotes channel set to #{channel} ({channel.id}) by {interaction.user}")
        await interaction.response.send_message(
            embed=success_embed(
                f"Quotes will now be posted to {channel.mention}.",
                title="Quotes Channel Set",
            ),
            ephemeral=True,
        )

    @quotesetup_group.command(
        name="status", description="Check the current quotes channel configuration"
    )
    @is_admin()
    async def quotesetup_status(self, interaction: discord.Interaction):
        ch_id = await self.db.get_config(interaction.guild_id, "quotes_channel_id")
        if not ch_id:
            await interaction.response.send_message(
                embed=info_embed(
                    "No quotes channel configured. Use `/quotesetup setchannel` to set one.",
                    title="Quotes Setup",
                ),
                ephemeral=True,
            )
            return
        ch = interaction.guild.get_channel(int(ch_id))
        ch_ref = ch.mention if ch else f"`{ch_id}` *(channel not found)*"
        await interaction.response.send_message(
            embed=info_embed(f"Quotes are currently posting to {ch_ref}.", title="Quotes Setup"),
            ephemeral=True,
        )

    # ─── Error handler ────────────────────────────────────────────────────────

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ):
        if isinstance(error, app_commands.CheckFailure):
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    embed=error_embed("You don't have permission to use this command."),
                    ephemeral=True,
                )
        else:
            log.error(f"Quotes command error: {error}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    embed=error_embed("An unexpected error occurred."), ephemeral=True
                )


async def setup(bot: commands.Bot):
    await bot.add_cog(Quotes(bot))
