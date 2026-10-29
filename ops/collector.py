# -*- coding: utf-8 -*-
"""采集模块：RSS/网页多源增量采集，自动清洗归档"""
import re
import time
import urllib.request
import urllib.parse
import hashlib
import os
import json
from html.parser import HTMLParser

import ops_db
import db


class TextExtractor(HTMLParser):
    """从HTML提取纯文本"""
    def __init__(self):
        super().__init__()
        self.text = []
        self.skip = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.skip = True

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self.skip = False

    def handle_data(self, data):
        if not self.skip:
            self.text.append(data.strip())

    def get_text(self):
        return "\n".join(t for t in self.text if t)


def fetch_url(url, timeout=15):
    """获取URL内容"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (KB-Ops-Bot)"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        return None, str(e)


def extract_feed_items(feed_xml):
    """从RSS/Atom feed提取条目"""
    items = []
    # RSS 2.0
    for match in re.finditer(r"<item>([\s\S]*?)</item>", feed_xml):
        item_xml = match.group(1)
        title = re.search(r"<title>(.*?)</title>", item_xml, re.DOTALL)
        link = re.search(r"<link>(.*?)</link>", item_xml, re.DOTALL)
        desc = re.search(r"<description>(.*?)</description>", item_xml, re.DOTALL)
        pub = re.search(r"<pubDate>(.*?)</pubDate>", item_xml, re.DOTALL)
        items.append({
            "title": _strip_html(title.group(1) if title else ""),
            "link": link.group(1) if link else "",
            "description": _strip_html(desc.group(1) if desc else ""),
            "published": pub.group(1) if pub else "",
        })
    # Atom
    if not items:
        for match in re.finditer(r"<entry>([\s\S]*?)</entry>", feed_xml):
            item_xml = match.group(1)
            title = re.search(r"<title>(.*?)</title>", item_xml, re.DOTALL)
            link = re.search(r'<link[^>]*href="([^"]*)"', item_xml)
            summary = re.search(r"<summary>(.*?)</summary>", item_xml, re.DOTALL)
            pub = re.search(r"<published>(.*?)</published>", item_xml, re.DOTALL)
            items.append({
                "title": _strip_html(title.group(1) if title else ""),
                "link": link.group(1) if link else "",
                "description": _strip_html(summary.group(1) if summary else ""),
                "published": pub.group(1) if pub else "",
            })
    return items


def _strip_html(html):
    if not html:
        return ""
    text = re.sub(r"<[^>]+>", "", html)
    return re.sub(r"\s+", " ", text).strip()


def fetch_rss(source):
    """采集单个RSS源"""
    feed_url = source["url"]
    content, err = fetch_url(feed_url)
    if content is None:
        return [], err
    items = extract_feed_items(content)
    # 过滤过期内容（超过7天的条目）
    recent = []
    for item in items:
        try:
            pub_ts = time.mktime(time.strptime(item["published"][:25], "%a, %d %b %Y %H:%M:%S"))
            if time.time() - pub_ts > 7 * 86400:
                continue
        except (ValueError, KeyError):
            pass
        recent.append(item)
    return recent, None


def fetch_web_article(url):
    """采集单篇网页文章"""
    content, err = fetch_url(url)
    if content is None:
        return None, err
    parser = TextExtractor()
    parser.feed(content)
    text = parser.get_text()
    # 提取标题
    title_match = re.search(r"<title[^>]*>(.*?)</title>", content, re.DOTALL)
    title = _strip_html(title_match.group(1)) if title_match else url
    return {"title": title, "content": text[:20000], "url": url}, None


def collect_from_source(source, uid):
    """从单个源采集内容并归档"""
    items = []
    if source["source_type"] == "rss":
        items, err = fetch_rss(source)
        if err:
            ops_db.update_source_status(source["name"], f"fetch_error: {err}")
            return [], 0, 0
    elif source["source_type"] == "web":
        article, err = fetch_web_article(source["url"])
        if article:
            items = [article]
        else:
            ops_db.update_source_status(source["name"], f"fetch_error: {err}")
            return [], 0, 0

    ops_db.update_source_status(source["name"], f"fetched_{len(items)}")
    created = 0
    for item in items:
        # 计算指纹
        content_str = item.get("content", "") or item.get("description", "")
        fingerprint = hashlib.sha256(f"{item['title']}:{content_str[:500]}".encode()).hexdigest()
        # 检查重复
        existing = ops_db.check_fingerprint(fingerprint)
        if existing:
            continue
        # 保存到采集表
        conn = db.get_conn()
        conn.execute(
            "INSERT INTO captures(user_id, source_type, source_url, title, raw_content, created_at) VALUES(?,?,?,?,?,?)",
            (uid, source["source_type"], item.get("link", source["url"]), item["title"], content_str[:20000], ops_db.now())
        )
        cap_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.close()
        # 记录指纹
        ops_db.add_fingerprint(cap_id, fingerprint, hashlib.sha256(content_str.encode()).hexdigest(), item["title"], source["name"])
        created += 1
    return items, created, 0


def collect_all(uid, sources=None):
    """采集所有启用的源"""
    if sources is None:
        sources = ops_db.get_sources(enabled_only=True)
    total_created = 0
    total_items = 0
    for src in sources:
        items, created, _ = collect_from_source(src, uid)
        total_items += len(items)
        total_created += created
    return total_items, total_created
