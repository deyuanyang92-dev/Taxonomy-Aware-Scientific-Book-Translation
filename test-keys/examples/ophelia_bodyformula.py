#!/usr/bin/env python3
"""Ophelia 种检索表：以 Tebble 体式（Xa + Yb + Za (+ Wn)）为主干，鳃形、肛部乳突为辅。

数据：/mnt/p/粘海蛹新种-宁德合作-2026/00_学习笔记/06_物种比较总表.md（34 种 + limacina）。
体式记法：a = 无鳃刚节，b = 具鳃刚节，n = 末刚节后的无刚毛体节。文献冲突不处理，取总表首列数值。
产物：ophelia_bodyformula.ir.json → keykit make → .docx/.pdf/.report.json。
"""
import json
import sys
from pathlib import Path

D = Path(__file__).parent
sys.path.insert(0, str(D.parent))

S = {  # 终点 -> 显示文本
    'algida': '*O. algida* Maciolek & Blake, 2006',
    'multibranchia': '*O. multibranchia* Hutchings & Murray, 1984',
    'verrilli': '*O. verrilli* Riser, 1987',
    'rathkei': '*O. rathkei* McIntosh, 1908',
    'elongata': '*O. elongata* Hutchings & Murray, 1984',
    'praetiosa': '*O. praetiosa* (Kinberg, 1866)',
    'roscoffensis': '*O. roscoffensis* Augener, 1910',
    'agulhana': '*O. agulhana* Day, 1961',
    'africana': '*O. africana* Tebble, 1953',
    'pulchella': '*O. pulchella* Tebble, 1953',
    'formosa': '*O. formosa* (Kinberg, 1866)',
    'kirkegaardi': '*O. kirkegaardi* Intes & Le Loeuff, 1977',
    'bipartita': '*O. bipartita* Monro, 1936',
    'koloana': '*O. koloana* Gibbs, 1971',
    'denticulata': '*O. denticulata* Verrill, 1875',
    'neglecta': '*O. neglecta* Schneider, 1887',
    'ashworthi': '*O. ashworthi* Fauvel, 1917',
    'magna': '*O. magna* (Treadwell, 1914)',
    'borealis': '*O. borealis* Quatrefages, 1866',
    'limacina': '*O. limacina* (Rathke, 1843)',
    'assimilis': '*O. assimilis* Tebble, 1953',
    'dannevigi': '*O. dannevigi* Benham, 1916',
    'capensis': '*O. capensis* Kirkegaard, 1959',
    'bulbibranchiata': '*O. bulbibranchiata* Hartmann-Schröder & Parker, 1995',
    'celtica': '*O. celtica* Amoureux & Dauvin, 1981',
    'peresi': '*O. peresi* Bellan & Picard, 1965',
    'rullieri': '*O. rullieri* Bellan, 1975',
    'bicornis': '*O. bicornis* Savigny, 1822',
    'radiata': '*O. radiata* (Delle Chiaje, 1828)',
    'barquii': '*O. barquii* Fauvel, 1927',
    'profunda': '*O. profunda* Hartman, 1965',
    'laubieri': '*O. laubieri* Bellan & Costa, 1988',
    'anomala': '*O. anomala* Day, 1961',
    'translucens': '*O. translucens* (Katzmann, 1973)',
    'amoureuxi': '*O. amoureuxi* Bellan & Costa, 1988',
}
DN = 'dn'  # denticulata / neglecta 同体式，并列终点

