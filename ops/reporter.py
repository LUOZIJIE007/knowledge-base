# -*- coding: utf-8 -*-
"""报告模块：每日更新摘要生成"""
import json
import time

import ops_db


def generate_daily_digest(uid, task_run_id, collect_result, clean_result, optimize_result, snapshot_result):
    """生成每日更新摘要"""
    today = time.strftime("%Y-%m-%d")
    digest = {
        "date": today,
        "task_run_id": task_run_id,
        "summary": {
            "total_sources": len(ops_db.get_sources(enabled_only=True)),
            "sources_fetched": collect_result.get("sources_fetched", 0),
            "new_items": collect_result.get("items_created", 0),
            "duplicate_items": clean_result.get("duplicates_found", 0),
            "expired_items": clean_result.get("expired_found", 0),
            "content_cleaned": clean_result.get("content_cleaned", 0),
            "optimizations": optimize_result.get("quality", {}).get("updated", 0),
            "changes_count": 0,
        },
        "details": {
            "collection": collect_result,
            "cleaning": clean_result,
            "optimization": optimize_result,
            "snapshot": snapshot_result,
        },
        "suggestions": [],
    }

    # 生成建议
    if clean_result.get("expired_found", 0) > 0:
        digest["suggestions"].append(f"⚠️ 检测到{clean_result['expired_found']}条过期内容，建议审查或归档")
    if optimize_result.get("categories", {}).get("suggestions"):
        for sug in optimize_result["categories"]["suggestions"]:
            if sug["action"] == "split_library":
                digest["suggestions"].append(f"📌 {sug['library']}下有{sug['count']}张卡片，建议拆分")
    if optimize_result.get("related"):
        digest["suggestions"].append(f"🔗 发现{len(optimize_result['related'])}组相关卡片，可建立关联")

    # 统计变更日志数
    logs = ops_db.get_change_logs(limit=1000)
    digest["summary"]["changes_count"] = len(logs)

    # 保存摘要
    ops_db.save_digest(
        today, task_run_id,
        digest["summary"]["total_sources"], digest["summary"]["sources_fetched"],
        digest["summary"]["new_items"], 0, digest["summary"]["duplicate_items"],
        digest["summary"]["expired_items"], digest["summary"]["optimizations"],
        digest["summary"]["changes_count"],
        json.dumps(digest, ensure_ascii=False, indent=2)
    )

    return digest


def get_digest(date=None):
    """获取指定日期的摘要，默认最新"""
    if date:
        digest = ops_db.get_digest_by_date(date)
    else:
        digests = ops_db.get_digests(limit=1)
        digest = digests[0] if digests else None
    if digest:
        digest["digest_data"] = json.loads(digest.pop("digest_json", "{}"))
    return digest


def get_digest_history(limit=15):
    """获取历史摘要列表"""
    digests = ops_db.get_digests(limit=limit)
    for d in digests:
        d.pop("digest_json", None)
    return digests
