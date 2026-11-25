# -*- coding: utf-8 -*-
"""分类学专门验证（Taxonomic Validator）：逐章比对英文原文与中文译文中不应改变的内容。

检查四类「证据性内容」是否原样保留（只读，不改译文）：
  1. 学名：原文中的双名法学名与属名（*Genus species* / Genus），译文须有同一拼写；
  2. 数字：原文中的阿拉伯数字（含小数、范围端点），译文须出现；
  3. 文献引证：(Author, Year) / Author (Year) 中的「作者姓 + 年份」，译文须有同一年份且有该姓；
  4. 图号：Fig./Figs./Plate 引用的图号（如 16.2b），译文须有「图 16.2」「图版 8」。
原文有、译文缺的逐条列出，附原文所在行，供核译者对照判断（自动结果只是线索，须人工确认）。

用法: python3 taxon_validate.py <书目录> [chNN ...]   输出 <书>/核译/验证/chNN.tsv 与汇总
"""
import collections, glob, os, re, sys

book = sys.argv[1]
chs = sys.argv[2:]
OUT = os.path.join(book, '核译', '验证')
os.makedirs(OUT, exist_ok=True)

STOP = set('The This These Those That There Their They When Where Which While With Within Without Although Because '
           'Following However Further Figure Figs Fig Plate Table Chapter In On Of For From Some Most Many Both Each '
           'All Other Such Its It As At By An And Or Not No Also Only More Less Here Thus Then Than Once Recent '
           'Recently Early Later Like Unlike Similar Several Molecular Morphological Phylogenetic Annelida Polychaeta'.split())
BINOM = re.compile(r'\b([A-Z][a-z]{2,})\s+([a-z]{3,})\b')
NUM = re.compile(r'(?<![\w.])(\d+(?:\.\d+)?)(?![\w])')
CITE = re.compile(r"\b([A-Z][A-Za-zÀ-ÿ'’\-]+)(?: et al\.| and [A-Z][A-Za-zÀ-ÿ'’\-]+)?,? \(?(\d{4}[a-z]?)\)?")
FIG = re.compile(r'\b(?:Figs?\.|Plates?)\s*((?:\d+\.\d+|\d+)[a-z]?)')


def load_genera():
    """已知属名集合：从术语库名录与志书基准取，减少把普通英文大写词当属名。"""
    T = os.path.expanduser('~/.claude/skills/yzz-translate/terms')
    g = set()
    for f in glob.glob(os.path.join(T, '名录_刘瑞玉2008_环节动物.tsv')) + glob.glob(os.path.join(T, '基准_*.tsv')):
        for line in open(f, encoding='utf-8').read().splitlines()[1:]:
            name = line.split('\t')[0].strip().split()
            if name and name[0][:1].isupper():
                g.add(name[0])
    return g


GENERA = load_genera()
# 已知学名：全书译文里以斜体出现过的 *Genus species*，加术语库种级基准
KNOWN = set()
for f in glob.glob(os.path.join(book, '译文', '*.md')):
    for g, sp in re.findall(r'\*([A-Z][a-z]+) ([a-z]{3,})\*', open(f, encoding='utf-8').read()):
        KNOWN.add(f'{g} {sp}')
for f in glob.glob(os.path.expanduser('~/.claude/skills/yzz-translate/terms/基准_*.tsv')):
    for line in open(f, encoding='utf-8').read().splitlines()[1:]:
        w = line.split('\t')[0].split()
        if len(w) >= 2 and w[0][:1].isupper() and w[1].islower():
            KNOWN.add(f'{w[0]} {w[1]}')

files = sorted(glob.glob(os.path.join(book, 'src_en', 'ch*.txt')))
summary = []
for src in files:
    ch = os.path.basename(src)[:-4]
    if chs and ch not in chs:
        continue
    zh_files = sorted(glob.glob(os.path.join(book, '译文', ch + '_*.md')) +
                      glob.glob(os.path.join(book, '译文', ch + '[ab]_*.md')))
    if not zh_files:
        continue
    en_lines = [l for l in open(src, encoding='utf-8').read().replace('-\n', '-').split('\n')
                if not re.fullmatch(r'\s*\d+\s*', l) and '©' not in l and 'DOI:' not in l]   # 去页码行、版权行
    en = ' '.join(en_lines)
    zh = '\n'.join(open(f, encoding='utf-8').read() for f in zh_files).replace('*', '')
    zh_flat = re.sub(r'[-‐–\s]', '', zh)          # 比对人名时忽略连字符与空格（原文跨行断词）
    rows = []

    def where(pat):
        for i, l in enumerate(en_lines, 1):
            if pat in l:
                return i, l.strip()[:120]
        return '', ''

    # 1 学名
    seen = set()
    for m in BINOM.finditer(en):
        g, sp = m.groups()
        name = f'{g} {sp}'
        if name not in KNOWN:
            continue
        if name in seen:
            continue
        seen.add(name)
        if name not in zh and f'{g[0]}. {sp}' not in zh:
            rows.append(('学名', name, *where(name)))
    # 2 数字（只看 ≥ 2 位或带小数的数，单个个位数在中文里常写成汉字）
    en_nums = collections.Counter(n for n in NUM.findall(en) if len(n) >= 2 or '.' in n)
    zh_nums = collections.Counter(NUM.findall(zh))
    for n, c in en_nums.items():
        if zh_nums[n] == 0:
            rows.append(('数字', n, *where(n)))
    # 3 引文
    for au, yr in sorted(set(CITE.findall(en))):
        au = re.sub(r"[’']s$", '', au)               # Orrhage’s (1995) → Orrhage
        if au in STOP:
            continue
        if yr not in zh or re.sub(r'[-‐–]', '', au) not in zh_flat:
            rows.append(('引文', f'{au} {yr}', *where(yr)))
    # 4 图号
    for f in sorted(set(FIG.findall(en))):
        base = re.match(r'\d+(?:\.\d+)?', f).group(0)
        if base not in zh:
            rows.append(('图号', f, *where(f)))

    with open(os.path.join(OUT, ch + '.tsv'), 'w', encoding='utf-8') as fo:
        fo.write('类别\t原文内容\t原文行号\t原文行\n')
        for r in rows:
            fo.write('\t'.join(map(str, r)) + '\n')
    cnt = collections.Counter(r[0] for r in rows)
    summary.append((ch, cnt['学名'], cnt['数字'], cnt['引文'], cnt['图号']))

with open(os.path.join(OUT, '汇总.tsv'), 'w', encoding='utf-8') as fo:
    fo.write('章\t学名缺\t数字缺\t引文缺\t图号缺\n')
    for s in summary:
        fo.write('\t'.join(map(str, s)) + '\n')
tot = [sum(s[i] for s in summary) for i in range(1, 5)]
print(f'{len(summary)} 章 | 学名缺 {tot[0]} | 数字缺 {tot[1]} | 引文缺 {tot[2]} | 图号缺 {tot[3]} → {OUT}')
