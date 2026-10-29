# -*- coding: utf-8 -*-
"""AI 层：OpenAI 兼容接口（可配置）+ 规则降级模式（零配置开箱即用）
P6b: API Key 落盘混淆（HMAC-SHA256 派生流密钥 + XOR，非军事级加密，防 casual 窃取）"""
import json
import os
import re
import hashlib
import hmac
import urllib.request
import urllib.error

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.join(BASE_DIR, "data", "settings.json")
SECRET_PATH = os.path.join(BASE_DIR, "data", ".secret_key")


def _get_secret():
    """首次运行生成机器绑定密钥文件"""
    if os.path.exists(SECRET_PATH):
        with open(SECRET_PATH, "rb") as f:
            return f.read()
    os.makedirs(os.path.dirname(SECRET_PATH), exist_ok=True)
    secret = os.urandom(32)
    with open(SECRET_PATH, "wb") as f:
        f.write(secret)
    return secret


def _derive_stream(secret, length):
    """从密钥派生指定长度的 XOR 流"""
    out = bytearray()
    counter = 0
    while len(out) < length:
        block = hmac.new(secret, counter.to_bytes(4, "big"), hashlib.sha256).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:length])


def _encrypt(text):
    """XOR 混淆（base64 存储）"""
    if not text:
        return ""
    secret = _get_secret()
    data = text.encode("utf-8")
    stream = _derive_stream(secret, len(data))
    enc = bytes(b ^ s for b, s in zip(data, stream))
    return enc.hex()


def _decrypt(hex_str):
    """解混淆"""
    if not hex_str:
        return ""
    try:
        secret = _get_secret()
        data = bytes.fromhex(hex_str)
        stream = _derive_stream(secret, len(data))
        dec = bytes(b ^ s for b, s in zip(data, stream))
        return dec.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def load_settings():
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            s = json.load(f)
        # 自动解密 api_key（兼容旧明文格式）
        if "api_key" in s and s["api_key"] and s["api_key"].startswith("_enc:"):
            s["_api_key_plain"] = _decrypt(s["api_key"][5:])
            s["api_key"] = s["_api_key_plain"]
        return s
    except Exception:
        return {}


def save_settings(s):
    # 加密 api_key 后落盘
    enc_s = dict(s)
    if enc_s.get("api_key"):
        enc_s["api_key"] = "_enc:" + _encrypt(enc_s["api_key"])
    os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(enc_s, f, ensure_ascii=False, indent=2)


def is_ai_enabled():
    s = load_settings()
    return bool(s.get("base_url") and s.get("api_key"))


def chat(prompt, system="", max_tokens=2000, temperature=0.4):
    """调用 OpenAI 兼容接口；未配置或失败返回 None，由调用方降级"""
    s = load_settings()
    base = (s.get("base_url") or "").rstrip("/")
    # P6b: 优先用解密后的明文 key，兼容旧格式直接用 api_key 字段
    key = s.get("_api_key_plain") or s.get("api_key") or ""
    model = s.get("model") or "gpt-4o-mini"
    if not base or not key:
        return None
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system or "你是用户个人AI知识库的助手，回答简洁、直接、具体。"},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    req = urllib.request.Request(
        base + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]
    except (urllib.error.URLError, KeyError, TimeoutError, OSError):
        return None


# ---------------- 规则降级模式 ----------------

def rule_distill(title, content, profile):
    """无AI时的规则蒸馏：启发式分类 + 简单原子化"""
    import re
    text = (title + "\n" + content).strip()
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    snippet = " ".join(lines[:3])[:200]
    # 识别行动信号
    action_keywords = re.findall(r"(?:需要|应该|必须|记得|todo|待办|下一步)[：:]?\s*([^。\n]{4,60})", text, re.I)
    # 识别问题信号
    has_question = "?" in text or "？" in text or re.search(r"如何|怎么|为什么|什么是", text)
    # 识别实体/术语
    import re as _re
    terms = _re.findall(r"[「《]([^」》]{2,20})[」》]|【([^】]{2,20})】", text)
    terms = [t for pair in terms for t in pair if t]
    return {
        "title": (title[:40] or "未命名卡片"),
        "content": snippet,
        "library": "07-原子库",
        "tags": ",".join(terms[:5]),
        "actions": action_keywords[:3],
        "source": "rule",
    }


def rule_classify(text):
    """规则路由：决定内容进哪个库"""
    if re.search(r"灵感|想法|点子|突然想到", text):
        return "00-灵感库"
    if re.search(r"复盘|教训|错题|改进|纠正", text):
        return "02-资产库"
    if re.search(r"问题|需求|卡点|怎么办", text):
        return "01-项目库"
    return "03-资源库"


def rule_review_analysis(content, profile):
    return "【规则模式】请在设置中配置 AI 接口以获得深度复盘分析。\n当前复盘已保存。建议自行回答：1)方法用对了吗 2)结果符合预期吗 3)下次改哪一个动作。"
