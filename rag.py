# -*- coding: utf-8 -*-
"""RAG 问答引擎：BM25 检索 + LLM 生成，支持来源引用
零依赖纯 Python 实现"""
import math
import re
import json
import db
import llm
from db import now


# ==================== BM25 检索 ====================

def _tokenize(text):
    """中英文混合分词：英文按单词，中文按 bigram"""
    text = text.lower()
    tokens = []
    # 英文/数字
    tokens.extend(re.findall(r"[a-z0-9]+", text))
    # 中文 bigram
    chinese = re.findall(r"[\u4e00-\u9fff]+", text)
    for seg in chinese:
        if len(seg) == 1:
            tokens.append(seg)
        else:
            for i in range(len(seg) - 1):
                tokens.append(seg[i:i + 2])
            # 也加 unigram 提升召回
            tokens.extend(seg)
    return tokens


class BM25Index:
    """纯 Python BM25 索引"""
    def __init__(self, k1=1.5, b=0.75):
        self.k1 = k1
        self.b = b
        self.docs = []           # [{id, tokens, text, title, library, tags, len}]
        self.df = {}             # doc freq per term
        self.avgdl = 0

    def add(self, doc_id, text, title="", library="", tags=""):
        tokens = _tokenize(title + " " + tags + " " + text)
        self.docs.append({
            "id": doc_id, "tokens": tokens, "text": text[:500],
            "title": title, "library": library, "tags": tags,
            "len": len(tokens)
        })
        seen = set()
        for t in tokens:
            if t not in seen:
                self.df[t] = self.df.get(t, 0) + 1
                seen.add(t)

    def finalize(self):
        if self.docs:
            self.avgdl = sum(d["len"] for d in self.docs) / len(self.docs)

    def search(self, query, top_k=5):
        if not self.docs:
            return []
        q_tokens = _tokenize(query)
        scores = []
        n = len(self.docs)
        for i, doc in enumerate(self.docs):
            score = 0.0
            tf_map = {}
            for t in doc["tokens"]:
                tf_map[t] = tf_map.get(t, 0) + 1
            for t in q_tokens:
                if t not in tf_map:
                    continue
                tf = tf_map[t]
                df = self.df.get(t, 0)
                idf = math.log((n - df + 0.5) / (df + 0.5) + 1)
                denom = tf + self.k1 * (1 - self.b + self.b * doc["len"] / self.avgdl)
                score += idf * tf * (self.k1 + 1) / denom
            if score > 0:
                scores.append((score, i))
        scores.sort(reverse=True)
        results = []
        for score, i in scores[:top_k]:
            d = self.docs[i]
            results.append({
                "score": round(score, 3),
                "id": d["id"],
                "title": d["title"],
                "content": d["text"],
                "library": d["library"],
                "tags": d["tags"],
            })
        return results


def build_index(user_id):
    """从数据库构建 BM25 索引"""
    conn = db.get_conn()
    cards = conn.execute(
        "SELECT id, title, content, library, tags FROM cards WHERE user_id=? AND status='active'",
        (user_id,)
    ).fetchall()
    conn.close()
    index = BM25Index()
    for c in cards:
        index.add(c["id"], c["content"], c["title"], c["library"], c["tags"])
    index.finalize()
    return index


# ==================== RAG 问答 ====================

RAG_SYSTEM = """你是用户个人 AI 知识库的问答助手。根据提供的知识库内容回答问题。

规则：
1. 严格基于提供的知识库内容回答，不要编造
2. 如果知识库中没有相关内容，诚实说"知识库中暂时没有相关记录"
3. 回答末尾列出引用来源，格式：[来源: 标题]
4. 如果多个来源互补，综合整理回答
5. 回答简洁、结构化、直接有用"""


