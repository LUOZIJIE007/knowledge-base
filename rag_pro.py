"""专业 RAG 检索引擎 v2 — 结构化深度回答
参考 GitHub 项目: KG_RAG, deep-rag, SubgraphRAG 的最佳实践
核心改进: 解析内容结构 → 按意图重组 → 生成专业级深度回答
"""

import os, re, json, math, sqlite3
from collections import Counter, OrderedDict

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, "data")
os.makedirs(DATA_DIR, exist_ok=True)

# ==================== 领域 & 意图 ====================

DOMAIN_LABELS = {
    "低压电气": "⚡ 低压电气", "防雷接地": "🌩 防雷接地",
    "弱电智能化": "📡 弱电智能化", "消防电气": "🔥 消防电气",
    "规范标准": "📋 规范标准", "综合": "📌 综合",
}

INTENT_PATTERNS = {
    "选型": ["选型", "选择", "选用", "怎么选", "如何选", "推荐", "用什么", "配什么"],
    "规范": ["规范", "标准", "条文", "要求", "规定", "限值", "间距", "距离", "多少米", "照度", "参数"],
    "列举": ["有哪些", "包括", "包含", "列举", "种类", "类型", "分类"],
    "计算": ["计算", "公式", "怎么算", "多大", "截面", "容量", "功率", "电流"],
    "故障": ["故障", "问题", "原因", "为什么", "排查", "维修", "不工作", "跳闸"],
    "设计": ["设计", "怎么做", "如何做", "步骤", "流程", "方法", "方案"],
    "对比": ["区别", "对比", "比较", "哪个好", "优缺点", "不同", "差异"],
}

SYNONYMS = {
    "空开": "断路器", "漏保": "漏电保护器", "防雷器": "电涌保护器",
    "监控": "视频监控", "烟感": "感烟探测器", "喷淋": "自动喷水灭火",
    "强电": "低压配电", "布线": "综合布线", "避雷": "防雷",
    "空开选型": "断路器选型", "开关": "断路器",
}

DOMAIN_TERMS = {
    "低压电气": ["低压","配电","断路器","负荷","线缆","回路","脱扣","漏电","载流量","电压降","配电箱","导线","电缆","变压器","母线"],
    "防雷接地": ["防雷","接地","接闪","引下","等电位","SPD","浪涌","接地电阻","防雷等级","雷电","接闪器","引下线"],
    "弱电智能化": ["弱电","布线","安防","监控","门禁","楼宇","DDC","PoE","信息插座","交换机","综合布线","光纤","网络"],
    "消防电气": ["消防","火灾","探测器","感烟","感温","联动","排烟","应急照明","疏散","喷淋","防火卷帘","消防水泵"],
    "规范标准": ["规范","标准","GB","JGJ","条文","图集","设计规范"],
}


# ==================== 查询理解 ====================

def detect_intent(query):
    for intent, keywords in INTENT_PATTERNS.items():
        if any(k in query for k in keywords):
            return intent
    return "general"


def expand_query(query):
    expanded = query
    for syn, norm in SYNONYMS.items():
        if syn in expanded and norm not in expanded:
            expanded += " " + norm
    return expanded


def tokenize(text):
    text = re.sub(r'[^\w\s一-鿿]', ' ', text)
    tokens = []
    all_terms = set()
    for terms in DOMAIN_TERMS.values():
        all_terms.update(terms)
    for t in sorted(all_terms, key=len, reverse=True):
        if t in text:
            tokens.append(t)
            text = text.replace(t, ' ')
    words = text.split()
    for w in words:
        if len(w) >= 2:
            tokens.append(w)
            for i in range(len(w)-1):
                tokens.append(w[i:i+2])
        elif w.strip():
            tokens.append(w)
    return tokens


