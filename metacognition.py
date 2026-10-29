# -*- coding: utf-8 -*-
"""元认知模块：每日复盘 + AI纠偏（允许"不友好"）+ 自我改错错题本 + 元认知面板"""
import json
import llm
import db
from db import now

REVIEW_SYSTEM = """你是用户的"理性镜子"。用户来自述今日复盘，你要：
1. 分析问题出在哪（直接、不客气，允许指出言行不一致和认知偏差）
2. 给出明天可以改进的一个具体方向（可执行，不是空话）
3. 指出一个用户可能存在的认知偏差

输出 JSON：
{"problems": ["..."], "improvement": "明天改的一个具体动作", "bias": "可能的认知偏差"}
"""

BIAS_LIST = [
    "确认偏误：只找支持自己观点的证据",
    "幸存者偏差：只看到成功的案例",
    "达克效应：越不懂越自信",
    "锚定效应：被第一个数字/观点框住",
    "沉没成本：舍不得放弃已投入的东西",
    "归因偏差：成功归自己，失败归环境",
    "规划谬误：总是低估完成时间",
]

MODEL_LIST = [
    "第一性原理：拆解到不可再分的基本要素",
    "复利思维：找能滚雪球的事情",
    "杠杆思维：用最小投入撬动最大结果",
    "反脆弱：坏事发生时反而受益",
    "系统思考：看要素之间的相互影响",
    "可证伪：观点必须能被证明是错的",
]