def answer(user_id, question, top_k=5):
    """RAG 问答：检索 + 生成"""
    index = build_index(user_id)
    results = index.search(question, top_k=top_k)

    if not results:
        return {
            "answer": "知识库中暂时没有相关记录。建议先添加一些知识内容再提问。",
            "sources": [],
            "mode": "empty"
        }

    # 构建上下文
    context_parts = []
    sources = []
    for i, r in enumerate(results, 1):
        context_parts.append(f"[{i}] {r['title']}（{r['library']}）\n{r['content']}")
        sources.append({"id": r["id"], "title": r["title"], "library": r["library"], "score": r["score"]})

    context = "\n\n".join(context_parts)
    prompt = f"知识库内容：\n{context}\n\n用户问题：{question}\n\n请基于以上知识库内容回答，末尾列出引用来源。"

    ai_answer = llm.chat(prompt, system=RAG_SYSTEM, max_tokens=1500)

    if ai_answer is None:
        # 规则降级模式
        lines = [f"找到 {len(results)} 条相关知识：\n"]
        for i, r in enumerate(results, 1):
            lines.append(f"**{i}. {r['title']}**（{r['library']}）")
            lines.append(f"   {r['content'][:150]}")
            lines.append("")
        lines.append("（当前为规则检索模式，配置 AI 接口后可获得智能综合回答）")
        ai_answer = "\n".join(lines)

    return {
        "answer": ai_answer,
        "sources": sources,
        "mode": "ai" if llm.is_ai_enabled() else "rule"
    }


# ==================== 知识图谱 ====================

KG_SYSTEM = """你是知识图谱抽取引擎。从文本中抽取实体和关系。

严格输出 JSON（不要其他文字）：
{
  "entities": [{"name": "实体名", "type": "concept|person|tool|method|field", "desc": "一句话描述"}],
  "relations": [{"from": "实体A", "to": "实体B", "label": "关系描述"}]
}

规则：
- 实体名用中文，2-8字
- 关系是有意义的知识关联（包含/使用/属于/对比/推导）
- 每次最多抽 10 个实体、15 个关系"""


def extract_entities(text, title=""):
    """抽取实体关系，优先 AI，降级规则"""
    prompt = f"标题：{title}\n内容：{text[:800]}"
    result = llm.chat(prompt, system=KG_SYSTEM, max_tokens=1000, temperature=0.2)
    if result:
        try:
            m = re.search(r"\{.*\}", result, re.S)
            if m:
                data = json.loads(m.group())
                if "entities" in data:
                    return data
        except Exception:
            pass
    # 规则降级：提取引号内术语 + 常见实体
    entities = []
    relations = []
    terms = re.findall(r"[「《]([^」》]{2,20})[」》]|【([^】]{2,20})】", text)
    terms = [t for pair in terms for t in pair if t]
    if title:
        terms.insert(0, title[:20])
    for t in terms[:10]:
        entities.append({"name": t, "type": "concept", "desc": ""})
    for i in range(len(entities) - 1):
        relations.append({"from": entities[i]["name"], "to": entities[i + 1]["name"], "label": "相关"})
    return {"entities": entities, "relations": relations}


KG_SCHEMA = """
CREATE TABLE IF NOT EXISTS kg_entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    type TEXT DEFAULT 'concept',
    desc TEXT DEFAULT '',
    freq INTEGER DEFAULT 1,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS kg_relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    from_id INTEGER NOT NULL,
    to_id INTEGER NOT NULL,
    label TEXT DEFAULT '相关',
    weight INTEGER DEFAULT 1,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS kg_card_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id INTEGER NOT NULL,
    card_id INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_kg_e_user ON kg_entities(user_id, name);
CREATE INDEX IF NOT EXISTS idx_kg_r_user ON kg_relations(user_id);
"""


def init_kg():
    conn = db.get_conn()
    conn.executescript(KG_SCHEMA)
    conn.close()


def _get_or_create_entity(conn, user_id, name, etype="concept", desc=""):
    row = conn.execute(
        "SELECT id FROM kg_entities WHERE user_id=? AND name=?", (user_id, name)
    ).fetchone()
    if row:
        conn.execute("UPDATE kg_entities SET freq=freq+1 WHERE id=?", (row["id"],))
        return row["id"]
    cur = conn.execute(
        "INSERT INTO kg_entities(user_id, name, type, desc, created_at) VALUES(?,?,?,?,?)",
        (user_id, name, etype, desc, now())
    )
    return cur.lastrowid


