CREATE TABLE IF NOT EXISTS users (
    user_id         INTEGER NOT NULL,
    guild_id        INTEGER NOT NULL,
    xp              INTEGER DEFAULT 0,
    level           INTEGER DEFAULT 0,
    credits         INTEGER DEFAULT 0,
    total_earned    INTEGER DEFAULT 0,
    last_daily      TIMESTAMP NULL,
    daily_streak    INTEGER DEFAULT 0,
    last_xp_msg     TIMESTAMP NULL,
    voice_joined_at TIMESTAMP NULL,
    created_at      TIMESTAMP NOT NULL,
    PRIMARY KEY (user_id, guild_id)
);

CREATE TABLE IF NOT EXISTS mod_logs (
    log_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER NOT NULL,
    target_id   INTEGER NOT NULL,
    mod_id      INTEGER NOT NULL,
    action      TEXT NOT NULL,
    reason      TEXT NOT NULL,
    duration    INTEGER NULL,
    created_at  TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS shop_items (
    item_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id        INTEGER NOT NULL DEFAULT 0,
    name            TEXT NOT NULL,
    type            TEXT NOT NULL,
    cost            INTEGER NOT NULL,
    role_id         INTEGER NULL,
    duration_days   INTEGER NULL,
    stock           INTEGER NULL,
    active          BOOLEAN DEFAULT 1,
    UNIQUE (guild_id, name)
);

CREATE TABLE IF NOT EXISTS inventory (
    inv_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    guild_id    INTEGER NOT NULL DEFAULT 0,
    item_id     INTEGER NOT NULL,
    acquired_at TIMESTAMP NOT NULL,
    expires_at  TIMESTAMP NULL,
    FOREIGN KEY (item_id) REFERENCES shop_items(item_id)
);

CREATE TABLE IF NOT EXISTS game_stats (
    stat_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    guild_id    INTEGER NOT NULL DEFAULT 0,
    game        TEXT NOT NULL,
    bet         INTEGER NOT NULL,
    outcome     TEXT NOT NULL,
    payout      INTEGER NOT NULL,
    played_at   TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS config (
    guild_id    INTEGER NOT NULL,
    key         TEXT NOT NULL,
    value       TEXT NOT NULL,
    PRIMARY KEY (guild_id, key)
);
