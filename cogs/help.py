import logging

import discord
from discord import app_commands
from discord.ext import commands

from utils.embeds import build_embed

log = logging.getLogger("cypher.help")

CYAN   = 0x00B4CC
PURPLE = 0x7C3AED
GREEN  = 0x059669
ORANGE = 0xD97706
RED    = 0xDC2626

# ─── Per-category page data ────────────────────────────────────────────────────

PAGES: dict[str, dict] = {
    "economy": {
        "label": "Economy",
        "emoji": "💰",
        "desc_short": "Credits, shop & transfers",
        "color": GREEN,
        "intro": "Earn, spend, and transfer **Cypher Credits (CC)** around the server.",
        "fields": [
            ("Commands", (
                "`/balance [user]` — Check your or another user's CC balance\n"
                "`/daily` — Claim daily CC *(streak bonuses apply)*\n"
                "`/pay <user> <amount>` — Send CC to another user *(min 10)*\n"
                "`/shop [page]` — Browse available shop items\n"
                "`/buy <item_id>` — Purchase an item from the shop\n"
                "`/inventory [user]` — View purchased items\n"
                "`/richlist` — Top 10 users by lifetime CC earned"
            ), False),
            ("Admin Only", (
                "`/give <user> <amount>` — Grant CC to a user\n"
                "`/take <user> <amount>` — Remove CC from a user"
            ), False),
        ],
    },
    "games": {
        "label": "Games",
        "emoji": "🎮",
        "desc_short": "Gambling & casino games",
        "color": PURPLE,
        "intro": "Risk your **Cypher Credits** in a variety of casino-style games.",
        "fields": [
            ("Commands", (
                "`/coinflip <bet> [side]` — Bet CC on a coin flip *(heads/tails)*\n"
                "`/slots <bet>` — Spin the slot machine *(jackpot available)*\n"
                "`/gamestats [user]` — View win/loss stats across all games"
            ), False),
            ("Notes", (
                "Minimum bet is **10 CC**. Winnings are paid out immediately.\n"
                "Slots jackpot pays **50×** your bet on triple 💎."
            ), False),
        ],
    },
    "ranks": {
        "label": "Ranks & XP",
        "emoji": "⭐",
        "desc_short": "XP, levels & leaderboards",
        "color": CYAN,
        "intro": "Earn **XP** by chatting and in voice. Level up to unlock rank roles.",
        "fields": [
            ("Commands", (
                "`/rank [user]` — Display your rank card with XP progress\n"
                "`/leaderboard` — Top 10 users by XP\n"
                "`/rankinfo` — List all rank tiers and their XP thresholds"
            ), False),
            ("Admin Only", (
                "`/xp add <user> <amount>` — Grant XP to a user\n"
                "`/xp remove <user> <amount>` — Remove XP from a user\n"
                "`/xp set <user> <amount>` — Set a user's XP to an exact value\n"
                "`/admin grantxp <user> <amount>` — Grant XP with an audit log entry"
            ), False),
            ("How XP is Earned", (
                "**Messages** — 15–25 XP per message *(60s cooldown)*\n"
                "**Voice** — 5 XP per minute in a voice channel\n"
                "**Daily** — Bonus XP on `/daily` *(streak bonuses at 7 days)*"
            ), False),
        ],
    },
    "moderation": {
        "label": "Moderation",
        "emoji": "🔨",
        "desc_short": "Mod tools — requires Mod role",
        "color": ORANGE,
        "intro": "Server moderation tools. Most commands require the **Mod** or **Admin** role.",
        "fields": [
            ("Punishments  *(Mod+)*", (
                "`/warn <user> <reason>` — Issue a formal warning *(auto-escalates at 3 & 5)*\n"
                "`/timeout <user> <duration> [reason]` — Temporarily mute a user\n"
                "`/untimeout <user>` — Remove an active timeout\n"
                "`/kick <user> [reason]` — Kick a user from the server\n"
                "`/ban <user> [reason]` — Permanently ban a user\n"
                "`/unban <user_id>` — Unban a user by Discord ID"
            ), False),
            ("Channel Tools  *(Mod+)*", (
                "`/purge <amount>` — Bulk-delete up to 100 messages\n"
                "`/slowmode <seconds>` — Set slowmode *(0 to disable, max 21600)*\n"
                "`/lock [channel]` — Prevent @everyone from sending messages\n"
                "`/unlock [channel]` — Restore @everyone send permissions"
            ), False),
            ("Logs  *(Mod+)*", (
                "`/warns <user>` — View a user's warning history\n"
                "`/modlogs <user>` — View a user's full moderation history\n"
                "`/delwarn <log_id>` — Delete a warning entry *(Admin only)*"
            ), False),
        ],
    },
    "market": {
        "label": "Market",
        "emoji": "📈",
        "desc_short": "Stocks & investments",
        "color": GREEN,
        "intro": "Buy and sell **simulated stocks** using Cypher Credits. Prices fluctuate over time.",
        "fields": [
            ("Commands", (
                "`/market` — View current stock prices and trends\n"
                "`/invest <ticker> <amount>` — Spend CC to buy shares of a stock\n"
                "`/divest <ticker> <shares>` — Sell shares and receive CC\n"
                "`/portfolio [user]` — View your current stock holdings"
            ), False),
            ("Available Tickers", (
                "`NEON` NeonTech Industries  |  `GRID` GridCore Systems\n"
                "`CYPH` CypherData Corp  |  `WIRE` WireNet Solutions\n"
                "`ARCH` Archon AI  |  `VOID` VoidSec Holdings"
            ), False),
        ],
    },
    "ai": {
        "label": "AI Chat",
        "emoji": "🤖",
        "desc_short": "Chat with Cypher AI",
        "color": CYAN,
        "intro": "Have a conversation or ask questions powered by **Cypher AI** (Gemini).",
        "fields": [
            ("Commands", (
                "`/ask <message>` — Send a message to Cypher AI and get a response\n"
                "`/ai_status` — Check whether the AI engine is online"
            ), False),
            ("Notes", (
                "The AI requires a valid Gemini API key configured on the server.\n"
                "Responses may take a moment depending on load."
            ), False),
        ],
    },
    "applications": {
        "label": "Applications",
        "emoji": "📋",
        "desc_short": "Staff mod applications",
        "color": CYAN,
        "intro": "Apply to become a server moderator via a guided DM interview.",
        "fields": [
            ("For Everyone", (
                "`/apply` — Start the moderator application process via DM\n"
                "You'll be asked **10 questions** — type `cancel` at any time to withdraw."
            ), False),
            ("Admin Only", (
                "`/appsetup setchannel <channel>` — Set where completed applications are posted\n"
                "`/appsetup status` — Check the current application channel"
            ), False),
        ],
    },
    "tickets": {
        "label": "Tickets & Reports",
        "emoji": "🎫",
        "desc_short": "Support tickets & reports",
        "color": CYAN,
        "intro": "Create support tickets or file reports through panel buttons in-channel.",
        "fields": [
            ("How It Works", (
                "Click the **Open a Ticket** or **File a Report** button in the configured channel.\n"
                "A private channel is created for your request. Staff close it when resolved."
            ), False),
            ("Admin Setup", (
                "`/ticketsetup panel <channel>` — Post the ticket panel\n"
                "`/ticketsetup setcategory <category>` — Set the category for ticket channels\n"
                "`/ticketsetup setlogchannel <channel>` — Set where closed tickets are logged\n"
                "`/reportsetup panel <channel>` — Post the report panel\n"
                "`/reportsetup setchannel <channel>` — Set where reports are sent"
            ), False),
        ],
    },
    "rules": {
        "label": "Rules",
        "emoji": "📜",
        "desc_short": "Rules acceptance panel",
        "color": CYAN,
        "intro": "Post a rules panel that grants a role when members click **Accept Rules**.",
        "fields": [
            ("How It Works", (
                "Members click the **Accept Rules** button to receive the configured role.\n"
                "Use this to gate access to the rest of the server."
            ), False),
            ("Admin Setup", (
                "`/rulessetup setrole <role>` — Set the role granted on acceptance\n"
                "`/rulessetup panel [channel] [title] [description]` — Post the rules panel\n"
                "`/rulessetup status` — Check the current configuration"
            ), False),
        ],
    },
    "quotes": {
        "label": "Quotes",
        "emoji": "💬",
        "desc_short": "Capture & post message quotes",
        "color": CYAN,
        "intro": "Turn any message into a stylised **quote card image** posted to a dedicated channel.",
        "fields": [
            ("How To Quote", (
                "**Right-click** any message → **Apps** → **Quote this**\n"
                "The bot generates an image card and posts it to the quotes channel."
            ), False),
            ("Admin Setup", (
                "`/quotesetup setchannel <channel>` — Set the channel where quotes are posted\n"
                "`/quotesetup status` — Check the current quotes channel"
            ), False),
        ],
    },
    "admin": {
        "label": "Admin",
        "emoji": "⚙️",
        "desc_short": "Bot administration — Admin only",
        "color": RED,
        "intro": "Core bot administration tools. Requires the **Admin** role or server ownership.",
        "fields": [
            ("Bot Management", (
                "`/admin reload <cog>` — Hot-reload a cog without restarting\n"
                "`/admin setconfig <key> <value>` — Update a bot config value\n"
                "`/admin eventbonus <on/off>` — Toggle the 2× XP & CC event bonus"
            ), False),
            ("Shop Management", (
                "`/admin additem <name> <type> <cost> ...` — Add a new shop item\n"
                "`/admin removeitem <item_id>` — Soft-delete a shop item"
            ), False),
            ("User Management", (
                "`/admin grantxp <user> <amount>` — Grant XP with an audit log entry"
            ), False),
        ],
    },
}

