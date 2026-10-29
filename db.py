# -*- coding: utf-8 -*-
"""SQLite 数据层：零依赖，用户数据隔离"""
import sqlite3
import os
import time
import secrets

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "kb.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phone TEXT UNIQUE NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS profiles (
    user_id INTEGER PRIMARY KEY,
    content TEXT NOT NULL DEFAULT '',
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS captures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    source_type TEXT NOT NULL,      -- link / file / note / video
    source_url TEXT DEFAULT '',
    title TEXT DEFAULT '',
    raw_content TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending / distilled / archived
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    library TEXT NOT NULL,          -- 00-灵感 01-项目 02-资产 03-资源 04-归档 05-Skills 06-Wiki 07-原子
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    source_type TEXT DEFAULT 'distill',
    source_id INTEGER,
    tags TEXT DEFAULT '',
    quality_score REAL DEFAULT 0,
    merged_from TEXT DEFAULT '',
    status TEXT DEFAULT 'active',   -- active / corrected / retired
    -- P6: 间隔重复（SRS）字段
    review_interval_days INTEGER DEFAULT 1,
    next_review_at REAL,
    review_count INTEGER DEFAULT 0,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    capture_id INTEGER,
    content TEXT NOT NULL,
    done INTEGER DEFAULT 0,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    date TEXT NOT NULL,             -- YYYY-MM-DD
    content TEXT NOT NULL,
    ai_analysis TEXT DEFAULT '',
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS corrections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    error TEXT NOT NULL,
    context TEXT DEFAULT '',
    lesson TEXT DEFAULT '',
    status TEXT DEFAULT 'open',     -- open / corrected / reviewed
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS meta_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    kind TEXT NOT NULL,             -- bias / model / insight / growth
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cards_user ON cards(user_id, library);
CREATE INDEX IF NOT EXISTS idx_captures_user ON captures(user_id);
"""

LIBRARIES = ["00-灵感库", "01-项目库", "02-资产库", "03-资源库", "04-归档库", "05-Skills", "06-Wiki", "07-原子库"]


def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, isolation_level=None)  # 自动提交
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        # P6: 迁移——为已有数据库补 SRS 列
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(cards)").fetchall()}
        for col, default in [("review_interval_days", "1"), ("next_review_at", None), ("review_count", "0")]:
            if col not in cols:
                d = f"DEFAULT {default}" if default else "DEFAULT NULL"
                conn.execute(f"ALTER TABLE cards ADD COLUMN {col} {d}")
                # 已有卡片初始化为 1 天后复习
                if col == "next_review_at":
                    conn.execute("UPDATE cards SET next_review_at=? WHERE next_review_at IS NULL", (now() + 86400,))


def now():
    return time.time()


def create_user(phone):
    with get_conn() as conn:
        cur = conn.execute("INSERT INTO users(phone, created_at) VALUES(?,?)", (phone, now()))
        uid = cur.lastrowid
        conn.execute("INSERT INTO profiles(user_id, content, updated_at) VALUES(?,?,?)", (uid, "", now()))
    return uid


def get_user_by_phone(phone):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE phone=?", (phone,)).fetchone()
    return dict(row) if row else None


def create_session(user_id):
    token = secrets.token_hex(32)
    with get_conn() as conn:
        # M2 修复：清理过期会话，避免 DB 无限累积
        conn.execute("DELETE FROM sessions WHERE expires_at<?", (now(),))
        conn.execute("INSERT INTO sessions(token, user_id, expires_at) VALUES(?,?,?)", (token, user_id, now() + 7 * 86400))
    return token


def get_user_by_token(token):
    with get_conn() as conn:
        row = conn.execute("SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE token=? AND expires_at>?", (token, now())).fetchone()
    return dict(row) if row else None


def ensure_dev_user():
    """确保开发者用户存在（固定 ID=0，phone='developer'）"""
    with get_conn() as conn:
        # 先检查是否已存在
        row = conn.execute("SELECT id FROM users WHERE phone='developer'").fetchone()
        if row:
            dev_id = row["id"]
        else:
            # 创建 dev 用户
            cur = conn.execute("INSERT INTO users(id, phone, created_at) VALUES(0, 'developer', ?)", (now(),))
            dev_id = 0
        # 确保 profile 存在
        conn.execute("INSERT OR IGNORE INTO profiles(user_id, content, updated_at) VALUES(?, '', ?)", (dev_id, now()))
    return dev_id
