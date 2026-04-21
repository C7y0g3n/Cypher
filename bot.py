import asyncio
import logging
import logging.handlers
import sys
from pathlib import Path

import discord
from discord.ext import commands

import config
from db import Database
from inference.engine import load_engine

Path("./logs").mkdir(exist_ok=True)
_handler = logging.handlers.RotatingFileHandler(
    "./logs/cypher.log", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
)
_handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S"))
logging.basicConfig(level=logging.INFO, handlers=[_handler, logging.StreamHandler(sys.stdout)])
log = logging.getLogger("cypher")

COGS = [
    "cogs.admin",
    "cogs.xp_ranks",
    "cogs.economy",
    "cogs.moderation",
    "cogs.games",
    "cogs.ai_chat",
    "cogs.market",
    "cogs.applications",
    "cogs.tickets",
]


class CypherBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        intents.presences = True

        super().__init__(command_prefix=config.PREFIX, intents=intents, help_command=None)
        self.db: Database = None
        self.slm_engine = None  # populated in setup_hook if model weights exist

    async def setup_hook(self):
        self.db = Database(config.DB_PATH)
        await self.db.init()

        self.slm_engine = load_engine(config.GEMINI_API_KEY, config.GEMINI_MODEL)
        if not self.slm_engine:
            log.warning("AI engine not loaded — set GEMINI_API_KEY in .env to enable /ask")

        for cog in COGS:
            try:
                await self.load_extension(cog)
                log.info(f"Loaded cog: {cog}")
            except Exception as e:
                log.error(f"Failed to load {cog}: {e}", exc_info=True)

        guild = discord.Object(id=config.GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        log.info(f"Commands synced to guild {config.GUILD_ID}")

    async def on_ready(self):
        log.info(f"Online as {self.user} ({self.user.id})")
        await self._seed_guild_defaults()
        await self.change_presence(
            activity=discord.Activity(type=discord.ActivityType.watching, name="the grid | /help")
        )

    async def _seed_guild_defaults(self):
        guild = self.get_guild(config.GUILD_ID)
        if not guild:
            return
        await self.db.seed_config(guild.id, config.CONFIG_DEFAULTS)
        await self.db.seed_shop(guild.id)
        log.info(f"Guild defaults seeded for {guild.id}")

    async def on_member_join(self, member: discord.Member):
        await self.db.ensure_user(member.id, member.guild.id)

        # Assign New Signal role if configured
        role_id = await self.db.get_config(member.guild.id, "rank_role_0")
        if role_id:
            role = member.guild.get_role(int(role_id))
            if role:
                try:
                    await member.add_roles(role, reason="New Signal rank on join")
                except discord.Forbidden:
                    pass

        # Welcome message
        welcome_id = await self.db.get_config(member.guild.id, "welcome_channel_id")
        if welcome_id:
            ch = member.guild.get_channel(int(welcome_id))
            if ch:
                from utils.embeds import build_embed
                embed = build_embed(
                    title="NEW SIGNAL DETECTED",
                    description=(
                        f"Welcome to the grid, {member.mention}.\n"
                        "Your credentials have been registered. Begin your ascent."
                    ),
                    color=0x00B4CC,
                    thumbnail=member.display_avatar.url,
                )
                await ch.send(embed=embed)

    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError):
        from utils.embeds import error_embed
        if isinstance(error, commands.CheckFailure):
            await ctx.send(embed=error_embed("You don't have permission to use this command."))
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(embed=error_embed(f"Missing argument: `{error.param.name}`"))
        elif isinstance(error, commands.BadArgument):
            await ctx.send(embed=error_embed(f"Invalid argument: {error}"))
        elif isinstance(error, commands.CommandNotFound):
            pass
        else:
            log.error(f"Prefix command error: {error}", exc_info=True)

    async def close(self):
        if self.db:
            await self.db.close()
        await super().close()


bot = CypherBot()

if __name__ == "__main__":
    if not config.DISCORD_TOKEN:
        log.critical("DISCORD_TOKEN not set. Fill your .env file.")
        sys.exit(1)
    if not config.GUILD_ID:
        log.critical("GUILD_ID not set. Fill your .env file.")
        sys.exit(1)
    asyncio.run(bot.start(config.DISCORD_TOKEN))
