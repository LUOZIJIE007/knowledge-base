# -*- coding: utf-8 -*-
"""清洗模块：去重检测、过期内容识别、内容规范化"""
import hashlib
import re
import time

import ops_db
import db


def normalize_title(title):
    """标题规范化：去空格、统一大小写"""
    if not title:
        return ""
    return re.sub(r"\s+", "", title).lower()


def content_fingerprint(title, content):
    """计算内容指纹"""
    norm_title = normalize_title(title)
    # 取前500字符做指纹
    body = content[:500] if content else ""
    raw = f"{norm_title}:{body}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def find_duplicates(uid, limit=50):
    """检测重复卡片"""
    conn = db.get_conn()
    cards = conn.execute("SELECT id, title, content, library, created_at FROM cards WHERE user_id=? AND status='active'", (uid,)).fetchall()
    conn.close()

    seen = {}
    duplicates = []
    for card in cards:
        fp = content_fingerprint(card["title"], card["content"])
        existing = seen.get(fp)
        if existing:
            duplicates.append({
                "card_id": card["id"],
                "title": card["title"],
                "duplicate_of": existing["id"],
                "duplicate_title": existing["title"],
            })
        else:
            seen[fp] = card
    return duplicates


def find_expired(uid, days=90):
    """识别过期内容：超过N天未修改且未被复习"""
    cutoff = time.time() - days * 86400
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT id, title, library, status, created_at, review_count FROM cards WHERE user_id=? AND status='active' AND created_at < ?",
        (uid, cutoff)
    ).fetchall()
    conn.close()

    expired = []
    for row in rows:
        # 超过90天未修改、复习次数为0的卡片标记为疑似过期
        if row["review_count"] == 0:
            expired.append({
                "card_id": row["id"],
                "title": row["title"],
                "library": row["library"],
                "days_since_created": int((time.time() - row["created_at"]) / 86400),
            })
    return expired


def clean_content(raw_text):
    """内容清洗：去除多余空白、HTML残留、特殊字符"""
    if not raw_text:
        return ""
    # 去HTML标签
    text = re.sub(r"<[^>]+>", "", raw_text)
    # 去多余空白
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"  {2,}", " ", text)
    # 去首尾空白
    text = text.strip()
    return text


def run_cleaning(uid, task_run_id):
    """执行完整清洗流程"""
    # 1. 去重检测
    duplicates = find_duplicates(uid)
    for dup in duplicates:
        ops_db.log_change("card", dup["card_id"], "duplicate_flagged",
                         reason=f"与卡片#{dup['duplicate_of']}({dup['duplicate_title']})内容重复",
                         task_run_id=task_run_id)

    # 2. 过期检测
    expired = find_expired(uid)
    for exp in expired:
        ops_db.flag_expired(exp["card_id"], "stale", f"超过{exp['days_since_created']}天未复习")
        ops_db.log_change("card", exp["card_id"], "expiry_flagged",
                         reason=f"超过{exp['days_since_created']}天未复习",
                         task_run_id=task_run_id)

    # 3. 内容清洗（更新采集记录中的raw_content）
    conn = db.get_conn()
    captures = conn.execute("SELECT id, raw_content FROM captures WHERE user_id=? AND status='pending'", (uid,)).fetchall()
    cleaned_count = 0
    for cap in captures:
        cleaned = clean_content(cap["raw_content"])
        if cleaned != cap["raw_content"]:
            conn.execute("UPDATE captures SET raw_content=? WHERE id=?", (cleaned, cap["id"]))
            cleaned_count += 1
    conn.close()

    return {
        "duplicates_found": len(duplicates),
        "expired_found": len(expired),
        "content_cleaned": cleaned_count,
    }
