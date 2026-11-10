# -*- coding: utf-8 -*-
"""生成书末类群名索引（附录 D）：条目取自原书索引（类群名），页码取自**译本**排好的 PDF。

- 条目：原书 PDF 第 603–621 页索引中的类群名（属及以上，另有少数双名）；英文俗名不收。
- 页码：在译本 PDF 的正文页（印刷页码 1 起，到「附录 C 参考文献」之前）里按整词查找拉丁名。
- 中文名：高阶元_核定.tsv（非「—」）优先，其次 yiku 中志书/近海/名录的定名；没有就只列拉丁名。
- 输出 译文/附录D_索引.md，每行「拉丁名 中文名<TAB>页码」；属、种名加斜体标记。
用法: python3 脚本/gen_index.py <译本.pdf>
"""
import os, re, sqlite3, sys
import pymupdf

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
pdf = sys.argv[1]
SRC = os.path.join(BASE, '原书', 'Rouse2022_Annelida_专著全本.pdf')
OUT = os.path.join(BASE, '译文', '附录D_索引.md')
T = os.path.expanduser('~/.claude/skills/yzz-translate/terms')

# ---- 条目 ----
d = pymupdf.open(SRC)
ents = []
for p in range(602, 621):
    for l in d[p].get_text().split('\n'):
        m = re.match(r"^([A-Z][a-z]+(?: [a-z]{3,}| incertae sedis)?)\s*\d[\d\s,–-]*$", l.strip())
        if m:
            ents.append(m.group(1))
ents = sorted(set(ents), key=str.lower)

# ---- 中文名 ----
zh = {}
con = sqlite3.connect(os.path.expanduser('~/.yiku/yiku.db'))
order = {'动物志09': 1, '动物志33': 1, '动物志54': 1, '动物志46': 1, '近海1988': 2, '刘瑞玉2008': 3}
best = {}
for en, z, src in con.execute("select en, zh, source from terms where domain='分类学' and status='已核'"):
    r = 0 if src == 'yzz_核定' else order.get(src, 9)
    if z and z not in ('—', '-') and (en not in best or r < best[en][0]):
        best[en] = (r, z)
zh = {k: v[1] for k, v in best.items()}
# 低 → 高依次覆盖：yiku（上）→ 志书属种名 → 高阶元_核定（主会话逐条核定）
for f in ('基准_动物志09.tsv', '基准_动物志33.tsv', '基准_动物志54.tsv', '基准_动物志46.tsv'):
    for line in open(os.path.join(T, f), encoding='utf-8').read().splitlines()[1:]:
        c = line.split('\t')
        if len(c) > 3 and c[3].strip() in ('属', '种') and c[2].strip():
            zh[c[0].strip()] = c[2].strip()
for line in open(os.path.join(T, '高阶元_核定.tsv'), encoding='utf-8').read().splitlines()[1:]:
    c = line.split('\t')
    if len(c) > 2 and c[2] not in ('', '—'):
        zh[c[0]] = c[2]
zh['Sabellonga'] = '长缨鳃虫属'

# ---- 译本页码 ----
t = pymupdf.open(pdf)
printed = {}
stop = None
for i, pg in enumerate(t):
    txt = pg.get_text()
    if re.search(r'附录\s*C\s*参考文献', txt) and i > 20 and stop is None and '.....' not in txt:
        stop = i
    for l in txt.splitlines()[:3] + txt.splitlines()[-3:]:
        if l.strip().isdigit():
            printed[i] = int(l.strip())
            break
body = [(i, t[i].get_text()) for i in sorted(printed) if stop is None or i < stop]


def ranges(ps):
    out, a, b = [], None, None
    for p in ps:
        if a is None:
            a = b = p
        elif p == b + 1:
            b = p
        else:
            out.append(f'{a}' if a == b else f'{a}–{b}')
            a = b = p
    if a is not None:
        out.append(f'{a}' if a == b else f'{a}–{b}')
    return ', '.join(out)


ZHSET = set(zh.values())
HIGHER = re.compile(r'(idae|inae|ini|ida|iformia|oidea|acea|ata|aria|ia|morpha)$')
rows, miss = [], 0
for e in ents:
    pat = re.compile(r'(?<![A-Za-z])' + re.escape(e) + r'(?![a-z])')
    z = zh.get(e, '')
    use_zh = len(z) >= 3 and HIGHER.search(e)        # 科及以上在译文里多只写中文名，按中文名一并查

    def zh_hit(txt):
        for m in re.finditer(re.escape(z), txt):
            # 排除更长的已知中文名（「沙蚕科」不算「吻沙蚕科」「齿吻沙蚕科」）
            if not any(txt[max(0, m.start() - k):m.end()] in ZHSET for k in range(1, 5) if m.start() - k >= 0):
                return True
        return False
    ps = sorted({printed[i] for i, txt in body if pat.search(txt) or (use_zh and zh_hit(txt))})
    if not ps:
        miss += 1
        continue
    italic = ' ' in e and 'incertae' not in e or (e in zh and zh[e].endswith('属')) or not HIGHER.search(e) and e not in zh
    name = f'*{e}*' if italic else e
    rows.append((name, zh.get(e, ''), ranges(ps)))

with open(OUT, 'w', encoding='utf-8') as f:
    f.write('# 附录 D 类群名索引\n\n')
    f.write('> 条目取自原书索引的类群名，页码为本译本页码；按拉丁名字母顺序排列，后附中文名（无权威中文名者只列拉丁名）。\n\n---\n\n')
    letter = ''
    for name, z, pp in rows:
        L = name.strip('*')[0].upper()
        if L != letter:
            letter = L
            f.write(f'## {L}\n\n')
        f.write(f'{name}{" " + z if z else ""}\t{pp}\n\n')
print(f'条目 {len(ents)}，入索引 {len(rows)}，译本中未出现 {miss}，有中文名 {sum(1 for r in rows if r[1])} → {OUT}')
