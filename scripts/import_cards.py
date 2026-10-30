import os, re, sqlite3, hashlib

CONTENT_DIR = 'content'
db = sqlite3.connect('data/kb.db')
db.isolation_level = None

count = 0
for root, dirs, files in os.walk(CONTENT_DIR):
    for f in files:
        if not f.endswith('.md'): continue
        path = os.path.join(root, f)
        with open(path, 'r', encoding='utf-8') as fh:
            text = fh.read()
        title = f.replace('.md', '')
        category = '07-原子库'
        tags = ''
        body = text
        m = re.match(r'^---\s*\n(.*?)\n---', text, re.DOTALL)
        if m:
            fm = m.group(1)
            tm = re.search(r'title:\s*["\']?(.+?)["\']?\s*$', fm, re.MULTILINE)
            if tm: title = tm.group(1).strip()
            cm = re.search(r'category:\s*(.+)', fm)
            if cm: category = cm.group(1).strip()
            tgm = re.search(r'tags:\s*\[([^\]]+)\]', fm)
            if tgm: tags = tgm.group(1).replace('"','').replace("'","").replace(' ','')
            body = text[m.end():].strip()
        exists = db.execute('SELECT 1 FROM cards WHERE title=?', (title,)).fetchone()
        if exists: continue
        h = hashlib.md5(body.encode()).hexdigest()
        db.execute('INSERT INTO cards (user_id, title, content, library, tags, created_at) VALUES (?,?,?,?,?,?)',
                   (0, title, body[:5000], category, tags, __import__('time').time()))
        count += 1
        print(f'  + {title} [{category}]')

print(f'Imported {count} new cards')
total = db.execute('SELECT COUNT(*) as c FROM cards').fetchone()[0]
print(f'Total cards: {total}')
db.close()