def bm25_search(query, docs, k1=1.5, b=0.75):
    if not docs: return []
    expanded = expand_query(query)
    query_tokens = tokenize(expanded)
    if not query_tokens: return []
    doc_tokens = [tokenize(doc["text"]) for doc in docs]
    avgdl = sum(len(t) for t in doc_tokens) / len(doc_tokens) if doc_tokens else 1
    df = Counter()
    for tokens in doc_tokens:
        for t in set(tokens): df[t] += 1
    scores = []
    for i, tokens in enumerate(doc_tokens):
        score = 0.0
        tf = Counter(tokens)
        for q in query_tokens:
            if q not in tf: continue
            n = len(docs)
            idf = math.log((n - df.get(q, 0) + 0.5) / (df.get(q, 0) + 0.5) + 1)
            score += idf * tf[q] * (k1 + 1) / (tf[q] + k1 * (1 - b + b * len(tokens) / avgdl))
        scores.append((i, score))
    scores.sort(key=lambda x: x[1], reverse=True)
    return scores


# ==================== 内容解析（结构化提取） ====================

def parse_content_structure(text):
    """解析 Markdown 内容的完整结构：章节、表格、列表、公式"""
    result = {
        "sections": [],      # [{title, content, tables, lists}]
        "tables": [],        # [{headers, rows}]
        "formulas": [],      # 公式行
        "standards": [],     # 规范编号
        "numbers": [],       # 关键数值
        "key_sentences": [],  # 核心结论句
    }

    current_section = {"title": "", "content": [], "tables": [], "lists": []}
    lines = text.split('\n')
    in_table = False
    table_rows = []
    table_headers = []

    for line in lines:
        stripped = line.strip()

        # 标题 → 新章节
        if stripped.startswith('#'):
            if current_section["title"] or current_section["content"]:
                result["sections"].append(current_section)
            current_section = {"title": stripped.lstrip('#').strip(), "content": [], "tables": [], "lists": []}
            in_table = False
            continue

        # 表格
        if '|' in stripped and len(stripped) > 3:
            # 跳过分隔行
            raw_cells = stripped.replace('|', ' ').split()
            if raw_cells and all(c.strip('-:') == '' for c in raw_cells):
                continue
            cells = [c.strip() for c in stripped.split('|') if c.strip()]
            if not in_table:
                in_table = True
                table_headers = cells
                table_rows = []
            else:
                table_rows.append(cells)
            continue
        elif in_table:
            # 表格结束
            if table_headers and table_rows:
                t = {"headers": table_headers, "rows": table_rows}
                result["tables"].append(t)
                current_section["tables"].append(t)
            in_table = False

        # 列表项
        if stripped.startswith('- ') or stripped.startswith('* '):
            current_section["lists"].append(stripped[2:])
            # 提取关键句
            item = stripped[2:]
            if any(k in item for k in ['核心', '关键', '原则', '注意', '要求', '优点', '缺点', '适用']):
                result["key_sentences"].append(item)
            continue

        # 编号列表
        if re.match(r'^\d+[\.\、]', stripped):
            current_section["lists"].append(stripped)
            continue

        # 公式行
        if re.search(r'[=＝×÷√∑]', stripped) and re.search(r'\w', stripped):
            result["formulas"].append(stripped)
            current_section["content"].append(stripped)
            continue

        # 普通文本
        if stripped and len(stripped) > 3:
            current_section["content"].append(stripped)
            # 提取规范编号
            for m in re.finditer(r'(GB[\s/]\d+[-–]\d+|JGJ[\s/]\d+[-–]\d+|GB/T[\s/]\d+[-–]\d+)', stripped):
                result["standards"].append(m.group(1))
            # 提取数值
            for m in re.finditer(r'(\d+\.?\d*)\s*(mA|kA|A|V|kV|Ω|lx|W/m²|W|kW|mm|m|km|℃|m²|h|s)', stripped):
                result["numbers"].append(f"{m.group(1)}{m.group(2)}")

    # 保存最后一个章节
    if current_section["title"] or current_section["content"]:
        result["sections"].append(current_section)

    # 处理结尾的表格
    if in_table and table_headers and table_rows:
        t = {"headers": table_headers, "rows": table_rows}
        result["tables"].append(t)

    # 合并父子章节：父章节（无内容）吸收子章节内容
    merged = []
    for sec in result["sections"]:
        if merged and not sec["title"].startswith(('一', '二', '三', '四', '五', '六', '七', '八', '九', '十', '#')):
            # 子章节：合并到上一个父章节
            parent = merged[-1]
            parent["content"].extend(sec["content"])
            parent["lists"].extend(sec["lists"])
            parent["tables"].extend(sec["tables"])
        elif merged and not (merged[-1]["content"] or merged[-1]["lists"] or merged[-1]["tables"]):
            # 父章节无内容，子章节有内容 → 合并
            parent = merged[-1]
            parent["content"].extend(sec["content"])
            parent["lists"].extend(sec["lists"])
            parent["tables"].extend(sec["tables"])
        else:
            merged.append(sec)
    result["sections"] = merged

    result["standards"] = list(set(result["standards"]))
    result["numbers"] = list(set(result["numbers"]))[:15]
    return result


