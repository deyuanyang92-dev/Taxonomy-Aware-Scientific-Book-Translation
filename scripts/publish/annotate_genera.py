# -*- coding: utf-8 -*-
"""为属名首次出现处补中文属名（据《中国动物志·缨鳃虫目》卷）。

忠实原文原则：属名本身保留斜体拉丁原名，只在**每章首次**出现时前置中文属名，
形如「鳍缨虫属 *Branchiomma*」；其后仍用 *Branchiomma*，不擅改为中文。
"""
import glob, os, io, re, collections

ZH = '译文'

GENUS = {
    'Monroika': '单缨虫属',
    'Sabella': '缨鳃虫属',
    'Sabellastarte': '光缨鳃虫属',
    'Branchiomma': '鳍缨虫属',
    'Megalomma': '麦缨虫属',
    'Pseudobranchiomma': '伪鳍缨虫属',
    'Oriopsis': '欧缨虫属',
    'Fabriciola': '似豆缨虫属',
    'Pseudofabricia': '伪豆缨虫属',
    'Sabellonga': '长缨鳃虫属',   # 2026-11-09：原取志54 p30 顺带写法「毛鳃虫」，与 Trichobranchus 毛鳃虫属重名，改依词源暂定
    'Laonome': '石缨虫属',
    'Caobangia': '前肛虫属',
    'Jasmineira': '茉莉缨虫属',
    'Chone': '管缨虫属',
    'Ddialychone': '全管缨虫属',
    'Paradialychone': '拟全管缨虫属',
    'Euchone': '真管缨虫属',
    'Desdomona': '从缨虫属',
    'Parasabella': '拟缨鳃虫属',
    'Amphiglena': '双缨虫属',
    'Spirobranchus': '旋鳃虫属',
}


def main():
    tot = collections.Counter()
    for f in sorted(glob.glob(os.path.join(ZH, 'ch*.md'))):
        s = io.open(f, encoding='utf-8').read()
        # 跳过章首标题行与拉丁学名行
        lines = s.split('\n')
        seen = set()
        for i, ln in enumerate(lines):
            if i == 0 or re.match(r'^[A-Z][A-Z\s,\.]+$', ln.strip()):
                continue
            for lat, zh in GENUS.items():
                pat = r'(?<![\u4e00-\u9fff（(])\*' + re.escape(lat) + r'\*(?![\u4e00-\u9fff])'
                if lat in seen or not re.search(pat, ln):
                    continue
                seen.add(lat)
                ln = re.sub(pat, '%s *%s*' % (zh, lat), ln, count=1)
                tot[lat] += 1
            lines[i] = ln
        new = '\n'.join(lines)
        if new != s:
            io.open(f, 'w', encoding='utf-8').write(new)
    print('补中文属名 %d 处，涉及 %d 属' % (sum(tot.values()), len(tot)))
    for k, v in tot.most_common(10):
        print('  %-20s %s ×%d' % (k, GENUS[k], v))


if __name__ == '__main__':
    main()
