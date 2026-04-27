import json
import logging
import os
from datetime import datetime
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from utils.checks import is_admin, prefix_is_admin
from utils.embeds import error_embed, success_embed, info_embed

log = logging.getLogger("cypher.admin")

VALID_ITEM_TYPES = ("role", "color", "channel", "crate", "music")


class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @property
    def db(self):
        return self.bot.db

    # ─── Slash command group ──────────────────────────────────────────────────

    admin_group = app_commands.Group(name="admin", description="Bot administration commands")

    @admin_group.command(name="reload", description="Hot-reload a cog without restarting the bot")
    @is_admin()
    @app_commands.describe(cog="Cog name (e.g. moderation) or 'all'")
    async def admin_reload(self, interaction: discord.Interaction, cog: str):
        await interaction.response.defer(ephemeral=True)
        if cog.lower() == "all":
            results = []
            for ext in list(self.bot.extensions):
                try:
                    await self.bot.reload_extension(ext)
                    results.append(f"✓ {ext}")
                except Exception as e:
                    results.append(f"✗ {ext}: {e}")
            await interaction.followup.send(
                embed=success_embed("\n".join(results), title="Reload Results"), ephemeral=True
            )
        else:
            ext = f"cogs.{cog}" if not cog.startswith("cogs.") else cog
            try:
                await self.bot.reload_extension(ext)
                log.info(f"Reloaded {ext} by {interaction.user}")
                await interaction.followup.send(
                    embed=success_embed(f"Reloaded `{ext}` successfully."), ephemeral=True
                )
            except Exception as e:
                await interaction.followup.send(
                    embed=error_embed(f"Failed to reload `{ext}`:\n```{e}```"), ephemeral=True
                )

    @admin_group.command(name="setconfig", description="Set a bot configuration value")
    @is_admin()
    @app_commands.describe(key="Config key", value="New value")
    async def admin_setconfig(self, interaction: discord.Interaction, key: str, value: str):
        await interaction.response.defer(ephemeral=True)
        await self.db.set_config(interaction.guild_id, key, value)
        log.info(f"Config [{key}={value}] set by {interaction.user}")
        await interaction.followup.send(
            embed=success_embed(f"`{key}` → `{value}`", title="Config Updated"), ephemeral=True
        )

    @admin_group.command(name="additem", description="Add a new item to the shop")
    @is_admin()
    @app_commands.describe(
        name="Item display name",
        item_type="Item type: role / color / channel / crate / music",
        cost="Price in Cypher Credits",
        role_id="Discord role ID to assign (optional)",
        days="Duration in days — omit for permanent",
        stock="Max stock — omit for unlimited",
    )
    async def admin_additem(
        self,
        interaction: discord.Interaction,
        name: str,
        item_type: str,
        cost: int,
        role_id: str | None = None,
        days: int | None = None,
        stock: int | None = None,
    ):
        await interaction.response.defer(ephemeral=True)
        if item_type not in VALID_ITEM_TYPES:
            await interaction.followup.send(
                embed=error_embed(f"Invalid type. Must be one of: {', '.join(VALID_ITEM_TYPES)}"),
                ephemeral=True,
            )
            return
        if cost < 0:
            await interaction.followup.send(
                embed=error_embed("Cost must be a positive number."), ephemeral=True
            )
            return
        rid = int(role_id) if role_id else None
        item_id = await self.db.add_shop_item(
            interaction.guild_id, name, item_type, cost, rid, days, stock
        )
        log.info(f"Shop item added: #{item_id} '{name}' by {interaction.user}")
        await interaction.followup.send(
            embed=success_embed(
                f"**#{item_id} — {name}**\nType: `{item_type}` | Cost: `{cost:,} CC`"
                + (f" | Duration: {days}d" if days else " | Permanent")
                + (f" | Stock: {stock}" if stock else " | Unlimited"),
                title="Shop Item Added",
            ),
            ephemeral=True,
        )

    @admin_group.command(name="removeitem", description="Soft-delete a shop item by ID")
    @is_admin()
    @app_commands.describe(item_id="Item ID to deactivate")
    async def admin_removeitem(self, interaction: discord.Interaction, item_id: int):
        await interaction.response.defer(ephemeral=True)
        ok = await self.db.deactivate_shop_item(item_id, interaction.guild_id)
        if not ok:
            await interaction.followup.send(
                embed=error_embed(f"No active item with ID `{item_id}` found."), ephemeral=True
            )
            return
        log.info(f"Shop item #{item_id} deactivated by {interaction.user}")
        await interaction.followup.send(
            embed=success_embed(f"Item `#{item_id}` removed from shop. Purchase history preserved."),
            ephemeral=True,
        )

    @admin_group.command(name="eventbonus", description="Toggle 2x XP and CC event bonus")
    @is_admin()
    @app_commands.describe(state="on or off")
    @app_commands.choices(state=[
        app_commands.Choice(name="on", value="on"),
        app_commands.Choice(name="off", value="off"),
    ])
    async def admin_eventbonus(self, interaction: discord.Interaction, state: str):
        await interaction.response.defer()
        val = "true" if state == "on" else "false"
        await self.db.set_config(interaction.guild_id, "event_bonus_active", val)
        status = "**ACTIVATED** — All XP and CC earn rates are now **2×**." if val == "true" \
            else "**DEACTIVATED** — Earn rates returned to normal."
        log.info(f"Event bonus {val} by {interaction.user}")
        await interaction.followup.send(
            embed=info_embed(status, title="⚡ Event Bonus"),
        )

    @admin_group.command(name="grantxp", description="Grant XP to a user (admin audit log)")
    @is_admin()
    @app_commands.describe(user="Target user", amount="XP to grant")
    async def admin_grantxp(self, interaction: discord.Interaction, user: discord.Member, amount: int):
        await interaction.response.defer()
        if amount <= 0:
            await interaction.followup.send(
                embed=error_embed("Amount must be positive."), ephemeral=True
            )
            return
        result = await self.db.update_xp(user.id, interaction.guild_id, amount)
        log.info(f"Admin XP grant: {amount} to {user} by {interaction.user}")
        desc = f"Granted **{amount:,} XP** to {user.mention}\nNew total: **{result['xp']:,} XP** (Level {result['level']})"
        await interaction.followup.send(embed=success_embed(desc, title="XP Granted"))
        if result["leveled_up"]:
            await self._handle_level_up(user, result["level"], interaction.guild)

    @admin_group.command(name="giveall", description="Give credits to every registered user in the server")
    @is_admin()
    @app_commands.describe(
        amount="Amount of CC to give every user",
        confirm="Must be True to execute — this affects all users",
    )
    async def admin_giveall(
        self, interaction: discord.Interaction, amount: int, confirm: bool = False
    ):
        await interaction.response.defer(ephemeral=True)
        if amount <= 0:
            await interaction.followup.send(
                embed=error_embed("Amount must be positive."), ephemeral=True
            )
            return
        if not confirm:
            await interaction.followup.send(
                embed=info_embed(
                    f"This will give **{amount:,} CC** to every registered user in the server.\n"
                    "Run the command again with `confirm: True` to proceed.",
                    title="Confirm Action",
                ),
                ephemeral=True,
            )
            return
        count = await self.db.give_all_credits(interaction.guild_id, amount)
        log.info(f"Admin giveall: {amount} CC to {count} users by {interaction.user}")
        await interaction.followup.send(
            embed=success_embed(
                f"Gave **{amount:,} CC** to **{count}** registered users.",
                title="Credits Distributed",
            ),
        )

    @admin_group.command(name="giveinvestment", description="Grant a user stock shares at no CC cost")
    @is_admin()
    @app_commands.describe(
        user="Target user",
        ticker="Stock ticker symbol (e.g. CYPH)",
        shares="Number of shares to grant",
    )
    async def admin_giveinvestment(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        ticker: str,
        shares: int,
    ):
        await interaction.response.defer(ephemeral=True)
        if shares <= 0:
            await interaction.followup.send(
                embed=error_embed("Shares must be positive."), ephemeral=True
            )
            return
        ok, reason = await self.db.admin_give_stock(user.id, interaction.guild_id, ticker, shares)
        if not ok:
            await interaction.followup.send(
                embed=error_embed(
                    f"Unknown ticker `{ticker.upper()}`. Use `/market` to see valid tickers."
                ),
                ephemeral=True,
            )
            return
        stock = await self.db.get_stock(interaction.guild_id, ticker)
        value = shares * stock["price"]
        log.info(
            f"Admin giveinvestment: {shares}x {ticker.upper()} to {user} by {interaction.user}"
        )
        await interaction.followup.send(
            embed=success_embed(
                f"Granted **{shares:,}× {ticker.upper()}** to {user.mention}\n"
                f"Market value: **{value:,} CC** at `{stock['price']:,} CC/share`",
                title="Investment Granted",
            ),
        )

    @admin_group.command(name="backupdb", description="Create a timestamped backup of the database")
    @is_admin()
    async def admin_backupdb(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            backup_dir = str(Path(self.bot.db.db_path).parent / "backups")
            backup_path = await self.db.backup_database(backup_dir)
            file_size = os.path.getsize(backup_path)
            size_kb = file_size / 1024
            log.info(f"DB backup: {backup_path} ({size_kb:.1f} KB) by {interaction.user}")
            embed = success_embed(
                f"Saved to `{Path(backup_path).name}`\nSize: **{size_kb:.1f} KB**",
                title="Database Backed Up",
            )
            if file_size <= 8 * 1024 * 1024:
                await interaction.followup.send(
                    embed=embed,
                    file=discord.File(backup_path, filename=Path(backup_path).name),
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    embed=success_embed(
                        f"Saved to `{backup_path}`\nSize: **{size_kb / 1024:.2f} MB** "
                        "(too large to attach — retrieve from server).",
                        title="Database Backed Up",
                    ),
                    ephemeral=True,
                )
        except Exception as e:
            log.error(f"Backup failed: {e}", exc_info=True)
            await interaction.followup.send(
                embed=error_embed(f"Backup failed:\n```{e}```"), ephemeral=True
            )

    @admin_group.command(name="serversave", description="Snapshot server roles, channels, and permissions to the database")
    @is_admin()
    @app_commands.describe(label="Optional label for this snapshot (e.g. 'pre-reorg')")
    async def admin_serversave(self, interaction: discord.Interaction, label: str = "snapshot"):
        await interaction.response.defer(ephemeral=True)
        data = self._capture_guild(interaction.guild)
        snapshot_id = await self.db.save_server_snapshot(interaction.guild_id, label, data)
        role_count = len(data["roles"])
        cat_count = len(data["categories"])
        ch_count = len(data["channels"])
        log.info(
            f"Server snapshot #{snapshot_id} '{label}' by {interaction.user} "
            f"({role_count} roles, {cat_count} cats, {ch_count} channels)"
        )
        await interaction.followup.send(
            embed=success_embed(
                f"**Snapshot #{snapshot_id}** — `{label}`\n"
                f"Captured: **{role_count}** roles · **{cat_count}** categories · **{ch_count}** channels",
                title="Server Snapshot Saved",
            ),
            ephemeral=True,
        )

    @admin_group.command(name="serverbackups", description="List saved server snapshots")
    @is_admin()
    async def admin_serverbackups(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        rows = await self.db.get_server_snapshots(interaction.guild_id)
        if not rows:
            await interaction.followup.send(
                embed=info_embed("No snapshots yet. Use `/admin serversave` to create one."),
                ephemeral=True,
            )
            return
        lines = [
            f"**#{r['snapshot_id']}** — `{r['label']}` — "
            f"<t:{int(datetime.fromisoformat(r['created_at']).timestamp())}:f>"
            for r in rows
        ]
        await interaction.followup.send(
            embed=info_embed("\n".join(lines), title=f"Server Snapshots ({len(rows)})"),
            ephemeral=True,
        )

    @admin_group.command(name="serverrestore", description="Wipe all channels/roles and rebuild from a saved snapshot")
    @is_admin()
    @app_commands.describe(
        snapshot_id="Snapshot ID from /admin serverbackups",
        confirm="Must be True to execute — deletes ALL existing channels and roles first",
    )
    async def admin_serverrestore(
        self, interaction: discord.Interaction, snapshot_id: int, confirm: bool = False
    ):
        await interaction.response.defer(ephemeral=True)
        row = await self.db.get_server_snapshot(snapshot_id, interaction.guild_id)
        if not row:
            await interaction.followup.send(
                embed=error_embed(f"Snapshot `#{snapshot_id}` not found."), ephemeral=True
            )
            return

        data = json.loads(row["data"])
        role_count = len([r for r in data["roles"] if not r["managed"]])
        cat_count = len(data["categories"])
        ch_count = len(data["channels"])

        if not confirm:
            await interaction.followup.send(
                embed=info_embed(
                    f"**Snapshot #{snapshot_id}** — `{row['label']}`\n"
                    f"Will restore: **{role_count}** roles · **{cat_count}** categories · **{ch_count}** channels\n\n"
                    "Every existing channel and non-bot role will be deleted first.\n"
                    "The completion report will be sent to your DMs.\n"
                    "Run again with `confirm: True` to proceed.",
                    title="Confirm Full Restore",
                ),
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            embed=info_embed(
                "Wiping existing server structure and rebuilding from snapshot. "
                "The completion report will arrive in your DMs.",
                title="Restore In Progress",
            ),
            ephemeral=True,
        )

        stats = await self._restore_guild(interaction.guild, data)
        log.info(f"Full server restore #{snapshot_id} by {interaction.user}: {stats}")

        error_text = ""
        if stats["errors"]:
            shown = stats["errors"][:10]
            error_text = f"\n\n**{len(stats['errors'])} error(s):**\n" + "\n".join(f"• {e}" for e in shown)
            if len(stats["errors"]) > 10:
                error_text += f"\n*...and {len(stats['errors']) - 10} more*"

        result_embed = success_embed(
            f"Restored from snapshot **#{snapshot_id}** (`{row['label']}`)\n"
            f"Deleted: **{stats['deleted_channels']}** channels · **{stats['deleted_roles']}** roles\n"
            f"Created: **{stats['roles']}** roles · **{stats['categories']}** categories · **{stats['channels']}** channels"
            + error_text,
            title="Server Restore Complete",
        )

        # Original channel is gone — DM the report, fall back to first accessible text channel
        try:
            await interaction.user.send(embed=result_embed)
        except discord.Forbidden:
            for ch in interaction.guild.text_channels:
                try:
                    await ch.send(interaction.user.mention, embed=result_embed)
                    break
                except Exception:
                    continue

    # ─── Server snapshot helpers ──────────────────────────────────────────────

    @staticmethod
    def _capture_guild(guild: discord.Guild) -> dict:
        def serialize_overwrites(ch) -> list:
            out = []
            for target, ow in ch.overwrites.items():
                allow, deny = ow.pair()
                out.append({
                    "target_id": target.id,
                    "target_type": "role" if isinstance(target, discord.Role) else "member",
                    "allow": allow.value,
                    "deny": deny.value,
                })
            return out

        roles = sorted(
            [
                {
                    "id": r.id,
                    "name": r.name,
                    "color": r.color.value,
                    "permissions": r.permissions.value,
                    "position": r.position,
                    "hoist": r.hoist,
                    "mentionable": r.mentionable,
                    "managed": r.managed,
                }
                for r in guild.roles
                if not r.is_default()
            ],
            key=lambda r: r["position"],
        )

        categories = [
            {
                "id": c.id,
                "name": c.name,
                "position": c.position,
                "overwrites": serialize_overwrites(c),
            }
            for c in sorted(guild.categories, key=lambda c: c.position)
        ]

        channels = []
        for ch in sorted(guild.channels, key=lambda c: c.position):
            if isinstance(ch, discord.CategoryChannel):
                continue
            entry = {
                "id": ch.id,
                "name": ch.name,
                "category_id": ch.category_id,
                "position": ch.position,
                "overwrites": serialize_overwrites(ch),
            }
            if isinstance(ch, discord.TextChannel):
                entry.update({
                    "kind": "text",
                    "topic": ch.topic,
                    "nsfw": ch.nsfw,
                    "slowmode_delay": ch.slowmode_delay,
                })
            elif isinstance(ch, discord.VoiceChannel):
                entry.update({"kind": "voice", "bitrate": ch.bitrate, "user_limit": ch.user_limit})
            elif isinstance(ch, discord.StageChannel):
                entry["kind"] = "stage"
            else:
                entry["kind"] = "text"
            channels.append(entry)

        return {
            "guild": {
                "name": guild.name,
                "description": guild.description,
                "verification_level": guild.verification_level.value,
                "everyone_role_id": guild.default_role.id,
            },
            "roles": roles,
            "categories": categories,
            "channels": channels,
        }

    async def _restore_guild(self, guild: discord.Guild, data: dict) -> dict:
        everyone_old_id = data["guild"].get("everyone_role_id")
        role_id_map: dict[int, discord.Role] = {}
        if everyone_old_id:
            role_id_map[everyone_old_id] = guild.default_role

        stats: dict = {
            "deleted_channels": 0, "deleted_roles": 0,
            "roles": 0, "categories": 0, "channels": 0,
            "errors": [],
        }

        # ── Wipe phase ────────────────────────────────────────────────────────
        # Child channels first — categories must be empty before deletion
        for ch in list(guild.channels):
            if isinstance(ch, discord.CategoryChannel):
                continue
            try:
                await ch.delete(reason="Server snapshot restore")
                stats["deleted_channels"] += 1
            except Exception as e:
                stats["errors"].append(f"delete channel '{ch.name}': {e}")

        for cat in list(guild.categories):
            try:
                await cat.delete(reason="Server snapshot restore")
                stats["deleted_channels"] += 1
            except Exception as e:
                stats["errors"].append(f"delete category '{cat.name}': {e}")

        # Delete roles lowest-position first; skip @everyone and managed (bot) roles
        for r in sorted(guild.roles, key=lambda r: r.position):
            if r.is_default() or r.managed:
                continue
            try:
                await r.delete(reason="Server snapshot restore")
                stats["deleted_roles"] += 1
            except Exception as e:
                stats["errors"].append(f"delete role '{r.name}': {e}")

        # ── Create phase ──────────────────────────────────────────────────────
        for r in data["roles"]:
            if r["managed"]:
                continue
            try:
                new_role = await guild.create_role(
                    name=r["name"],
                    color=discord.Color(r["color"]),
                    permissions=discord.Permissions(r["permissions"]),
                    hoist=r["hoist"],
                    mentionable=r["mentionable"],
                    reason="Server snapshot restore",
                )
                role_id_map[r["id"]] = new_role
                stats["roles"] += 1
            except Exception as e:
                stats["errors"].append(f"role '{r['name']}': {e}")

        def map_overwrites(ow_list: list) -> dict:
            result: dict = {}
            for ow in ow_list:
                if ow["target_type"] != "role":
                    continue
                role = role_id_map.get(ow["target_id"])
                if role is None:
                    continue
                result[role] = discord.PermissionOverwrite.from_pair(
                    discord.Permissions(ow["allow"]),
                    discord.Permissions(ow["deny"]),
                )
            return result

        cat_id_map: dict[int, discord.CategoryChannel] = {}
        for c in data["categories"]:
            try:
                new_cat = await guild.create_category(
                    name=c["name"],
                    overwrites=map_overwrites(c["overwrites"]),
                    reason="Server snapshot restore",
                )
                cat_id_map[c["id"]] = new_cat
                stats["categories"] += 1
            except Exception as e:
                stats["errors"].append(f"category '{c['name']}': {e}")

        for ch in data["channels"]:
            try:
                category = cat_id_map.get(ch["category_id"]) if ch["category_id"] else None
                ow = map_overwrites(ch["overwrites"])
                kind = ch.get("kind", "text")
                if kind == "voice":
                    await guild.create_voice_channel(
                        name=ch["name"],
                        overwrites=ow,
                        category=category,
                        bitrate=min(ch.get("bitrate", 64000), 64000),
                        user_limit=ch.get("user_limit", 0),
                        reason="Server snapshot restore",
                    )
                elif kind == "stage":
                    await guild.create_stage_channel(
                        name=ch["name"],
                        overwrites=ow,
                        category=category,
                        reason="Server snapshot restore",
                    )
                else:
                    await guild.create_text_channel(
                        name=ch["name"],
                        overwrites=ow,
                        category=category,
                        topic=ch.get("topic"),
                        nsfw=ch.get("nsfw", False),
                        slowmode_delay=ch.get("slowmode_delay", 0),
                        reason="Server snapshot restore",
                    )
                stats["channels"] += 1
            except Exception as e:
                stats["errors"].append(f"channel '{ch['name']}': {e}")

        return stats

    async def _handle_level_up(self, member: discord.Member, new_level: int, guild: discord.Guild):
        from config import RANK_THRESHOLDS
        rank_name, _ = RANK_THRESHOLDS[new_level]
        rankup_id = await self.db.get_config(guild.id, "rankup_channel_id")
        if rankup_id:
            ch = guild.get_channel(int(rankup_id))
            if ch:
                from utils.embeds import build_embed
                embed = build_embed(
                    title="⚡ RANK UP",
                    description=f"{member.mention} has ascended to **{rank_name}**!",
                    color=0x00B4CC,
                    footer=f"Level {new_level}",
                )
                await ch.send(embed=embed)

    # ─── Prefix equivalents ───────────────────────────────────────────────────

    @commands.group(name="admin", invoke_without_command=True)
    @prefix_is_admin()
    async def prefix_admin(self, ctx: commands.Context):
        await ctx.send(embed=info_embed("Use `/admin <subcommand>`. Available: reload, setconfig, additem, removeitem, eventbonus, grantxp, giveall, giveinvestment, backupdb, serversave, serverbackups, serverrestore"))

    @prefix_admin.command(name="reload")
    @prefix_is_admin()
    async def prefix_reload(self, ctx: commands.Context, cog: str = "all"):
        if cog.lower() == "all":
            for ext in list(self.bot.extensions):
                try:
                    await self.bot.reload_extension(ext)
                except Exception as e:
                    await ctx.send(embed=error_embed(f"Failed: `{ext}`: {e}"))
            await ctx.send(embed=success_embed("All cogs reloaded."))
        else:
            ext = f"cogs.{cog}" if not cog.startswith("cogs.") else cog
            try:
                await self.bot.reload_extension(ext)
                await ctx.send(embed=success_embed(f"Reloaded `{ext}`."))
            except Exception as e:
                await ctx.send(embed=error_embed(f"Failed: {e}"))

    @prefix_admin.command(name="setconfig")
    @prefix_is_admin()
    async def prefix_setconfig(self, ctx: commands.Context, key: str, *, value: str):
        await self.db.set_config(ctx.guild.id, key, value)
        await ctx.send(embed=success_embed(f"`{key}` → `{value}`", title="Config Updated"))

    @prefix_admin.command(name="eventbonus")
    @prefix_is_admin()
    async def prefix_eventbonus(self, ctx: commands.Context, state: str):
        val = "true" if state.lower() == "on" else "false"
        await self.db.set_config(ctx.guild.id, "event_bonus_active", val)
        await ctx.send(embed=info_embed(f"Event bonus set to `{state}`."))

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CheckFailure):
            msg = error_embed("You don't have permission to use this command.")
        else:
            log.error(f"Admin command error: {error}", exc_info=True)
            msg = error_embed("An unexpected error occurred.")

        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=msg, ephemeral=True)
            else:
                await interaction.response.send_message(embed=msg, ephemeral=True)
        except discord.NotFound:
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(Admin(bot))
