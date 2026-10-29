# -*- coding: utf-8 -*-
"""版本管理模块：快照管理、变更说明、版本回滚"""
import json
import time

import ops_db
import db


def create_snapshot(uid, version_tag, description=""):
    """创建当前知识库快照"""
    data = {"profile": None, "cards": [], "captures": [], "reviews": [], "corrections": [], "meta_notes": [], "actions": []}
    conn = db.get_conn()
    p = conn.execute("SELECT content FROM profiles WHERE user_id=?", (uid,)).fetchone()
    data["profile"] = p["content"] if p else ""
    for table in ("cards", "captures", "reviews", "corrections", "meta_notes", "actions"):
        data[table] = [dict(r) for r in conn.execute(f"SELECT * FROM {table} WHERE user_id=?", (uid,)).fetchall()]
    conn.close()

    ops_db.save_snapshot(version_tag, description, json.dumps(data, ensure_ascii=False),
                        len(data["cards"]), len(data["captures"]))
    return {"version_tag": version_tag, "card_count": len(data["cards"]), "capture_count": len(data["captures"])}


def list_versions():
    """列出所有版本"""
    return ops_db.get_snapshots()


def get_version(version_tag):
    """获取指定版本详情"""
    versions = ops_db.get_snapshots(limit=100)
    for v in versions:
        if v["version_tag"] == version_tag:
            data = json.loads(v["snapshot_data"])
            return {"version_tag": version_tag, "description": v["description"], "data": data, "created_at": v["created_at"]}
    return None


def rollback(uid, version_tag):
    """回滚到指定版本"""
    ver = get_version(version_tag)
    if not ver:
        return {"error": "版本不存在"}

    data = ver["data"]
    conn = db.get_conn()
    try:
        # 先清空当前数据
        for table in ("cards", "captures", "reviews", "corrections", "meta_notes", "actions", "profiles"):
            conn.execute(f"DELETE FROM {table} WHERE user_id=?", (uid,))
        # 恢复快照数据
        if data.get("profile") is not None:
            conn.execute("INSERT INTO profiles(user_id, content, updated_at) VALUES(?,?,?)", (uid, data["profile"], ops_db.now()))
        for table in ("cards", "captures", "reviews", "corrections", "meta_notes", "actions"):
            for row in data.get(table, []):
                cols = list(row.keys())
                cols_sql = ",".join(cols)
                ph = ",".join("?" for _ in cols)
                vals = [row[c] for c in cols]
                conn.execute(f"INSERT INTO {table}({cols_sql}) VALUES({ph})", vals)
    except Exception as e:
        conn.close()
        return {"error": f"回滚失败: {e}"}
    conn.close()

    ops_db.log_change("knowledge_base", uid, "rollback",
                     old_value="current", new_value=version_tag,
                     reason=f"回滚到版本{version_tag}")
    return {"rolled_back": True, "version_tag": version_tag}
