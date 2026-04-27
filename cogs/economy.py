import logging
import secrets
from datetime import datetime, timezone, timedelta
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
from utils.checks import is_admin, prefix_is_admin
from utils.embeds import error_embed, success_embed, info_embed, warning_embed, build_embed

log = logging.getLogger("cypher.economy")

MIN_BET = 10
MIN_TRANSFER = 10
DAILY_XP_BONUS = 50
STREAK_7_XP = 150
ITEMS_PER_PAGE = 5


class Economy(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # {(user_id, guild_id): {"earned": int, "reset_at": datetime}}
        self._msg_cc_tracker: dict[tuple[int, int], dict] = {}
        self.expired_roles_task.start()

    def cog_unload(self):
        self.expired_roles_task.cancel()

    @property
    def db(self):
        return self.bot.db

    # ─── Background: purge expired timed roles ────────────────────────────────

    @tasks.loop(minutes=1)
    async def expired_roles_task(self):
        rows = await self.db.get_expired_inventory()
        for row in rows:
            guild = self.bot.get_guild(row["guild_id"])
            if not guild:
                await self.db.remove_inventory(row["inv_id"])
                continue
            role_id = row["role_id"]
            if role_id:
                role = guild.get_role(int(role_id))
                if role:
                    try:
                        member = guild.get_member(row["user_id"]) or await guild.fetch_member(row["user_id"])
                        if role in member.roles:
                            await member.remove_roles(role, reason="Timed item expired")
                    except Exception as e:
                        log.warning(f"Could not remove expired role: {e}")
            await self.db.remove_inventory(row["inv_id"])
            log.info(f"Expired inventory row {row['inv_id']} removed")

    @expired_roles_task.before_loop
    async def before_expired_roles(self):
        await self.bot.wait_until_ready()

    # ─── on_message CC earn ───────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if len(message.content) < 5:
            return

        key = (message.author.id, message.guild.id)
        now = datetime.now(timezone.utc)
        tracker = self._msg_cc_tracker.get(key, {"earned": 0, "reset_at": now + timedelta(hours=1)})

        if now >= tracker["reset_at"]:
            tracker = {"earned": 0, "reset_at": now + timedelta(hours=1)}

        msg_cc_max = 30
        if tracker["earned"] >= msg_cc_max:
            return

        bonus = await self._event_bonus(message.guild.id)
        cc_gain = await self._get_cfg_int(message.guild.id, "msg_credits_per_msg", config.MSG_CREDITS_PER_MSG)
        if bonus:
            cc_gain *= 2

        cc_gain = min(cc_gain, msg_cc_max - tracker["earned"])
        tracker["earned"] += cc_gain
        self._msg_cc_tracker[key] = tracker

        await self.db.mutate_credits(message.author.id, message.guild.id, cc_gain)

    # ─── /balance ─────────────────────────────────────────────────────────────

    @app_commands.command(name="balance", description="Check your Cypher Credits balance")
    @app_commands.describe(user="User to check (defaults to you)")
    async def balance(self, interaction: discord.Interaction, user: discord.Member | None = None):
        target = user or interaction.user
        await self.db.ensure_user(target.id, interaction.guild_id)
        row = await self.db.get_user(target.id, interaction.guild_id)
        embed = build_embed(
            title="⚡ Cypher Credits",
            description=f"{target.mention}\n**Balance:** `{row['credits']:,} CC`\n**Lifetime Earned:** `{row['total_earned']:,} CC`",
            color=0x00B4CC,
            thumbnail=target.display_avatar.url,
        )
        await interaction.response.send_message(embed=embed)

    # ─── /daily ───────────────────────────────────────────────────────────────

    @app_commands.command(name="daily", description="Claim your daily Cypher Credits")
    async def daily(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await self.db.ensure_user(interaction.user.id, interaction.guild_id)
        row = await self.db.get_user(interaction.user.id, interaction.guild_id)
        now = datetime.now(timezone.utc)

        if row["last_daily"]:
            last = datetime.fromisoformat(row["last_daily"])
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            diff = (now - last).total_seconds()
            if diff < 86400:
                remaining = timedelta(seconds=86400 - diff)
                h, rem = divmod(int(remaining.total_seconds()), 3600)
                m = rem // 60
                await interaction.followup.send(
                    embed=warning_embed(
                        f"You already claimed today. Come back in **{h}h {m}m**.",
                        title="Daily Cooldown",
                    ),
                    ephemeral=True,
                )
                return
            # Streak check: claimed within last 48 hours
            if diff <= 172800:
                new_streak = row["daily_streak"] + 1
            else:
                new_streak = 1
        else:
            new_streak = 1

        base = await self._get_cfg_int(interaction.guild_id, "daily_amount", config.DAILY_CREDITS)
        bonus = await self._event_bonus(interaction.guild_id)
        total_cc = base * (2 if bonus else 1)
        xp_gain = DAILY_XP_BONUS
        extra_lines = []

        if new_streak == 7:
            total_cc += 500
            xp_gain += STREAK_7_XP
            extra_lines.append("🔥 **7-day streak bonus: +500 CC, +150 XP!**")
        elif new_streak == 30:
            total_cc += 1500
            extra_lines.append("⚡ **30-day streak bonus: +1,500 CC!**")

        await self.db.update_daily(interaction.user.id, interaction.guild_id, new_streak)
        await self.db.mutate_credits(interaction.user.id, interaction.guild_id, total_cc)
        await self.db.update_xp(interaction.user.id, interaction.guild_id, xp_gain)

        new_balance = await self.db.get_balance(interaction.user.id, interaction.guild_id)
        desc_lines = [
            f"**+{total_cc:,} CC** claimed!",
            f"Streak: **{new_streak} day{'s' if new_streak != 1 else ''}** 🔥",
            f"Balance: **{new_balance:,} CC**",
        ] + extra_lines

        await interaction.followup.send(
            embed=success_embed("\n".join(desc_lines), title="Daily Reward Claimed")
        )

    # ─── /pay ─────────────────────────────────────────────────────────────────

    @app_commands.command(name="pay", description="Transfer Cypher Credits to another user")
    @app_commands.describe(user="Recipient", amount="CC to send (minimum 10)")
    async def pay(self, interaction: discord.Interaction, user: discord.Member, amount: int):
        if user.bot or user.id == interaction.user.id:
            await interaction.response.send_message(
                embed=error_embed("You can't transfer credits to yourself or a bot."), ephemeral=True
            )
            return
        if amount < MIN_TRANSFER:
            await interaction.response.send_message(
                embed=error_embed(f"Minimum transfer is **{MIN_TRANSFER} CC**."), ephemeral=True
            )
            return

        success, new_bal = await self.db.mutate_credits(interaction.user.id, interaction.guild_id, -amount)
        if not success:
            await interaction.response.send_message(
                embed=error_embed("Insufficient balance for this transfer."), ephemeral=True
            )
            return

        await self.db.mutate_credits(user.id, interaction.guild_id, amount)
        log.info(f"Transfer: {interaction.user} → {user} {amount} CC")
        await interaction.response.send_message(
            embed=success_embed(
                f"Transferred **{amount:,} CC** to {user.mention}\nYour balance: **{new_bal:,} CC**",
                title="Transfer Complete",
            )
        )

    # ─── /shop ────────────────────────────────────────────────────────────────

    @app_commands.command(name="shop", description="Browse available shop items")
    @app_commands.describe(page="Page number")
    async def shop(self, interaction: discord.Interaction, page: int = 1):
        if page < 1:
            page = 1
        offset = (page - 1) * ITEMS_PER_PAGE
        items = await self.db.get_shop_items(interaction.guild_id, active_only=True, limit=ITEMS_PER_PAGE, offset=offset)
        total = await self.db.count_shop_items(interaction.guild_id)
        total_pages = max(1, (total + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)

        if not items:
            await interaction.response.send_message(
                embed=info_embed("The shop is currently empty. Check back later.", title="Shop"), ephemeral=True
            )
            return

        lines = []
        for item in items:
            stock_str = f"Stock: {item['stock']}" if item["stock"] is not None else "Unlimited"
            dur_str = f"{item['duration_days']}d" if item["duration_days"] else "Permanent"
            lines.append(
                f"**#{item['item_id']} — {item['name']}**\n"
                f"> `{item['cost']:,} CC` · {item['type'].upper()} · {dur_str} · {stock_str}"
            )

        embed = build_embed(
            title="⚡ Cypher Shop",
            description="\n\n".join(lines),
            color=0x00B4CC,
            footer=f"Page {page}/{total_pages} · Use /buy <item_id> to purchase",
        )
        view = _ShopView(self, interaction.guild_id, page, total_pages)
        await interaction.response.send_message(embed=embed, view=view)

    # ─── /buy ─────────────────────────────────────────────────────────────────

    @app_commands.command(name="buy", description="Purchase a shop item by ID")
    @app_commands.describe(item_id="Item ID from /shop")
    async def buy(self, interaction: discord.Interaction, item_id: int):
        await interaction.response.defer()
        item = await self.db.get_shop_item(item_id)
        if not item or not item["active"] or item["guild_id"] != interaction.guild_id:
            await interaction.followup.send(embed=error_embed(f"Item `#{item_id}` not found in the shop."), ephemeral=True)
            return

        if item["stock"] is not None and item["stock"] <= 0:
            await interaction.followup.send(embed=error_embed("This item is out of stock."), ephemeral=True)
            return

        success, new_bal = await self.db.mutate_credits(interaction.user.id, interaction.guild_id, -item["cost"])
        if not success:
            bal = await self.db.get_balance(interaction.user.id, interaction.guild_id)
            await interaction.followup.send(
                embed=error_embed(
                    f"Insufficient balance. Item costs **{item['cost']:,} CC**, you have **{bal:,} CC**."
                ),
                ephemeral=True,
            )
            return

        expires_at: Optional[datetime] = None
        if item["duration_days"]:
            expires_at = datetime.now(timezone.utc) + timedelta(days=item["duration_days"])

        await self.db.add_inventory(interaction.user.id, interaction.guild_id, item_id, expires_at)
        await self.db.decrement_stock(item_id)

        # Assign Discord role if applicable
        if item["role_id"]:
            role = interaction.guild.get_role(int(item["role_id"]))
            if role:
                try:
                    await interaction.user.add_roles(role, reason=f"Purchased: {item['name']}")
                except discord.Forbidden:
                    log.warning(f"Cannot assign role {role} to {interaction.user}")

        # Loot crate special handling
        if item["type"] == "crate":
            embed = await self._resolve_loot_crate(interaction.user, interaction.guild_id, item)
        else:
            dur_str = f"{item['duration_days']} days" if item["duration_days"] else "permanent"
            embed = success_embed(
                f"Purchased **{item['name']}** for `{item['cost']:,} CC`\n"
                f"Duration: **{dur_str}**\nBalance: **{new_bal:,} CC**",
                title="Purchase Complete",
            )

        log.info(f"{interaction.user} purchased #{item_id} ({item['name']}) for {item['cost']} CC")
        await interaction.followup.send(embed=embed)

    async def _resolve_loot_crate(self, user: discord.Member, guild_id: int, item) -> discord.Embed:
        pool = (
            ["small"] * 50 +
            ["medium"] * 25 +
            ["large"] * 15 +
            ["role"] * 8 +
            ["jackpot"] * 2
        )
        outcome = secrets.choice(pool)

        if outcome == "small":
            reward_cc = secrets.randbelow(101) + 50
            await self.db.mutate_credits(user.id, guild_id, reward_cc)
            return build_embed(
                title="📦 Loot Crate Opened",
                description=f"_Decrypting payload..._\n\n**Signal intercepted: +{reward_cc} CC**\nSmall data packet recovered.",
                color=0x00B4CC,
            )
        elif outcome == "medium":
            reward_cc = secrets.randbelow(201) + 200
            await self.db.mutate_credits(user.id, guild_id, reward_cc)
            return build_embed(
                title="📦 Loot Crate Opened",
                description=f"_Deep scan complete..._\n\n**Encrypted vault cracked: +{reward_cc} CC**\nMedium payload extracted.",
                color=0x059669,
            )
        elif outcome == "large":
            reward_cc = secrets.randbelow(301) + 500
            await self.db.mutate_credits(user.id, guild_id, reward_cc)
            return build_embed(
                title="📦 Loot Crate Opened",
                description=f"_Core memory accessed..._\n\n**Neural cache breached: +{reward_cc} CC**\nLarge payload unlocked.",
                color=0xD97706,
            )
        elif outcome == "role":
            timed_roles = await self.db.get_random_timed_roles(guild_id)
            if timed_roles:
                chosen = secrets.choice(timed_roles)
                expires_at = datetime.now(timezone.utc) + timedelta(days=3)
                await self.db.add_inventory(user.id, guild_id, chosen["item_id"], expires_at)
                if chosen["role_id"]:
                    guild = user.guild
                    role = guild.get_role(int(chosen["role_id"]))
                    if role:
                        try:
                            await user.add_roles(role, reason="Loot crate reward")
                        except discord.Forbidden:
                            pass
                return build_embed(
                    title="📦 Loot Crate Opened",
                    description=f"_Access granted..._\n\n**Temporary clearance unlocked:** {chosen['name']}\nDuration: 3 days.",
                    color=0x00B4CC,
                )
            else:
                reward_cc = 100
                await self.db.mutate_credits(user.id, guild_id, reward_cc)
                return build_embed(
                    title="📦 Loot Crate Opened",
                    description=f"_No roles available. Compensation issued._\n\n**+{reward_cc} CC**",
                    color=0x00B4CC,
                )
        else:  # jackpot
            reward_cc = 1000
            xp_bonus = 100
            await self.db.mutate_credits(user.id, guild_id, reward_cc)
            await self.db.update_xp(user.id, guild_id, xp_bonus)
            return build_embed(
                title="⚡ JACKPOT — Loot Crate",
                description=f"_SYSTEM BREACH DETECTED..._\n\n**ROOT ACCESS ACHIEVED**\n+{reward_cc} CC + {xp_bonus} XP\nYou found the god key.",
                color=0xFFD700,
            )

    # ─── /inventory ───────────────────────────────────────────────────────────

    @app_commands.command(name="inventory", description="View your purchased items")
    @app_commands.describe(user="User to check (defaults to you)")
    async def inventory(self, interaction: discord.Interaction, user: discord.Member | None = None):
        target = user or interaction.user
        items = await self.db.get_inventory(target.id, interaction.guild_id)
        if not items:
            await interaction.response.send_message(
                embed=info_embed("No items in inventory.", title=f"{target.display_name}'s Inventory"),
                ephemeral=True,
            )
            return
        lines = []
        for item in items:
            exp = (
                f"Expires: <t:{int(datetime.fromisoformat(item['expires_at']).timestamp())}:R>"
                if item["expires_at"]
                else "Permanent"
            )
            lines.append(f"**{item['name']}** (`{item['type']}`) — {exp}")
        embed = build_embed(
            title=f"⚡ {target.display_name}'s Inventory",
            description="\n".join(lines),
            color=0x00B4CC,
        )
        await interaction.response.send_message(embed=embed)

    # ─── /richlist ────────────────────────────────────────────────────────────

    @app_commands.command(name="richlist", description="Top 10 users by lifetime credits earned")
    async def richlist(self, interaction: discord.Interaction):
        rows = await self.db.get_richlist(interaction.guild_id)
        if not rows:
            await interaction.response.send_message(embed=info_embed("No data yet.", title="Rich List"), ephemeral=True)
            return
        lines = []
        for i, row in enumerate(rows, 1):
            m = interaction.guild.get_member(row["user_id"])
            name = m.display_name if m else f"User#{row['user_id']}"
            lines.append(f"`{i:>2}.` **{name}** — {row['total_earned']:,} CC lifetime")
        await interaction.response.send_message(
            embed=build_embed(title="⚡ Rich List", description="\n".join(lines), color=0xD97706)
        )

    # ─── /give & /take (admin) ────────────────────────────────────────────────

    @app_commands.command(name="give", description="Admin: grant CC to a user (no deduction)")
    @is_admin()
    @app_commands.describe(user="Target user", amount="CC to grant")
    async def give(self, interaction: discord.Interaction, user: discord.Member, amount: int):
        if amount <= 0:
            await interaction.response.send_message(embed=error_embed("Amount must be positive."), ephemeral=True)
            return
        new_bal = await self.db.admin_mutate_credits(user.id, interaction.guild_id, amount)
        log.info(f"Admin give: {amount} CC to {user} by {interaction.user}")
        await interaction.response.send_message(
            embed=success_embed(f"Granted **{amount:,} CC** to {user.mention}\nBalance: **{new_bal:,} CC**")
        )

    @app_commands.command(name="take", description="Admin: remove CC from a user (floors at 0)")
    @is_admin()
    @app_commands.describe(user="Target user", amount="CC to remove")
    async def take(self, interaction: discord.Interaction, user: discord.Member, amount: int):
        if amount <= 0:
            await interaction.response.send_message(embed=error_embed("Amount must be positive."), ephemeral=True)
            return
        new_bal = await self.db.admin_mutate_credits(user.id, interaction.guild_id, -amount)
        log.info(f"Admin take: {amount} CC from {user} by {interaction.user}")
        await interaction.response.send_message(
            embed=success_embed(f"Removed **{amount:,} CC** from {user.mention}\nBalance: **{new_bal:,} CC**")
        )

    # ─── Prefix equivalents ───────────────────────────────────────────────────

    @commands.command(name="balance", aliases=["bal", "cc"])
    async def prefix_balance(self, ctx: commands.Context, user: discord.Member | None = None):
        target = user or ctx.author
        row = await self.db.get_user(target.id, ctx.guild.id)
        if not row:
            await ctx.send(embed=info_embed("No account found."))
            return
        await ctx.send(embed=info_embed(f"**{target.display_name}**: {row['credits']:,} CC", title="Balance"))

    @commands.command(name="daily")
    async def prefix_daily(self, ctx: commands.Context):
        # Reuse slash command logic via a fake interaction is complex; simplified prefix version:
        await self.db.ensure_user(ctx.author.id, ctx.guild.id)
        row = await self.db.get_user(ctx.author.id, ctx.guild.id)
        now = datetime.now(timezone.utc)
        if row["last_daily"]:
            last = datetime.fromisoformat(row["last_daily"])
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            if (now - last).total_seconds() < 86400:
                await ctx.send(embed=warning_embed("Daily already claimed. Use `/daily` to see time remaining."))
                return
            new_streak = row["daily_streak"] + 1 if (now - last).total_seconds() <= 172800 else 1
        else:
            new_streak = 1
        base = config.DAILY_CREDITS
        total_cc = base + (500 if new_streak == 7 else 1500 if new_streak == 30 else 0)
        await self.db.update_daily(ctx.author.id, ctx.guild.id, new_streak)
        await self.db.mutate_credits(ctx.author.id, ctx.guild.id, total_cc)
        await ctx.send(embed=success_embed(f"+{total_cc:,} CC claimed! Streak: {new_streak}d"))

    @commands.command(name="pay")
    async def prefix_pay(self, ctx: commands.Context, user: discord.Member, amount: int):
        if amount < MIN_TRANSFER:
            await ctx.send(embed=error_embed(f"Minimum transfer: {MIN_TRANSFER} CC"))
            return
        success, _ = await self.db.mutate_credits(ctx.author.id, ctx.guild.id, -amount)
        if not success:
            await ctx.send(embed=error_embed("Insufficient balance."))
            return
        await self.db.mutate_credits(user.id, ctx.guild.id, amount)
        await ctx.send(embed=success_embed(f"Sent {amount:,} CC to {user.display_name}."))

    @commands.command(name="shop")
    async def prefix_shop(self, ctx: commands.Context, page: int = 1):
        items = await self.db.get_shop_items(ctx.guild.id, active_only=True, limit=ITEMS_PER_PAGE, offset=(page-1)*ITEMS_PER_PAGE)
        if not items:
            await ctx.send(embed=info_embed("Shop is empty."))
            return
        lines = [f"#{i['item_id']} **{i['name']}** — {i['cost']:,} CC" for i in items]
        await ctx.send(embed=build_embed(title="⚡ Shop", description="\n".join(lines), color=0x00B4CC))

    @commands.command(name="give")
    @prefix_is_admin()
    async def prefix_give(self, ctx: commands.Context, user: discord.Member, amount: int):
        new_bal = await self.db.admin_mutate_credits(user.id, ctx.guild.id, amount)
        await ctx.send(embed=success_embed(f"Gave {amount:,} CC to {user.display_name}. Balance: {new_bal:,}"))

    @commands.command(name="take")
    @prefix_is_admin()
    async def prefix_take(self, ctx: commands.Context, user: discord.Member, amount: int):
        new_bal = await self.db.admin_mutate_credits(user.id, ctx.guild.id, -amount)
        await ctx.send(embed=success_embed(f"Removed {amount:,} CC from {user.display_name}. Balance: {new_bal:,}"))

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
            log.error(f"Economy command error: {error}", exc_info=True)
            msg = error_embed("An unexpected error occurred.")

        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=msg, ephemeral=True)
            else:
                await interaction.response.send_message(embed=msg, ephemeral=True)
        except discord.NotFound:
            pass


class _ShopView(discord.ui.View):
    def __init__(self, cog: Economy, guild_id: int, page: int, total_pages: int):
        super().__init__(timeout=60)
        self.cog = cog
        self.guild_id = guild_id
        self.page = page
        self.total_pages = total_pages

    @discord.ui.button(label="◀ Previous", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page <= 1:
            await interaction.response.defer()
            return
        self.page -= 1
        await self._update(interaction)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page >= self.total_pages:
            await interaction.response.defer()
            return
        self.page += 1
        await self._update(interaction)

    async def _update(self, interaction: discord.Interaction):
        offset = (self.page - 1) * ITEMS_PER_PAGE
        items = await self.cog.db.get_shop_items(self.guild_id, limit=ITEMS_PER_PAGE, offset=offset)
        if not items:
            await interaction.response.defer()
            return
        lines = []
        for item in items:
            dur_str = f"{item['duration_days']}d" if item["duration_days"] else "Permanent"
            stock_str = f"Stock: {item['stock']}" if item["stock"] is not None else "Unlimited"
            lines.append(
                f"**#{item['item_id']} — {item['name']}**\n"
                f"> `{item['cost']:,} CC` · {item['type'].upper()} · {dur_str} · {stock_str}"
            )
        embed = build_embed(
            title="⚡ Cypher Shop",
            description="\n\n".join(lines),
            color=0x00B4CC,
            footer=f"Page {self.page}/{self.total_pages} · Use /buy <item_id>",
        )
        await interaction.response.edit_message(embed=embed, view=self)


async def setup(bot: commands.Bot):
    await bot.add_cog(Economy(bot))
