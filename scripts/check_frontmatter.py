#!/usr/bin/env python3
"""Validate frontmatter on all Markdown files"""
import sys
import re
from pathlib import Path

BASE = Path(__file__).parent.parent
CONTENT = BASE / "content"
REQUIRED_FIELDS = ["title", "date", "tags", "category"]

def check_frontmatter(md_file):
    raw = md_file.read_text(encoding='utf-8')
    m = re.match(r'^---\n(.*?)\n---', raw, re.DOTALL)
    if not m:
        return False, "No frontmatter"

    fm = {}
    for line in m.group(1).split('\n'):
        if ':' in line:
            key, val = line.split(':', 1)
            fm[key.strip()] = val.strip()

    missing = [f for f in REQUIRED_FIELDS if f not in fm]
    if missing:
        return False, f"Missing fields: {missing}"

    if 'status' in fm and fm['status'] not in ('active', 'stale', 'archived'):
        return False, f"Invalid status: {fm['status']}"

    return True, ""

def main():
    errors = []
    checked = 0
    for md_file in CONTENT.rglob('*.md'):
        if '_templates' in str(md_file):
            continue
        checked += 1
        ok, msg = check_frontmatter(md_file)
        if not ok:
            rel = str(md_file.relative_to(BASE))
            errors.append(f"  {rel}: {msg}")

    if errors:
        print(f"❌ {len(errors)}/{checked} files have issues:")
        for e in errors:
            print(e)
        sys.exit(1)
    else:
        print(f"✅ All {checked} files passed frontmatter validation")

if __name__ == '__main__':
    main()
