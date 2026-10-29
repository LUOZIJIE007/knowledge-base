# -*- coding: utf-8 -*-
"""优化模块：知识分类优化、关联推荐、质量评分更新"""
import time

import ops_db
import db


def optimize_categories(uid, task_run_id):
    """优化知识分类：统计各库分布，建议调整"""
    conn = db.get_conn()
    # 统计各库卡片数
    libs = conn.execute("SELECT library, COUNT(*) as count FROM cards WHERE user_id=? AND status='active' GROUP BY library", (uid,)).fetchall()
    conn.close()

    suggestions = []
    lib_counts = {}
    for lib in libs:
        lib_counts[lib["library"]] = lib["count"]
        if lib["count"] == 0:
            suggestions.append({"action": "empty_library", "library": lib["library"], "reason": "该分类下无卡片"})

    # 如果某库卡片数过多（>50），建议拆分
    for lib, count in lib_counts.items():
        if count > 50:
            suggestions.append({"action": "split_library", "library": lib, "count": count, "reason": f"{lib}下有{count}张卡片，建议拆分"})

    return {"libraries": lib_counts, "suggestions": suggestions}


def find_related_cards(uid, min_similarity=0.3):
    """查找相关卡片（基于标签和库的相似性）"""
    conn = db.get_conn()
    cards = conn.execute("SELECT id, title, library, tags FROM cards WHERE user_id=? AND status='active'", (uid,)).fetchall()
    conn.close()

    related = []
    for i, card in enumerate(cards):
        tags = [t.strip() for t in (card["tags"] or "").split(",") if t.strip()]
        for j in range(i + 1, len(cards)):
            other = cards[j]
            other_tags = [t.strip() for t in (other["tags"] or "").split(",") if t.strip()]
            # 相同库
            same_lib = card["library"] == other["library"]
            # 共享标签
            shared = set(tags) & set(other_tags)
            if same_lib or len(shared) >= 1:
                related.append({
                    "card_id": card["id"],
                    "title": card["title"],
                    "related_card_id": other["id"],
                    "related_title": other["title"],
                    "reason": "same_library" if same_lib else f"shared_tags:{','.join(shared)}"
                })
    return related[:50]


def update_quality_scores(uid, task_run_id):
    """基于使用情况更新质量评分"""
    conn = db.get_conn()
    cards = conn.execute("SELECT id, quality_score, review_count, review_interval_days FROM cards WHERE user_id=? AND status='active'", (uid,)).fetchall()
    conn.close()

    updated = 0
    for card in cards:
        score = card["quality_score"] or 0
        review_count = card["review_count"] or 0
        # 基础分 + 复习次数加成 - 间隔衰减
        new_score = round(min(5.0, max(1.0, score + review_count * 0.1 - 0.5)), 1)
        if abs(new_score - score) > 0.5:
            ops_db.log_change("card", card["id"], "quality_update",
                           old_value=str(score), new_value=str(new_score),
                           reason=f"复习次数{review_count}次", task_run_id=task_run_id)
            updated += 1
    return {"updated": updated}


def run_optimization(uid, task_run_id):
    """执行完整优化流程"""
    results = {}
    results["categories"] = optimize_categories(uid, task_run_id)
    results["related"] = find_related_cards(uid)
    results["quality"] = update_quality_scores(uid, task_run_id)
    return results
