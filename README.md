# Project CYPHER — Discord Bot

A production-grade Discord bot for a private gaming community. Cyberpunk aesthetic, full economy, XP ranks, moderation, mini-games, a live stock market, AI chat, and a DM-based moderator application system.

---

## Setup

### Prerequisites
- Python 3.11+
- Docker & Docker Compose (for containerized deployment)
- A Discord bot application with all three Privileged Gateway Intents enabled

### Required Privileged Intents
Enable all three in the [Discord Developer Portal](https://discord.com/developers/applications) under **Bot → Privileged Gateway Intents**:
- `GUILD_MEMBERS`
- `MESSAGE_CONTENT`
- `PRESENCE`

### First-Run Checklist
1. Copy `.env.example` to `.env` and fill in at minimum `DISCORD_TOKEN` and `GUILD_ID`
2. Invite the bot with Administrator permission (integer `8`) or the scoped permission set
3. Build and start: `docker compose up -d --build`
4. After first start, configure core channels:
   ```
   /admin setconfig log_channel_id <channel_id>
   /admin setconfig rankup_channel_id <channel_id>
   /admin setconfig welcome_channel_id <channel_id>
   ```
5. Configure mod/admin roles:
   ```
   /admin setconfig mod_role_id <role_id>
   /admin setconfig admin_role_id <role_id>
   ```
6. Configure rank roles (per tier):
   ```
   /admin setconfig rank_role_0 <role_id>   ← New Signal
   /admin setconfig rank_role_1 <role_id>   ← Data Runner
   /admin setconfig rank_role_2 <role_id>   ← Code Walker
   /admin setconfig rank_role_3 <role_id>   ← Neon Operative
   /admin setconfig rank_role_4 <role_id>   ← Cypher Elite
   /admin setconfig rank_role_5 <role_id>   ← System Architect
   /admin setconfig rank_role_6 <role_id>   ← The Overclocked
   ```
7. Set the market feed channel in `.env`:
   ```
   MARKET_CHANNEL_ID=<channel_id>
   ```
8. Set the moderator application channel:
   ```
   /appsetup setchannel #your-applications-channel
   ```

---

## Command Reference

### Moderation (MOD role required)
| Command | Description |
|---|---|
| `/ban <user> <reason> [delete_days]` | Ban user. DMs them before banning. |
| `/kick <user> <reason>` | Kick user. DMs them before kicking. |
| `/timeout <user> <minutes> <reason>` | Timeout up to 40,320 min (28 days). |
| `/untimeout <user> [reason]` | Remove a user's timeout. |
| `/warn <user> <reason>` | Issue a warning. 3 warns = auto 1hr timeout. 5 warns = admin notified. |
| `/warns <user> [page]` | View paginated warning history. |
| `/purge <count> [user]` | Delete up to 100 messages, optionally filtered by user. |
| `/slowmode <seconds>` | Set channel slowmode (0 to disable, max 21,600). |
| `/lock [channel] [reason]` | Deny @everyone from sending messages. |
| `/unlock [channel] [reason]` | Restore send permissions. |
| `/modlogs <user> [page]` | Full paginated moderation history with navigation buttons. |

### Moderation (ADMIN role required)
| Command | Description |
|---|---|
| `/delwarn <log_id>` | Delete a specific warning by log ID. |
| `/unban <user_id> [reason]` | Unban a user by their Discord snowflake ID. |

### Moderator Applications
| Command | Who | Description |
|---|---|---|
| `/apply` | Any member | Start a DM-based moderator application (10 questions). |
| `/appsetup setchannel <channel>` | Admin | Set the channel where completed applications are posted. |
| `/appsetup status` | Admin | Check which channel applications are posting to. |

The `/apply` flow: the bot DMs the applicant one question at a time. After all 10 answers are collected, the full Q&A is posted as a formatted embed to the configured channel. Applicants can type `cancel` at any time. Applications time out after 5 minutes of inactivity per question.

### XP & Ranks
| Command | Description |
|---|---|
| `/rank [user]` | Display rank card with XP bar and level. |
| `/leaderboard [page]` | Top 10 by XP with pagination. |
| `/rankinfo` | List all 7 rank tiers and XP thresholds. |
| `/xp add <user> <amount>` | Grant XP (admin). |
| `/xp remove <user> <amount>` | Remove XP (admin). |
| `/xp set <user> <amount>` | Hard-set a user's XP (admin). |

XP is earned passively — messages grant 15–25 XP (60s cooldown, minimum 5 characters). Voice chat grants XP every minute when 2+ humans are present. All rates double during an active event bonus.

### Economy
| Command | Description |
|---|---|
| `/balance [user]` | Check Cypher Credits (CC) balance. |
| `/daily` | Claim daily CC (24hr cooldown). Streak bonuses at 7d and 30d. |
| `/pay <user> <amount>` | Transfer CC to another member (minimum 10 CC). |
| `/shop [page]` | Browse the server shop. |
| `/buy <item_id>` | Purchase an item from the shop. |
| `/inventory [user]` | View purchased items and expiry dates. |
| `/richlist` | Top 10 by lifetime CC earned. |
| `/give <user> <amount>` | Admin: grant CC to a user. |
| `/take <user> <amount>` | Admin: remove CC from a user. |

### Stock Market
| Command | Description |
|---|---|
| `/market` | View all stocks with current price and % change. |
| `/invest <ticker> <amount>` | Spend CC to buy shares of a stock. |
| `/divest <ticker> <shares>` | Sell shares back for CC. |
| `/portfolio [user]` | View holdings with per-stock P&L and total portfolio value. |

Prices update automatically every 30 minutes using a mean-reverting random walk. A price feed embed is posted to the configured `MARKET_CHANNEL_ID` on each tick. Six stocks are seeded by default:

| Ticker | Company | Base Price | Volatility |
|---|---|---|---|
| `NEON` | NeonTech Industries | 100 CC | 8% |
| `GRID` | GridCore Systems | 250 CC | 6% |
| `CYPH` | CypherData Corp | 500 CC | 10% |
| `WIRE` | WireNet Solutions | 75 CC | 12% |
| `ARCH` | Archon AI | 1,000 CC | 7% |
| `VOID` | VoidSec Holdings | 150 CC | 15% |

### Mini-Games
| Command | Cooldown | Description |
|---|---|---|
| `/coinflip <bet> <heads\|tails>` | 30s | 2× payout on a correct call. |
| `/slots <bet>` | 60s | 3-reel slots. Jackpot = 10× bet + 1,000 CC bonus. |
| `/gamestats [user]` | — | Win/loss record and net P&L per game. |

### AI Chat
| Command | Cooldown | Description |
|---|---|---|
| `/ask <message>` | 30s/user | Chat with the Cypher AI (powered by Gemini). Requires `GEMINI_API_KEY` in `.env`. |

### Admin
| Command | Description |
|---|---|
| `/admin reload <cog\|all>` | Hot-reload one or all cogs without restarting. |
| `/admin setconfig <key> <value>` | Update any config key in the database. |
| `/admin additem <name> <type> <cost> [role_id] [days] [stock]` | Add a shop item. |
| `/admin removeitem <item_id>` | Soft-delete a shop item (purchase history preserved). |
| `/admin eventbonus <on\|off>` | Toggle 2× XP and CC earn event for the server. |
| `/admin grantxp <user> <amount>` | Grant XP to a user with audit log entry. |

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `DISCORD_TOKEN` | Yes | Bot token from the Developer Portal. |
| `GUILD_ID` | Yes | The target server's snowflake ID. |
| `PREFIX` | No | Prefix for legacy commands (default: `!`). |
| `DB_PATH` | No | SQLite path (default: `./data/cypher.db`). |
| `LOG_CHANNEL_ID` | No | Default mod-log channel (can also be set via `/admin setconfig`). |
| `RANKUP_CHANNEL_ID` | No | Default rank-up announcement channel. |
| `WELCOME_CHANNEL_ID` | No | Default welcome message channel. |
| `MARKET_CHANNEL_ID` | No | Channel that receives the market price feed every 30 minutes. |
| `ADMIN_USER_IDS` | No | Comma-separated Discord IDs that bypass role permission checks. |
| `GEMINI_API_KEY` | No | Enables the `/ask` AI command (Gemini). |
| `GEMINI_MODEL` | No | Gemini model ID (default: `gemini-2.0-flash-lite`). |

---

## Deployment

```bash
# Build and start
docker compose up -d --build

# View logs
docker compose logs -f

# Stop
docker compose down
```

### Daily backup
```bash
sqlite3 ./data/cypher.db .dump > backup/cypher_$(date +%Y%m%d).sql
```

---

## Rank Tiers

| Level | Name | XP Required |
|---|---|---|
| 0 | New Signal | 0 |
| 1 | Data Runner | 500 |
| 2 | Code Walker | 1,500 |
| 3 | Neon Operative | 4,000 |
| 4 | Cypher Elite | 9,000 |
| 5 | System Architect | 18,000 |
| 6 | The Overclocked | 35,000 |