def ingest_card(user_id, card_id, title, content, tags=""):
    """从卡片中抽取知识图谱"""
    init_kg()
    data = extract_entities(content, title)
    conn = db.get_conn()
    ent_ids = {}
    for e in data.get("entities", []):
        eid = _get_or_create_entity(conn, user_id, e["name"], e.get("type", "concept"), e.get("desc", ""))
        ent_ids[e["name"]] = eid
        conn.execute("INSERT OR IGNORE INTO kg_card_links(entity_id, card_id) VALUES(?,?)", (eid, card_id))
    for r in data.get("relations", []):
        fid = ent_ids.get(r["from"])
        tid = ent_ids.get(r["to"])
        if fid and tid and fid != tid:
            existing = conn.execute(
                "SELECT id FROM kg_relations WHERE user_id=? AND from_id=? AND to_id=?",
                (user_id, fid, tid)
            ).fetchone()
            if existing:
                conn.execute("UPDATE kg_relations SET weight=weight+1 WHERE id=?", (existing["id"],))
            else:
                conn.execute(
                    "INSERT INTO kg_relations(user_id, from_id, to_id, label, created_at) VALUES(?,?,?,?,?)",
                    (user_id, fid, tid, r.get("label", "相关"), now())
                )
    conn.close()
    return len(data.get("entities", [])), len(data.get("relations", []))


def get_graph(user_id, min_freq=1, limit=80):
    """获取知识图谱 JSON（D3.js 力导向图格式）"""
    init_kg()
    conn = db.get_conn()
    entities = conn.execute(
        "SELECT id, name, type, freq FROM kg_entities WHERE user_id=? AND freq>=? ORDER BY freq DESC LIMIT ?",
        (user_id, min_freq, limit)
    ).fetchall()
    valid_ids = {e["id"] for e in entities}
    relations = conn.execute(
        "SELECT from_id, to_id, label, weight FROM kg_relations WHERE user_id=?",
        (user_id,)
    ).fetchall()
    conn.close()

    nodes = [{"id": str(e["id"]), "name": e["name"], "type": e["type"], "freq": e["freq"]} for e in entities]
    links = []
    for r in relations:
        if r["from_id"] in valid_ids and r["to_id"] in valid_ids:
            links.append({
                "source": str(r["from_id"]),
                "target": str(r["to_id"]),
                "label": r["label"],
                "weight": r["weight"]
            })
    return {"nodes": nodes, "links": links, "stats": {"entities": len(nodes), "relations": len(links)}}


# ==================== 自主学习代理 ====================

LEARNING_SCHEMA = """
CREATE TABLE IF NOT EXISTS learning_paths (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    steps TEXT DEFAULT '[]',
    progress REAL DEFAULT 0,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS learning_gaps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    topic TEXT NOT NULL,
    gap_type TEXT DEFAULT 'missing',
    detail TEXT DEFAULT '',
    resolved INTEGER DEFAULT 0,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS learning_streaks (
    user_id INTEGER PRIMARY KEY,
    current_streak INTEGER DEFAULT 0,
    longest_streak INTEGER DEFAULT 0,
    last_active_date TEXT DEFAULT '',
    total_cards_reviewed INTEGER DEFAULT 0,
    total_questions_asked INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS agent_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    agent_name TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT DEFAULT '',
    created_at REAL NOT NULL
);
"""


def init_learning():
    conn = db.get_conn()
    conn.executescript(LEARNING_SCHEMA)
    conn.close()


def detect_gaps(user_id):
    """检测知识盲区：分析卡片分布找出薄弱主题"""
    init_learning()
    conn = db.get_conn()
    cards = conn.execute(
        "SELECT title, content, tags, library FROM cards WHERE user_id=? AND status='active'",
        (user_id,)
    ).fetchall()
    conn.close()

    if not cards:
        return {"gaps": [], "coverage": {}}

    # 统计标签覆盖
    tag_freq = {}
    lib_freq = {}
    for c in cards:
        lib_freq[c["library"]] = lib_freq.get(c["library"], 0) + 1
        for t in (c["tags"] or "").split(","):
            t = t.strip()
            if t:
                tag_freq[t] = tag_freq.get(t, 0) + 1

    # 检测低覆盖领域
    gaps = []
    for lib in db.LIBRARIES:
        count = lib_freq.get(lib, 0)
        if count < 3:
            gaps.append({
                "topic": lib,
                "type": "low_coverage",
                "detail": f"{lib} 仅 {count} 条知识，建议补充",
            })

    # 检测孤立标签（只有1条关联）
    orphan_tags = [t for t, c in tag_freq.items() if c == 1]
    if orphan_tags:
        gaps.append({
            "topic": "、".join(orphan_tags[:5]),
            "type": "orphan_tags",
            "detail": f"{len(orphan_tags)} 个标签仅出现1次，可深入拓展",
        })

    return {"gaps": gaps, "coverage": lib_freq, "tag_count": len(tag_freq)}


