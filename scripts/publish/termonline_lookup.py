# -*- coding: utf-8 -*-
"""按英文术语逐条查「术语在线」(termonline.cn，全国科学技术名词审定委员会)，记录出处。

只查本书用到的术语（不批量抓取全库），每次请求间隔 0.4 s，结果缓存可复用。
接口：tips（取候选词形）+ drawWordSearch（取条目：中文、英文、来源书名、版次、公布年、学科、条目编号、定义）；均无需登录。
用法: python3 脚本/termonline_lookup.py <输入.tsv 第一列为英文> <输出.tsv>
"""
import json, os, sys, time, urllib.parse, urllib.request, csv

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_F = os.path.join(BASE, '核译', '术语在线', 'cache.json')
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
            time.sleep(0.4)
            return cache[key]
        except Exception:
            time.sleep(3)
    return None


src, out = sys.argv[1], sys.argv[2]
terms = [r[0].strip() for r in csv.reader(open(src, encoding='utf-8'), delimiter='\t') if r and r[0] != 'English']
rows = []
for k, en in enumerate(terms):
    cands = {en}
    for w in (get('tips', en) or {}).get('wordEsVos') or []:
        c = (w.get('cnName') or '').split('",')[0].strip()
        if c.lower() == en.lower() or c.lower().startswith((en.lower() + ' (', en.lower() + '(')):
            cands.add(c)
    seen = set()
    for c in sorted(cands):
        r = get('drawWordSearch', c)
        if not r or not r.get('cn') or not (r.get('en') or '').strip().lower().startswith(en.lower()):
            continue
        key = (r['cn'], r.get('source'))
        if key in seen:
            continue
        seen.add(key)
        rows.append([en, r['cn'].strip(), (r.get('en') or '').strip(), r.get('source') or '', r.get('bbh') or '',
                     r.get('publishYear') or '', r.get('subjectFullName') or '', r.get('wordNumber') or '',
                     (r.get('definition') or '').replace('\t', ' ').replace('\n', ' ')[:150]])
    if not seen:
        rows.append([en, '', '', '', '', '', '', '', ''])
    if k % 20 == 0:
        json.dump(cache, open(CACHE_F, 'w', encoding='utf-8'), ensure_ascii=False)
json.dump(cache, open(CACHE_F, 'w', encoding='utf-8'), ensure_ascii=False)
with open(out, 'w', encoding='utf-8') as f:
    f.write('English\t名词委中文\t名词委英文\t来源书名\t版次\t公布年\t学科\t条目编号\t定义\n')
    for r in rows:
        f.write('\t'.join(map(str, r)) + '\n')
print('查询', len(terms), '| 有条目', len({r[0] for r in rows if r[1]}))
