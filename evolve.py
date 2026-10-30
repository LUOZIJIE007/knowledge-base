"""自我进化引擎 — 持续学习、自动提炼、结构化整理、知识质量评估"""

import os, re, json, sqlite3, hashlib
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
CONTENT_DIR = os.path.join(BASE, "content")
DATA_DIR = os.path.join(BASE, "data")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "kb.db")

# ==================== 领域知识词典 ====================
DOMAIN_DICT = {
    "低压电气": ["低压配电", "断路器", "负荷计算", "线缆", "配电箱", "回路", "脱扣器", "漏电保护",
                  "RCD", "SPD", "电涌保护", "载流量", "电压降", "选择性", "配电系统", "供电"],
    "防雷接地": ["防雷", "接地", "接闪器", "引下线", "等电位", "SPD", "电涌保护器", "接地电阻",
                  "滚球法", "防雷等级", "LEB", "MEB", "TN-S", "浪涌", "过电压"],
    "弱电智能化": ["综合布线", "安防", "监控", "门禁", "楼宇自控", "BA", "DDC", "PoE",
                    "信息插座", "配线架", "光纤", "交换机", "NVR", "入侵报警", "广播", "会议"],
    "消防电气": ["火灾报警", "探测器", "感烟", "感温", "联动", "消防水泵", "排烟", "正压送风",
                  "应急照明", "疏散指示", "防火卷帘", "消防广播", "消防电话", "电气火灾监控", "灭火"],
    "规范标准": ["GB 50054", "GB 50052", "GB 50057", "GB 50116", "GB 51348", "GB 50311",
                  "GB 50016", "JGJ 16", "规范", "标准", "条文", "图集", "设计规范", "施工验收"],
}

# 同义词扩展（专业术语规范化）
SYNONYMS = {
    "空开": "断路器", "空开开关": "断路器", "开关": "断路器",
    "漏保": "漏电保护器", "漏电开关": "漏电保护器",
    "防雷器": "电涌保护器", "避雷器": "接闪器", "避雷针": "接闪器",
    "监控": "视频监控", "摄像头": "视频监控",
    "弱电箱": "综合布线", "网线": "综合布线",
    "喷淋": "自动喷水灭火", "烟感": "感烟探测器", "温感": "感温探测器",
    "强电": "低压配电", "配电柜": "配电箱",
    "布线": "综合布线", "光纤": "光缆",
}


def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.isolation_level = None
    return conn


