#!/usr/bin/env python3
"""AI knowledge extraction using GitHub Models"""
import os
import sys
import json
import hashlib
import urllib.request
from pathlib import Path

BASE = Path(__file__).parent.parent
CONTENT = BASE / "content"
CACHE = BASE / ".cache" / "knowledge_cache.json"

def load_cache():
    if CACHE.exists():
        return json.loads(CACHE.read_text(encoding='utf-8'))
    return {}

def save_cache(cache):
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding='utf-8')

def chunk_text(text, max_chars=3000):
    chunks = []
    current = ""
    for line in text.split('\n'):
        if len(current) + len(line) > max_chars:
            if current:
                chunks.append(current)
            current = line
        else:
            current += '\n' + line if current else line
    if current:
        chunks.append(current)
    return chunks

def call_github_models(chunk, token):
    url = "https://models.github.ai/inference"
    payload = json.dumps({
        "model": "gpt-4o-mini",
        "messages": [
            {
                "role": "system",
                "content": "Extract key knowledge points, entities, and relationships from the following text. Return JSON with: 'key_points' (list of strings), 'entities' (list of {name, type}), 'tags' (list of strings), 'summary' (one sentence)."
            },
            {"role": "user", "content": chunk[:2000]}
        ],
        "max_tokens": 500,
        "temperature": 0.2
    }).encode('utf-8')

    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "Accept": "application/json"
        },
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode('utf-8'))
            return result.get('choices', [{}])[0].get('message', {}).get('content', '')
    except Exception as e:
        print(f"  Error: {e}")
        return None

def main():
    token = os.environ.get('GITHUB_TOKEN', '')
    if not token:
        print("⚠️ GITHUB_TOKEN not set, skipping AI extraction")
        return

    cache = load_cache()
    processed = 0
    skipped = 0

    for md_file in CONTENT.rglob('*.md'):
        if '_templates' in str(md_file):
            continue

        raw = md_file.read_text(encoding='utf-8')
        # Hash content for cache
        content_hash = hashlib.sha256(raw.encode()).hexdigest()
        rel_path = str(md_file.relative_to(BASE))

        if cache.get(rel_path, {}).get('hash') == content_hash:
            skipped += 1
            continue

        chunks = chunk_text(raw)
        extracted = []
        for chunk in chunks:
            result = call_github_models(chunk, token)
            if result:
                try:
                    extracted.append(json.loads(result))
                except json.JSONDecodeError:
                    extracted.append({"raw": result})

        if extracted:
            cache[rel_path] = {
                'hash': content_hash,
                'extracted': extracted,
                'processed_at': time.time() if 'time' in dir() else 0
            }
            processed += 1

    save_cache(cache)
    print(f"AI extraction complete: {processed} new, {skipped} cached")

if __name__ == '__main__':
    import time
    main()
