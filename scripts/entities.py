#!/usr/bin/env python3
"""约定俗成名称的通用解析（书名、人名、机构、地名、标准术语）——取代「发现一个、补一个」的特例表。

问题（2026-11-15）：the Origin 被译成《起源》。根因不是少了某一条规则，而是**有通行中文名的专名被当作普通文字逐词翻译**。
做法：
1 extract：每段原文让便宜模型列出有通行译名可能的专名，并给出规范英文全称（the Origin → On the Origin of Species）。
2 resolve：先查 yiku（有出处、已核者为准），没有再查 Wikidata 简体中文标签（标「候选」，须核），都没有就标「无通行名」
  （人名等按规则保留原文，不逐词音译/意译）。缓存于 ~/.cache/yzz-translate/entities.sqlite。
3 table：解析结果做成「专名表」注入译者/改写提示词（必用）。
4 check：译文里没有用到专名的通行中文名 → 问题（已核 major，候选 minor）。

    python3 entities.py extract SRC.md -o ents.json [--engine codex-luna] [--domain 进化生物学]
    python3 entities.py check SRC.md TGT.md ents.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

EXTRACT_SYS = """List the proper names in the text that a translator must NOT translate word by word because they may have an
established rendering in the target language: titles of books and papers, people, institutions, museums, expeditions,
ships, geographic names, named theories/laws/concepts. Include short references (e.g. "the Origin" means Darwin's
"On the Origin of Species"; "Lamarck" means Jean-Baptiste Lamarck). Do NOT list Latin scientific names of taxa or ordinary
technical words. Output ONLY a JSON array: [{"surface": "exact text as it appears", "canonical": "full standard English
name", "type": "book|person|institution|place|concept|other"}]."""


def _cache() -> sqlite3.Connection:
    p = Path.home() / '.cache/yzz-translate/entities.sqlite'
    p.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(p))
    db.execute('create table if not exists wd(k text primary key, v text)')
    return db


def wikidata_zh(name: str, retries: int = 4) -> tuple[str, str] | None:
    """Wikidata 简体中文标签（zh-cn > zh-hans > zh）。返回 (标签, QID) 或 None。网络错误重试，结果缓存。"""
    db = _cache()
    k = hashlib.sha1(name.encode()).hexdigest()
    row = db.execute('select v from wd where k=?', (k,)).fetchone()
    if row:
        v = json.loads(row[0])
        return (v[0], v[1]) if v else None
    api = 'https://www.wikidata.org/w/api.php?'
    result: tuple[str, str] | None = None
    for a in range(retries):
        try:
            q = api + urllib.parse.urlencode({'action': 'wbsearchentities', 'search': name, 'language': 'en',
                                              'limit': 1, 'format': 'json'})
            hits = json.load(urllib.request.urlopen(urllib.request.Request(q, headers={'User-Agent': 'yzz-translate'}),
                                                    timeout=20)).get('search', [])
            if hits:
                qid = hits[0]['id']
                q2 = api + urllib.parse.urlencode({'action': 'wbgetentities', 'ids': qid, 'props': 'labels',
                                                   'languages': 'zh-cn|zh-hans|zh', 'format': 'json'})
                labels = json.load(urllib.request.urlopen(urllib.request.Request(q2, headers={'User-Agent': 'yzz-translate'}),
                                                          timeout=20))['entities'][qid].get('labels', {})
                for lang in ('zh-cn', 'zh-hans', 'zh'):
                    if lang in labels:
                        result = (labels[lang]['value'], qid)
                        break
            break
        except Exception:  # noqa: BLE001 - 网络错误：退避重试
            time.sleep(2 ** a)
    else:
        return ('', 'FAILED')                         # 网络失败：不缓存，标「查询失败」，下次再查
    db.execute('insert or replace into wd values(?,?)', (k, json.dumps(list(result) if result else None)))
    db.commit()
    return result


def yiku_zh(name: str, domain: str) -> tuple[str, str] | None:
    """yiku 里该英文名的首选译名与状态（已核优先）。没有则 None。"""
    try:
        out = subprocess.run(['yiku', 'lookup', name, '--domain', domain], capture_output=True, text=True,
                             timeout=60).stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    rows = [ln.split('\t') for ln in out.splitlines() if '\t' in ln]
    rows = [r for r in rows if len(r) > 1 and r[1] in ('已核', '候选')]
    if not rows:
        return None
    rows.sort(key=lambda r: r[1] != '已核')
    return rows[0][0], rows[0][1]


def resolve(ents: list[dict[str, Any]], domain: str, use_wikidata: bool = True) -> list[dict[str, Any]]:
    out = []
    for e in ents:
        name = str(e.get('canonical') or e.get('surface') or '').strip()
        if not name:
            continue
        r: dict[str, Any] = dict(e)
        hit = yiku_zh(name, domain) or (yiku_zh(str(e['surface']), domain) if e.get('surface') else None)
        if hit:
            r.update(zh=hit[0], status=hit[1], source='yiku')
        elif use_wikidata and (wd := wikidata_zh(name)):
            if wd[1] == 'FAILED':
                r.update(zh=None, status='查询失败', source='Wikidata 网络错误，下次重查')
            else:
                r.update(zh=wd[0], status='候选', source=f'Wikidata {wd[1]}')
        else:
            r.update(zh=None, status='无通行名', source='')
        out.append(r)
    return out


def table_md(res: list[dict[str, Any]]) -> str:
    rows = [f"- {r['surface']} ({r.get('canonical', '')}) = {r['zh']}"
            + ('' if r['status'] == '已核' else '（候选，须核；语境不合可保留原文）')
            for r in res if r.get('zh')]
    keep = [f"- {r['surface']}：无通行中文名，保留原文，不逐词意译" for r in res if not r.get('zh') and r.get('type') == 'person']
    return '\n'.join(rows + keep) or '（无）'


def check(src: str, tgt: str, res: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """原文出现了该专名、译文却没有用通行中文名 → 问题。书名额外核对书名号内是否为全称。"""
    out = []
    for r in res:
        zh = r.get('zh')
        if not zh or str(r.get('surface', '')) not in src:
            continue
        plain = zh.strip('《》')
        ok = plain in tgt
        if r.get('type') == 'person' and r['status'] != '已核':
            # 人名惯例（STYLE.md §6）：家喻户晓者用通行中文名（多为姓：华莱士），其余保留原文——两者都算合格
            surname = plain.split('·')[-1]
            ok = ok or surname in tgt or str(r['surface']).split()[-1] in tgt
        if not ok:
            sev = 'major' if r['status'] == '已核' else 'minor'
            out.append({'severity': sev, 'surface': r['surface'], 'expected': zh, 'source': r.get('source'),
                        'message': f"专名「{r['surface']}」应译为通行名「{zh}」（{r.get('source')}，{r['status']}）"})
    return out


def extract(text: str, engine: str, work: Path) -> list[dict[str, Any]]:
    import auto_translate as at
    v = at._ask_json(engine, EXTRACT_SYS, text, 'entities/extract', work)
    seen, out = set(), []
    for e in v or []:
        key = (str(e.get('surface', '')), str(e.get('canonical', '')))
        if key[0] and key not in seen:
            seen.add(key)
            out.append(e)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=['extract', 'check'])
    ap.add_argument('src')
    ap.add_argument('tgt', nargs='?')
    ap.add_argument('ents', nargs='?')
    ap.add_argument('-o', '--out', default='entities.json')
    ap.add_argument('--engine', default='codex-luna')
    ap.add_argument('--domain', default='进化生物学')
    a = ap.parse_args(argv)
    src = Path(a.src).read_text(encoding='utf-8')
    if a.cmd == 'extract':
        res = resolve(extract(src, a.engine, Path(a.out).parent), a.domain)
        Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')
        print(table_md(res))
        return 0
    if not (a.tgt and a.ents):
        ap.error('check 需要 TGT 与 ents.json')
    issues = check(src, Path(a.tgt).read_text(encoding='utf-8'),
                   json.loads(Path(a.ents).read_text(encoding='utf-8')))
    print(json.dumps(issues, ensure_ascii=False, indent=1))
    return 1 if any(i['severity'] == 'major' for i in issues) else 0


if __name__ == '__main__':
    sys.exit(main())
