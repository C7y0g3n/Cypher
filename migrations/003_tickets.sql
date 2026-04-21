CREATE TABLE IF NOT EXISTS tickets (
    ticket_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    channel_id  INTEGER NOT NULL UNIQUE,
    created_at  TIMESTAMP NOT NULL,
    closed_at   TIMESTAMP,
    closed_by   INTEGER
);
