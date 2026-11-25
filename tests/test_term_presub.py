import term_presub as tp


def test_presub_longest_first_and_count():
    m = {'疣足': 'parapodia', '背疣足': 'notopodium'}
    out, n = tp.presub('背疣足と疣足', m)
    assert n == 2 and 'notopodium' in out and 'parapodia' in out


def test_presub_empty_map_noop():
    assert tp.presub('abc', {}) == ('abc', 0)


def test_learn_maps_repeating_term_and_denies():
    other = ['short', 'pale', 'thick', 'slender', 'dark']
    pairs = [(f'疣足は{o}。', f'The parapodia are {o}.') for o in other]
    rows = tp.learn(pairs, 'ja', min_count=3, min_dice=0.5)
    assert any(r['src'] == '疣足' and r['en'] == 'parapodia' for r in rows)
    assert not any(r['src'] == '疣足' for r in tp.learn(pairs, 'ja', 3, 0.5, deny={'疣足'}))


def test_align_skips_extra_paragraph_and_keeps_order():
    src = ['一 Nereis virens 12', '二 Aphrodita 34', '三 Syllis 56']
    tgt = ['One Nereis virens 12', 'Three Syllis 56']
    got = tp.align(src, tgt)
    assert (0, 0) in got and (2, 1) in got and all(i != 1 for i, _ in got)


def test_stage_draft_presub_sent_to_google(tmp_path, monkeypatch):
    import auto_translate as at
    sent: list[str] = []

    class FakeG:
        failed: list = []
        requests = 0

        def __init__(self, *a, **k):
            self.g = self

        def prefetch(self, texts, n):
            sent.extend(texts)

        def one(self, t):
            return f'EN[{t}]'
    monkeypatch.setattr(at, 'Google', FakeG)
    src = '<!-- PDF p.1 -->\n\n疣足は長く、背面に毛がある。\n'
    out = at.stage_draft(at.pages(src), tmp_path, 'ja', 'en', presub={'疣足': 'parapodia'})
    assert any('parapodia' in t for t in sent) and 'parapodia' in out[1] and '疣足' not in out[1]
