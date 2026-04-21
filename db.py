import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import aiosqlite

log = logging.getLogger("cypher.db")

MIGRATIONS_PATH = Path("./migrations")


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._conn: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()

    async def init(self):
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.db_path, isolation_level=None)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._run_migrations()
        log.info(f"Database initialized: {self.db_path}")

    async def _run_migrations(self):
        for mf in sorted(MIGRATIONS_PATH.glob("*.sql")):
            sql = mf.read_text(encoding="utf-8")
            await self._conn.executescript(sql)
            log.info(f"Ran migration: {mf.name}")

    async def close(self):
        if self._conn:
            await self._conn.close()

    # ─── Users ────────────────────────────────────────────────────────────────

    async def ensure_user(self, user_id: int, guild_id: int):
        await self._conn.execute(
            "INSERT OR IGNORE INTO users (user_id, guild_id, created_at) VALUES (?, ?, ?)",
            (user_id, guild_id, _now()),
        )

    async def get_user(self, user_id: int, guild_id: int) -> Optional[aiosqlite.Row]:
        async with self._conn.execute(
            "SELECT * FROM users WHERE user_id=? AND guild_id=?", (user_id, guild_id)
        ) as cur:
            return await cur.fetchone()

    async def update_xp(self, user_id: int, guild_id: int, delta: int) -> dict:
        """Add delta XP and recalculate level. Returns change summary."""
        await self.ensure_user(user_id, guild_id)
        async with self._lock:
            await self._conn.execute("BEGIN IMMEDIATE")
            try:
                async with self._conn.execute(
                    "SELECT xp, level FROM users WHERE user_id=? AND guild_id=?",
                    (user_id, guild_id),
                ) as cur:
                    row = await cur.fetchone()
                new_xp = max(0, row["xp"] + delta)
                old_level = row["level"]
                new_level = _calc_level(new_xp)
                await self._conn.execute(
                    "UPDATE users SET xp=?, level=? WHERE user_id=? AND guild_id=?",
                    (new_xp, new_level, user_id, guild_id),
                )
                await self._conn.execute("COMMIT")
            except Exception:
                await self._conn.execute("ROLLBACK")
                raise
        return {
            "xp": new_xp,
            "level": new_level,
            "old_level": old_level,
            "leveled_up": new_level > old_level,
            "leveled_down": new_level < old_level,
        }

    async def set_xp(self, user_id: int, guild_id: int, xp: int) -> dict:
        await self.ensure_user(user_id, guild_id)
        async with self._lock:
            await self._conn.execute("BEGIN IMMEDIATE")
            try:
                async with self._conn.execute(
                    "SELECT level FROM users WHERE user_id=? AND guild_id=?",
                    (user_id, guild_id),
                ) as cur:
                    row = await cur.fetchone()
                old_level = row["level"]
                new_level = _calc_level(xp)
                await self._conn.execute(
                    "UPDATE users SET xp=?, level=? WHERE user_id=? AND guild_id=?",
                    (xp, new_level, user_id, guild_id),
                )
                await self._conn.execute("COMMIT")
            except Exception:
                await self._conn.execute("ROLLBACK")
                raise
        return {
            "xp": xp,
            "level": new_level,
            "old_level": old_level,
            "leveled_up": new_level > old_level,
            "leveled_down": new_level < old_level,
        }

    async def update_last_xp_msg(self, user_id: int, guild_id: int):
        await self._conn.execute(
            "UPDATE users SET last_xp_msg=? WHERE user_id=? AND guild_id=?",
            (_now(), user_id, guild_id),
        )

    async def update_voice_joined(self, user_id: int, guild_id: int, joined_at: Optional[datetime]):
        val = joined_at.isoformat() if joined_at else None
        await self._conn.execute(
            "UPDATE users SET voice_joined_at=? WHERE user_id=? AND guild_id=?",
            (val, user_id, guild_id),
        )

    async def get_xp_leaderboard(self, guild_id: int, limit: int = 10, offset: int = 0):
        async with self._conn.execute(
            "SELECT * FROM users WHERE guild_id=? ORDER BY xp DESC LIMIT ? OFFSET ?",
            (guild_id, limit, offset),
        ) as cur:
            return await cur.fetchall()

    async def get_xp_rank(self, user_id: int, guild_id: int) -> int:
        async with self._conn.execute(
            "SELECT COUNT(*) as r FROM users WHERE guild_id=? AND xp > "
            "(SELECT xp FROM users WHERE user_id=? AND guild_id=?)",
            (guild_id, user_id, guild_id),
        ) as cur:
            row = await cur.fetchone()
            return (row["r"] or 0) + 1

    async def get_guild_user_count(self, guild_id: int) -> int:
        async with self._conn.execute(
            "SELECT COUNT(*) as c FROM users WHERE guild_id=?", (guild_id,)
        ) as cur:
            row = await cur.fetchone()
            return row["c"] or 0

    # ─── Credits ──────────────────────────────────────────────────────────────

    async def get_balance(self, user_id: int, guild_id: int) -> int:
        await self.ensure_user(user_id, guild_id)
        async with self._conn.execute(
            "SELECT credits FROM users WHERE user_id=? AND guild_id=?",
            (user_id, guild_id),
        ) as cur:
            row = await cur.fetchone()
            return row["credits"] if row else 0

    async def mutate_credits(
        self, user_id: int, guild_id: int, delta: int
    ) -> tuple[bool, int]:
        """Atomically change credits. Returns (success, new_balance).
        Fails if delta would make balance negative."""
        await self.ensure_user(user_id, guild_id)
        async with self._lock:
            await self._conn.execute("BEGIN IMMEDIATE")
            try:
                async with self._conn.execute(
                    "SELECT credits FROM users WHERE user_id=? AND guild_id=?",
                    (user_id, guild_id),
                ) as cur:
                    row = await cur.fetchone()
                current = row["credits"]
                new_balance = current + delta
                if new_balance < 0:
                    await self._conn.execute("ROLLBACK")
                    return False, current
                earned_delta = max(0, delta)
                await self._conn.execute(
                    "UPDATE users SET credits=?, total_earned=total_earned+? "
                    "WHERE user_id=? AND guild_id=?",
                    (new_balance, earned_delta, user_id, guild_id),
                )
                await self._conn.execute("COMMIT")
                return True, new_balance
            except Exception:
                await self._conn.execute("ROLLBACK")
                raise

    async def admin_mutate_credits(
        self, user_id: int, guild_id: int, delta: int
    ) -> int:
        """Admin credit mutation — floors at 0, never fails."""
        await self.ensure_user(user_id, guild_id)
        async with self._lock:
            await self._conn.execute("BEGIN IMMEDIATE")
            try:
                async with self._conn.execute(
                    "SELECT credits FROM users WHERE user_id=? AND guild_id=?",
                    (user_id, guild_id),
                ) as cur:
                    row = await cur.fetchone()
                new_balance = max(0, row["credits"] + delta)
                earned_delta = max(0, delta)
                await self._conn.execute(
                    "UPDATE users SET credits=?, total_earned=total_earned+? "
                    "WHERE user_id=? AND guild_id=?",
                    (new_balance, earned_delta, user_id, guild_id),
                )
                await self._conn.execute("COMMIT")
                return new_balance
            except Exception:
                await self._conn.execute("ROLLBACK")
                raise

    async def get_richlist(self, guild_id: int, limit: int = 10, offset: int = 0):
        async with self._conn.execute(
            "SELECT * FROM users WHERE guild_id=? ORDER BY total_earned DESC LIMIT ? OFFSET ?",
            (guild_id, limit, offset),
        ) as cur:
            return await cur.fetchall()

    async def update_daily(self, user_id: int, guild_id: int, new_streak: int):
        await self._conn.execute(
            "UPDATE users SET last_daily=?, daily_streak=? WHERE user_id=? AND guild_id=?",
            (_now(), new_streak, user_id, guild_id),
        )

    # ─── Mod Logs ─────────────────────────────────────────────────────────────

    async def add_mod_log(
        self,
        guild_id: int,
        target_id: int,
        mod_id: int,
        action: str,
        reason: str,
        duration: Optional[int] = None,
    ) -> int:
        cur = await self._conn.execute(
            "INSERT INTO mod_logs (guild_id, target_id, mod_id, action, reason, duration, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (guild_id, target_id, mod_id, action, reason, duration, _now()),
        )
        return cur.lastrowid

    async def get_mod_logs(
        self, guild_id: int, target_id: int, limit: int = 10, offset: int = 0
    ):
        async with self._conn.execute(
            "SELECT * FROM mod_logs WHERE guild_id=? AND target_id=? "
            "ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (guild_id, target_id, limit, offset),
        ) as cur:
            return await cur.fetchall()

    async def count_mod_logs(self, guild_id: int, target_id: int) -> int:
        async with self._conn.execute(
            "SELECT COUNT(*) as c FROM mod_logs WHERE guild_id=? AND target_id=?",
            (guild_id, target_id),
        ) as cur:
            row = await cur.fetchone()
            return row["c"] or 0

    async def get_warn_count(self, guild_id: int, target_id: int) -> int:
        async with self._conn.execute(
            "SELECT COUNT(*) as c FROM mod_logs WHERE guild_id=? AND target_id=? AND action='warn'",
            (guild_id, target_id),
        ) as cur:
            row = await cur.fetchone()
            return row["c"] or 0

    async def delete_mod_log(self, log_id: int, guild_id: int) -> bool:
        cur = await self._conn.execute(
            "DELETE FROM mod_logs WHERE log_id=? AND guild_id=?", (log_id, guild_id)
        )
        return cur.rowcount > 0

    # ─── Shop ─────────────────────────────────────────────────────────────────

    async def get_shop_items(
        self, guild_id: int, active_only: bool = True, limit: int = 10, offset: int = 0
    ):
        q = "SELECT * FROM shop_items WHERE guild_id=?"
        p: list = [guild_id]
        if active_only:
            q += " AND active=1"
        q += " ORDER BY cost ASC LIMIT ? OFFSET ?"
        p += [limit, offset]
        async with self._conn.execute(q, p) as cur:
            return await cur.fetchall()

    async def count_shop_items(self, guild_id: int, active_only: bool = True) -> int:
        q = "SELECT COUNT(*) as c FROM shop_items WHERE guild_id=?"
        p: list = [guild_id]
        if active_only:
            q += " AND active=1"
        async with self._conn.execute(q, p) as cur:
            row = await cur.fetchone()
            return row["c"] or 0

    async def get_shop_item(self, item_id: int) -> Optional[aiosqlite.Row]:
        async with self._conn.execute(
            "SELECT * FROM shop_items WHERE item_id=?", (item_id,)
        ) as cur:
            return await cur.fetchone()

    async def get_random_timed_roles(self, guild_id: int):
        async with self._conn.execute(
            "SELECT * FROM shop_items WHERE guild_id=? AND active=1 AND duration_days IS NOT NULL AND type='role'",
            (guild_id,),
        ) as cur:
            return await cur.fetchall()

    async def add_shop_item(
        self,
        guild_id: int,
        name: str,
        item_type: str,
        cost: int,
        role_id: Optional[int],
        duration_days: Optional[int],
        stock: Optional[int],
    ) -> int:
        cur = await self._conn.execute(
            "INSERT INTO shop_items (guild_id, name, type, cost, role_id, duration_days, stock, active) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
            (guild_id, name, item_type, cost, role_id, duration_days, stock),
        )
        return cur.lastrowid

    async def deactivate_shop_item(self, item_id: int, guild_id: int) -> bool:
        cur = await self._conn.execute(
            "UPDATE shop_items SET active=0 WHERE item_id=? AND guild_id=?",
            (item_id, guild_id),
        )
        return cur.rowcount > 0

    async def decrement_stock(self, item_id: int):
        await self._conn.execute(
            "UPDATE shop_items SET stock=stock-1 WHERE item_id=? AND stock IS NOT NULL AND stock>0",
            (item_id,),
        )

    # ─── Inventory ────────────────────────────────────────────────────────────

    async def add_inventory(
        self,
        user_id: int,
        guild_id: int,
        item_id: int,
        expires_at: Optional[datetime],
    ) -> int:
        cur = await self._conn.execute(
            "INSERT INTO inventory (user_id, guild_id, item_id, acquired_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                user_id,
                guild_id,
                item_id,
                _now(),
                expires_at.isoformat() if expires_at else None,
            ),
        )
        return cur.lastrowid

    async def get_inventory(
        self, user_id: int, guild_id: int, limit: int = 10, offset: int = 0
    ):
        async with self._conn.execute(
            "SELECT inv.*, si.name, si.type, si.role_id "
            "FROM inventory inv JOIN shop_items si ON inv.item_id=si.item_id "
            "WHERE inv.user_id=? AND inv.guild_id=? "
            "ORDER BY inv.acquired_at DESC LIMIT ? OFFSET ?",
            (user_id, guild_id, limit, offset),
        ) as cur:
            return await cur.fetchall()

    async def get_expired_inventory(self):
        now = _now()
        async with self._conn.execute(
            "SELECT inv.*, si.role_id, inv.guild_id "
            "FROM inventory inv JOIN shop_items si ON inv.item_id=si.item_id "
            "WHERE inv.expires_at IS NOT NULL AND inv.expires_at <= ?",
            (now,),
        ) as cur:
            return await cur.fetchall()

    async def remove_inventory(self, inv_id: int):
        await self._conn.execute("DELETE FROM inventory WHERE inv_id=?", (inv_id,))

    # ─── Game Stats ───────────────────────────────────────────────────────────

    async def add_game_stat(
        self,
        user_id: int,
        guild_id: int,
        game: str,
        bet: int,
        outcome: str,
        payout: int,
    ):
        await self._conn.execute(
            "INSERT INTO game_stats (user_id, guild_id, game, bet, outcome, payout, played_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, guild_id, game, bet, outcome, payout, _now()),
        )

    async def get_game_stats(self, user_id: int, guild_id: int):
        async with self._conn.execute(
            "SELECT game, "
            "COUNT(*) as total_games, "
            "SUM(CASE WHEN outcome IN ('win','jackpot') THEN 1 ELSE 0 END) as wins, "
            "SUM(CASE WHEN outcome='loss' THEN 1 ELSE 0 END) as losses, "
            "SUM(bet) as total_wagered, "
            "SUM(payout)-SUM(bet) as net_pnl "
            "FROM game_stats WHERE user_id=? AND guild_id=? GROUP BY game",
            (user_id, guild_id),
        ) as cur:
            return await cur.fetchall()

    # ─── Config ───────────────────────────────────────────────────────────────

    async def get_config(self, guild_id: int, key: str) -> Optional[str]:
        async with self._conn.execute(
            "SELECT value FROM config WHERE guild_id=? AND key=?", (guild_id, key)
        ) as cur:
            row = await cur.fetchone()
            return row["value"] if row else None

    async def set_config(self, guild_id: int, key: str, value: str):
        await self._conn.execute(
            "INSERT INTO config (guild_id, key, value) VALUES (?, ?, ?) "
            "ON CONFLICT(guild_id, key) DO UPDATE SET value=excluded.value",
            (guild_id, key, value),
        )

    async def seed_config(self, guild_id: int, defaults: dict):
        for key, value in defaults.items():
            async with self._conn.execute(
                "SELECT 1 FROM config WHERE guild_id=? AND key=?", (guild_id, key)
            ) as cur:
                exists = await cur.fetchone()
            if not exists:
                await self.set_config(guild_id, key, str(value))

    # ─── Stocks ───────────────────────────────────────────────────────────────

    async def seed_stocks(self, guild_id: int):
        async with self._conn.execute(
            "SELECT COUNT(*) as c FROM stocks WHERE guild_id=?", (guild_id,)
        ) as cur:
            row = await cur.fetchone()
        if row["c"] > 0:
            return
        defaults = [
            ("NEON", "NeonTech Industries",  100,  0.08),
            ("GRID", "GridCore Systems",     250,  0.06),
            ("CYPH", "CypherData Corp",      500,  0.10),
            ("WIRE", "WireNet Solutions",     75,  0.12),
            ("ARCH", "Archon AI",           1000,  0.07),
            ("VOID", "VoidSec Holdings",     150,  0.15),
        ]
        for ticker, name, price, vol in defaults:
            await self._conn.execute(
                "INSERT OR IGNORE INTO stocks (ticker, guild_id, name, price, prev_price, base_price, volatility) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ticker, guild_id, name, price, price, price, vol),
            )
        log.info(f"Seeded default stocks for guild {guild_id}")

    async def get_stocks(self, guild_id: int):
        async with self._conn.execute(
            "SELECT * FROM stocks WHERE guild_id=? ORDER BY ticker", (guild_id,)
        ) as cur:
            return await cur.fetchall()

    async def get_stock(self, guild_id: int, ticker: str) -> Optional[aiosqlite.Row]:
        async with self._conn.execute(
            "SELECT * FROM stocks WHERE guild_id=? AND ticker=?", (guild_id, ticker.upper())
        ) as cur:
            return await cur.fetchone()

    async def update_stock_price(self, guild_id: int, ticker: str, new_price: int):
        await self._conn.execute(
            "UPDATE stocks SET prev_price=price, price=? WHERE guild_id=? AND ticker=?",
            (new_price, guild_id, ticker),
        )

    async def add_stock_history(self, guild_id: int, ticker: str, price: int):
        await self._conn.execute(
            "INSERT INTO stock_history (ticker, guild_id, price, recorded_at) VALUES (?, ?, ?, ?)",
            (ticker, guild_id, price, _now()),
        )
        # Keep only last 48 entries per stock
        await self._conn.execute(
            "DELETE FROM stock_history WHERE history_id NOT IN ("
            "  SELECT history_id FROM stock_history WHERE ticker=? AND guild_id=? "
            "  ORDER BY recorded_at DESC LIMIT 48"
            ")",
            (ticker, guild_id),
        )

    async def get_stock_history(self, guild_id: int, ticker: str, limit: int = 10):
        async with self._conn.execute(
            "SELECT price, recorded_at FROM stock_history "
            "WHERE guild_id=? AND ticker=? ORDER BY recorded_at DESC LIMIT ?",
            (guild_id, ticker, limit),
        ) as cur:
            return await cur.fetchall()

    async def get_holding(self, user_id: int, guild_id: int, ticker: str) -> Optional[aiosqlite.Row]:
        async with self._conn.execute(
            "SELECT * FROM stock_holdings WHERE user_id=? AND guild_id=? AND ticker=?",
            (user_id, guild_id, ticker.upper()),
        ) as cur:
            return await cur.fetchone()

    async def get_holdings(self, user_id: int, guild_id: int):
        async with self._conn.execute(
            "SELECT h.*, s.name, s.price as current_price "
            "FROM stock_holdings h JOIN stocks s ON h.ticker=s.ticker AND h.guild_id=s.guild_id "
            "WHERE h.user_id=? AND h.guild_id=? AND h.shares > 0 ORDER BY h.ticker",
            (user_id, guild_id),
        ) as cur:
            return await cur.fetchall()

    async def buy_stock(
        self, user_id: int, guild_id: int, ticker: str, shares: int, cost_cc: int
    ) -> tuple[bool, str]:
        """Atomically deduct cost_cc from credits and add shares. Returns (ok, reason)."""
        await self.ensure_user(user_id, guild_id)
        ticker = ticker.upper()
        async with self._lock:
            await self._conn.execute("BEGIN IMMEDIATE")
            try:
                async with self._conn.execute(
                    "SELECT credits FROM users WHERE user_id=? AND guild_id=?",
                    (user_id, guild_id),
                ) as cur:
                    row = await cur.fetchone()
                if row["credits"] < cost_cc:
                    await self._conn.execute("ROLLBACK")
                    return False, "insufficient_funds"

                await self._conn.execute(
                    "UPDATE users SET credits=credits-? WHERE user_id=? AND guild_id=?",
                    (cost_cc, user_id, guild_id),
                )

                async with self._conn.execute(
                    "SELECT shares, avg_cost FROM stock_holdings "
                    "WHERE user_id=? AND guild_id=? AND ticker=?",
                    (user_id, guild_id, ticker),
                ) as cur:
                    holding = await cur.fetchone()

                price_per = cost_cc / shares
                if holding:
                    new_shares = holding["shares"] + shares
                    new_avg = (holding["shares"] * holding["avg_cost"] + cost_cc) / new_shares
                    await self._conn.execute(
                        "UPDATE stock_holdings SET shares=?, avg_cost=? "
                        "WHERE user_id=? AND guild_id=? AND ticker=?",
                        (new_shares, new_avg, user_id, guild_id, ticker),
                    )
                else:
                    await self._conn.execute(
                        "INSERT INTO stock_holdings (user_id, guild_id, ticker, shares, avg_cost) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (user_id, guild_id, ticker, shares, price_per),
                    )

                await self._conn.execute("COMMIT")
                return True, "ok"
            except Exception:
                await self._conn.execute("ROLLBACK")
                raise

    async def sell_stock(
        self, user_id: int, guild_id: int, ticker: str, shares: int, proceeds_cc: int
    ) -> tuple[bool, str]:
        """Atomically remove shares and credit proceeds. Returns (ok, reason)."""
        ticker = ticker.upper()
        async with self._lock:
            await self._conn.execute("BEGIN IMMEDIATE")
            try:
                async with self._conn.execute(
                    "SELECT shares, avg_cost FROM stock_holdings "
                    "WHERE user_id=? AND guild_id=? AND ticker=?",
                    (user_id, guild_id, ticker),
                ) as cur:
                    holding = await cur.fetchone()

                if not holding or holding["shares"] < shares:
                    await self._conn.execute("ROLLBACK")
                    return False, "insufficient_shares"

                new_shares = holding["shares"] - shares
                if new_shares == 0:
                    await self._conn.execute(
                        "DELETE FROM stock_holdings WHERE user_id=? AND guild_id=? AND ticker=?",
                        (user_id, guild_id, ticker),
                    )
                else:
                    await self._conn.execute(
                        "UPDATE stock_holdings SET shares=? WHERE user_id=? AND guild_id=? AND ticker=?",
                        (new_shares, user_id, guild_id, ticker),
                    )

                await self._conn.execute(
                    "UPDATE users SET credits=credits+?, total_earned=total_earned+? "
                    "WHERE user_id=? AND guild_id=?",
                    (proceeds_cc, proceeds_cc, user_id, guild_id),
                )

                await self._conn.execute("COMMIT")
                return True, "ok"
            except Exception:
                await self._conn.execute("ROLLBACK")
                raise

    async def seed_shop(self, guild_id: int):
        """Seed default shop items for a guild if none exist."""
        async with self._conn.execute(
            "SELECT COUNT(*) as c FROM shop_items WHERE guild_id=?", (guild_id,)
        ) as cur:
            row = await cur.fetchone()
        if row["c"] > 0:
            return
        defaults = [
            ("Custom Color Role", "role", 800, None, 30, None),
            ("VIP Access Channel", "role", 1200, None, 7, None),
            ("Music Control Role", "role", 500, None, None, None),
            ("Loot Crate", "crate", 400, None, None, None),
            ("Custom Name Role", "role", 2500, None, None, None),
            ("Booster Badge Role", "role", 3500, None, None, None),
        ]
        for name, itype, cost, role_id, duration_days, stock in defaults:
            await self.add_shop_item(guild_id, name, itype, cost, role_id, duration_days, stock)
        log.info(f"Seeded default shop items for guild {guild_id}")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _calc_level(xp: int) -> int:
    from config import RANK_THRESHOLDS
    level = 0
    for lvl, (_, threshold) in RANK_THRESHOLDS.items():
        if xp >= threshold:
            level = lvl
    return level