T = [
 ('Branchiae absent throughout', [
   ('22–24 chaetigers', [
     ('22 chaetigers; anal funnel with 1 pair of short conical ventral lobes and a dorsal membrane bearing 5 marginal processes', 'profunda'),
     ('24 chaetigers; anal funnel with up to 10 papillae', 'laubieri')]),
   ('26–28 chaetigers', [
     ('26 chaetigers; anal funnel with 2 stout ventral papillae and 16–18 dorsal papillae', 'anomala'),
     ('About 28 chaetigers', [
       ('Anal funnel with 2 large ventromedian papillae and 6–9 rounded papillae', 'translucens'),
       ('Anal funnel with 11–19 papillae', 'amoureuxi')])])]),
 ('Branchiae present', [
   ('Branchiae from chaetiger 2, continuing to 8 chaetigers before the anus (1a + 26b + 8a = 35)', 'algida'),
   ('Branchiae beginning on chaetiger 8 or later', [
     ('Branchiae beginning on chaetiger 12 (11 anterior abranchiate chaetigers)', [
       ('11a + 12–13b + 4–5a = 28; anal funnel with 2 lanceolate ventral lobes and 13–15 papillae', 'verrilli'),
       ('11a + 9b + 4a = 24; anal funnel with 1 ventral papilla and 7–10 papillae', 'rathkei')]),
     ('Branchiae beginning on chaetiger 8–11 (7–10 anterior abranchiate chaetigers)', [
       ('Branchiae beginning on chaetiger 8 (7a + 17b + 3a + 2n = 29); anal funnel trumpet-shaped, with 10 papillae', 'multibranchia'),
       ('Branchiae beginning on chaetiger 9–11', [
         ('Branchiae beginning on chaetiger 9 (8 anterior abranchiate chaetigers)', [
           ('Anal funnel elongate, with 10 subequal papillae, without enlarged ventral pair', 'elongata'),
           ('Anal funnel with a pair of enlarged ventral papillae', [
             ('8a + 18b + 5a = 31', 'praetiosa'),
             ('8a + 23b + 1a (+ 1n) = 32–33', 'roscoffensis')])]),
         ('Branchiae beginning on chaetiger 10 or 11', [
           ('Branchiae beginning on chaetiger 10 (9 anterior abranchiate chaetigers)', [
             ('24–27 pairs of branchiae; 37–41 chaetigers', [
               ('2–3 posterior abranchiate chaetigers, followed by 1 achaetous segment', [
                 ('9a + 25b + 2a + 1n = 37; anal funnel with 2 stout conical ventral papillae and about 15 dorsal papillae', 'agulhana'),
                 ('9a + 27b + 3a + 1n = 40; anal funnel with 2 enlarged ventral and about 13 dorsal papillae', 'africana')]),
               ('5–6 posterior abranchiate chaetigers, without achaetous segment', [
                 ('9a + 24b + 5a = 38; anal funnel with 2 enlarged ventral and about 15 papillae', 'pulchella'),
                 ('9a + 26b + 6a = 41; anal funnel with 2 enlarged ventral papillae', 'formosa')])]),
             ('16–18 pairs of branchiae; 29–33 chaetigers', [
               ('16–17 pairs of branchiae', [
                 ('9a + 16b + 4–5a + 1n = 29–30; anal funnel with 2 long ventral and 12 dorsal papillae', 'kirkegaardi'),
                 ('9a + 17b + 5a = 31; anal funnel with 2 stout and 16 slender papillae', 'bipartita')]),
               ('18 pairs of branchiae', [
                 ('9a + 18b + 4a + 2n = 33; anal funnel with up to 10 papillae', 'koloana'),
                 ('9a + 18b + 5a = 32, without achaetous segments (two nominal species with identical formula)', DN)])])]),
           ('Branchiae beginning on chaetiger 11 (10 anterior abranchiate chaetigers)', [
             ('Branchiae bifid (twin filaments); anal funnel with 18–23 subequal papillae, without enlarged ventral pair; 10a + 20b + 2a = 32', 'ashworthi'),
             ('Branchiae simple, cirriform; anal funnel with enlarged ventral papillae', [
               ('20 or more pairs of branchiae; 36–46 chaetigers', [
                 ('10a + 31b + 5a = 46', 'magna'),
                 ('20–22 pairs of branchiae; 36–39 chaetigers', [
                   ('10a + 20b + 6a = 36; anal funnel with 2 ventral and 9–16 papillae of equal length', 'borealis'),
                   ('10a + 22b + 7a = 39; anal funnel with 2 ventral and 6–12 short blunt dorsal papillae', 'limacina')])]),
               ('13–19 pairs of branchiae; 29–33 chaetigers', [
                 ('19 pairs of branchiae', [
                   ('10a + 19b + 4a = 33; anal funnel with 2 enlarged ventral and about 11 subglobular papillae', 'assimilis'),
                   ('10a + 19b + 3a = 32', [
                     ('Anal funnel with 16 long slender tentacular dorsal papillae (8 each side) and 2 lanceolate ventral cirri', 'dannevigi'),
                     ('Anal funnel with 2 large ventral and 12 dorsal papillae; 4 achaetous segments behind last chaetiger', 'capensis')])]),
                 ('13–17 pairs of branchiae', [
                   ('Branchiae with swollen (bulbous) base; 10a + 15b + 5a = 30; anal funnel with 2 large ventral and 7–9 small papillae', 'bulbibranchiata'),
                   ('Branchiae not swollen basally', [
                     ('Achaetous segments present behind last chaetiger', [
                       ('10a + 16b + 3a + 1n = 30; anal funnel with 2 large ventral and 12 small dorsal papillae', 'celtica'),
                       ('10a + 15b + 4a + 3n = 32; anal funnel with 2 ventral and 12 papillae', 'peresi')]),
                     ('No achaetous segments behind last chaetiger; 32 chaetigers', [
                       ('10a + 17b + 5a = 32', 'rullieri'),
                       ('13–15 pairs of branchiae; 7–9 posterior abranchiate chaetigers', [
                         ('10a + 15b + 7a = 32', 'bicornis'),
                         ('13–14 pairs of branchiae; 8–9 posterior abranchiate chaetigers', [
                           ('10a + 14b + 8a = 32', 'radiata'),
                           ('10a + 13b + 9a = 32', 'barquii')])])])])])])])])])])])])]),
]


