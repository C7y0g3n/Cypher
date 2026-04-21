import logging
import time

import discord
from discord import app_commands
from discord.ext import commands

from utils.embeds import build_embed, error_embed

log = logging.getLogger("cypher.ai_chat")

_MAX_DISCORD_CHARS = 1900
_MAX_INPUT_CHARS = 2000


class AIChatCog(commands.Cog, name="AI"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @property
    def _engine(self):
        return getattr(self.bot, "slm_engine", None)

    def _build_prompt(self, message: str) -> str:
        return (
            "[INST] You are Cypher, a helpful and friendly AI assistant living inside a Discord server. "
            "Respond conversationally and concisely.\n\n"
            f"{message} [/INST]"
        )

    @app_commands.command(name="ask", description="Chat with Cypher AI.")
    @app_commands.describe(message="What do you want to ask or talk about?")
    @app_commands.checks.cooldown(rate=1, per=15, key=lambda i: i.user.id)
    async def ask(self, interaction: discord.Interaction, message: str) -> None:
        if self._engine is None:
            await interaction.response.send_message(
                embed=error_embed("AI is not configured. Ask a server admin to set it up."),
                ephemeral=True,
            )
            return

        if len(message) > _MAX_INPUT_CHARS:
            await interaction.response.send_message(
                embed=error_embed(f"Message too long — keep it under {_MAX_INPUT_CHARS:,} characters."),
                ephemeral=True,
            )
            return

        await interaction.response.defer(thinking=True)

        prompt = self._build_prompt(message)
        start = time.perf_counter()

        try:
            reply = await self._engine.generate(prompt, max_new_tokens=512)
        except Exception as exc:
            log.error(f"AI inference error: {exc}", exc_info=True)
            await interaction.followup.send(embed=error_embed(f"Something went wrong: `{exc}`"))
            return

        elapsed = time.perf_counter() - start
        chunks = [reply[i : i + _MAX_DISCORD_CHARS] for i in range(0, len(reply), _MAX_DISCORD_CHARS)]

        embed = build_embed(
            title="Cypher AI",
            description=chunks[0] if chunks else "_No response generated._",
            color=0x00B4CC,
            footer=f"{self._engine.model_id}  •  {elapsed:.1f}s",
        )
        embed.add_field(name="Your message", value=message[:1024], inline=False)
        await interaction.followup.send(embed=embed)

        for chunk in chunks[1:]:
            await interaction.followup.send(chunk)

    @ask.error
    async def ask_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        if isinstance(error, app_commands.CommandOnCooldown):
            await interaction.response.send_message(
                embed=error_embed(f"Slow down — try again in {error.retry_after:.0f}s."),
                ephemeral=True,
            )
        else:
            log.error(f"/ask unhandled error: {error}", exc_info=True)
            await interaction.response.send_message(
                embed=error_embed("An unexpected error occurred."), ephemeral=True
            )

    @app_commands.command(name="ai_status", description="Show Cypher AI connection status.")
    async def ai_status(self, interaction: discord.Interaction) -> None:
        engine = self._engine
        if engine is None:
            embed = build_embed(
                title="AI Status",
                description="Not connected. Set `HF_API_TOKEN` and `HF_MODEL_ID` in `.env` and restart.",
                color=0xDC2626,
            )
        else:
            embed = build_embed(
                title="AI Status",
                color=0x059669,
                fields=[
                    ("Backend", "`HuggingFace Inference API`", False),
                    ("Model", f"`{engine.model_id}`", False),
                ],
            )
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AIChatCog(bot))