def init_evolve_db():
    """初始化自我进化相关表"""
    db = get_db()
    db.execute("DROP TABLE IF EXISTS knowledge_domains")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS knowledge_domains (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        domain_name TEXT UNIQUE NOT NULL,
        description TEXT DEFAULT '',
        entry_count INTEGER DEFAULT 0,
        avg_quality REAL DEFAULT 0,
        last_evolved TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    );
    CREATE TABLE IF NOT EXISTS daily_evolutions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        type TEXT NOT NULL,
        title TEXT NOT NULL,
        content TEXT DEFAULT '',
        domain TEXT DEFAULT '',
        quality_score REAL DEFAULT 0,
        source TEXT DEFAULT '',
        tags TEXT DEFAULT '',
        structured_json TEXT DEFAULT '{}',
        created_at TEXT DEFAULT (datetime('now','localtime'))
    );
    CREATE TABLE IF NOT EXISTS knowledge_gaps (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        topic TEXT NOT NULL,
        domain TEXT NOT NULL,
        priority INTEGER DEFAULT 3,
        detail TEXT DEFAULT '',
        status TEXT DEFAULT 'open',
        resolved_at TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    );
    CREATE TABLE IF NOT EXISTS evolution_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        action TEXT NOT NULL,
        target TEXT DEFAULT '',
        detail TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now','localtime'))
    );
    CREATE TABLE IF NOT EXISTS domain_lexicon (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        term TEXT UNIQUE NOT NULL,
        domain TEXT NOT NULL,
        weight REAL DEFAULT 1.0,
        synonyms TEXT DEFAULT ''
    );
    """)
    db.close()


def load_lexicon():
    """加载领域词典到数据库"""
    db = get_db()
    for domain, terms in DOMAIN_DICT.items():
        for t in terms:
            syns = [k for k, v in SYNONYMS.items() if v == t]
            try:
                db.execute(
                    "INSERT OR IGNORE INTO domain_lexicon (term, domain, weight, synonyms) VALUES (?,?,?,?)",
                    (t, domain, 1.0, json.dumps(syns, ensure_ascii=False))
                )
            except: pass
    for syn, norm in SYNONYMS.items():
        try:
            db.execute(
                "INSERT OR IGNORE INTO domain_lexicon (term, domain, weight, synonyms) VALUES (?,?,?,?)",
                (syn, "同义词", 0.5, json.dumps([norm], ensure_ascii=False))
            )
        except: pass
    db.close()


def normalize_text(text):
    """专业术语规范化"""
    result = text
    for syn, norm in SYNONYMS.items():
        result = result.replace(syn, norm)
    return result


def classify_domain(text):
    """自动分类到专业领域"""
    scores = {}
    for domain, terms in DOMAIN_DICT.items():
        score = sum(1 for t in terms if t in text)
        if score > 0:
            scores[domain] = score
    if scores:
        return max(scores, key=scores.get)
    return "综合"


def extract_structured(text):
    """从文本中提取结构化知识"""
    result = {
        "terms": [],
        "numbers": [],
        "standards": [],
        "formulas": [],
        "tables_detected": "表格" in text or "|" in text,
        "sections": [],
    }
    # 提取专业术语
    for domain, terms in DOMAIN_DICT.items():
        for t in terms:
            if t in text:
                result["terms"].append({"term": t, "domain": domain})
    # 提取标准编号
    standards = re.findall(r'(GB[\s/]\d+[-–]\d+|JGJ[\s/]\d+[-–]\d+|GB/T[\s/]\d+[-–]\d+)', text)
    result["standards"] = list(set(standards))
    # 提取数值参数
    numbers = re.findall(r'(\d+\.?\d*)\s*(mA|kA|A|V|kV|Ω|lx|W/m²|W|kW|mm|m|km|℃|m²)', text)
    result["numbers"] = [{"value": n[0], "unit": n[1]} for n in numbers[:10]]
    # 提取公式
    formulas = re.findall(r'([A-Z]\w*\s*[=≈]\s*[^\n。;]+)', text)
    result["formulas"] = formulas[:5]
    # 提取章节标题
    sections = re.findall(r'^#{1,3}\s+(.+)$', text, re.MULTILINE)
    result["sections"] = sections[:10]
    return result


def compute_quality(text, structured):
    """计算知识质量评分（1-5）"""
    score = 3.0
    # 长度适中加分
    if 200 < len(text) < 5000: score += 0.5
    # 有结构化数据加分
    if structured["tables_detected"]: score += 0.3
    if structured["standards"]: score += 0.5
    if structured["numbers"]: score += 0.3
    if structured["formulas"]: score += 0.2
    if len(structured["sections"]) >= 3: score += 0.3
    # 术语密度加分
    term_density = len(structured["terms"]) / max(len(text) / 100, 1)
    if term_density > 2: score += 0.4
    return min(round(score, 1), 5.0)


# ==================== 核心进化功能 ====================

def digest_content(title, content, source=""):
    """提炼单条内容 — 术语规范化 + 自动分类 + 结构化提取 + 质量评估"""
    normalized = normalize_text(content)
    domain = classify_domain(title + " " + content)
    structured = extract_structured(normalized)
    quality = compute_quality(normalized, structured)

    tags = [domain]
    tags += [t["term"] for t in structured["terms"][:5]]
    tags = list(set(tags))

    db = get_db()
    db.execute("""
        INSERT INTO daily_evolutions (date, type, title, content, domain, quality_score, source, tags, structured_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        datetime.now().strftime("%Y-%m-%d"),
        "distilled", title, normalized, domain, quality, source,
        json.dumps(tags, ensure_ascii=False),
        json.dumps(structured, ensure_ascii=False)
    ))
    # 更新领域统计
    db.execute("""
        INSERT INTO knowledge_domains (domain_name, entry_count, avg_quality, last_evolved)
        VALUES (?, 1, ?, datetime('now','localtime'))
        ON CONFLICT(domain_name) DO UPDATE SET
            entry_count = entry_count + 1,
            avg_quality = (avg_quality * (entry_count) + ?) / (entry_count + 1),
            last_evolved = datetime('now','localtime')
    """, (domain, quality, quality))
    db.execute("INSERT INTO evolution_log (date, action, target, detail) VALUES (?,?,?,?)",
               (datetime.now().strftime("%Y-%m-%d"), "digest", title, f"分类:{domain} 质量:{quality}"))
    db.close()
    return {"domain": domain, "quality": quality, "tags": tags, "structured": structured}