# ==================== 专业回答生成器 ====================

class AnswerBuilder:
    """专业回答构建器 — 按意图生成结构化深度回答"""

    def __init__(self, question, intent, domain, sources_data):
        self.question = question
        self.intent = intent
        self.domain = domain
        self.sources = sources_data  # [{title, text, parsed, score, library}]

    def build(self):
        """构建完整回答"""
        if not self.sources:
            return self._no_result()

        # 合并所有来源的解析结果（带领域相关性过滤）
        all_tables = []
        all_formulas = []
        all_standards = []
        all_key_sentences = []
        all_sections = []
        all_numbers = []

        for s in self.sources:
            p = s.get("parsed", {})
            # 只取领域相关或第一个来源的全部内容
            is_primary = (s == self.sources[0])
            is_relevant = (s.get("domain") == self.domain)
            if is_primary or is_relevant:
                all_tables.extend(p.get("tables", []))
                all_formulas.extend(p.get("formulas", []))
                all_key_sentences.extend(p.get("key_sentences", []))
                all_sections.extend(p.get("sections", []))
            all_standards.extend(p.get("standards", []))
            all_numbers.extend(p.get("numbers", []))

        all_standards = list(set(all_standards))
        all_numbers = list(set(all_numbers))[:12]

        # 按意图选择回答模板
        builders = {
            "选型": self._answer_selection,
            "计算": self._answer_calculation,
            "规范": self._answer_standards,
            "故障": self._answer_troubleshoot,
            "设计": self._answer_design,
            "对比": self._answer_comparison,
            "列举": self._answer_listing,
            "general": self._answer_general,
        }
        builder = builders.get(self.intent, self._answer_general)
        return builder(all_tables, all_formulas, all_standards, all_key_sentences, all_sections, all_numbers)

    def _header(self):
        label = DOMAIN_LABELS.get(self.domain, "📌")
        return f"**{label} | {self.question}**\n"

    def _no_result(self):
        return (f"**❌ 未找到**「{self.question}」的直接答案。\n\n"
                "**建议：**\n"
                "1. 换用专业术语提问（如「断路器选型」「防雷等级」「负荷计算」）\n"
                "2. 在「采集」页面补充相关知识资料\n"
                "3. 查看「知识图谱」了解已有知识覆盖范围")

    def _format_table(self, table, max_rows=8):
        """格式化表格为 Markdown"""
        if not table.get("headers") or not table.get("rows"):
            return ""
        headers = table["headers"]
        rows = table["rows"][:max_rows]
        lines = ["| " + " | ".join(headers) + " |"]
        lines.append("|" + "|".join(["---"] * len(headers)) + "|")
        for row in rows:
            # 补齐列数
            while len(row) < len(headers):
                row.append("")
            lines.append("| " + " | ".join(row[:len(headers)]) + " |")
        return "\n".join(lines)

    def _format_all_tables(self, tables, max_tables=2):
        """格式化多个表格"""
        result = []
        for i, t in enumerate(tables[:max_tables]):
            formatted = self._format_table(t)
            if formatted:
                result.append(formatted)
        return "\n\n".join(result)

    # ---------- 选型类回答 ----------
    def _answer_selection(self, tables, formulas, standards, key_sents, sections, numbers):
        parts = [self._header()]

        # 1. 选型步骤
        parts.append("### 📋 选型步骤\n")
        steps = [
            "**Step 1** — 计算负荷电流 Ijs（需要系数法）",
            "**Step 2** — 确定额定电流 In ≥ Ijs",
            "**Step 3** — 校验分断能力 Icu ≥ 安装点最大短路电流",
            "**Step 4** — 选择脱扣特性（C 型 / D 型 / 电子式）",
            "**Step 5** — 校验上下级选择性配合（系数 ≥ 1.2）",
        ]
        for s in steps:
            parts.append(f"- {s}")

        # 2. 核心公式
        if formulas:
            parts.append("\n### 🔢 关键公式\n")
            for f in formulas[:4]:
                parts.append(f"```\n{f}\n```")

        # 3. 选型参数表
        if tables:
            parts.append("\n### 📊 选型参数速查\n")
            parts.append(self._format_all_tables(tables))

        # 4. 从内容中提取选型要点
        selection_tips = [s for s in key_sents if any(k in s for k in ['选型', '额定', '分断', '脱扣', '配合', '选择'])]
        if not selection_tips:
            # 从 section lists 中提取
            for sec in sections:
                for item in sec.get("lists", []):
                    if any(k in item for k in ['选型', '额定', 'In', 'Icu', '脱扣']):
                        selection_tips.append(item)

        if selection_tips:
            parts.append("\n### ✅ 选型要点\n")
            for t in selection_tips[:6]:
                parts.append(f"- {t}")

        # 5. 参数汇总
        if numbers:
            parts.append(f"\n### 📐 关键参数\n`{'`  `'.join(numbers[:8])}`")

        # 6. 规范依据
        if standards:
            parts.append(f"\n### 📜 规范依据\n{'、'.join(standards)}")

        # 7. 实操建议
        # 领域专属建议
        domain_advice = {
            "防雷接地": [
                "- **先定等级**：按 GB 50057 计算 N 值确定防雷等级",
                "- **联合接地优先**：共用接地体 ≤ 1Ω，经济且安全",
                "- **SPD 三级配合**：I 级→总配、II 级→分配、III 级→设备端",
            ],
            "消防电气": [
                "- **报警形式**：大型建筑用控制中心报警，中型用集中报警",
                "- **消防电源**：双电源+EPS，线路用矿物绝缘电缆（耐火 3h）",
                "- **联动逻辑**：先报警→确认→联动，误报率要控制",
            ],
            "弱电智能化": [
                "- **布线先行**：综合布线是基础，预留 20% 冗余",
                "- **网络架构**：核心/汇聚/接入三层，PoE 供电 ≤ 90m",
                "- **安防覆盖**：无死角+人脸可识别（≥ 50px）",
            ],
            "低压电气": [
                "- **先算后选**：先完成负荷计算，再根据 Ijs 选 In",
                "- **留有裕量**：In 取 1.1~1.25 倍 Ijs，避免频繁跳闸",
                "- **上下级配合**：总断路器分断能力 ≥ 所有下级短路电流之和",
                "- **消防回路**：仅设短路保护，不设过载保护（GB 50054 §6.1.2）",
            ],
        }
        advice = domain_advice.get(self.domain, domain_advice["低压电气"])
        parts.append("\n### 💡 实操建议\n")
        for a in advice:
            parts.append(a)

        return "\n".join(parts)

    # ---------- 计算类回答 ----------
    def _answer_calculation(self, tables, formulas, standards, key_sents, sections, numbers):
        parts = [self._header()]

        parts.append("### 🔢 计算方法\n")
        calc_sections = [s for s in sections if any(k in s["title"] for k in ['计算', '公式', '负荷', '功率', '电流'])]
        if calc_sections:
            for sec in calc_sections[:2]:
                if sec["title"]:
                    parts.append(f"**{sec['title']}**")
                for line in sec["content"][:5]:
                    parts.append(f"  {line}")
                if sec.get("lists"):
                    for item in sec["lists"][:5]:
                        parts.append(f"  - {item}")
                parts.append("")
        else:
            parts.append("基于知识库中的计算方法：\n")
            for line in key_sents[:3]:
                parts.append(f"- {line}")

        if formulas:
            parts.append("\n### 📐 核心公式\n")
            for f in formulas[:5]:
                parts.append(f"```\n{f}\n```")

        if tables:
            parts.append("\n### 📊 计算参数表\n")
            parts.append(self._format_all_tables(tables))

        if numbers:
            parts.append(f"\n### 📏 常用参数\n`{'`  `'.join(numbers[:10])}`")

        if standards:
            parts.append(f"\n### 📜 规范依据\n{'、'.join(standards)}")

        parts.append("\n### 💡 计算提示\n")
        parts.append("- **需要系数 Kx**：民用建筑取 0.3~0.8（查 GB 51348 附录）")
        parts.append("- **功率因数 cosφ**：照明 0.9，动力 0.8，综合 0.85")
        parts.append("- **同时系数**：一般取 0.7~0.9")

        return "\n".join(parts)

    # ---------- 规范类回答 ----------
    def _answer_standards(self, tables, formulas, standards, key_sents, sections, numbers):
        parts = [self._header()]

        # 规范速查表
        if tables:
            parts.append("### 📋 规范要求速查\n")
            parts.append(self._format_all_tables(tables, max_tables=3))

        # 规范条文
        std_sections = [s for s in sections if any(k in s["title"] for k in ['规范', '标准', '条文', '要求', '规定'])]
        if std_sections:
            for sec in std_sections[:2]:
                if sec["title"]:
                    parts.append(f"\n**{sec['title']}**")
                for line in sec["content"][:6]:
                    parts.append(f"  {line}")
                if sec.get("lists"):
                    for item in sec["lists"][:6]:
                        parts.append(f"  - {item}")

        # 数值参数
        if numbers:
            parts.append(f"\n### 📐 关键限值\n`{'`  `'.join(numbers[:10])}`")

        # 规范编号
        if standards:
            parts.append(f"\n### 📜 相关规范\n{'、'.join(standards)}")

        parts.append("\n### ⚠️ 注意\n")
        parts.append("- 以上为设计速查，**以现行规范原文为准**")
        parts.append("- 规范更新时以**最新版本**为准（如 GB 51348-2019 替代 JGJ 16-2008）")

        return "\n".join(parts)

    # ---------- 故障类回答 ----------
    def _answer_troubleshoot(self, tables, formulas, standards, key_sents, sections, numbers):
        parts = [self._header()]

        parts.append("### 🔍 故障排查流程\n")
        parts.append("```\n电源端 → 线路 → 保护元件 → 负荷端 → 接地\n```")

        # 故障相关要点
        fault_items = []
        for sec in sections:
            for item in sec.get("lists", []):
                if any(k in item for k in ['故障', '原因', '排查', '跳闸', '不工作', '问题']):
                    fault_items.append(item)
            for line in sec["content"]:
                if any(k in line for k in ['故障', '原因', '排查']):
                    fault_items.append(line)

        if fault_items:
            parts.append("\n### 📋 常见故障与原因\n")
            for item in fault_items[:8]:
                parts.append(f"- {item}")

        if tables:
            parts.append("\n### 📊 故障对照表\n")
            parts.append(self._format_all_tables(tables))

        parts.append("\n### 🔧 排查步骤\n")
        parts.append("1. **查电源**：测量进线电压是否正常（220V/380V ±7%）")
        parts.append("2. **查保护**：断路器/RCD 是否跳闸，查看脱扣原因")
        parts.append("3. **查线路**：绝缘电阻测试（≥ 0.5MΩ），检查接头")
        parts.append("4. **查负荷**：设备端是否短路/过载/漏电")
        parts.append("5. **查接地**：接地电阻是否达标（≤ 4Ω / ≤ 1Ω）")

        if standards:
            parts.append(f"\n### 📜 参考规范\n{'、'.join(standards)}")

        return "\n".join(parts)

    # ---------- 设计类回答 ----------
    def _answer_design(self, tables, formulas, standards, key_sents, sections, numbers):
        parts = [self._header()]

        # 按领域定制设计流程
        domain_flows = {
            "防雷接地": [
                "**1. 防雷等级判定** — 按 GB 50057 计算年雷击次数 N",
                "**2. 接闪器设计** — 避雷带/避雷针/避雷网布置",
                "**3. 引下线设计** — 间距 ≤ 18m（二类）/ ≤ 25m（三类）",
                "**4. 接地装置设计** — 联合接地 ≤ 1Ω / 独立接地 ≤ 4Ω",
                "**5. 等电位连接** — MEB/LEB 设置",
                "**6. SPD 配置** — 三级防护体系",
            ],
            "消防电气": [
                "**1. 报警系统选型** — 集中报警/控制中心报警",
                "**2. 探测器布置** — 感烟/感温/手报覆盖",
                "**3. 联动控制设计** — 消防泵/排烟/卷帘/广播",
                "**4. 消防电源** — 双电源+EPS，耐火电缆",
                "**5. 应急照明** — 疏散指示+备用照明",
                "**6. 消防控制室** — 图形显示+联动控制台",
            ],
            "弱电智能化": [
                "**1. 需求分析** — 确定系统清单和功能需求",
                "**2. 综合布线** — 工作区/水平/干线/设备间",
                "**3. 安防系统** — 视频监控/门禁/入侵报警",
                "**4. 楼宇自控** — DDC 控制/暖通/照明",
                "**5. 网络系统** — 核心/汇聚/接入三层架构",
                "**6. 机房工程** — UPS/空调/消防/监控",
            ],
            "低压电气": [
                "**1. 需求分析** — 明确负荷等级、供电要求",
                "**2. 负荷计算** — 需要系数法/单位面积法",
                "**3. 系统方案** — 配电方式、供电电源",
                "**4. 设备选型** — 断路器、线缆、配电箱",
                "**5. 保护设计** — 短路/过载/漏电/防雷",
                "**6. 校验出图** — 电压降、热稳定、选择性",
            ],
        }
        flow = domain_flows.get(self.domain, domain_flows["低压电气"])

        parts.append("### 📐 设计流程\n")
        for s in flow:
            parts.append(f"- {s}")

        # 从内容提取设计要点（只取领域相关的）
        domain_keywords = DOMAIN_TERMS.get(self.domain, [])
        design_sections = []
        for s in sections:
            title_content = s['title'] + "".join(s['content'][:2])
            if any(k in title_content for k in ['设计', '方案', '系统', '要点', '核心', '构成', '等级', '分类']):
                design_sections.append(s)
        if design_sections:
            for sec in design_sections[:3]:
                if not (sec["content"] or sec.get("lists") or sec.get("tables")):
                    continue  # 跳过空章节
                if sec["title"]:
                    parts.append(f"\n### 📌 {sec['title']}")
                for line in sec["content"][:5]:
                    parts.append(f"  {line}")
                if sec.get("lists"):
                    for item in sec["lists"][:6]:
                        parts.append(f"  - {item}")
                if sec.get("tables"):
                    parts.append("")
                    parts.append(self._format_table(sec["tables"][0]))

        # 核心要点（只取领域相关的）
        domain_keywords = DOMAIN_TERMS.get(self.domain, []) + ['设计', '要求', '原则', '注意', '核心', '关键']
        filtered_sents = [s for s in key_sents if any(k in s for k in domain_keywords)]
        if not filtered_sents:
            filtered_sents = key_sents[:3]  # fallback
        if filtered_sents:
            parts.append("\n### ✅ 设计要点\n")
            for s in filtered_sents[:6]:
                parts.append(f"- {s}")

        if numbers:
            parts.append(f"\n### 📏 关键参数\n`{'`  `'.join(numbers[:8])}`")

        if standards:
            parts.append(f"\n### 📜 规范依据\n{'、'.join(standards)}")

        # 领域专属建议
        domain_advice = {
            "防雷接地": [
                "- **先定等级**：按 GB 50057 计算年雷击次数 N 确定防雷等级",
                "- **联合接地优先**：共用接地体 ≤ 1Ω，经济且安全",
                "- **SPD 三级配合**：I 级→总配、II 级→分配、III 级→设备端",
            ],
            "消防电气": [
                "- **报警形式**：大型建筑用控制中心报警，中型用集中报警",
                "- **消防电源**：双电源+EPS，线路用矿物绝缘电缆（耐火 3h）",
                "- **联动逻辑**：先报警→确认→联动，控制误报率",
            ],
            "弱电智能化": [
                "- **布线先行**：综合布线是基础，预留 20% 冗余",
                "- **网络架构**：核心/汇聚/接入三层，PoE 供电 ≤ 90m",
                "- **安防覆盖**：无死角+人脸可识别（≥ 50px）",
            ],
            "低压电气": [
                "- **预留裕量**：变压器负载率 60%~80%，断路器 In = 1.1~1.25 Ijs",
                "- **安全第一**：消防负荷独立供电，人身安全用 30mA RCD",
                "- **经济合理**：线缆截面按载流量+压降+热稳定三重校验",
            ],
        }
        advice = domain_advice.get(self.domain, domain_advice["低压电气"])
        parts.append("\n### 💡 设计建议\n")
        for a in advice:
            parts.append(a)

        return "\n".join(parts)

    # ---------- 对比类回答 ----------
    def _answer_comparison(self, tables, formulas, standards, key_sents, sections, numbers):
        parts = [self._header()]

        # 找对比相关的表格和内容
        comp_tables = []
        for t in tables:
            if len(t.get("headers", [])) >= 2:
                comp_tables.append(t)

        if comp_tables:
            parts.append("### 📊 对比速查\n")
            parts.append(self._format_all_tables(comp_tables, max_tables=3))

        # 对比要点
        comp_items = []
        for sec in sections:
            for item in sec.get("lists", []):
                if any(k in item for k in ['优点', '缺点', '适用', '区别', '对比', '不同']):
                    comp_items.append(item)

        if comp_items:
            parts.append("\n### 📋 对比要点\n")
            for item in comp_items[:8]:
                parts.append(f"- {item}")

        if standards:
            parts.append(f"\n### 📜 参考规范\n{'、'.join(standards)}")

        return "\n".join(parts)

    # ---------- 列举类回答 ----------
    def _answer_listing(self, tables, formulas, standards, key_sents, sections, numbers):
        parts = [self._header()]

        # 从所有章节中提取列表项（列举类问题需要全面）
        all_items = []
        for sec in sections:
            if sec["title"]:
                all_items.append(("header", sec["title"]))
            for item in sec.get("lists", []):
                all_items.append(("item", item))
            for t in sec.get("tables", []):
                all_items.append(("table", t))

        # 用表格呈现列举内容
        if tables:
            parts.append("### 📊 分类速查\n")
            parts.append(self._format_all_tables(tables, max_tables=3))

        # 列表项
        list_items = [x[1] for x in all_items if x[0] == "item"]
        if list_items:
            parts.append("\n### 📋 详细说明\n")
            for item in list_items[:10]:
                parts.append(f"- {item}")

        if numbers:
            parts.append(f"\n### 📏 关键参数\n`{'`  `'.join(numbers[:8])}`")

        if standards:
            parts.append(f"\n### 📜 规范依据\n{'、'.join(standards)}")

        return "\n".join(parts)

    # ---------- 通用回答 ----------
    def _answer_general(self, tables, formulas, standards, key_sents, sections, numbers):
        parts = [self._header()]

        # 核心内容（取最相关的 section）
        if sections:
            # 找标题与问题最相关且有实际内容的 section
            q_chars = set(self.question)
            content_secs = [s for s in sections if s["content"] or s.get("lists") or s.get("tables")]
            if content_secs:
                best_sec = max(content_secs, key=lambda s: len(q_chars & set(s["title"] + "".join(s["content"][:2]))))
                if best_sec["title"]:
                    parts.append(f"### 📌 {best_sec['title']}\n")
                for line in best_sec["content"][:6]:
                    parts.append(f"  {line}")
                if best_sec.get("lists"):
                    parts.append("")
                    for item in best_sec["lists"][:6]:
                        parts.append(f"- {item}")
                if best_sec.get("tables"):
                    parts.append("")
                    parts.append(self._format_table(best_sec["tables"][0]))

        # 补充其他要点
        if key_sents:
            parts.append("\n### ✅ 关键要点\n")
            for s in key_sents[:5]:
                parts.append(f"- {s}")

        # 表格
        if tables and len(tables) > 1:
            parts.append("\n### 📊 参考数据\n")
            parts.append(self._format_table(tables[1] if len(tables) > 1 else tables[0]))

        if numbers:
            parts.append(f"\n### 📏 关键参数\n`{'`  `'.join(numbers[:8])}`")

        if standards:
            parts.append(f"\n### 📜 相关规范\n{'、'.join(standards)}")

        return "\n".join(parts)