def generate_learning_path(user_id, topic=""):
    """生成学习路径"""
    init_learning()
    ai_path = llm.chat(
        f"主题：{topic or '全领域知识'}\n请生成一个 5 步学习路径，每步包含标题和具体行动。输出 JSON: {{\"title\":\"...\",\"steps\":[{{\"step\":1,\"title\":\"...\",\"action\":\"...\"}}]}}",
        system="你是学习路径规划专家。输出严格 JSON。",
        max_tokens=800
    )
    if ai_path:
        try:
            m = re.search(r"\{.*\}", ai_path, re.S)
            if m:
                path = json.loads(m.group())
                conn = db.get_conn()
                cur = conn.execute(
                    "INSERT INTO learning_paths(user_id, title, description, steps, created_at) VALUES(?,?,?,?,?)",
                    (user_id, path.get("title", topic or "学习路径"), topic, json.dumps(path.get("steps", []), ensure_ascii=False), now())
                )
                conn.close()
                return {"id": cur.lastrowid, **path}
        except Exception:
            pass

    # 规则降级
    default_path = {
        "title": topic or "知识体系构建",
        "steps": [
            {"step": 1, "title": "基础概念", "action": f"学习{topic or '核心'}领域的基础概念和术语"},
            {"step": 2, "title": "实践应用", "action": "通过实际项目或案例练习"},
            {"step": 3, "title": "深度理解", "action": "阅读进阶资料，理解底层原理"},
            {"step": 4, "title": "知识输出", "action": "写总结、教别人、做分享"},
            {"step": 5, "title": "查漏补缺", "action": "回顾盲区，完善知识图谱"},
        ]
    }
    conn = db.get_conn()
    cur = conn.execute(
        "INSERT INTO learning_paths(user_id, title, description, steps, created_at) VALUES(?,?,?,?,?)",
        (user_id, default_path["title"], topic, json.dumps(default_path["steps"], ensure_ascii=False), now())
    )
    conn.close()
    return {"id": cur.lastrowid, **default_path}


def update_streak(user_id):
    """更新学习连击"""
    init_learning()
    import datetime
    today = datetime.date.today().isoformat()
    conn = db.get_conn()
    row = conn.execute("SELECT * FROM learning_streaks WHERE user_id=?", (user_id,)).fetchone()
    if row:
        last = row["last_active_date"]
        if last == today:
            pass  # 今天已打卡
        else:
            yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
            if last == yesterday:
                new_streak = row["current_streak"] + 1
            else:
                new_streak = 1
            longest = max(row["longest_streak"], new_streak)
            conn.execute(
                "UPDATE learning_streaks SET current_streak=?, longest_streak=?, last_active_date=? WHERE user_id=?",
                (new_streak, longest, today, user_id)
            )
    else:
        conn.execute(
            "INSERT INTO learning_streaks(user_id, current_streak, longest_streak, last_active_date) VALUES(?,?,?,?)",
            (user_id, 1, 1, today)
        )
    conn.close()


def get_learning_dashboard(user_id):
    """获取学习看板数据"""
    init_learning()
    update_streak(user_id)
    conn = db.get_conn()
    streak = conn.execute("SELECT * FROM learning_streaks WHERE user_id=?", (user_id,)).fetchone()
    cards_count = conn.execute("SELECT COUNT(*) c FROM cards WHERE user_id=? AND status='active'", (user_id,)).fetchone()["c"]
    reviews_today = conn.execute(
        "SELECT COUNT(*) c FROM cards WHERE user_id=? AND next_review_at<=?", (user_id, now() + 86400)
    ).fetchone()["c"]
    paths = conn.execute(
        "SELECT * FROM learning_paths WHERE user_id=? ORDER BY created_at DESC LIMIT 3", (user_id,)
    ).fetchall()
    conn.close()
    gaps = detect_gaps(user_id)
    return {
        "streak": dict(streak) if streak else {"current_streak": 0, "longest_streak": 0},
        "cards_count": cards_count,
        "reviews_today": reviews_today,
        "paths": [{"id": p["id"], "title": p["title"], "steps": json.loads(p["steps"])} for p in paths],
        "gaps": gaps["gaps"],
        "coverage": gaps["coverage"],
    }


# ==================== 知识蒸馏代理 ====================

