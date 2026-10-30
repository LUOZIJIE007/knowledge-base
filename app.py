# -*- coding: utf-8 -*-
"""主服务：零依赖 HTTP 服务（http.server 子类），REST API + 静态前端"""
import json
import os
import re
import secrets
import sys
import ipaddress
import time
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

import db
import llm
import pipeline
import metacognition
import rag
import evolve
import rag_pro
from db import now

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 运维模块
sys_path_ops = os.path.join(BASE_DIR, "ops")
if sys_path_ops not in sys.path:
    sys.path.insert(0, sys_path_ops)
import ops_db
import collector
import cleaner
import optimizer
import version as version_mgr
import reporter as reporter_mod
import ops_main
STATIC_DIR = os.path.join(BASE_DIR, "static")
PORT = 8848

CAPTCHA_TTL = 300  # 5分钟
CAPTCHAS = {}      # phone -> {code, expires}

# 开发模式开关：仅当显式设置环境变量 KB_DEV_MODE=1 时才允许验证码回显
DEV_MODE = os.environ.get("KB_DEV_MODE", "0") == "1"

# 短信接口：仅允许通过环境变量 KB_SMS_URL 配置（管理员私有，普通用户不可写）
SMS_URL = os.environ.get("KB_SMS_URL", "")

# 开发者模式用户 ID（固定为 0，与真实用户隔离）
DEV_USER_ID = 0

# ---- 限流器 ----
_RATE = {}  # key -> [count, first_ts]


def rate_limit(key, window, max_calls):
    """简单固定窗口限流。key 形如 'sendcode:13800138000'"""
    now_ts = now()
    entry = _RATE.get(key)
    if entry is None or now_ts - entry[1] > window:
        _RATE[key] = [1, now_ts]
        _cleanup_rate(now_ts)
        return True
    entry[0] += 1
    return entry[0] <= max_calls


def _cleanup_rate(now_ts):
    """清理过期窗口，避免 _RATE 无限增长"""
    if len(_RATE) < 500:
        return
    expired = [k for k, v in _RATE.items() if now_ts - v[1] > 3600]
    for k in expired:
        _RATE.pop(k, None)


# ---- URL 安全校验 ----
def is_url_allowed(url):
    """仅允许 http/https，且拒绝内网/回环/元数据地址"""
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = parsed.hostname
    if not host:
        return False
    if host.lower() in ("localhost",):
        return False
    # 解析 IP 做网段黑名单
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        # 域名：拒绝内网域名
        if re.match(r"^(.*\.)?(localhost|internal|local|metadata)$", host.lower()):
            return False
        return True
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
        return False
    if str(ip) == "169.254.169.254":
        return False
    return True


def gen_captcha(phone):
    code = f"{secrets.randbelow(1000000):06d}"
    CAPTCHAS[phone] = {"code": code, "expires": now() + CAPTCHA_TTL}
    # M4 修复：验证码字典容量上限，清理过期项
    if len(CAPTCHAS) > 1000:
        now_ts = now()
        expired = [k for k, v in CAPTCHAS.items() if now_ts > v["expires"]]
        for k in expired:
            CAPTCHAS.pop(k, None)
    return code


def verify_captcha(phone, code):
    item = CAPTCHAS.get(phone)
    if not item:
        return False
    if now() > item["expires"]:
        CAPTCHAS.pop(phone, None)
        return False
    CAPTCHAS.pop(phone, None)
    return item["code"] == code


