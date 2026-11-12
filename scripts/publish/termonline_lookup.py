# -*- coding: utf-8 -*-
"""按英文术语逐条查「术语在线」(termonline.cn，全国科学技术名词审定委员会)，记录出处。

只查本书用到的术语（不批量抓取全库），每次请求间隔 0.4 s，结果缓存可复用。
接口：tips（取候选词形）+ drawWordSearch（取条目：中文、英文、来源书名、版次、公布年、学科、条目编号、定义）；均无需登录。
缓存路径：环境变量 TERMONLINE_CACHE，缺省 ~/.cache/termonline/cache.json；写入前自动建目录。
用法: python3 termonline_lookup.py <输入.tsv 第一列为英文> <输出.tsv>
"""
import csv
import json
import os
import sys
import time
import urllib.parse
import urllib.request

API = 'https://www.termonline.cn/main-serve/business/tm/tmWord/'
HDR = {'Referer': 'https://www.termonline.cn/search', 'User-Agent': 'Mozilla/5.0 (term-check)'}
DEFAULT_CACHE = '~/.cache/termonline/cache.json'
RETRY_WAIT = 3     # 请求失败后等几秒再试
POLITE_WAIT = 0.4  # 两次成功请求之间的间隔


def cache_path():
    return os.path.expanduser(os.environ.get('TERMONLINE_CACHE') or DEFAULT_CACHE)


def load_cache():
    p = cache_path()
    if os.path.exists(p):
        with open(p, encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_cache(cache):
    p = cache_path()
    os.makedirs(os.path.dirname(p) or '.', exist_ok=True)
    tmp = p + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False)
    os.replace(tmp, p)


def get(cache, ep, term):
    key = f'{ep}|{term}'
    if key in cache:
        return cache[key]
    url = API + ep + '?' + urllib.parse.urlencode({'term': term})
    for _ in range(3):
        try:
            r = json.load(urllib.request.urlopen(urllib.request.Request(url, headers=HDR), timeout=20))
            cache[key] = r.get('result')
            time.sleep(POLITE_WAIT)
            return cache[key]
        except Exception:
            time.sleep(RETRY_WAIT)
    return None


def lookup(cache, terms, on_progress=None):
    rows = []
    for k, en in enumerate(terms):
        cands = {en}
        for w in (get(cache, 'tips', en) or {}).get('wordEsVos') or []:
            c = (w.get('cnName') or '').split('",')[0].strip()
            if c.lower() == en.lower() or c.lower().startswith((en.lower() + ' (', en.lower() + '(')):
                cands.add(c)
        seen = set()
        for c in sorted(cands):
            r = get(cache, 'drawWordSearch', c)
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
        if k % 20 == 0 and on_progress:
            on_progress()
    return rows


def main(argv=None):
    a = sys.argv[1:] if argv is None else argv
    if len(a) != 2:
        print(__doc__)
        return 2
    src, out = a
    with open(src, encoding='utf-8') as f:
        terms = [r[0].strip() for r in csv.reader(f, delimiter='\t') if r and r[0] != 'English']
    cache = load_cache()
    try:
        rows = lookup(cache, terms, on_progress=lambda: save_cache(cache))
    finally:
        save_cache(cache)  # 中途出错也保住已查到的缓存
    with open(out, 'w', encoding='utf-8') as f:
        f.write('English\t名词委中文\t名词委英文\t来源书名\t版次\t公布年\t学科\t条目编号\t定义\n')
        for r in rows:
            f.write('\t'.join(map(str, r)) + '\n')
    print('查询', len(terms), '| 有条目', len({r[0] for r in rows if r[1]}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
