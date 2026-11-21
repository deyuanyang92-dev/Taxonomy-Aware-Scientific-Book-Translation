"""植入基准：qa_seed 只植入有效错误；qa_score 只按页内位置严格匹配。"""
import json

import pytest

import qa_score
import qa_seed
import auto_translate as at

N_PAGES = 12
SRC_PARA = '体長は{n} mm、体節数は約300。Exogone gemmifera Pagenstecher, 1863 は泥底に多い。'


def _page(n, paras):
    return f'<!-- PDF p.{n} | x -->\n\n' + '\n\n'.join(paras) + '\n\n'


def _t1(n):
    return (f'Body {60 + n} mm long, with about 300 chaetigers, station {n}. Prostomium rounded, anterior margin '
            f'entire. The dorsal cirri are longer than the ventral cirri. Exogone gemmifera Pagenstecher, 1863 is '
            f'common here. Errant polychaetous worms are abundant in muddy sediments.')


def _t2(n):
    return (f'Sample {n} was described from Japan and has been recorded widely. . Annelida. The setae are numerous '
            f'and slender in the median chaetigers of the posterior region. The pygidium bears two anal cirri of '
            f'equal length, upper pair larger than the lower pair.')


@pytest.fixture()
def pair():
    src = ''.join(_page(n, [SRC_PARA.format(n=60 + n), '標本' + str(n) + 'は日本産で、広く分布する。']) for n in range(1, N_PAGES + 1))
    tgt = ''.join(_page(n, [_t1(n), _t2(n)]) for n in range(1, N_PAGES + 1))
    return src, tgt


def test_seed_rejects_trivial_omissions_and_non_binomial_species(pair):
    src, tgt = pair
    for rng in range(10):
        _, seeds = qa_seed.seed(src, tgt, n_per_kind=2, rng_seed=rng)
        kinds = [s['kind'] for s in seeds]
        assert {k: kinds.count(k) for k in ('number', 'flip', 'species', 'addition', 'omission')} == \
            dict.fromkeys(('number', 'flip', 'species', 'addition', 'omission'), 2)
        assert all(s['valid'] is True for s in seeds)
        for s in seeds:
            if s['kind'] == 'omission':
                gone = s['orig']
                assert gone not in {'.', 'Annelida.'}
                assert len(gone) >= 20 and len(gone.split()) >= 3
            if s['kind'] == 'species':
                assert s['orig'] == 'Exogone gemmifera'     # 只有它在原文里真实出现
                assert 'Errant' not in s['orig']


def test_seed_is_deterministic_and_reversible(pair):
    src, tgt = pair
    a, sa = qa_seed.seed(src, tgt, n_per_kind=2, rng_seed=7)
    b, sb = qa_seed.seed(src, tgt, n_per_kind=2, rng_seed=7)
    assert (a, sa) == (b, sb)
    c, sc = qa_seed.seed(src, tgt, n_per_kind=2, rng_seed=8)
    assert sc != sa
    assert a != tgt
    back = a                                   # 逐条还原得到输入译文：别处逐字节不变
    for s in sa:
        assert back.count(s['new_para']) == 1
        back = back.replace(s['new_para'], s['old_para'])
    assert back == tgt
    for s in sa:                               # 页内位置：span 就是被改的那一段
        lo, hi = s['span']
        assert s['new_para'][lo:hi] == s['mut'] or s['kind'] == 'omission'
        if s['kind'] == 'omission':
            assert lo == hi


def _write_work(tmp_path, log=(), align=(), applied=None):
    w = tmp_path / 'work'
    w.mkdir()
    (w / 'check_log.jsonl').write_text(''.join(json.dumps(x, ensure_ascii=False) + '\n' for x in log),
                                       encoding='utf-8')
    (w / 'qa_align.json').write_text(json.dumps(list(align)), encoding='utf-8')
    if applied is not None:
        (w / 'qa_applied.jsonl').write_text(''.join(json.dumps(x, ensure_ascii=False) + '\n' for x in applied),
                                            encoding='utf-8')
    return w


def test_score_counts_only_strict_span_matches(pair, tmp_path):
    src, tgt = pair
    seeded, seeds = qa_seed.seed(src, tgt, n_per_kind=1, rng_seed=1)
    num = next(s for s in seeds if s['kind'] == 'number')
    lo, hi = num['span']
    para = num['new_para']
    fixed_old = para[max(0, lo - 5):hi + 8]
    fixed_new = num['old_para'][max(0, lo - 5):hi + 8]
    near = para[40:70]                       # 同段、离 span 不到 120 字符、但不重叠
    assert near and not (40 < hi and lo < 70)
    page = num['page']
    unseeded = next(p for p in at.pages(tgt) if p not in {s['page'] for s in seeds})
    clean_old = f'station {unseeded}' if f'station {unseeded}' in at.pages(tgt)[unseeded] else 'Prostomium rounded'
    log = [
        {'pdf_page': page, 'old': fixed_old, 'new': fixed_new, 'result': 'applied'},
        {'pdf_page': page, 'old': near, 'new': near.upper(), 'result': 'queued: 仅第二模型发现，须人工裁定'},
        {'pdf_page': unseeded, 'old': clean_old, 'new': clean_old + '!', 'result': 'applied'},
        {'pdf_page': unseeded, 'old': 'Prostomium rounded', 'new': 'x', 'result': 'rejected: 预过滤'},
    ]
    w = _write_work(tmp_path, log, align=[{'page': num['page'], 'para': num['para'], 'type': 'omitted',
                                           'quote': 'x', 'reason': 'r'}],
                    applied=[log[0], log[2]])
    r = qa_score.score(seeds, w)
    k = r['by_kind']['number']
    assert (k['n'], k['detected_any'], k['applied'], k['applied_restores']) == (1, 1, 1, 1)
    assert r['in_seeded_para_not_span']['queued'] == 1          # 宽松的 ±120 窗口会把它算成命中
    assert r['clean'] == {'applied': 1, 'queued': 0, 'rejected': 1}
    row = next(x for x in r['seeds'] if x['kind'] == 'number')
    assert row['status'] == 'applied' and row['level'] == 'span'


