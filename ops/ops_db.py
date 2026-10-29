# -*- coding: utf-8 -*-
"""运维数据库层：版本记录、变更日志、任务状态、重复检测、源配置"""
import sqlite3
import os
import time

OPS_DIR = os.path.dirname(os.path.abspath(__file__))
OPS_DB_PATH = os.path.join(os.path.dirname(OPS_DIR), "data", "ops.db")

SCHEMA = """
-- 源配置表
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    source_type TEXT NOT NULL DEFAULT 'rss',
    url TEXT NOT NULL,
    category TEXT DEFAULT '',
    keywords TEXT DEFAULT '',
    enabled INTEGER DEFAULT 1,
    created_at REAL NOT NULL,
    last_fetched_at REAL,
    last_fetch_status TEXT DEFAULT '',
    fetch_count INTEGER DEFAULT 0
);

-- 任务状态表
CREATE TABLE IF NOT EXISTS task_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    started_at REAL NOT NULL,
    finished_at REAL,
    duration REAL,
    items_processed INTEGER DEFAULT 0,
    items_created INTEGER DEFAULT 0,
    items_updated INTEGER DEFAULT 0,
    items_deleted INTEGER DEFAULT 0,
    items_duplicated INTEGER DEFAULT 0,
    error_count INTEGER DEFAULT 0,
    summary TEXT DEFAULT ''
);

-- 版本快照表
CREATE TABLE IF NOT EXISTS version_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version_tag TEXT UNIQUE NOT NULL,
    description TEXT DEFAULT '',
    snapshot_data TEXT NOT NULL,
    card_count INTEGER DEFAULT 0,
    capture_count INTEGER DEFAULT 0,
    created_at REAL NOT NULL
);

-- 变更日志表
CREATE TABLE IF NOT EXISTS change_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,
    entity_id INTEGER,
    action TEXT NOT NULL,
    old_value TEXT DEFAULT '',
    new_value TEXT DEFAULT '',
    reason TEXT DEFAULT '',
    task_run_id INTEGER,
    created_at REAL NOT NULL
);

-- 内容指纹表（重复检测）
CREATE TABLE IF NOT EXISTS content_fingerprints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id INTEGER,
    fingerprint TEXT UNIQUE NOT NULL,
    content_hash TEXT NOT NULL,
    title_normalized TEXT DEFAULT '',
    source TEXT DEFAULT '',
    created_at REAL NOT NULL,
    last_seen_at REAL NOT NULL
);

-- 过期内容标记表
CREATE TABLE IF NOT EXISTS expiry_flags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id INTEGER NOT NULL,
    flag_type TEXT NOT NULL,
    reason TEXT DEFAULT '',
    flagged_at REAL NOT NULL,
    reviewed INTEGER DEFAULT 0,
    review_result TEXT DEFAULT ''
);

-- 每日摘要表
CREATE TABLE IF NOT EXISTS daily_digests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    task_run_id INTEGER,
    total_sources INTEGER DEFAULT 0,
    sources_fetched INTEGER DEFAULT 0,
    new_items INTEGER DEFAULT 0,
    updated_items INTEGER DEFAULT 0,
    duplicate_items INTEGER DEFAULT 0,
    expired_items INTEGER DEFAULT 0,
    optimizations INTEGER DEFAULT 0,
    changes_count INTEGER DEFAULT 0,
    digest_json TEXT NOT NULL,
    created_at REAL NOT NULL
);

-- 运维设置表
CREATE TABLE IF NOT EXISTS ops_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    description TEXT DEFAULT '',
    updated_at REAL NOT NULL
);
"""


