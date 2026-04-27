import logging
import secrets
from datetime import datetime, timezone, timedelta

import discord
from discord import app_commands
from discord.ext import commands

from utils.embeds import error_embed, success_embed, info_embed, build_embed, warning_embed

log = logging.getLogger("cypher.games")

MIN_BET = 10
COINFLIP_CD = 30
SLOTS_CD = 60

SYMBOLS = ["⚡", "💎", "⌬", "🔮", "⬡", "⬢"]
WEIGHTS = [1, 2, 3, 5, 7, 10]

_POOL: list[str] = []
for sym, weight in zip(SYMBOLS, WEIGHTS):
    _POOL.extend([sym] * weight)

JACKPOT_BONUS = 1000
XP_WIN_BONUS = 10


class Games(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # {(user_id, guild_id, game): cooldown_expiry}
        self._cooldowns: dict[tuple[int, int, str], datetime] = {}

    @property
    def db(self):
        return self.bot.db

    def _check_cooldown(self, user_id: int, guild_id: int, game: str, cd_secs: int) -> int | None:
        """Returns remaining seconds if on cooldown, else None."""
        key = (user_id, guild_id, game)
        expiry = self._cooldowns.get(key)
        if expiry:
            remaining = (expiry - datetime.now(timezone.utc)).total_seconds()
            if remaining > 0:
                return int(remaining)
        self._cooldowns[key] = datetime.now(timezone.utc) + timedelta(seconds=cd_secs)
        return None

    def _spin_reel() -> str:
        return secrets.choice(_POOL)

    # ─── /coinflip ────────────────────────────────────────────────────────────

    @app_commands.command(name="coinflip", description="Bet Cypher Credits on a coin flip")
    @app_commands.describe(bet="Amount to wager (min 10 CC)", side="heads or tails")
    @app_commands.choices(side=[
        app_commands.Choice(name="heads", value="heads"),
        app_commands.Choice(name="tails", value="tails"),
    ])
    async def coinflip(self, interaction: discord.Interaction, bet: int, side: str):
        await interaction.response.defer()
        if bet < MIN_BET:
            await interaction.followup.send(
                embed=error_embed(f"Minimum bet is **{MIN_BET} CC**."), ephemeral=True
            )
            return

        remaining = self._check_cooldown(interaction.user.id, interaction.guild_id, "coinflip", COINFLIP_CD)
        if remaining:
            await interaction.followup.send(
                embed=warning_embed(f"Cooldown active. Try again in **{remaining}s**.", title="Coinflip Cooldown"),
                ephemeral=True,
            )
            return

        # Deduct BEFORE resolving
        success, new_bal = await self.db.mutate_credits(interaction.user.id, interaction.guild_id, -bet)
        if not success:
            self._cooldowns.pop((interaction.user.id, interaction.guild_id, "coinflip"), None)
            await interaction.followup.send(
                embed=error_embed("Insufficient balance to place this bet."), ephemeral=True
            )
            return

        result = secrets.choice(["heads", "tails"])
        won = result == side

        if won:
            payout = bet * 2
            await self.db.mutate_credits(interaction.user.id, interaction.guild_id, payout)
            await self.db.update_xp(interaction.user.id, interaction.guild_id, XP_WIN_BONUS)
            net = payout - bet
            outcome = "win"
            embed = success_embed(
                f"The coin landed on **{result}**! You guessed **{side}**.\n"
                f"**+{net:,} CC** | Balance: **{new_bal + net:,} CC**",
                title="⚡ Coinflip — WIN",
            )
        else:
            net = -bet
            outcome = "loss"
            embed = error_embed(
                f"The coin landed on **{result}**. You guessed **{side}**.\n"
                f"**-{bet:,} CC** | Balance: **{new_bal:,} CC**",
                title="Coinflip — Loss",
            )

        await self.db.add_game_stat(
            interaction.user.id, interaction.guild_id, "coinflip", bet, outcome, payout if won else 0
        )
        await interaction.followup.send(embed=embed)

    # ─── /slots ───────────────────────────────────────────────────────────────

    @app_commands.command(name="slots", description="Spin the slot machine")
    @app_commands.describe(bet="Amount to wager (min 10 CC)")
    async def slots(self, interaction: discord.Interaction, bet: int):
        await interaction.response.defer()
        if bet < MIN_BET:
            await interaction.followup.send(
                embed=error_embed(f"Minimum bet is **{MIN_BET} CC**."), ephemeral=True
            )
            return

        remaining = self._check_cooldown(interaction.user.id, interaction.guild_id, "slots", SLOTS_CD)
        if remaining:
            await interaction.followup.send(
                embed=warning_embed(f"Cooldown active. Try again in **{remaining}s**.", title="Slots Cooldown"),
                ephemeral=True,
            )
            return

        success, new_bal = await self.db.mutate_credits(interaction.user.id, interaction.guild_id, -bet)
        if not success:
            self._cooldowns.pop((interaction.user.id, interaction.guild_id, "slots"), None)
            await interaction.followup.send(
                embed=error_embed("Insufficient balance to place this bet."), ephemeral=True
            )
            return

        r1 = secrets.choice(_POOL)
        r2 = secrets.choice(_POOL)
        r3 = secrets.choice(_POOL)
        reels = f"[ {r1} | {r2} | {r3} ]"

        payout, outcome, result_text = self._resolve_slots(r1, r2, r3, bet)
        jackpot_bonus = 0

        if payout > 0:
            if outcome == "jackpot":
                jackpot_bonus = JACKPOT_BONUS
                payout += jackpot_bonus
            await self.db.mutate_credits(interaction.user.id, interaction.guild_id, payout)
            await self.db.update_xp(interaction.user.id, interaction.guild_id, XP_WIN_BONUS)
            net = payout - bet
            balance = new_bal + net
            color = 0xFFD700 if outcome == "jackpot" else 0x059669
            title = "⚡⚡⚡ JACKPOT" if outcome == "jackpot" else f"Slots — {result_text}"
            desc = (
                f"{reels}\n\n"
                f"**{result_text}** · Payout: `{payout:,} CC`"
                + (f"\n**+{JACKPOT_BONUS:,} CC JACKPOT BONUS!**" if jackpot_bonus else "")
                + f"\nBalance: **{balance:,} CC**"
            )
            embed = build_embed(title=title, description=desc, color=color)
        else:
            balance = new_bal
            embed = build_embed(
                title="Slots — No Match",
                description=f"{reels}\n\n**No match.** Lost **{bet:,} CC**.\nBalance: **{balance:,} CC**",
                color=0xDC2626,
            )

        await self.db.add_game_stat(
            interaction.user.id, interaction.guild_id, "slots", bet, outcome, payout
        )
        await interaction.followup.send(embed=embed)

    def _resolve_slots(self, r1: str, r2: str, r3: str, bet: int) -> tuple[int, str, str]:
        if r1 == r2 == r3:
            sym = r1
            if sym == "⚡":
                return int(bet * 10), "jackpot", "JACKPOT — Triple Lightning"
            elif sym == "💎":
                return int(bet * 5), "win", "Diamond Match"
            elif sym == "⌬":
                return int(bet * 4), "win", "Cypher Triple"
            else:
                return int(bet * 3), "win", "Triple Match"
        elif r1 == r2 or r2 == r3 or r1 == r3:
            return int(bet * 1.5), "win", "Partial Match"
        else:
            return 0, "loss", "No Match"

    # ─── /gamestats ───────────────────────────────────────────────────────────

    @app_commands.command(name="gamestats", description="View win/loss statistics")
    @app_commands.describe(user="User to check (defaults to you)")
    async def gamestats(self, interaction: discord.Interaction, user: discord.Member | None = None):
        await interaction.response.defer()
        target = user or interaction.user
        rows = await self.db.get_game_stats(target.id, interaction.guild_id)

        if not rows:
            await interaction.followup.send(
                embed=info_embed("No game history found.", title=f"{target.display_name}'s Game Stats"),
                ephemeral=True,
            )
            return

        fields = []
        for row in rows:
            wl = f"{row['wins']}W / {row['losses']}L"
            fields.append((
                row["game"].upper(),
                f"Games: `{row['total_games']}` | W/L: `{wl}`\nWagered: `{row['total_wagered']:,} CC` | Net P&L: `{row['net_pnl']:+,} CC`",
                False,
            ))

        embed = build_embed(
            title=f"⚡ {target.display_name}'s Game Stats",
            color=0x00B4CC,
            fields=fields,
        )
        await interaction.followup.send(embed=embed)

    # ─── Prefix equivalents ───────────────────────────────────────────────────

    @commands.command(name="coinflip", aliases=["cf"])
    async def prefix_coinflip(self, ctx: commands.Context, bet: int, side: str = "heads"):
        side = side.lower()
        if side not in ("heads", "tails"):
            await ctx.send(embed=error_embed("Side must be `heads` or `tails`."))
            return
        if bet < MIN_BET:
            await ctx.send(embed=error_embed(f"Minimum bet: {MIN_BET} CC."))
            return
        remaining = self._check_cooldown(ctx.author.id, ctx.guild.id, "coinflip", COINFLIP_CD)
        if remaining:
            await ctx.send(embed=warning_embed(f"Cooldown: {remaining}s remaining."))
            return
        ok, new_bal = await self.db.mutate_credits(ctx.author.id, ctx.guild.id, -bet)
        if not ok:
            self._cooldowns.pop((ctx.author.id, ctx.guild.id, "coinflip"), None)
            await ctx.send(embed=error_embed("Insufficient balance."))
            return
        result = secrets.choice(["heads", "tails"])
        won = result == side
        if won:
            await self.db.mutate_credits(ctx.author.id, ctx.guild.id, bet * 2)
            await ctx.send(embed=success_embed(f"{result} — YOU WIN! +{bet} CC"))
            await self.db.add_game_stat(ctx.author.id, ctx.guild.id, "coinflip", bet, "win", bet * 2)
        else:
            await ctx.send(embed=error_embed(f"{result} — You lose. -{bet} CC"))
            await self.db.add_game_stat(ctx.author.id, ctx.guild.id, "coinflip", bet, "loss", 0)

    @commands.command(name="slots")
    async def prefix_slots(self, ctx: commands.Context, bet: int):
        if bet < MIN_BET:
            await ctx.send(embed=error_embed(f"Minimum bet: {MIN_BET} CC."))
            return
        remaining = self._check_cooldown(ctx.author.id, ctx.guild.id, "slots", SLOTS_CD)
        if remaining:
            await ctx.send(embed=warning_embed(f"Cooldown: {remaining}s remaining."))
            return
        ok, new_bal = await self.db.mutate_credits(ctx.author.id, ctx.guild.id, -bet)
        if not ok:
            self._cooldowns.pop((ctx.author.id, ctx.guild.id, "slots"), None)
            await ctx.send(embed=error_embed("Insufficient balance."))
            return
        r1, r2, r3 = secrets.choice(_POOL), secrets.choice(_POOL), secrets.choice(_POOL)
        payout, outcome, result_text = self._resolve_slots(r1, r2, r3, bet)
        if payout > 0:
            if outcome == "jackpot":
                payout += JACKPOT_BONUS
            await self.db.mutate_credits(ctx.author.id, ctx.guild.id, payout)
            await ctx.send(embed=success_embed(f"[ {r1} | {r2} | {r3} ] — {result_text}! +{payout} CC"))
        else:
            await ctx.send(embed=error_embed(f"[ {r1} | {r2} | {r3} ] — No match. -{bet} CC"))
        await self.db.add_game_stat(ctx.author.id, ctx.guild.id, "slots", bet, outcome, payout)

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CheckFailure):
            msg = error_embed("You don't have permission to use this command.")
        else:
            log.error(f"Games command error: {error}", exc_info=True)
            msg = error_embed("An unexpected error occurred.")

        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=msg, ephemeral=True)
            else:
                await interaction.response.send_message(embed=msg, ephemeral=True)
        except discord.NotFound:
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(Games(bot))