def disp(t: str) -> str:
    return '*O. denticulata* / *O. neglecta*' if t == DN else S[t]


def to_ir(tree):
    cps = []
    def walk(node, back):
        num = len(cps) + 1
        cp = {'num': num, 'backref': back, 'leads': []}
        cps.append(cp)
        for text, child in node:
            if isinstance(child, str):
                cp['leads'].append({'text': text, 'kind': 'taxon', 'target': disp(child), 'page': None, 'fig': '', 'name_zh': ''})
            else:
                lead = {'text': text, 'kind': 'jump', 'target': '', 'page': None, 'fig': '', 'name_zh': ''}
                cp['leads'].append(lead)
                lead['target'] = str(walk(child, num))
        return num
    walk(tree, None)
    return cps


def terminals(node):
    for _t, c in node:
        yield from ([c] if isinstance(c, str) else terminals(c))


if __name__ == '__main__':
    got = [x for x in terminals(T)]
    flat = [y for x in got for y in (['denticulata', 'neglecta'] if x == DN else [x])]
    assert sorted(flat) == sorted(S), set(S) ^ set(flat)
    assert len(flat) == len(set(flat)), 'species twice'
    assert all(len(n) == 2 for n in [T]), 'non-binary root'
    cps = to_ir(T)
    assert all(len(c['leads']) == 2 for c in cps), 'non-binary couplet'
    title = ('Key to species of *Ophelia* based on body formula (Tebble 1953): '
             'a = abranchiate chaetiger, b = branchiate chaetiger, n = achaetous segment; counts for mature specimens')
    ir = {'keys': [{'heading': title, 'couplets': cps, 'lang': 'en', 'source_style': 'dash'}]}
    p = D / 'ophelia_bodyformula'
    Path(str(p) + '.ir.json').write_text(json.dumps(ir, ensure_ascii=False, indent=1), 'utf-8')
    print('species', len(flat), 'couplets', len(cps))
    from keykit.__main__ import main
    sys.exit(main(['make', str(p) + '.ir.json', '-o', str(p) + '.docx', '--lang', 'en', '--source-style', 'dash']))
