"""SQLite storage. One file under data/, accessed through a single locked connection."""

import json
import sqlite3
import threading
import time
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "signature.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS relays (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    base_url TEXT NOT NULL,
    api_key TEXT NOT NULL,
    auth_mode TEXT NOT NULL DEFAULT 'auto',
    model_map TEXT NOT NULL DEFAULT '{}',
    stream INTEGER NOT NULL DEFAULT 0,
    note TEXT NOT NULL DEFAULT '',
    deleted INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS official_keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    api_key TEXT NOT NULL,
    is_default INTEGER NOT NULL DEFAULT 0,
    note TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL NOT NULL,
    finished_at REAL,
    status TEXT NOT NULL,
    official_key_id INTEGER,
    official_key_name TEXT NOT NULL DEFAULT '',
    rounds INTEGER NOT NULL,
    stream_mode TEXT NOT NULL,
    models TEXT NOT NULL,
    relay_ids TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS controls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    model TEXT NOT NULL,
    status TEXT NOT NULL,
    ok INTEGER,
    reason TEXT NOT NULL DEFAULT '',
    detail TEXT NOT NULL DEFAULT '{}',
    cost_official REAL NOT NULL DEFAULT 0,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    relay_id INTEGER,
    relay_name TEXT NOT NULL,
    relay_url TEXT NOT NULL,
    model TEXT NOT NULL,
    relay_model TEXT NOT NULL,
    stream INTEGER NOT NULL,
    status TEXT NOT NULL,
    verdict TEXT,
    reason TEXT NOT NULL DEFAULT '',
    negative TEXT NOT NULL DEFAULT '{}',
    cost_official REAL NOT NULL DEFAULT 0,
    cost_relay REAL NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    finished_at REAL,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS rounds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id INTEGER NOT NULL,
    idx INTEGER NOT NULL,
    verdict TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    mint TEXT NOT NULL DEFAULT '{}',
    replay TEXT NOT NULL DEFAULT '{}',
    heuristics TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (record_id) REFERENCES records(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_records_task ON records(task_id);
CREATE INDEX IF NOT EXISTS idx_records_relay ON records(relay_id);
CREATE INDEX IF NOT EXISTS idx_rounds_record ON rounds(record_id);
CREATE INDEX IF NOT EXISTS idx_controls_task ON controls(task_id);
"""

JSON_FIELDS = {"model_map", "models", "relay_ids", "detail", "negative", "mint", "replay", "heuristics"}

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None


def init() -> None:
    global _conn
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    _conn.row_factory = sqlite3.Row
    _conn.execute("PRAGMA foreign_keys = ON")
    _conn.execute("PRAGMA journal_mode = WAL")
    _conn.executescript(SCHEMA)
    _conn.commit()


def now() -> float:
    return time.time()


def _decode(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    for k in JSON_FIELDS & d.keys():
        if isinstance(d[k], str):
            d[k] = json.loads(d[k])
    return d


def _encode(v):
    return json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v


def query(sql: str, params: tuple | list = ()) -> list[dict]:
    with _lock:
        return [_decode(r) for r in _conn.execute(sql, params).fetchall()]


def one(sql: str, params: tuple | list = ()) -> dict | None:
    with _lock:
        return _decode(_conn.execute(sql, params).fetchone())


def execute(sql: str, params: tuple | list = ()) -> int:
    with _lock:
        cur = _conn.execute(sql, [_encode(p) for p in params])
        _conn.commit()
        return cur.lastrowid


def insert(table: str, data: dict) -> int:
    cols = ", ".join(data)
    marks = ", ".join("?" for _ in data)
    return execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", list(data.values()))


def update(table: str, row_id: int, data: dict) -> None:
    if not data:
        return
    sets = ", ".join(f"{k} = ?" for k in data)
    execute(f"UPDATE {table} SET {sets} WHERE id = ?", [*data.values(), row_id])


def get_setting(key: str, default):
    row = one("SELECT value FROM settings WHERE key = ?", (key,))
    return json.loads(row["value"]) if row else default


def set_setting(key: str, value) -> None:
    execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, json.dumps(value)),
    )