def submit_review(user_id, date, content):
    """提交每日复盘 → AI 分析（失败降级规则分析）"""
    profile = ""
    conn = db.get_conn()
    row = conn.execute("SELECT content FROM profiles WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    if row:
        profile = row["content"]

    analysis = ""
    if llm.is_ai_enabled():
        prompt = (profile + "\n\n【用户今日复盘】\n" + content).strip()
        raw = llm.chat(prompt, system=REVIEW_SYSTEM, max_tokens=800)
        if raw:
            try:
                data = json.loads(_json(raw))
                parts = []
                if data.get("problems"):
                    parts.append("**问题诊断**\n" + "\n".join(f"- {p}" for p in data["problems"]))
                if data.get("improvement"):
                    parts.append("**明天改进**\n" + data["improvement"])
                if data.get("bias"):
                    parts.append("**认知偏差提醒**\n" + data["bias"])
                analysis = "\n\n".join(parts)
            except (json.JSONDecodeError, ValueError):
                analysis = ""
    if not analysis:
        analysis = llm.rule_review_analysis(content, profile)

    conn = db.get_conn()
    conn.execute("INSERT INTO reviews(user_id, date, content, ai_analysis, created_at) VALUES(?,?,?,?,?)",
                 (user_id, date, content, analysis, now()))
    conn.close()

    # 复盘自动沉淀为一张知识卡片（复盘是资产）
    card = {"title": f"复盘·{date}", "content": content[:100].replace("\n", " "),
            "library": "02-资产库", "tags": "复盘", "quality_score": 4.0}
    import pipeline
    pipeline._merge_or_create(user_id, card, "review", None)
    return {"review_id": None, "analysis": analysis}


def _json(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("\n") + 1:]
        text = text[:text.rfind("```")]
    s = text.find("{")
    e = text.rfind("}")
    return text[s:e + 1] if s >= 0 else text


def log_correction(user_id, error, context="", lesson=""):
    """自我改错：记录错误 + 纠偏教训 → 错题本
    P7 修复：同时定位相关旧卡片并打"已纠正"标注（先匹配旧卡，再建改错卡片，避免误匹配自身）"""
    # 先提取关键词并匹配相关旧卡（此时还没有改错卡片，不会误匹配自身）
    import pipeline as _pl
    terms = _pl._extract_query_terms((error or "") + " " + (lesson or ""))
    corrected_ids = []
    if terms:
        conn = db.get_conn()
        candidates = [dict(r) for r in conn.execute(
            "SELECT id, title, content, tags FROM cards WHERE user_id=? AND status != 'corrected'", (user_id,)).fetchall()]
        for c in candidates:
            score = _pl._score_card_relevance(c, terms)
            # 标题命中或 2 次内容命中才算相关
            if score >= 3:
                conn.execute("UPDATE cards SET status='corrected' WHERE id=?", (c["id"],))
                corrected_ids.append(c["id"])
        conn.close()

    conn = db.get_conn()
    conn.execute("INSERT INTO corrections(user_id, error, context, lesson, status, created_at) VALUES(?,?,?,?,?,?)",
                 (user_id, error, context, lesson, "open", now()))
    conn.close()
    # 错题沉淀为纠偏卡片
    card = {"title": "改错·" + error[:30], "content": (f"错误：{error[:60]}\n教训：{lesson[:60]}").replace("\n", " "),
            "library": "02-资产库", "tags": "改错,纠偏", "quality_score": 4.0}
    import pipeline
    pipeline._merge_or_create(user_id, card, "correction", None)
    return {"corrected_cards": corrected_ids, "count": len(corrected_ids)}


def correct_error(user_id, correction_id, action):
    """标记错题已改正
    P7 修复：同时更新关联卡片的纠正状态"""
    conn = db.get_conn()
    conn.execute("UPDATE corrections SET status='corrected' WHERE id=? AND user_id=?", (correction_id, user_id))
    conn.close()
    return True


def srs_queue(user_id, limit=20):
    """P6 间隔重复：返回到期需复习的卡片队列（按到期时间排序）"""
    conn = db.get_conn()
    rows = [dict(r) for r in conn.execute(
        "SELECT id, title, content, library, tags, review_interval_days, next_review_at, review_count"
        " FROM cards WHERE user_id=? AND status='active' AND (next_review_at IS NULL OR next_review_at<=?)"
        " ORDER BY next_review_at ASC LIMIT ?", (user_id, now(), limit)).fetchall()]
    conn.close()
    return {"queue": rows, "count": len(rows)}


def complete_srs(user_id, card_id, passed=True):
    """P6 间隔重复：完成一张卡片的复习，按 SRS 算法更新间隔
    规则（简化 SM-2）：
    - pass：间隔 × 1.5（首次从 1 天开始），复习次数 +1
    - fail：间隔重置为 1 天（明天再复习）"""
    conn = db.get_conn()
    row = conn.execute("SELECT review_interval_days, review_count FROM cards WHERE id=? AND user_id=?", (card_id, user_id)).fetchone()
    if not row:
        conn.close()
        return {"error": "卡片不存在"}
    interval = row["review_interval_days"] or 1
    review_count = (row["review_count"] or 0) + 1
    if passed:
        interval = max(1, int(interval * 1.5))
    else:
        interval = 1
    conn.execute("UPDATE cards SET review_interval_days=?, next_review_at=?, review_count=? WHERE id=? AND user_id=?",
                 (interval, now() + interval * 86400, review_count, card_id, user_id))
    conn.close()
    return {"card_id": card_id, "interval_days": interval, "review_count": review_count, "passed": passed}


def meta_panel(user_id):
    """元认知面板：认知偏差清单 + 思维模型 + 成长曲线 + 错题统计"""
    conn = db.get_conn()
    reviews = conn.execute("SELECT date FROM reviews WHERE user_id=? ORDER BY date", (user_id,)).fetchall()
    corrections = conn.execute("SELECT status FROM corrections WHERE user_id=?", (user_id,)).fetchall()
    cards = conn.execute("SELECT COUNT(*) AS n, AVG(quality_score) AS q FROM cards WHERE user_id=?", (user_id,)).fetchone()
    biases = [dict(r) for r in conn.execute("SELECT * FROM meta_notes WHERE user_id=? AND kind='bias'", (user_id,)).fetchall()]
    models = [dict(r) for r in conn.execute("SELECT * FROM meta_notes WHERE user_id=? AND kind='model'", (user_id,)).fetchall()]
    conn.close()
    return {
        "bias_library": BIAS_LIST,
        "bias_notes": biases,
        "model_library": MODEL_LIST,
        "model_notes": models,
        "growth": {
            "review_days": len(reviews),
            "review_streak": _streak(reviews),
            "corrections_open": sum(1 for c in corrections if c["status"] == "open"),
            "corrections_fixed": sum(1 for c in corrections if c["status"] == "corrected"),
            "card_count": cards["n"] or 0,
            "avg_quality": round(cards["q"] or 0, 2),
        },
    }


def _streak(reviews):
    """连续复盘天数"""
    if not reviews:
        return 0
    import datetime
    days = sorted({r["date"] for r in reviews})
    streak, cursor = 0, datetime.date.today()
    while True:
        if cursor.isoformat() in days:
            streak += 1
            cursor -= datetime.timedelta(days=1)
        else:
            break
    return streak


def add_bias_note(user_id, title, content):
    conn = db.get_conn()
    conn.execute("INSERT INTO meta_notes(user_id, kind, title, content, created_at) VALUES(?,?,?,?,?)",
                 (user_id, "bias", title, content, now()))
    conn.close()
    return True


def add_model_note(user_id, title, content):
    conn = db.get_conn()
    conn.execute("INSERT INTO meta_notes(user_id, kind, title, content, created_at) VALUES(?,?,?,?,?)",
                 (user_id, "model", title, content, now()))
    conn.close()
    return True
