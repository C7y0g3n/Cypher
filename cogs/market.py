import logging
import math
import random
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
from utils.embeds import build_embed, error_embed, success_embed

log = logging.getLogger("cypher.market")

_PRICE_FLOOR = 10
_TICK_MINUTES = 30


def _next_price(current: int, base: int, volatility: float) -> int:
    ratio = current / base
    if ratio > 2.0:
        drift = -0.015
    elif ratio < 0.5:
        drift = 0.015
    else:
        drift = 0.0
    ret = random.gauss(drift, volatility)
    return max(_PRICE_FLOOR, round(current * math.exp(ret)))


def _change_str(current: int, prev: int) -> str:
    if prev == 0:
        return ""
    pct = (current - prev) / prev * 100
    arrow = "▲" if pct >= 0 else "▼"
    return f"{arrow} {abs(pct):.1f}%"


def _change_color(current: int, prev: int) -> int:
    if current >= prev:
        return 0x059669
    return 0xDC2626


class MarketCog(commands.Cog, name="Market"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.price_tick.start()

    def cog_unload(self):
        self.price_tick.cancel()

    @property
    def db(self):
        return self.bot.db

    # ─── Background price tick ────────────────────────────────────────────────

    @tasks.loop(minutes=_TICK_MINUTES)
    async def price_tick(self):
        guild = self.bot.get_guild(config.GUILD_ID)
        if not guild:
            return

        stocks = await self.db.get_stocks(guild.id)
        if not stocks:
            return

        lines = []
        for s in stocks:
            new_price = _next_price(s["price"], s["base_price"], s["volatility"])
            await self.db.update_stock_price(guild.id, s["ticker"], new_price)
            await self.db.add_stock_history(guild.id, s["ticker"], new_price)
            change = _change_str(new_price, s["price"])
            lines.append(f"`{s['ticker']:<4}` **{s['name']}** — `{new_price:,} CC`  {change}")

        channel_id = config.MARKET_CHANNEL_ID
        if not channel_id:
            return
        channel = guild.get_channel(channel_id)
        if not channel:
            return

        embed = build_embed(
            title="⚡ Market Update",
            description="\n".join(lines),
            color=0x00B4CC,
            footer=f"Next update in {_TICK_MINUTES} min",
        )
        try:
            await channel.send(embed=embed)
        except discord.Forbidden:
            log.warning("Cannot post market update — missing send permission")

    @price_tick.before_loop
    async def before_price_tick(self):
        await self.bot.wait_until_ready()
        guild = self.bot.get_guild(config.GUILD_ID)
        if guild:
            await self.db.seed_stocks(guild.id)

    # ─── /market ──────────────────────────────────────────────────────────────

    @app_commands.command(name="market", description="View current stock prices")
    async def market(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        stocks = await self.db.get_stocks(interaction.guild_id)
        if not stocks:
            await interaction.followup.send(
                embed=error_embed("No stocks available yet."), ephemeral=True
            )
            return

        lines = []
        for s in stocks:
            change = _change_str(s["price"], s["prev_price"])
            lines.append(
                f"`{s['ticker']:<4}` **{s['name']}**\n"
                f"> Price: `{s['price']:,} CC`  {change}"
            )

        embed = build_embed(
            title="⚡ Cypher Market",
            description="\n\n".join(lines),
            color=0x00B4CC,
            footer=f"Use /invest <ticker> <amount> to buy · /divest <ticker> <shares> to sell",
        )
        await interaction.followup.send(embed=embed)

    # ─── /invest ──────────────────────────────────────────────────────────────

    @app_commands.command(name="invest", description="Spend CC to buy shares of a stock")
    @app_commands.describe(ticker="Stock ticker (e.g. NEON)", amount="CC to spend")
    async def invest(self, interaction: discord.Interaction, ticker: str, amount: int):
        if amount <= 0:
            await interaction.response.send_message(
                embed=error_embed("Amount must be positive."), ephemeral=True
            )
            return

        await interaction.response.defer(thinking=True)

        stock = await self.db.get_stock(interaction.guild_id, ticker)
        if not stock:
            await interaction.followup.send(
                embed=error_embed(f"Unknown ticker `{ticker.upper()}`. Use `/market` to see available stocks."),
                ephemeral=True,
            )
            return

        shares = amount // stock["price"]
        if shares < 1:
            await interaction.followup.send(
                embed=error_embed(
                    f"**{ticker.upper()}** costs `{stock['price']:,} CC` per share — "
                    f"you need at least that much to buy 1 share."
                ),
                ephemeral=True,
            )
            return

        actual_cost = shares * stock["price"]
        ok, reason = await self.db.buy_stock(
            interaction.user.id, interaction.guild_id, ticker, shares, actual_cost
        )
        if not ok:
            bal = await self.db.get_balance(interaction.user.id, interaction.guild_id)
            await interaction.followup.send(
                embed=error_embed(
                    f"Insufficient funds. You have `{bal:,} CC`, this costs `{actual_cost:,} CC`."
                ),
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            embed=success_embed(
                f"Bought **{shares:,} share{'s' if shares != 1 else ''}** of `{stock['ticker']}` "
                f"(**{stock['name']}**) for `{actual_cost:,} CC`\n"
                f"Price per share: `{stock['price']:,} CC`",
                title="Investment Complete",
            )
        )

    # ─── /divest ──────────────────────────────────────────────────────────────

    @app_commands.command(name="divest", description="Sell shares of a stock for CC")
    @app_commands.describe(ticker="Stock ticker (e.g. NEON)", shares="Number of shares to sell")
    async def divest(self, interaction: discord.Interaction, ticker: str, shares: int):
        if shares <= 0:
            await interaction.response.send_message(
                embed=error_embed("Shares must be positive."), ephemeral=True
            )
            return

        await interaction.response.defer(thinking=True)

        stock = await self.db.get_stock(interaction.guild_id, ticker)
        if not stock:
            await interaction.followup.send(
                embed=error_embed(f"Unknown ticker `{ticker.upper()}`."), ephemeral=True
            )
            return

        holding = await self.db.get_holding(interaction.user.id, interaction.guild_id, ticker)
        if not holding or holding["shares"] < shares:
            owned = holding["shares"] if holding else 0
            await interaction.followup.send(
                embed=error_embed(
                    f"You only own **{owned:,} share{'s' if owned != 1 else ''}** of `{ticker.upper()}`."
                ),
                ephemeral=True,
            )
            return

        proceeds = shares * stock["price"]
        avg = holding["avg_cost"]
        pnl = (stock["price"] - avg) * shares
        pnl_sign = "+" if pnl >= 0 else ""

        ok, _ = await self.db.sell_stock(
            interaction.user.id, interaction.guild_id, ticker, shares, proceeds
        )
        if not ok:
            await interaction.followup.send(
                embed=error_embed("Sale failed — please try again."), ephemeral=True
            )
            return

        await interaction.followup.send(
            embed=success_embed(
                f"Sold **{shares:,} share{'s' if shares != 1 else ''}** of `{stock['ticker']}` "
                f"(**{stock['name']}**)\n"
                f"Proceeds: `{proceeds:,} CC` · P&L: `{pnl_sign}{pnl:,.0f} CC`",
                title="Sale Complete",
            )
        )

    # ─── /portfolio ───────────────────────────────────────────────────────────

    @app_commands.command(name="portfolio", description="View your stock holdings")
    @app_commands.describe(user="User to check (defaults to you)")
    async def portfolio(self, interaction: discord.Interaction, user: discord.Member | None = None):
        await interaction.response.defer(thinking=True)
        target = user or interaction.user
        holdings = await self.db.get_holdings(target.id, interaction.guild_id)

        if not holdings:
            await interaction.followup.send(
                embed=build_embed(
                    title=f"⚡ {target.display_name}'s Portfolio",
                    description="No holdings. Use `/invest <ticker> <amount>` to get started.",
                    color=0x00B4CC,
                ),
                ephemeral=(target == interaction.user),
            )
            return

        total_value = 0
        total_cost = 0
        lines = []
        for h in holdings:
            value = h["shares"] * h["current_price"]
            cost = h["shares"] * h["avg_cost"]
            pnl = value - cost
            pnl_sign = "+" if pnl >= 0 else ""
            total_value += value
            total_cost += cost
            lines.append(
                f"`{h['ticker']:<4}` **{h['name']}** — {h['shares']:,} shares\n"
                f"> Value: `{value:,.0f} CC` · Avg cost: `{h['avg_cost']:,.1f}` · "
                f"P&L: `{pnl_sign}{pnl:,.0f} CC`"
            )

        total_pnl = total_value - total_cost
        pnl_sign = "+" if total_pnl >= 0 else ""
        color = 0x059669 if total_pnl >= 0 else 0xDC2626

        embed = build_embed(
            title=f"⚡ {target.display_name}'s Portfolio",
            description="\n\n".join(lines),
            color=color,
            footer=f"Total value: {total_value:,.0f} CC  ·  Total P&L: {pnl_sign}{total_pnl:,.0f} CC",
            thumbnail=target.display_avatar.url,
        )
        await interaction.followup.send(embed=embed)

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CheckFailure):
            msg = error_embed("You don't have permission to use this command.")
        elif isinstance(error, app_commands.CommandInvokeError) and isinstance(error.original, discord.NotFound):
            log.warning(f"Interaction expired for {interaction.user} in /invest: {error}")
            return
        else:
            log.error(f"Market command error: {error}", exc_info=True)
            msg = error_embed("An unexpected error occurred.")

        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(embed=msg, ephemeral=True)
            else:
                await interaction.followup.send(embed=msg, ephemeral=True)
        except discord.NotFound:
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(MarketCog(bot))
