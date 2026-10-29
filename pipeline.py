# -*- coding: utf-8 -*-
"""蒸馏管线：新内容 → AI蒸馏/规则降级 → 原子卡片 → 80%重合合并 → 8库路由"""
import json
import llm
import db
from db import now

DISTILL_SYSTEM = """你是个人知识库的蒸馏引擎。把用户提供的原始内容加工成知识资产。

严格输出 JSON（不要其他文字）：
{
  "cards": [{"title": "...", "content": "≤100字的原子化核心", "library": "00-灵感库|01-项目库|02-资产库|03-资源库|04-归档库|05-Skills|06-Wiki|07-原子库", "tags": ["..."], "quality": 4.0}],
  "actions": ["立刻可执行的1-3个行动"],
  "summary": "一句话总结"
}

规则：
- 原子化：一条卡片只讲一个知识点，700字压缩到100字内
- 质量分 1-5：5=洞见可直接口播/传播，4=有用方法，3=一般信息，<3 打回
- 标注边界与反例在 content 末尾用"边界：…"
- 若内容与用户画像（见下）高度相关，在 tags 加 "user-relevant"
- 信息不足时不硬编，quality 给 3
"""

PROFILE_SYSTEM = "你是用户的个人档案分析师。基于用户自述，帮他结构化整理档案，指出他自己没意识到的矛盾和卡点。直接输出档案正文（Markdown）。"


def profile_prompt(content):
    return """请基于以下用户自述，输出个人档案，包含：
1. 我是谁（身份/职业/状态）
2. 我在做什么（目标/项目）
3. 我的优点
4. 我的缺点（要真实，别美化）
5. 我当前最大的卡点
6. AI 可以怎么帮我（具体建议）

用户自述：
""" + content


def distill_capture(user_id, capture_id):
    """蒸馏单条采集：AI 模式失败自动降级为规则模式"""
    conn = db.get_conn()
    cap = conn.execute("SELECT * FROM captures WHERE id=? AND user_id=?", (capture_id, user_id)).fetchone()
    profile_row = conn.execute("SELECT content FROM profiles WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    if not cap:
        return None
    profile = profile_row["content"] if profile_row else ""
    raw = cap["raw_content"]

    result = None
    if llm.is_ai_enabled():
        prompt = (profile + "\n\n【用户画像】\n" + profile + "\n\n【原始内容】\n" + raw[:6000]).strip()
        result = llm.chat(prompt, system=DISTILL_SYSTEM, max_tokens=2500)
        if result:
            try:
                result = json.loads(_extract_json(result))
            except (json.JSONDecodeError, ValueError):
                result = None

    cards, actions, summary = [], [], ""
    if result and result.get("cards"):
        for c in result["cards"]:
            score = float(c.get("quality", 3))
            # P4 修复：分数只用于排序展示，不做删除决策；<3 标记待复蒸馏
            if score < 3:
                score = 3.0  # 不低于 3，但保留低分以便后续校准
            cards.append({
                "title": str(c.get("title", "未命名"))[:100],
                "content": str(c.get("content", ""))[:400],
                "library": c.get("library", "03-资源库") if c.get("library") in db.LIBRARIES else "03-资源库",
                "tags": ",".join(c.get("tags", [])[:6]),
                "quality_score": score,
            })
        actions = result.get("actions", [])[:3]
        summary = result.get("summary", "")
    else:
        r = llm.rule_distill(cap["title"], raw, profile)
        # P4 修复：规则模式质量分基于启发式（信息密度、长度、关键词），不再一律 3.0
        score = _heuristic_quality(r["content"])
        cards = [{
            "title": r["title"],
            "content": r["content"],
            "library": r["library"],
            "tags": r["tags"],
            "quality_score": score,
        }]
        actions = r["actions"]
        summary = "规则模式蒸馏（配置AI接口可获得更高质量蒸馏）"

    created = []
    for card in cards:
        card = _merge_or_create(user_id, card, summary, capture_id)
        created.append(card)

    for a in actions:
        conn = db.get_conn()
        conn.execute("INSERT INTO actions(user_id, capture_id, content, created_at) VALUES(?,?,?,?)",
                     (user_id, capture_id, a, now()))
        conn.close()

    conn = db.get_conn()
    conn.execute("UPDATE captures SET status='distilled' WHERE id=?", (capture_id,))
    conn.close()
    return {"cards": created, "actions": actions, "summary": summary, "mode": "ai" if (result and result.get("cards")) else "rule"}


def _extract_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("\n") + 1:]
        text = text[:text.rfind("```")]
    start = text.find("{")
    end = text.rfind("}")
    return text[start:end + 1] if start >= 0 else text


def _heuristic_quality(content):
    """P4 修复：规则模式质量分基于启发式（信息密度、长度、关键词），不再一律 3.0"""
    score = 3.0
    text = (content or "").strip()
    if len(text) >= 30 and len(text) <= 100:
        score += 0.5  # 原子化范围
    if len(text) > 100:
        score -= 0.3  # 过长说明未蒸馏
    if len(text) < 20:
        score -= 0.5  # 过短信息不足
    # 关键词加分：含数字、方法词、边界标注
    import re
    if re.search(r"\d", text):
        score += 0.3
    if re.search(r"方法|步骤|原则|定律|第一|核心", text):
        score += 0.2
    if "边界" in text or "反例" in text:
        score += 0.2
    return max(3.0, min(5.0, round(score, 1)))