# ==================== 数据获取 ====================

def get_all_cards():
    db_path = os.path.join(DATA_DIR, "kb.db")
    if not os.path.exists(db_path): return []
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT id, title, content, library, tags FROM cards").fetchall()
        cards = []
        for r in rows:
            text = f"{r['title']}\n{r['content']}\n{r['tags'] or ''}"
            cards.append({"id": r["id"], "title": r["title"], "text": text, "library": r["library"], "tags": r["tags"] or ""})
        return cards
    except: return []
    finally: conn.close()


def classify_domain(text):
    scores = {}
    for d, terms in DOMAIN_TERMS.items():
        s = sum(1 for t in terms if t in text)
        if s > 0: scores[d] = s
    return max(scores, key=scores.get) if scores else "综合"


# ==================== 主入口 ====================

def rag_answer(question):
    """RAG 专业问答主入口 v2"""
    cards = get_all_cards()
    if not cards:
        return {"answer": "知识库为空，请先添加知识内容。", "sources": [], "mode": "empty", "intent": detect_intent(question)}

    intent = detect_intent(question)
    results = bm25_search(question, cards)

    sources = []
    for idx, score in results[:5]:
        if score <= 0: continue
        c = cards[idx]
        full_text = c["text"]
        domain = classify_domain(full_text)
        parsed = parse_content_structure(full_text)
        sources.append({
            "id": c["id"], "title": c["title"],
            "library": c.get("library", ""), "score": round(score, 2),
            "domain": domain, "text": full_text, "parsed": parsed
        })

    # 构建专业回答
    builder = AnswerBuilder(question, intent, sources[0]["domain"] if sources else "综合", sources)
    answer = builder.build()

    return {
        "answer": answer,
        "sources": [{"id": s["id"], "title": s["title"], "library": s["library"], "score": s["score"], "domain": s["domain"]} for s in sources],
        "mode": "professional-v2",
        "intent": intent,
    }


if __name__ == "__main__":
    tests = [
        "断路器怎么选型？",
        "防雷接地怎么做？",
        "消防联动控制有哪些？",
        "负荷怎么计算？",
    ]
    for q in tests:
        r = rag_answer(q)
        print("=" * 60)
        print(f"Q: {q}")
        print(f"意图: {r['intent']} | 来源: {len(r['sources'])}条")
        print(r["answer"])
        print()
