#!/usr/bin/env python3
"""Build search index from Markdown content"""
import os
import re
import json
import time
from pathlib import Path

BASE = Path(__file__).parent.parent
CONTENT = BASE / "content"
OUTPUT = BASE / "assets" / "search-index.json"

def parse_frontmatter(text):
    fm = {}
    m = re.match(r'^---\n(.*?)\n---', text, re.DOTALL)
    if m:
        for line in m.group(1).split('\n'):
            if ':' in line:
                key, val = line.split(':', 1)
                fm[key.strip()] = val.strip()
    return fm

def extract_text(md_text):
    # Remove frontmatter
    text = re.sub(r'^---\n.*?\n---', '', md_text, flags=re.DOTALL)
    # Remove markdown syntax
    text = re.sub(r'[#*`>\[\]]', '', text)
    # Remove links keep text
    text = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', text)
    # Remove HTML
    text = re.sub(r'<[^>]+>', '', text)
    # Collapse whitespace
    text = re.sub(r'\n{2,}', '\n', text)
    return text.strip()

def main():
    documents = []
    for md_file in CONTENT.rglob('*.md'):
        if '_templates' in str(md_file):
            continue
        rel_path = str(md_file.relative_to(BASE))
        raw = md_file.read_text(encoding='utf-8')
        fm = parse_frontmatter(raw)
        text = extract_text(raw)
        title = fm.get('title', md_file.stem)
        tags = fm.get('tags', '').replace('[', '').replace(']', '').split(',')
        tags = [t.strip() for t in tags if t.strip()]
        category = fm.get('category', str(md_file.parent.relative_to(CONTENT)))

        documents.append({
            'id': rel_path,
            'title': title,
            'text': text,
            'tags': tags,
            'category': category,
            'url': f'/{rel_path}'
        })

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(documents, ensure_ascii=False), encoding='utf-8')
    print(f'Indexed {len(documents)} documents -> {OUTPUT}')

if __name__ == '__main__':
    main()