def test_score_align_item_matches_at_paragraph_level_only(pair, tmp_path):
    src, tgt = pair
    _, seeds = qa_seed.seed(src, tgt, n_per_kind=1, rng_seed=1)
    om = next(s for s in seeds if s['kind'] == 'omission')
    w = _write_work(tmp_path, align=[{'page': om['page'], 'para': om['para'], 'type': 'omitted',
                                      'quote': 'x', 'reason': 'r'}])
    r = qa_score.score(seeds, w)
    row = next(x for x in r['seeds'] if x['kind'] == 'omission')
    assert row['status'] == 'queued' and row['level'] == 'para' and row['sources'] == ['align']
    assert r['by_kind']['omission']['surfaced'] == 1
    assert r['by_kind']['number']['surfaced'] == 0


def test_score_rolled_back_applied_edit_counts_as_queued(pair, tmp_path):
    src, tgt = pair
    _, seeds = qa_seed.seed(src, tgt, n_per_kind=1, rng_seed=1)
    num = next(s for s in seeds if s['kind'] == 'number')
    lo, hi = num['span']
    old = num['new_para'][max(0, lo - 5):hi + 8]
    e = {'pdf_page': num['page'], 'old': old, 'new': old.replace(num['mut'], 'X'), 'result': 'applied'}
    w = _write_work(tmp_path, [e], applied=[])      # postgate 回滚：qa_applied.jsonl 里没有它
    r = qa_score.score(seeds, w)
    assert r['by_kind']['number']['applied'] == 0 and r['by_kind']['number']['queued'] == 1


def test_seed_species_rejects_english_phrase_that_appears_verbatim_in_source(tmp_path):
    """真实数据：参考文献标题里的 'Polychaetous annelids' 原样出现在原文，不是学名；属名必须是已知属。"""
    src = ''.join(_page(n, ['Imajima, M., 1982. Polychaetous annelids around Shimoda. 体長は60 mm。'
                            'Exogone gemmifera Pagenstecher, 1863 は泥底に多い。']) for n in range(1, 8))
    tgt_para = ('Imajima, M., 1982. Polychaetous annelids around Shimoda. Body 60 mm long, with many segments, '
                'station {n}. Exogone gemmifera Pagenstecher, 1863 is common in muddy bottoms of the region.')
    tgt = ''.join(_page(n, [tgt_para.format(n=n)]) for n in range(1, 8))
    for rng in range(15):
        _, seeds = qa_seed.seed(src, tgt, n_per_kind=3, rng_seed=rng)
        for s in seeds:
            if s['kind'] == 'species':
                assert s['orig'] == 'Exogone gemmifera', s['orig']


def test_seed_omission_does_not_cut_at_figure_abbreviation(pair):
    src, _ = pair
    para = ('Body 60 mm long, with about 300 chaetigers in total. Exogone gemmifera Pagenstecher (Fig. 12) is '
            'common. The dorsal cirri are longer than the ventral cirri in all specimens examined here.')
    tgt = ''.join(_page(n, [para + f' Station {n}.']) for n in range(1, 8))
    src2 = ''.join(_page(n, ['体長は60 mm。']) for n in range(1, 8))
    for rng in range(20):
        _, seeds = qa_seed.seed(src2, tgt, n_per_kind=2, rng_seed=rng)
        for s in seeds:
            if s['kind'] == 'omission':
                assert not s['orig'].rstrip().endswith('(Fig.'), s['orig']


def test_score_omission_edit_that_starts_at_the_next_sentence_is_a_span_hit(pair, tmp_path):
    """真实数据（p.224）：删除点在句间空格处，补回漏句的改动从下一句开头起（偏 1 个字符），不该判成漏检。"""
    src, tgt = pair
    _, seeds = qa_seed.seed(src, tgt, n_per_kind=1, rng_seed=1)
    om = next(s for s in seeds if s['kind'] == 'omission')
    lo = om['span'][0]
    para = om['new_para']
    assert para[lo] == ' '                                   # 点在句间空格上，下一句从 lo+1 开始
    edit = {'pdf_page': om['page'], 'old': para[lo + 1:lo + 31], 'new': 'x ' + para[lo + 1:lo + 31],
            'result': 'applied'}
    far = {'pdf_page': om['page'], 'old': para[lo + 3:lo + 33], 'new': 'y', 'result': 'applied'}
    r = qa_score.score(seeds, _write_work(tmp_path, [edit], applied=[edit]))
    assert next(x for x in r['seeds'] if x['kind'] == 'omission')['status'] == 'applied'
    (tmp_path / 'w2').mkdir()
    r2 = qa_score.score(seeds, _write_work(tmp_path / 'w2', [far], applied=[far]))   # 离删除点 ≥ 2 字符：仍不算
    assert next(x for x in r2['seeds'] if x['kind'] == 'omission')['status'] == 'missed'