def detect_gaps():
    """检测知识盲区"""
    db = get_db()
    gaps = []
    for domain, terms in DOMAIN_DICT.items():
        row = db.execute("SELECT COUNT(*) as cnt FROM daily_evolutions WHERE domain=?", (domain,)).fetchone()
        count = row["cnt"] if row else 0
        if count < 3:
            gaps.append({
                "topic": domain, "domain": domain,
                "priority": 1 if count == 0 else 2,
                "detail": f"当前 {count} 条，建议补充至 3 条以上"
            })
    # 检查规范覆盖
    rows = db.execute("SELECT DISTINCT tags FROM daily_evolutions").fetchall()
    all_tags = set()
    for r in rows:
        try: all_tags.update(json.loads(r["tags"]))
        except: pass
    for std in ["GB 50054", "GB 50057", "GB 50116", "GB 51348"]:
        if std not in all_tags:
            gaps.append({"topic": std, "domain": "规范标准", "priority": 2, "detail": f"缺少 {std} 相关内容"})
    for g in gaps:
        db.execute("INSERT INTO knowledge_gaps (topic, domain, priority, detail) VALUES (?,?,?,?)",
                   (g["topic"], g["domain"], g["priority"], g["detail"]))
    db.close()
    return gaps


def auto_evolve():
    """全自动进化 — 扫描内容目录、提炼、整理、评估"""
    log = {"evolved": 0, "gaps_found": 0, "domains_updated": 0, "actions": []}
    # 扫描 content 目录下所有 md 文件
    for root, dirs, files in os.walk(CONTENT_DIR):
        for f in files:
            if not f.endswith(".md"): continue
            path = os.path.join(root, f)
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    text = fh.read()
                # 解析 frontmatter
                title = f
                m = re.match(r'^---\s*\n(.*?)\n---', text, re.DOTALL)
                if m:
                    fm = m.group(1)
                    tm = re.search(r'title:\s*(.+)', fm)
                    if tm: title = tm.group(1).strip()
                    body = text[m.end():].strip()
                else:
                    body = text
                # 检查是否已处理过（内容指纹）
                content_hash = hashlib.md5(body.encode()).hexdigest()
                existing = db_check_fingerprint(content_hash)
                if existing: continue
                # 提炼
                result = digest_content(title, body, source=path)
                db_add_fingerprint(content_hash, title)
                log["evolved"] += 1
                log["domains_updated"] += 1
                log["actions"].append(f"提炼: {title} → {result['domain']} (质量:{result['quality']})")
            except Exception as e:
                log["actions"].append(f"错误: {f} - {str(e)}")
    # 检测盲区
    gaps = detect_gaps()
    log["gaps_found"] = len(gaps)
    log["actions"].append(f"盲区检测: 发现 {len(gaps)} 个")
    return log


def db_check_fingerprint(h):
    db = get_db()
    try:
        row = db.execute("SELECT 1 FROM content_fingerprints WHERE content_hash=?", (h,)).fetchone()
        return bool(row)
    except:
        return False
    finally:
        db.close()


def db_add_fingerprint(h, ref):
    db = get_db()
    try:
        db.execute("INSERT OR IGNORE INTO content_fingerprints (content_hash, reference) VALUES (?,?)", (h, ref))
    except: pass
    db.close()


def get_evolution_summary():
    """获取进化摘要"""
    try:
        db = get_db()
        domains = [dict(r) for r in db.execute("SELECT * FROM knowledge_domains ORDER BY entry_count DESC").fetchall()]
        recent = [dict(r) for r in db.execute("SELECT * FROM daily_evolutions ORDER BY created_at DESC LIMIT 10").fetchall()]
        gaps = [dict(r) for r in db.execute("SELECT * FROM knowledge_gaps WHERE status='open' ORDER BY priority LIMIT 10").fetchall()]
        total = db.execute("SELECT COUNT(*) as c FROM daily_evolutions").fetchone()["c"]
        avg_q = db.execute("SELECT AVG(quality_score) as a FROM daily_evolutions").fetchone()["a"] or 0
        db.close()
        return {
            "total_knowledge": total,
            "avg_quality": round(avg_q, 1),
            "domains": domains,
            "recent": recent,
            "gaps": gaps,
        }
    except Exception as e:
        return {"total_knowledge": 0, "avg_quality": 0, "domains": [], "recent": [], "gaps": [], "error": str(e)}


def get_domain_stats():
    """获取领域统计"""
    db = get_db()
    rows = [dict(r) for r in db.execute("""
        SELECT domain, COUNT(*) as count, AVG(quality_score) as avg_q
        FROM daily_evolutions GROUP BY domain ORDER BY count DESC
    """).fetchall()]
    db.close()
    return rows


if __name__ == "__main__":
    init_evolve_db()
    load_lexicon()
    result = auto_evolve()
    print(json.dumps(result, ensure_ascii=False, indent=2))
