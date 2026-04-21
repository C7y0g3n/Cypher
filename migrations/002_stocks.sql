CREATE TABLE IF NOT EXISTS stocks (
    ticker      TEXT    NOT NULL,
    guild_id    INTEGER NOT NULL,
    name        TEXT    NOT NULL,
    price       INTEGER NOT NULL,
    prev_price  INTEGER NOT NULL,
    base_price  INTEGER NOT NULL,
    volatility  REAL    NOT NULL DEFAULT 0.08,
    PRIMARY KEY (ticker, guild_id)
);

CREATE TABLE IF NOT EXISTS stock_holdings (
    user_id     INTEGER NOT NULL,
    guild_id    INTEGER NOT NULL,
    ticker      TEXT    NOT NULL,
    shares      INTEGER NOT NULL DEFAULT 0,
    avg_cost    REAL    NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, guild_id, ticker)
);

CREATE TABLE IF NOT EXISTS stock_history (
    history_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker      TEXT    NOT NULL,
    guild_id    INTEGER NOT NULL,
    price       INTEGER NOT NULL,
    recorded_at TIMESTAMP NOT NULL
);
