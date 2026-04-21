# Project CYPHER — Discord Bot

A production-grade Discord bot for a private gaming community. Cyberpunk aesthetic, full economy, XP ranks, moderation, and mini-games.

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
1. Copy `.env.example` to `.env` and fill in `DISCORD_TOKEN` and `GUILD_ID`
2. Invite the bot with Administrator permission (integer `8`) or the scoped permission set
3. Build and start: `docker compose up -d --build`
4. After first start, configure channels:
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

---

## Command Reference

### Moderation (`MOD` role required)
| Command | Description |
|---|---|
| `/ban <user> <reason>` | Ban user. DMs before banning. |
| `/kick <user> <reason>` | Kick user. |
| `/timeout <user> <minutes> <reason>` | Timeout (up to 40320 min). |
| `/untimeout <user>` | Remove timeout. |
| `/warn <user> <reason>` | Warn user. 3 warns = auto-timeout 1hr. 5 warns = admin notified. |
| `/warns <user>` | View warning history. |
| `/purge <count> [user]` | Delete up to 100 messages. |
| `/slowmode <seconds>` | Set channel slowmode. |
| `/lock [channel]` | Lock channel. |
| `/unlock [channel]` | Unlock channel. |
| `/modlogs <user>` | Full mod history. |

### Moderation (`ADMIN` role required)
| Command | Description |
|---|---|
| `/delwarn <log_id>` | Delete a specific warning. |
| `/unban <user_id>` | Unban by snowflake ID. |

### XP & Ranks
| Command | Description |
|---|---|
| `/rank [user]` | Display rank card with XP bar. |
| `/leaderboard [page]` | Top 10 by XP with pagination. |
| `/rankinfo` | List all 7 rank tiers. |
| `/xp add <user> <amount>` | Grant XP (admin). |
| `/xp remove <user> <amount>` | Remove XP (admin). |
| `/xp set <user> <amount>` | Hard-set XP (admin). |

### Economy
| Command | Description |
|---|---|
| `/balance [user]` | Check CC balance. |
| `/daily` | Claim daily CC (24hr cooldown). Streak bonuses at 7d and 30d. |
| `/pay <user> <amount>` | Transfer CC (min 10). |
| `/shop [page]` | Browse shop. |
| `/buy <item_id>` | Purchase item. |
| `/inventory [user]` | View purchased items. |
| `/richlist` | Top 10 by lifetime earnings. |
| `/give <user> <amount>` | Admin: grant CC. |
| `/take <user> <amount>` | Admin: remove CC. |

### Mini-Games
| Command | Cooldown | Description |
|---|---|---|
| `/coinflip <bet> <heads\|tails>` | 30s | 2x payout on win. |
| `/slots <bet>` | 60s | 3-reel slots. Jackpot = 10x + 1000 CC. |
| `/gamestats [user]` | — | Win/loss record and net P&L. |

### Admin
| Command | Description |
|---|---|
| `/admin reload <cog\|all>` | Hot-reload cog(s). |
| `/admin setconfig <key> <value>` | Update config key. |
| `/admin additem <name> <type> <cost> [role_id] [days] [stock]` | Add shop item. |
| `/admin removeitem <item_id>` | Soft-delete shop item. |
| `/admin eventbonus <on\|off>` | Toggle 2x earn event. |
| `/admin grantxp <user> <amount>` | Grant XP with audit log. |

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

| # | Name | XP Required |
|---|---|---|
| 1 | New Signal | 0 |
| 2 | Data Runner | 500 |
| 3 | Code Walker | 1,500 |
| 4 | Neon Operative | 4,000 |
| 5 | Cypher Elite | 9,000 |
| 6 | System Architect | 18,000 |
| 7 | The Overclocked | 35,000 |
