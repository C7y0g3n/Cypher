CREATE TABLE IF NOT EXISTS server_snapshots (
    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER NOT NULL,
    label       TEXT    NOT NULL DEFAULT 'snapshot',
    created_at  TIMESTAMP NOT NULL,
    data        TEXT    NOT NULL
);