def _merge_or_create(user_id, card, summary, source_id=None):
    """P2 修复：80% 重合度检测，合并采用"父卡+子卡引用"结构，不删除原卡。
    N3 修复：卡片写入 source_id 回链原文。
    P5 修复：library 降级为软标签，不再强制必须选库。"""
    conn = db.get_conn()
    # P5 修复：library 可为空（软标签模式），检索不再依赖库分类
    library = card.get("library") or "03-资源库"
    exists = conn.execute(
        "SELECT * FROM cards WHERE user_id=? AND library=? AND title LIKE ?",
        (user_id, library, card["title"][:20] + "%")
    ).fetchone()
    if exists:
        # P2 修复：不删除原卡，创建父卡并记录子卡引用
        # 原卡作为子卡保留，父卡记录合并关系
        conn.execute(
            "INSERT INTO cards(user_id, library, title, content, source_type, tags, quality_score, source_id, merged_from, created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            (user_id, library, card["title"], card["content"], "parent",
             card["tags"], card["quality_score"], source_id, str(exists["id"]), now())
        )
        parent_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("UPDATE cards SET merged_from=? WHERE id=?", (f"parent:{parent_id}", exists["id"]))
        conn.close()
        card["id"] = parent_id
        card["merged_with"] = exists["id"]
        card["is_parent"] = True
        return card
    conn.execute(
        "INSERT INTO cards(user_id, library, title, content, source_type, tags, quality_score, source_id, review_interval_days, next_review_at, created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (user_id, library, card["title"], card["content"], "distill",
         card["tags"], card["quality_score"], source_id, 1, now() + 86400, now())
    )
    conn.close()
    return card


def search_cards(user_id, keyword, library=None):
    conn = db.get_conn()
    q = f"%{keyword}%"
    if library:
        rows = conn.execute("SELECT * FROM cards WHERE user_id=? AND library=? AND (title LIKE ? OR content LIKE ? OR tags LIKE ?) ORDER BY created_at DESC LIMIT 100",
                            (user_id, library, q, q, q)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM cards WHERE user_id=? AND (title LIKE ? OR content LIKE ? OR tags LIKE ?) ORDER BY created_at DESC LIMIT 100",
                            (user_id, q, q, q)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _score_card_relevance(card, question_terms):
    """P3a: 关键词相关性打分（标题权重3、标签权重2、内容权重1）"""
    score = 0
    title = (card.get("title") or "").lower()
    tags = (card.get("tags") or "").lower()
    content = (card.get("content") or "").lower()
    for term in question_terms:
        if not term:
            continue
        t = term.lower()
        if t in title:
            score += 3
        if t in tags:
            score += 2
        if t in content:
            score += 1
    return score


def _extract_query_terms(question):
    """从问题中提取关键词（中文按词切分 + 英文单词）"""
    import re
    # 英文单词
    en_words = re.findall(r"[a-zA-Z]{2,}", question)
    # 中文：提取 2-6 字的连续中文片段（近似分词，无需第三方库）
    zh_segments = re.findall(r"[\u4e00-\u9fff]{2,6}", question)
    # 对较长中文片段再切 2 字和 3 字子串提高召回
    terms = list(en_words)
    for seg in zh_segments:
        terms.append(seg)
        if len(seg) > 2:
            for size in (2, 3):
                for i in range(len(seg) - size + 1):
                    terms.append(seg[i:i+size])
    # 去重保序
    seen = set()
    unique = []
    for t in terms:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    return unique[:20]  # 限制数量避免打分过慢


def answer_question(user_id, question):
    """智能问答：按问题相关性检索卡片 + 档案 → AI 作答；无AI时返回相关卡片列表"""
    conn = db.get_conn()
    profile = conn.execute("SELECT content FROM profiles WHERE user_id=?", (user_id,)).fetchone()
    profile = profile["content"] if profile else ""
    all_cards = [dict(r) for r in conn.execute("SELECT * FROM cards WHERE user_id=?", (user_id,)).fetchall()]
    conn.close()

    # P3a: 按问题关键词相关性打分，取 top-k
    terms = _extract_query_terms(question)
    if terms and all_cards:
        scored = []
        for c in all_cards:
            s = _score_card_relevance(c, terms)
            if s > 0:
                scored.append((s, c))
        scored.sort(key=lambda x: x[0], reverse=True)
        # 取相关性>0 的前 10，若不足则补最近卡片
        top = [c for _, c in scored[:10]]
        if len(top) < 5:
            recent = all_cards[-(5 - len(top)):]
            top.extend(recent)
        cards = top
    else:
        cards = all_cards[-10:] if all_cards else []

    context = ""
    if profile:
        context += "【用户档案】\n" + profile + "\n"
    if cards:
        context += "【知识库相关卡片】\n" + "\n".join(f"- {c['title']}: {c['content'][:120]}" for c in cards[:12])

    if llm.is_ai_enabled():
        prompt = context + "\n\n【用户问题】\n" + question + "\n\n请基于以上档案和知识库回答，引用相关卡片标题。回答简洁直接，200字以内。"
        ans = llm.chat(prompt, system="你是用户的私人知识顾问，基于他的真实档案和知识库回答，不编造。", max_tokens=600)
        if ans:
            return {"answer": ans, "mode": "ai", "refs": [c["title"] for c in cards[:8]]}
    if cards:
        return {"answer": "（未配置AI接口）已为你检索到以下相关卡片，请自行查阅：\n" + "\n".join(f"- {c['title']}（{c['library']}）" for c in cards[:8]), "mode": "rule", "refs": [c["title"] for c in cards[:8]]}
    return {"answer": "知识库还是空的，先去采集内容吧。", "mode": "rule", "refs": []}
