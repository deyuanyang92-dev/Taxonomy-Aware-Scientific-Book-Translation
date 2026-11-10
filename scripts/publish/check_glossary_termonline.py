# -*- coding: utf-8 -*-
"""附录术语表逐条对照「术语在线」(termonline.cn，全国科学技术名词审定委员会)。

做法：对每个英文术语
  1. tips 接口取候选词形（如「parapodium (多毛类)」）；
  2. 对与该术语相同或以「该术语 (」开头的候选，调 drawWordSearch 取名词委条目（中文、来源、学科、释义）。
两个接口均无需登录（allSearch 需登录，不用）。结果缓存，重复运行不重复请求。
输出：核译/术语在线/附录术语_术语在线对照.tsv
用法：python3 脚本/check_glossary_termonline.py
"""
import glob, json, os, re, time, urllib.parse, urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, '核译', '术语在线')
os.makedirs(OUT, exist_ok=True)
CACHE_F = os.path.join(OUT, 'cache.json')
cache = json.load(open(CACHE_F, encoding='utf-8')) if os.path.exists(CACHE_F) else {}
API = 'https://www.termonline.cn/main-serve/business/tm/tmWord/'
HDR = {'Referer': 'https://www.termonline.cn/search', 'User-Agent': 'Mozilla/5.0 (term-check)'}


def get(ep, term):
    key = f'{ep}|{term}'
    if key in cache:
        return cache[key]
    url = API + ep + '?' + urllib.parse.urlencode({'term': term})
    for _ in range(3):
        try:
            r = json.load(urllib.request.urlopen(urllib.request.Request(url, headers=HDR), timeout=20))
            cache[key] = r.get('result')
            time.sleep(0.3)
            return cache[key]
        except Exception:
            time.sleep(2)
    return None


pairs = []
for f in sorted(glob.glob(os.path.join(BASE, '译文', '附录A*.md'))):
    for line in open(f, encoding='utf-8'):
        m = re.match(r'^\*\*(.+?)\*\*\s*(.*)$', line.strip())
        if not m:
            continue
        head = m.group(1)
        mm = re.match(r"^([A-Za-z][A-Za-z0-9 ,'’()/\-.]*?)\s+([^A-Za-z].*)$", head)
        if mm:
            pairs.append((mm.group(1).strip(), mm.group(2).strip(), m.group(2)[:40]))

rows = []
for i, (en, zh, defi) in enumerate(pairs):
    tips = get('tips', en) or {}
    cands = {en}
    for w in tips.get('wordEsVos') or []:
        c = (w.get('cnName') or '').split('",')[0].strip()
        if c.lower() == en.lower() or c.lower().startswith(en.lower() + ' (') or c.lower().startswith(en.lower() + '('):
            cands.add(c)
    hits = []
    for c in sorted(cands):
        r = get('drawWordSearch', c)
        if r and r.get('cn') and (r.get('en') or '').strip().lower().startswith(en.lower()):
            hits.append(r)
    seen = set()
    for r in hits:
        k = (r.get('cn'), r.get('source'))
        if k in seen:
            continue
        seen.add(k)
        same = 'Y' if r['cn'].strip() == zh.split('（')[0].strip() else 'N'
        rows.append([en, zh, r['cn'].strip(), r.get('en', ''), r.get('source', ''), r.get('bbh') or '',
                     r.get('publishYear') or '', r.get('subjectFullName') or '', same,
                     (r.get('definition') or '').replace('\t', ' ').replace('\n', ' ')[:120]])
    if not hits:
        rows.append([en, zh, '', '', '', '', '', '', '无条目', ''])
    if i % 25 == 0:
        json.dump(cache, open(CACHE_F, 'w', encoding='utf-8'), ensure_ascii=False)
json.dump(cache, open(CACHE_F, 'w', encoding='utf-8'), ensure_ascii=False)

with open(os.path.join(OUT, '附录术语_术语在线对照.tsv'), 'w', encoding='utf-8') as f:
    f.write('English\t现译\t术语在线中文\t术语在线英文\t来源\t版次\t公布年\t学科\t一致\t释义(前120字)\n')
    for r in rows:
        f.write('\t'.join(map(str, r)) + '\n')
n = len(pairs)
print('术语', n, '| 有条目', len({r[0] for r in rows if r[8] != '无条目'}),
      '| 不一致', len({r[0] for r in rows if r[8] == 'N'}), '| 一致', len({r[0] for r in rows if r[8] == 'Y'}))