DISTILL_REVIEW_SYSTEM = """你是知识蒸馏专家。分析用户的知识库，生成一份综述报告。

输出 Markdown 格式，包含：
1. **知识全景**：当前知识库覆盖的主题和结构
2. **核心洞见**：最重要的 3-5 个知识点
3. **知识关联**：概念之间的联系
4. **成长建议**：基于知识缺口的下一步行动"""


def generate_digest(user_id):
    """生成知识蒸馏综述"""
    init_learning()
    conn = db.get_conn()
    cards = conn.execute(
        "SELECT title, content, library, tags FROM cards WHERE user_id=? AND status='active' ORDER BY quality_score DESC LIMIT 30",
        (user_id,)
    ).fetchall()
    conn.close()

    if not cards:
        return {"digest": "知识库暂无内容，先添加一些知识吧！", "mode": "empty"}

    context = "\n".join([f"- [{c['library']}] {c['title']}: {c['content'][:80]}" for c in cards])

    ai_digest = llm.chat(
        f"知识库内容（共{len(cards)}条）：\n{context}\n\n请生成综述。",
        system=DISTILL_REVIEW_SYSTEM,
        max_tokens=1500
    )

    if ai_digest:
        conn = db.get_conn()
        conn.execute(
            "INSERT INTO agent_log(user_id, agent_name, action, detail, created_at) VALUES(?,?,?,?,?)",
            (user_id, "distiller", "generate_digest", f"生成综述，覆盖{len(cards)}条知识", now())
        )
        conn.close()
        return {"digest": ai_digest, "mode": "ai", "card_count": len(cards)}

    # 规则降级
    lines = [f"# 知识库综述（共 {len(cards)} 条知识）\n"]
    lines.append("## 知识全景\n")
    lib_stats = {}
    for c in cards:
        lib_stats[c["library"]] = lib_stats.get(c["library"], 0) + 1
    for lib, count in sorted(lib_stats.items()):
        lines.append(f"- **{lib}**: {count} 条")
    lines.append("\n## 核心知识\n")
    for c in cards[:5]:
        lines.append(f"- **{c['title']}**: {c['content'][:80]}")
    lines.append("\n（配置 AI 接口后可获得深度蒸馏综述）")
    return {"digest": "\n".join(lines), "mode": "rule", "card_count": len(cards)}


# ==================== 多 Agent 编排 ====================

AGENT_ROLES = {
    "researcher": {"name": "研究员", "desc": "负责内容采集、信息检索、资料分析"},
    "editor": {"name": "编辑", "desc": "负责知识整理、去重、格式化"},
    "tutor": {"name": "导师", "desc": "负责答疑、学习规划、复习指导"},
    "curator": {"name": "策展人", "desc": "负责知识蒸馏、体系化、图谱维护"},
}


def run_agents(user_id, task_type, input_data=""):
    """Agent 编排入口"""
    init_learning()
    results = {}

    if task_type == "analyze":
        # 全员出动分析知识库
        results["curator"] = generate_digest(user_id)
        results["tutor"] = {"gaps": detect_gaps(user_id)}
        results["editor"] = {"message": f"共 {len(db.get_conn().execute('SELECT COUNT(*) c FROM cards WHERE user_id=?', (user_id,)).fetchone()) if True else 0} 条知识待整理"}
        results["researcher"] = {"message": "研究员认为需要更多高质量外部资料"}

    elif task_type == "qa":
        results["tutor"] = answer(user_id, input_data)

    elif task_type == "learn":
        results["tutor"] = {"path": generate_learning_path(user_id, input_data)}

    elif task_type == "digest":
        results["curator"] = generate_digest(user_id)

    # 记录 Agent 日志
    conn = db.get_conn()
    for agent_name in results:
        conn.execute(
            "INSERT INTO agent_log(user_id, agent_name, action, detail, created_at) VALUES(?,?,?,?,?)",
            (user_id, agent_name, task_type, json.dumps(results[agent_name], ensure_ascii=False)[:500], now())
        )
    conn.close()

    return {
        "task": task_type,
        "agents": results,
        "roles": AGENT_ROLES
    }


def get_agent_log(user_id, limit=20):
    """获取 Agent 活动日志"""
    conn = db.get_conn()
    logs = conn.execute(
        "SELECT agent_name, action, detail, created_at FROM agent_log WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
        (user_id, limit)
    ).fetchall()
    conn.close()
    return [dict(l) for l in logs]
