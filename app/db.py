"""SQLite storage. One file, one user."""
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS profile (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    sex TEXT,                 -- 'm' or 'f'
    birth_date TEXT,          -- YYYY-MM-DD
    height_cm REAL,
    weight_kg REAL,
    goal_kcal_delta INTEGER DEFAULT 0,    -- -400 = deficit, +300 = surplus
    protein_g_per_kg REAL DEFAULT 1.8,
    fat_g_per_kg REAL DEFAULT 0.9,
    active_kcal_factor REAL DEFAULT 0.85  -- watches overestimate active calories
);
INSERT OR IGNORE INTO profile (id) VALUES (1);

-- One row per day, filled from Health Connect aggregates
CREATE TABLE IF NOT EXISTS daily_activity (
    date TEXT PRIMARY KEY,
    steps INTEGER,
    distance_m REAL,
    active_kcal REAL,
    total_kcal REAL,
    resting_hr REAL,
    avg_hr REAL,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sleep_sessions (
    start_time TEXT PRIMARY KEY,   -- ISO with offset
    end_time TEXT NOT NULL,
    wake_date TEXT NOT NULL,       -- local date the sleep ended on
    duration_min REAL,
    deep_min REAL, light_min REAL, rem_min REAL, awake_min REAL
);

-- Food diary (from FatSecret via Health Connect, or logged through the bot)
CREATE TABLE IF NOT EXISTS food_entries (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,          -- 'health_connect' or 'bot'
    time TEXT NOT NULL,
    date TEXT NOT NULL,
    name TEXT,
    meal TEXT,
    kcal REAL, protein_g REAL, fat_g REAL, carbs_g REAL
);
CREATE INDEX IF NOT EXISTS food_entries_date ON food_entries(date);

CREATE TABLE IF NOT EXISTS weight_log (
    time TEXT PRIMARY KEY,
    date TEXT NOT NULL,
    kg REAL NOT NULL
);

-- Fridge / pantry: raw products and cooked dishes
CREATE TABLE IF NOT EXISTS inventory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'product',   -- 'product' or 'dish'
    quantity REAL,
    unit TEXT,                              -- g, ml, pcs, portion
    kcal_per_100g REAL, protein_per_100g REAL, fat_per_100g REAL, carbs_per_100g REAL,
    expires_on TEXT,
    note TEXT,
    added_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS preferences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,   -- likes, dislikes, allergy, habit, goal, other
    text TEXT NOT NULL,
    added_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def rows(conn: sqlite3.Connection, sql: str, params=()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def row(conn: sqlite3.Connection, sql: str, params=()) -> dict | None:
    r = conn.execute(sql, params).fetchone()
    return dict(r) if r else None
