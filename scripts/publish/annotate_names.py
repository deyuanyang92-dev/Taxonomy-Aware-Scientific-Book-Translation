# -*- coding: utf-8 -*-
"""为属名、种名在每章首次出现处前置中文名（只用中国海名录基准里有的名称）。

用户规则（2026-11-09）：
  · 尊重原文：拉丁学名原样保留，只在每章首次出现时前置中文名，
    形如「小头虫 *Capitella capitata*」「小头虫属 *Capitella*」；其后仍只用拉丁名。
  · 中文名只取基准：高阶元_核定.tsv（属，排除「推定」「—」）> 动物志54卷属名（annotate_genera.py）
    > 刘瑞玉2008 名录（属：名录_刘瑞玉2008_环节动物.tsv；种：基准_种_刘瑞玉2008.tsv）。查不到就不加。
  · 种名只做拉丁名完全一致的匹配（异名匹配另做）。
  · 不动：标题行、图注行（**图 …）、「作为 *X*」（原书误定/旧名语境）、已带中文名者。

用法: python3 annotate_names.py [--dry]   报告写 核译/annotate_names_report.tsv
"""
import glob, os, re, sys, unicodedata

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 书目录（脚本在 脚本/ 下）
T = os.path.expanduser('~/.claude/skills/yzz-translate/terms')
DRY = '--dry' in sys.argv


def tsv(path):
    rows = open(path, encoding='utf-8').read().splitlines()
    return [r.split('\t') for r in rows[1:] if r.strip()]


def clean(name):
    # 匹配键：去亚属括号、去变音符号（志书 Pholoë ＝ 原书 Pholoe）；正文拉丁名本身不改
    name = re.sub(r'\s+', ' ', re.sub(r'\s+\((?:sensu stricto|[A-Z][a-z]+)\)', '', name)).strip()
    return ''.join(ch for ch in unicodedata.normalize('NFKD', name) if not unicodedata.combining(ch))


genus = {}
for c in tsv(f'{T}/名录_刘瑞玉2008_环节动物.tsv'):
    if c[2] == '属':
        genus[clean(c[0])] = (c[1], '刘瑞玉2008')
src = open(os.path.join(BASE, '脚本', 'annotate_genera.py'), encoding='utf-8').read()
for g, z in re.findall(r"'([A-Z][a-z]+)':\s*'([^']+属)'", src):
    genus[g] = (z, '动物志54')
species = {}
for c in tsv(f'{T}/基准_种_刘瑞玉2008.tsv'):
    name = clean(c[0])
    if ' sp.' in name or 'group' in name or '/' in name:
        continue
    species[name] = (c[2], c[9])

# 志书基准覆盖名录（优先级：动物志 > 近海1988 > 刘瑞玉2008）
FAUNA = [('基准_近海1988.tsv', '杨德渐孙瑞平1988'), ('基准_动物志46.tsv', '动物志46'),
         ('基准_动物志54.tsv', '动物志54'), ('基准_动物志33.tsv', '动物志33'), ('基准_动物志09.tsv', '动物志9')]
for fn, book in FAUNA:
    if not os.path.exists(f'{T}/{fn}'):
        continue
    for c in tsv(f'{T}/{fn}'):
        if len(c) < 8 or not c[2].strip() or c[2].strip() in ('—', '-'):
            continue
        name, zh, rank = clean(c[0]), c[2].strip(), c[3].strip()
        src = f'{book} PDF第{c[7]}页'
        if rank == '属' and ' ' not in name:
            genus[name] = (zh, src)
        elif rank in ('种', '亚种') and ' ' in name:
            species[' '.join(name.split()[:2]) if rank == '种' else name] = (zh, src)

for c in tsv(f'{T}/高阶元_核定.tsv'):
    if c[1] == '属':
        if c[2] in ('—', '') or '推定' in c[3]:
            genus.pop(c[0], None)
        else:
            genus[c[0]] = (c[2], '高阶元_核定')


SKIP_LINE = re.compile(r'^\s*(#|\*\*图|\*\*Plate|\*\*图版)')
PAT = re.compile(r'\*([A-Z][a-zà-ÿ]+)(?: ([a-zà-ÿ][a-zà-ÿ\-]+))?\*')

report = []
for path in sorted(glob.glob(os.path.join(BASE, '译文', 'ch*.md'))):
    fn = os.path.basename(path)
    lines = open(path, encoding='utf-8').read().split('\n')
    seen_g, seen_s = set(), set()
    changed = False
    for i, line in enumerate(lines):
        if SKIP_LINE.match(line):
            continue
        out, pos = [], 0
        for m in PAT.finditer(line):
            g, sp = clean(m.group(1)), (clean(m.group(2)) if m.group(2) else None)
            before = line[max(0, m.start() - 14):m.start()]
            zh = None
            if sp:
                key = f'{g} {sp}'
                if key in species and key not in seen_s:
                    zh, why = species[key]
                    kind, seen = '种', seen_s
            elif g in genus and g not in seen_g:
                zh, why = genus[g]
                kind, seen, key = '属', seen_g, g
            if not zh:
                continue
            if before.rstrip().endswith(('作为', '作')):
                report.append((fn, kind, m.group(0), zh, why, '跳过：作为（不计首现）'))
                continue
            seen.add(key)
            if zh in before:
                report.append((fn, kind, m.group(0), zh, why, '跳过：已有中文名'))
                continue
            seg = line[pos:m.start()]
            # 「如 *X*」→「如白毛虫属 *X*」：中文/全角标点后的空格去掉
            if re.search(r'[\u3400-\u9fff\U00020000-\U0002ffff\u3000-\u303f\uff00-\uffef] $', seg):
                seg = seg[:-1]
            out.append(seg + zh + ' ')
            pos = m.start()
            report.append((fn, kind, m.group(0), zh, why, '添加'))
            changed = True
        if out:
            lines[i] = ''.join(out) + line[pos:]
    if changed and not DRY:
        open(path, 'w', encoding='utf-8').write('\n'.join(lines))

os.makedirs(os.path.join(BASE, '核译'), exist_ok=True)
with open(os.path.join(BASE, '核译', 'annotate_names_report.tsv'), 'w', encoding='utf-8') as f:
    f.write('章\t阶元\t拉丁名\t中文名\t依据\t处理\n')
    for r in report:
        f.write('\t'.join(r) + '\n')
add = [r for r in report if r[5] == '添加']
print(f"{'DRY ' if DRY else ''}添加 属 {sum(r[1]=='属' for r in add)} 处、种 {sum(r[1]=='种' for r in add)} 处；跳过 {len(report)-len(add)}")
