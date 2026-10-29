#!/usr/bin/env python3
"""Check for broken internal links"""
import re
import sys
from pathlib import Path

BASE = Path(__file__).parent.parent
CONTENT = BASE / "content"

LINK_PATTERNS = [
    re.compile(r'\[([^\]]*)\]\(([^)]+)\)'),  # [text](path)
    re.compile(r'\[\[([^\]]+)\]\]'),          # [[wiki-link]]
]

def collect_valid_paths():
    paths = set()
    stems = set()
    for f in CONTENT.rglob('*.md'):
        rel = str(f.relative_to(BASE))
        paths.add(rel)
        paths.add(rel.replace('.md', ''))
        stems.add(f.stem)
    # Also include root-level .md files
    for f in BASE.glob('*.md'):
        paths.add(f.name)
        paths.add(f.stem)
        stems.add(f.stem)
    # Include root-level .txt files
    for f in BASE.glob('*.txt'):
        paths.add(f.name)
        paths.add(f.stem)
        stems.add(f.stem)
    return paths, stems

def check_links(md_file, valid_paths, stems, titles):
    raw = md_file.read_text(encoding='utf-8')
    # Remove frontmatter
    raw = re.sub(r'^---\n.*?\n---', '', raw, flags=re.DOTALL)

    issues = []
    for pattern in LINK_PATTERNS:
        for match in pattern.finditer(raw):
            link = match.group(2) if match.lastindex >= 2 else match.group(1)
            # Skip external links
            if link.startswith(('http', '#', 'mailto:')):
                continue
            # Check path
            clean = link.split('#')[0].strip()
            if clean and clean not in valid_paths:
                # For wiki-links, also check stem and title matches
                is_wiki = pattern == LINK_PATTERNS[1]
                if is_wiki:
                    # Try matching against stems and titles
                    if clean in stems or clean in titles:
                        continue
                issues.append(f"Broken link: {link}")
    return issues

def collect_titles():
    titles = set()
    for f in CONTENT.rglob('*.md'):
        m = re.match(r'^---\n(.*?)\n---', f.read_text(encoding='utf-8'), re.DOTALL)
        if m:
            for line in m.group(1).split('\n'):
                if line.startswith('title:'):
                    val = line.split(':', 1)[1].strip().strip('"\'')
                    titles.add(val)
    return titles

def main():
    valid_paths, stems = collect_valid_paths()
    titles = collect_titles()
    all_issues = []
    checked = 0
    for md_file in CONTENT.rglob('*.md'):
        if '_templates' in str(md_file):
            continue
        checked += 1
        issues = check_links(md_file, valid_paths, stems, titles)
        for issue in issues:
            rel = str(md_file.relative_to(BASE))
            all_issues.append(f"  {rel}: {issue}")

    if all_issues:
        print(f"❌ Found {len(all_issues)} broken links across {checked} files:")
        for i in all_issues:
            print(i)
        sys.exit(1)
    else:
        print(f"✅ All {checked} files passed link check")

if __name__ == '__main__':
    main()