# ─── Embed builders ────────────────────────────────────────────────────────────

def _overview_embed() -> discord.Embed:
    lines = []
    for data in PAGES.values():
        lines.append(f"{data['emoji']} **{data['label']}** — {data['desc_short']}")

    embed = build_embed(
        title="Cypher Bot  —  Command Reference",
        description=(
            "Select a category from the dropdown below to see its commands.\n\n"
            + "\n".join(lines)
        ),
        color=CYAN,
        footer="[ ] = optional  |  < > = required  |  Admin-only commands are marked",
    )
    return embed


def _category_embed(key: str) -> discord.Embed:
    page = PAGES[key]
    embed = build_embed(
        title=f"{page['emoji']}  {page['label']}",
        description=page["intro"],
        color=page["color"],
        fields=page["fields"],
        footer="[ ] = optional  |  < > = required",
    )
    return embed


# ─── View ──────────────────────────────────────────────────────────────────────

class _CategorySelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label=data["label"],
                value=key,
                description=data["desc_short"],
                emoji=data["emoji"],
            )
            for key, data in PAGES.items()
        ]
        super().__init__(
            placeholder="Choose a category…",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(embed=_category_embed(self.values[0]))


class _HomeButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Overview", style=discord.ButtonStyle.secondary, emoji="🏠", row=1)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(embed=_overview_embed())


class HelpView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(_CategorySelect())
        self.add_item(_HomeButton())

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ─── Cog ───────────────────────────────────────────────────────────────────────

class Help(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="help", description="Browse all Cypher bot commands")
    async def help_slash(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=_overview_embed(), view=HelpView())

    @commands.command(name="help", aliases=["h", "commands"])
    async def help_prefix(self, ctx: commands.Context):
        await ctx.send(embed=_overview_embed(), view=HelpView())

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ):
        log.error(f"Help command error: {error}", exc_info=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Help(bot))
