import discord
from discord import app_commands
from discord.ext import commands

import config


async def _get_role_id(interaction_or_ctx, key: str) -> int | None:
    if isinstance(interaction_or_ctx, discord.Interaction):
        db = interaction_or_ctx.client.db
        guild_id = interaction_or_ctx.guild_id
    else:
        db = interaction_or_ctx.bot.db
        guild_id = interaction_or_ctx.guild.id
    val = await db.get_config(guild_id, key)
    return int(val) if val else None


async def _has_role(member: discord.Member, role_id: int | None) -> bool:
    if not role_id:
        return False
    return any(r.id == role_id for r in member.roles)


# ─── Slash command checks ─────────────────────────────────────────────────────

def _is_whitelisted(user_id: int) -> bool:
    return user_id in config.ADMIN_USER_IDS


def is_admin():
    async def predicate(interaction: discord.Interaction) -> bool:
        if _is_whitelisted(interaction.user.id):
            return True
        if interaction.guild.owner_id == interaction.user.id:
            return True
        role_id = await _get_role_id(interaction, "admin_role_id")
        return await _has_role(interaction.user, role_id)

    return app_commands.check(predicate)


def is_mod():
    async def predicate(interaction: discord.Interaction) -> bool:
        if _is_whitelisted(interaction.user.id):
            return True
        if interaction.guild.owner_id == interaction.user.id:
            return True
        admin_id = await _get_role_id(interaction, "admin_role_id")
        if await _has_role(interaction.user, admin_id):
            return True
        mod_id = await _get_role_id(interaction, "mod_role_id")
        return await _has_role(interaction.user, mod_id)

    return app_commands.check(predicate)


# ─── Prefix command checks ────────────────────────────────────────────────────

def prefix_is_admin():
    async def predicate(ctx: commands.Context) -> bool:
        if _is_whitelisted(ctx.author.id):
            return True
        if ctx.guild.owner_id == ctx.author.id:
            return True
        role_id = await _get_role_id(ctx, "admin_role_id")
        return await _has_role(ctx.author, role_id)

    return commands.check(predicate)


def prefix_is_mod():
    async def predicate(ctx: commands.Context) -> bool:
        if _is_whitelisted(ctx.author.id):
            return True
        if ctx.guild.owner_id == ctx.author.id:
            return True
        admin_id = await _get_role_id(ctx, "admin_role_id")
        if await _has_role(ctx.author, admin_id):
            return True
        mod_id = await _get_role_id(ctx, "mod_role_id")
        return await _has_role(ctx.author, mod_id)

    return commands.check(predicate)