def send_sms(phone, code):
    """短信发送：开发模式打印到控制台；配置 KB_SMS_URL 时走真实接口"""
    print(f"[SMS] 验证码 {code} 到 {phone}")
    if SMS_URL:
        try:
            req = urllib.request.Request(
                SMS_URL,
                data=json.dumps({"phone": phone, "code": code}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=10)
            return True
        except OSError:
            print(f"[SMS] 接口调用失败，降级为控制台输出")
    return True


def get_user(handler):
    token = handler.headers.get("Authorization", "").replace("Bearer ", "")
    return db.get_user_by_token(token)


def _backup_data(uid):
    """P6a：导出当前用户全部数据为 dict（供 backup/import 共用）"""
    data = {"profile": None, "cards": [], "captures": [], "reviews": [], "corrections": [], "meta_notes": [], "actions": [], "exported_at": now()}
    conn = db.get_conn()
    p = conn.execute("SELECT content FROM profiles WHERE user_id=?", (uid,)).fetchone()
    data["profile"] = p["content"] if p else ""
    for table in ("cards", "captures", "reviews", "corrections", "meta_notes", "actions"):
        data[table] = [dict(r) for r in conn.execute(f"SELECT * FROM {table} WHERE user_id=?", (uid,)).fetchall()]
    conn.close()
    return data


def _restore_data(uid, data):
    """P6a：从备份 dict 恢复（先清空后写入）"""
    conn = db.get_conn()
    try:
        for table in ("cards", "captures", "reviews", "corrections", "meta_notes", "actions", "profiles"):
            conn.execute(f"DELETE FROM {table} WHERE user_id=?", (uid,))
        if data.get("profile") is not None:
            conn.execute("INSERT INTO profiles(user_id, content, updated_at) VALUES(?,?,?)", (uid, data["profile"], now()))
        for table in ("cards", "captures", "reviews", "corrections", "meta_notes", "actions"):
            for row in data.get(table, []):
                cols = list(row.keys())
                cols_sql = ",".join(cols)
                ph = ",".join("?" for _ in cols)
                vals = [row[c] for c in cols]
                conn.execute(f"INSERT INTO {table}({cols_sql}) VALUES({ph})", vals)
    except Exception:
        conn.close()
        raise
    conn.close()
    return True


class Handler(BaseHTTPRequestHandler):
    server_version = "KBApp/1.0"

    def log_message(self, fmt, *args):
        print(f"[{time.strftime('%H:%M:%S')}] {args[0]}")

    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        # L1 修复：安全响应头
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        # P6: 安全响应头补全
        self.send_header("X-XSS-Protection", "1; mode=block")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Permitted-Cross-Domain-Policies", "none")
        self.end_headers()
        self.wfile.write(body)

    def _static(self, path):
        if path == "/":
            path = "/index.html"
        full = os.path.normpath(os.path.join(STATIC_DIR, path.lstrip("/")))
        # L3 修复：严格路径校验（commonpath + 分隔符收尾）
        try:
            full_real = os.path.realpath(full)
            root_real = os.path.realpath(STATIC_DIR)
            if not (full_real == root_real or full_real.startswith(root_real + os.sep)):
                self.send_error(404)
                return
        except OSError:
            self.send_error(404)
            return
        if not os.path.isfile(full_real):
            self.send_error(404)
            return
        ext = os.path.splitext(full_real)[1].lower()
        mime = {".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
                ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png"}.get(ext, "application/octet-stream")
        with open(full_real, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        # L1 修复：安全响应头
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        # P6: 安全响应头补全
        self.send_header("X-XSS-Protection", "1; mode=block")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Permitted-Cross-Domain-Policies", "none")
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        length = int(self.headers.get("Content-Length", 0))
        # M3 修复：请求体大小上限 1MB
        if length > 1024 * 1024:
            return {}
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path.startswith("/api/"):
            return self.api_get(path)
        return self._static(path)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if path.startswith("/api/"):
            return self.api_post(path)
        self.send_error(404)

    def api_get(self, path):
        user = get_user(self)
        if not user:
            return self._json({"error": "unauthorized"}, 401)
        uid = user["id"]
        if path == "/api/profile":
            row = db.get_conn().execute("SELECT content FROM profiles WHERE user_id=?", (uid,)).fetchone()
            db.get_conn().close()
            return self._json({"content": row["content"] if row else ""})
        if path == "/api/cards":
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            keyword = qs.get("q", [""])[0]
            library = qs.get("library", [""])[0] or None
            return self._json({"cards": pipeline.search_cards(uid, keyword, library)})
        if path == "/api/captures":
            conn = db.get_conn()
            rows = [dict(r) for r in conn.execute("SELECT * FROM captures WHERE user_id=? ORDER BY created_at DESC LIMIT 50", (uid,)).fetchall()]
            conn.close()
            return self._json({"captures": rows})
        if path == "/api/actions":
            conn = db.get_conn()
            rows = [dict(r) for r in conn.execute("SELECT * FROM actions WHERE user_id=? ORDER BY created_at DESC", (uid,)).fetchall()]
            conn.close()
            return self._json({"actions": rows})
        if path == "/api/reviews":
            conn = db.get_conn()
            rows = [dict(r) for r in conn.execute("SELECT * FROM reviews WHERE user_id=? ORDER BY created_at DESC LIMIT 30", (uid,)).fetchall()]
            conn.close()
            return self._json({"reviews": rows})
        if path == "/api/corrections":
            conn = db.get_conn()
            rows = [dict(r) for r in conn.execute("SELECT * FROM corrections WHERE user_id=? ORDER BY created_at DESC", (uid,)).fetchall()]
            conn.close()
            return self._json({"corrections": rows})
        if path == "/api/meta":
            return self._json(metacognition.meta_panel(uid))
        if path == "/api/review/queue":
            # P6: 间隔重复复习队列（到期卡片）
            return self._json(metacognition.srs_queue(uid))
        if path == "/api/settings":
            s = llm.load_settings()
            return self._json({"ai_enabled": llm.is_ai_enabled(), "base_url": s.get("base_url", ""), "model": s.get("model", "")})

        # ---- 终极形态：RAG / 知识图谱 / 学习看板 / Agent ----
        if path == "/api/kg/graph":
            return self._json(rag.get_graph(uid))
        if path == "/api/learning/dashboard":
            return self._json(rag.get_learning_dashboard(uid))
        if path == "/api/agent/log":
            return self._json(rag.get_agent_log(uid))

        # ---- 自我进化 GET ----
        if path == "/api/evolve/summary":
            return self._json(evolve.get_evolution_summary())
        if path == "/api/evolve/domains":
            return self._json(evolve.get_domain_stats())
        if path == "/api/evolve/gaps":
            return self._json({"gaps": evolve.detect_gaps()})

        # ---- 运维看板 ----
        if path == "/api/ops/dashboard":
            ops_db.init_db()
            task_runs = ops_db.get_task_runs(limit=10)
            digests = ops_db.get_digests(limit=10)
            sources = ops_db.get_sources(enabled_only=False)
            expired = ops_db.get_expiry_flags(reviewed=0, limit=10)
            snapshots = ops_db.get_snapshots(limit=10)
            changes = ops_db.get_change_logs(limit=20)
            return self._json({
                "task_runs": task_runs,
                "digests": digests,
                "sources": sources,
                "expired_flags": expired,
                "snapshots": snapshots,
                "change_logs": changes,
            })
        if path == "/api/ops/digest":
            ops_db.init_db()
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            date = qs.get("date", [""])[0] or None
            if date:
                digest = ops_db.get_digest_by_date(date)
            else:
                digests = ops_db.get_digests(limit=1)
                digest = digests[0] if digests else None
            if digest:
                import json as _j
                digest["digest_data"] = _j.loads(digest.pop("digest_json", "{}"))
            return self._json(digest or {})
        if path == "/api/ops/digests":
            ops_db.init_db()
            digests = ops_db.get_digests(limit=30)
            for d in digests:
                d.pop("digest_json", None)
            return self._json({"digests": digests})
        if path == "/api/ops/sources":
            ops_db.init_db()
            sources = ops_db.get_sources(enabled_only=False)
            return self._json({"sources": sources})
        if path == "/api/ops/versions":
            ops_db.init_db()
            snapshots = ops_db.get_snapshots(limit=20)
            return self._json({"snapshots": snapshots})
        if path == "/api/ops/changes":
            ops_db.init_db()
            changes = ops_db.get_change_logs(limit=50)
            return self._json({"changes": changes})
        if path == "/api/ops/expiry":
            ops_db.init_db()
            reviewed = None
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if "reviewed" in qs:
                reviewed = qs.get("reviewed", ["0"])[0] == "1"
            flags = ops_db.get_expiry_flags(reviewed=reviewed, limit=50)
            return self._json({"flags": flags})

        if path == "/api/export" or path == "/api/backup":
            # N2 修复：一键导出全部数据为 JSON；P6a：/api/backup 同源（带时间戳文件名）
            import json as _json
            data = _backup_data(uid)
            body = _json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
            ts = time.strftime("%Y%m%d_%H%M%S")
            fname = "kb-backup-" + ts + ".json" if path == "/api/backup" else "kb-export.json"
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Disposition", f"attachment; filename={fname}")
            self.send_header("Content-Length", str(len(body)))
            # P6: 安全响应头补全
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("X-XSS-Protection", "1; mode=block")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Permitted-Cross-Domain-Policies", "none")
            self.end_headers()
            self.wfile.write(body)
            return
        self._json({"error": "not found"}, 404)

    def api_post(self, path):
        user = get_user(self)
        body = self._body()

        # ---- 认证 ----
        if path == "/api/send-code":
            phone = re.sub(r"[^\d]", "", body.get("phone", ""))
            # 去掉 86 国家码前缀（支持 +86 139... / 86139... 格式）
            if phone.startswith("86") and len(phone) == 13:
                phone = phone[2:]
            if not re.match(r"^1\d{10}$", phone):
                return self._json({"error": "手机号格式不正确"}, 400)
            # 限流：每手机号每分钟 1 次、每 10 分钟 3 次（S4 修复）
            if not rate_limit(f"sendcode:{phone}", 60, 1):
                return self._json({"error": "请求过于频繁，请稍后再试"}, 429)
            if not rate_limit(f"sendcode10m:{phone}", 600, 3):
                return self._json({"error": "今日请求次数已达上限，请稍后再试"}, 429)
            code = gen_captcha(phone)
            send_sms(phone, code)
            resp = {"expires_in": CAPTCHA_TTL}
            # 仅开发模式回显验证码（S1 修复）
            if DEV_MODE:
                resp["dev_code"] = code
            return self._json(resp)
        if path == "/api/register":
            phone, code = body.get("phone", ""), body.get("code", "")
            phone = re.sub(r"[^\d]", "", phone)
            if phone.startswith("86") and len(phone) == 13:
                phone = phone[2:]
            if not verify_captcha(phone, code):
                return self._json({"error": "验证码错误或已过期"}, 400)
            if db.get_user_by_phone(phone):
                return self._json({"error": "该手机号已注册"}, 400)
            uid = db.create_user(phone)
            token = db.create_session(uid)
            return self._json({"token": token, "user": {"id": uid, "phone": phone}})
        if path == "/api/login":
            phone, code = body.get("phone", ""), body.get("code", "")
            phone = re.sub(r"[^\d]", "", phone)
            if phone.startswith("86") and len(phone) == 13:
                phone = phone[2:]
            if not verify_captcha(phone, code):
                return self._json({"error": "验证码错误或已过期"}, 400)
            u = db.get_user_by_phone(phone)
            if not u:
                # N1 修复：未注册手机号自动注册，而非拒绝
                uid = db.create_user(phone)
                token = db.create_session(uid)
                return self._json({"token": token, "user": {"id": uid, "phone": phone}, "registered": True})
            token = db.create_session(u["id"])
            return self._json({"token": token, "user": {"id": u["id"], "phone": phone}, "registered": False})

        # ---- 开发者模式：免密登录 ----
        if path == "/api/dev-login":
            # 安全检查：仅当开发模式开启时才允许
            if not DEV_MODE:
                return self._json({"error": "开发者模式未启用"}, 403)
            # 检查是否来自本地回环
            client_ip = self.client_address[0] if self.client_address else ""
            if client_ip not in ("127.0.0.1", "::1"):
                return self._json({"error": "仅允许本地访问"}, 403)
            # 确保 dev 用户存在并获取 ID
            uid = db.ensure_dev_user()
            token = db.create_session(uid)
            return self._json({
                "token": token,
                "user": {"id": uid, "phone": "developer", "is_dev": True},
                "dev_mode": True
            })

        if not user:
            return self._json({"error": "unauthorized"}, 401)
        uid = user["id"]

        # ---- 档案 ----
        if path == "/api/profile":
            content = body.get("content", "")
            conn = db.get_conn()
            conn.execute("INSERT INTO profiles(user_id, content, updated_at) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET content=excluded.content, updated_at=excluded.updated_at",
                         (uid, content, now()))
            conn.close()
            ai_help = ""
            if llm.is_ai_enabled() and body.get("raw_self"):
                # S5 修复：AI 调用限流
                if not rate_limit(f"ai:{uid}", 60, 20) or not rate_limit(f"ai10m:{uid}", 600, 60):
                    return self._json({"error": "AI 调用过于频繁，请稍后再试"}, 429)
                raw = llm.chat(pipeline.profile_prompt(body["raw_self"]), system=pipeline.PROFILE_SYSTEM, max_tokens=1200)
                if raw:
                    ai_help = raw
            return self._json({"saved": True, "ai_help": ai_help})

        # ---- 采集 ----
        if path == "/api/capture":
            conn = db.get_conn()
            conn.execute("INSERT INTO captures(user_id, source_type, source_url, title, raw_content, created_at) VALUES(?,?,?,?,?,?)",
                         (uid, body.get("source_type", "note"), body.get("source_url", ""), body.get("title", ""), body.get("raw_content", ""), now()))
            conn.close()
            return self._json({"ok": True})
        if path == "/api/capture/fetch":
            url = body.get("url", "")
            # S2 修复：URL 安全校验
            if not is_url_allowed(url):
                return self._json({"error": "URL 不允许：仅支持公网 http/https，拒绝内网/回环/文件协议"}, 400)
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    html = resp.read().decode("utf-8", errors="ignore")
                text = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", "", html)
                text = re.sub(r"<[^>]+>", "\n", text)
                text = re.sub(r"\n{2,}", "\n", text)
                title = re.search(r"<title[^>]*>([^<]+)</title>", html)
                conn = db.get_conn()
                conn.execute("INSERT INTO captures(user_id, source_type, source_url, title, raw_content, created_at) VALUES(?,?,?,?,?,?)",
                             (uid, "link", url, title.group(1) if title else "", text[:20000], now()))
                conn.close()
                return self._json({"ok": True, "title": title.group(1) if title else ""})
            except OSError as e:
                return self._json({"error": f"抓取失败：{e}"}, 400)

        # ---- 蒸馏 ----
        if path == "/api/distill":
            # S5 修复：AI 调用限流
            if not rate_limit(f"ai:{uid}", 60, 20) or not rate_limit(f"ai10m:{uid}", 600, 60):
                return self._json({"error": "AI 调用过于频繁，请稍后再试"}, 429)
            result = pipeline.distill_capture(uid, body.get("capture_id", 0))
            if result is None:
                return self._json({"error": "采集记录不存在"}, 404)
            return self._json(result)

        # ---- 问答 ----
        if path == "/api/ask":
            question = body.get("question", "")
            if not question.strip():
                return self._json({"error": "问题不能为空"}, 400)
            # S5 修复：AI 调用限流
            if not rate_limit(f"ai:{uid}", 60, 20) or not rate_limit(f"ai10m:{uid}", 600, 60):
                return self._json({"error": "AI 调用过于频繁，请稍后再试"}, 429)
            return self._json(pipeline.answer_question(uid, question))

        # ---- 元认知 ----
        if path == "/api/review":
            date = body.get("date") or time.strftime("%Y-%m-%d")
            content = body.get("content", "")
            if not content.strip():
                return self._json({"error": "复盘内容不能为空"}, 400)
            # S5 修复：AI 调用限流
            if not rate_limit(f"ai:{uid}", 60, 20) or not rate_limit(f"ai10m:{uid}", 600, 60):
                return self._json({"error": "AI 调用过于频繁，请稍后再试"}, 429)
            return self._json(metacognition.submit_review(uid, date, content))
        if path == "/api/correction":
            return self._json(metacognition.log_correction(uid, body.get("error", ""), body.get("context", ""), body.get("lesson", "")))
        if path == "/api/correction/fix":
            metacognition.correct_error(uid, body.get("id", 0), body.get("action", ""))
            return self._json({"ok": True})
        if path == "/api/meta/bias":
            metacognition.add_bias_note(uid, body.get("title", ""), body.get("content", ""))
            return self._json({"ok": True})
        if path == "/api/meta/model":
            metacognition.add_model_note(uid, body.get("title", ""), body.get("content", ""))
            return self._json({"ok": True})

        # ---- 终极形态 API ----
        if path == "/api/rag/ask":
            question = body.get("question", "")
            if not question.strip():
                return self._json({"error": "问题不能为空"}, 400)
            if not rate_limit(f"ai:{uid}", 60, 20):
                return self._json({"error": "AI 调用过于频繁"}, 429)
            return self._json(rag_pro.rag_answer(question))

        # ---- 自我进化 API ----
        if path == "/api/evolve/summary":
            return self._json(evolve.get_evolution_summary())

        if path == "/api/evolve/domains":
            return self._json(evolve.get_domain_stats())

        if path == "/api/evolve/run":
            result = evolve.auto_evolve()
            return self._json(result)

        if path == "/api/evolve/digest":
            title = body.get("title", "")
            content = body.get("content", "")
            if not content.strip():
                return self._json({"error": "内容不能为空"}, 400)
            result = evolve.digest_content(title, content, body.get("source", "manual"))
            return self._json(result)

        if path == "/api/evolve/gaps":
            gaps = evolve.detect_gaps()
            return self._json({"gaps": gaps})

        if path == "/api/kg/ingest":
            card_id = body.get("card_id", 0)
            title = body.get("title", "")
            content = body.get("content", "")
            tags = body.get("tags", "")
            e_count, r_count = rag.ingest_card(uid, card_id, title, content, tags)
            return self._json({"entities": e_count, "relations": r_count})

        if path == "/api/learning/path":
            if not rate_limit(f"ai:{uid}", 60, 10):
                return self._json({"error": "AI 调用过于频繁"}, 429)
            return self._json(rag.generate_learning_path(uid, body.get("topic", "")))

        if path == "/api/agent/run":
            task_type = body.get("type", "analyze")
            input_data = body.get("input", "")
            if not rate_limit(f"ai:{uid}", 60, 15):
                return self._json({"error": "AI 调用过于频繁"}, 429)
            return self._json(rag.run_agents(uid, task_type, input_data))

        # ---- 设置 ----
        if path == "/api/settings/save":
            s = llm.load_settings()
            # S3 修复：sms_url 已移出用户可写范围，仅允许环境变量 KB_SMS_URL 配置
            for key in ("base_url", "api_key", "model"):
                if key in body and body[key] is not None:
                    s[key] = body[key]
            llm.save_settings(s)
            return self._json({"ok": True, "ai_enabled": llm.is_ai_enabled()})

        # ---- 登出 ----
        if path == "/api/logout":
            # M2 修复：服务端吊销 token
            token = self.headers.get("Authorization", "").replace("Bearer ", "")
            conn = db.get_conn()
            conn.execute("DELETE FROM sessions WHERE token=?", (token,))
            conn.close()
            return self._json({"ok": True})

        # ---- 数据主权：导入恢复 ----
        if path == "/api/import":
            # P6a：从备份 JSON 恢复（先清空当前数据再写入）
            data = body.get("data") or body
            if not isinstance(data, dict) or "cards" not in data:
                return self._json({"error": "备份文件格式不正确"}, 400)
            _restore_data(uid, data)
            return self._json({"ok": True, "restored": True})

        # ---- 间隔重复：复习队列 ----
        if path == "/api/review/card":
            # P6: SRS 完成复习，更新间隔
            return self._json(metacognition.complete_srs(uid, body.get("card_id", 0), body.get("passed", True)))

        # ---- 运维 ----
        if path == "/api/ops/run":
            ops_db.init_db()
            # 异步执行（简单线程）
            import threading
            def _ops_task():
                ops_main.run_ops(uid)
            t = threading.Thread(target=_ops_task, daemon=True)
            t.start()
            return self._json({"ok": True, "message": "运维任务已启动"})
        if path == "/api/ops/run-quick":
            ops_db.init_db()
            import threading
            def _ops_quick():
                ops_main.run_quick_ops(uid)
            t = threading.Thread(target=_ops_quick, daemon=True)
            t.start()
            return self._json({"ok": True, "message": "快速运维已启动"})
        if path == "/api/ops/sources/add":
            ops_db.init_db()
            ops_db.upsert_source(
                body.get("name", ""),
                body.get("source_type", "rss"),
                body.get("url", ""),
                body.get("category", ""),
                body.get("keywords", "")
            )
            return self._json({"ok": True})
        if path == "/api/ops/sources/delete":
            ops_db.init_db()
            name = body.get("name", "")
            with ops_db.get_conn() as conn:
                conn.execute("DELETE FROM sources WHERE name=?", (name,))
            return self._json({"ok": True})
        if path == "/api/ops/sources/toggle":
            ops_db.init_db()
            name = body.get("name", "")
            enabled = body.get("enabled", 1)
            with ops_db.get_conn() as conn:
                conn.execute("UPDATE sources SET enabled=? WHERE name=?", (1 if enabled else 0, name))
            return self._json({"ok": True})
        if path == "/api/ops/expiry/review":
            ops_db.init_db()
            flag_id = body.get("flag_id", 0)
            reviewed = body.get("reviewed", True)
            result = body.get("result", "")
            ops_db.review_expiry(flag_id, reviewed, result)
            return self._json({"ok": True})
        if path == "/api/ops/snapshot/create":
            ops_db.init_db()
            version_tag = body.get("version_tag", f"v_custom_{int(time.time())}")
            description = body.get("description", "")
            snap = version_mgr.create_snapshot(uid, version_tag, description)
            return self._json(snap)
        if path == "/api/ops/rollback":
            ops_db.init_db()
            version_tag = body.get("version_tag", "")
            if not version_tag:
                return self._json({"error": "版本标签不能为空"}, 400)
            result = version_mgr.rollback(uid, version_tag)
            return self._json(result)

        self._json({"error": "not found"}, 404)


def main():
    db.init_db()
    # 初始化运维数据库
    ops_db.init_db()
    # 确保开发者用户存在（如果开启了开发模式）
    if DEV_MODE:
        db.ensure_dev_user()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    server.daemon_threads = True  # P6: 连接治理，线程不阻塞退出
    print(f"知识库系统已启动：http://127.0.0.1:{PORT}")
    if DEV_MODE:
        print("⚠️ 开发模式：验证码将回显到 API 响应（仅限本机开发）")
    else:
        print("生产模式：验证码仅通过短信/控制台输出，不回显")
    server.serve_forever()


if __name__ == "__main__":
    main()