def get_conn():
    os.makedirs(os.path.dirname(OPS_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(OPS_DB_PATH, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def now():
    return time.time()


def upsert_source(name, source_type, url, category="", keywords=""):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO sources(name, source_type, url, category, keywords, created_at) VALUES(?,?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET source_type=excluded.source_type, url=excluded.url, category=excluded.category, keywords=excluded.keywords",
            (name, source_type, url, category, keywords, now())
        )


def get_sources(enabled_only=True):
    with get_conn() as conn:
        if enabled_only:
            rows = conn.execute("SELECT * FROM sources WHERE enabled=1").fetchall()
        else:
            rows = conn.execute("SELECT * FROM sources").fetchall()
    return [dict(r) for r in rows]


def update_source_status(name, status, fetched_at=None):
    with get_conn() as conn:
        conn.execute("UPDATE sources SET last_fetch_status=?, last_fetched_at=?, fetch_count=fetch_count+1 WHERE name=?",
                     (status, fetched_at or now(), name))


def start_task_run(task_name):
    with get_conn() as conn:
        cur = conn.execute("INSERT INTO task_runs(task_name, status, started_at) VALUES(?,?,?)", (task_name, "running", now()))
        return cur.lastrowid


def finish_task_run(run_id, status, items_processed=0, items_created=0, items_updated=0, items_deleted=0, items_duplicated=0, error_count=0, summary=""):
    with get_conn() as conn:
        conn.execute(
            "UPDATE task_runs SET status=?, finished_at=?, duration=?, items_processed=?, items_created=?, items_updated=?, items_deleted=?, items_duplicated=?, error_count=?, summary=? WHERE id=?",
            (status, now(), now() - 0, items_processed, items_created, items_updated, items_deleted, items_duplicated, error_count, summary, run_id)
        )


def get_task_runs(limit=20):
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM task_runs ORDER BY started_at DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def save_snapshot(version_tag, description, snapshot_data, card_count, capture_count):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO version_snapshots(version_tag, description, snapshot_data, card_count, capture_count, created_at) VALUES(?,?,?,?,?,?) ON CONFLICT(version_tag) DO UPDATE SET description=excluded.description, snapshot_data=excluded.snapshot_data, card_count=excluded.card_count, capture_count=excluded.capture_count, created_at=excluded.created_at",
            (version_tag, description, snapshot_data, card_count, capture_count, now())
        )


def get_snapshots(limit=20):
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM version_snapshots ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def log_change(entity_type, entity_id, action, old_value="", new_value="", reason="", task_run_id=None):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO change_logs(entity_type, entity_id, action, old_value, new_value, reason, task_run_id, created_at) VALUES(?,?,?,?,?,?,?,?)",
            (entity_type, entity_id, action, old_value, new_value, reason, task_run_id, now())
        )


def get_change_logs(entity_type=None, entity_id=None, limit=50):
    with get_conn() as conn:
        if entity_type and entity_id:
            rows = conn.execute("SELECT * FROM change_logs WHERE entity_type=? AND entity_id=? ORDER BY created_at DESC LIMIT ?", (entity_type, entity_id, limit)).fetchall()
        elif entity_type:
            rows = conn.execute("SELECT * FROM change_logs WHERE entity_type=? ORDER BY created_at DESC LIMIT ?", (entity_type, limit)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM change_logs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def add_fingerprint(card_id, fingerprint, content_hash, title_normalized, source=""):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO content_fingerprints(card_id, fingerprint, content_hash, title_normalized, source, created_at, last_seen_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(fingerprint) DO UPDATE SET last_seen_at=excluded.last_seen_at, card_id=excluded.card_id",
            (card_id, fingerprint, content_hash, title_normalized, source, now(), now())
        )


def check_fingerprint(fingerprint):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM content_fingerprints WHERE fingerprint=?", (fingerprint,)).fetchone()
    return dict(row) if row else None


def get_fingerprints(card_id=None, limit=100):
    with get_conn() as conn:
        if card_id:
            rows = conn.execute("SELECT * FROM content_fingerprints WHERE card_id=?", (card_id,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM content_fingerprints ORDER BY last_seen_at DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def flag_expired(card_id, flag_type, reason=""):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO expiry_flags(card_id, flag_type, reason, flagged_at) VALUES(?,?,?,?) ON CONFLICT(card_id, flag_type) DO UPDATE SET reason=excluded.reason, flagged_at=excluded.flagged_at",
            (card_id, flag_type, reason, now())
        )


def get_expiry_flags(reviewed=None, limit=50):
    with get_conn() as conn:
        if reviewed is None:
            rows = conn.execute("SELECT * FROM expiry_flags ORDER BY flagged_at DESC LIMIT ?", (limit,)).fetchall()
        elif reviewed:
            rows = conn.execute("SELECT * FROM expiry_flags WHERE reviewed=1 ORDER BY flagged_at DESC LIMIT ?", (limit,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM expiry_flags WHERE reviewed=0 ORDER BY flagged_at DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def review_expiry(flag_id, reviewed, result=""):
    with get_conn() as conn:
        conn.execute("UPDATE expiry_flags SET reviewed=?, review_result=? WHERE id=?", (1 if reviewed else 0, result, flag_id))


def save_digest(date, task_run_id, total_sources, sources_fetched, new_items, updated_items, duplicate_items, expired_items, optimizations, changes_count, digest_json):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO daily_digests(date, task_run_id, total_sources, sources_fetched, new_items, updated_items, duplicate_items, expired_items, optimizations, changes_count, digest_json, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (date, task_run_id, total_sources, sources_fetched, new_items, updated_items, duplicate_items, expired_items, optimizations, changes_count, digest_json, now())
        )


def get_digests(limit=30):
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM daily_digests ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_digest_by_date(date):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM daily_digests WHERE date=?", (date,)).fetchone()
    return dict(row) if row else None


def get_setting(key, default=None):
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM ops_settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key, value, description=""):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO ops_settings(key, value, description, updated_at) VALUES(?,?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, description=excluded.description, updated_at=excluded.updated_at",
            (key, value, description, now())
        )


def get_all_settings():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM ops_settings ORDER BY key").fetchall()
    return [dict(r) for r in rows]
