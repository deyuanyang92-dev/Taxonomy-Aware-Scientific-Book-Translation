"""一本书的人民币预算闸：默认 ¥2；按该书 usage.tsv 累计（跨续跑）；调用前预留最坏情况；未定价引擎不放行。
全部 mock，不真调 API。"""
import pytest

import llm_engines as le
import token_economy as te

PRICE_IN, PRICE_OUT, PRICE_CACHE = te.DS_PRICE['in'], te.DS_PRICE['out'], te.DS_PRICE['cache']


def _usage(path, *rows):
    """rows: (engine, 输入token, 输出token, 缓存读token)。"""
    with open(path, 'w', encoding='utf8') as f:
        f.write(le.USAGE_HEADER)
        for eng, i, o, c in rows:
            f.write(f'2026-11-20 10:00:00\t{eng}\tauto/revise/c000/0\t{i}\t{o}\t{c}\t1.0\n')


@pytest.fixture()
def book(tmp_path, monkeypatch):
    monkeypatch.setenv('LLM_SKIP_OFFPEAK', '1')
    monkeypatch.delenv('YZZ_BUDGET_CNY', raising=False)
    monkeypatch.setenv('YZZ_USD_CNY', '7.2')
    return tmp_path / 'usage.tsv'


def _fake_deepseek(monkeypatch, calls, usage=None):
    def fake(engine, system, user, max_tokens, check_window=False):
        calls.append((engine, max_tokens))
        return 'ok', usage or {'input_tokens': 100, 'output_tokens': 50, 'cache_read_tokens': 0}
    monkeypatch.setattr(le, '_deepseek', fake)


def test_cost_cny_follows_published_deepseek_flash_price(monkeypatch):
    monkeypatch.setenv('YZZ_USD_CNY', '7.2')
    got = te.cost_cny('deepseek-flash', 1_000_000, 1_000_000, 1_000_000)
    assert got == pytest.approx((PRICE_IN + PRICE_OUT + PRICE_CACHE) * 7.2)


def test_cost_cny_is_none_for_unpriced_engines():
    for eng in ('claude-sonnet', 'codex', 'deepseek-v4-pro'):
        assert te.cost_cny(eng, 10, 10, 0) is None


def test_default_cap_is_two_yuan_and_env_overrides(monkeypatch):
    monkeypatch.delenv('YZZ_BUDGET_CNY', raising=False)
    assert te.budget_cny() == 2.0
    monkeypatch.setenv('YZZ_BUDGET_CNY', '0.5')
    assert te.budget_cny() == 0.5
    monkeypatch.setenv('YZZ_BUDGET_CNY', 'off')
    assert te.budget_cny() is None
    monkeypatch.setenv('YZZ_BUDGET_CNY', 'abc')
    with pytest.raises(ValueError):
        te.budget_cny()


def test_spent_cny_sums_the_books_usage_file_across_runs(book):
    _usage(book, ('deepseek-flash', 1_000_000, 0, 0), ('deepseek-flash', 0, 1_000_000, 0))
    assert te.spent_cny(book) == pytest.approx((PRICE_IN + PRICE_OUT) * 7.2)
    assert te.spent_cny(book.parent / 'missing.tsv') == 0.0


def test_call_refuses_before_any_request_when_book_is_already_at_cap(book, monkeypatch):
    _usage(book, ('deepseek-flash', 0, 3_000_000, 0))          # ≈ ¥12.96
    calls = []
    _fake_deepseek(monkeypatch, calls)
    with pytest.raises(te.BudgetExceeded, match='¥2'):
        le.call('deepseek-flash', 'sys', 'user', usage_file=book)
    assert calls == []


def test_call_under_cap_runs_and_logs(book, monkeypatch):
    calls = []
    _fake_deepseek(monkeypatch, calls)
    text, _ = le.call('deepseek-flash', 'sys', 'user', usage_file=book)
    assert text == 'ok' and len(calls) == 1
    assert te.spent_cny(book) > 0


def test_worst_case_reservation_stops_a_call_that_could_overshoot(book, monkeypatch):
    # 已花约 ¥1.99；这次请求即使只实际花几厘，最坏情况（输出打满 max_tokens）也会越过 ¥2 → 不发
    out = int((1.99 / 7.2) / PRICE_OUT * 1e6)
    _usage(book, ('deepseek-flash', 0, out, 0))
    calls = []
    _fake_deepseek(monkeypatch, calls)
    with pytest.raises(te.BudgetExceeded):
        le.call('deepseek-flash', 'sys', 'user', usage_file=book, max_tokens=8192)
    assert calls == []


def test_concurrent_reservations_cannot_jointly_exceed_cap(book):
    te.reserve_cny(book, 1.2, 2.0)
    with pytest.raises(te.BudgetExceeded):
        te.reserve_cny(book, 1.2, 2.0)             # 并行第二个：1.2+1.2 > 2.0
    te.release_cny(book, 1.2)
    te.reserve_cny(book, 1.2, 2.0)                 # 释放后可再预留
    te.release_cny(book, 1.2)


def test_reservation_is_released_even_if_the_request_fails(book, monkeypatch):
    def boom(*a, **k):
        raise le.EngineError('网络断')
    monkeypatch.setattr(le, '_deepseek', boom)
    for _ in range(5):                              # 若失败不释放，5 次预留早就把 ¥2 占满
        with pytest.raises(le.EngineError):
            le.call('deepseek-flash', 'sys', 'user', usage_file=book)


def test_unpriced_engine_is_refused_under_cap_but_allowed_when_off(book, monkeypatch):
    monkeypatch.setattr(le, '_claude', lambda *a, **k: ('ok', {'input_tokens': None, 'output_tokens': None,
                                                              'cache_read_tokens': None}))
    with pytest.raises(te.BudgetExceeded, match='没有人民币单价'):
        le.call('claude-sonnet', 'sys', 'user', usage_file=book)
    monkeypatch.setenv('YZZ_BUDGET_CNY', 'off')
    assert le.call('claude-sonnet', 'sys', 'user', usage_file=book)[0] == 'ok'


def test_auto_translate_default_makes_zero_model_calls(tmp_path, monkeypatch, capsys):
    """不写 --engine：只走 Google 初稿 + 术语表 + 确定性脚本，一次模型也不调（模型只在显式开启时用）。"""
    import auto_translate as at
    src = tmp_path / 'src.md'
    src.write_text('<!-- PDF p.1 | x -->\n\n体長は60 mm。Exogone gemmifera Pagenstecher, 1863 は泥底に多い。\n\n', encoding='utf-8')
    draft = '<!-- PDF p.1 | x -->\n\nBody length 60 mm. Exogone gemmifera Pagenstecher, 1863 is common in muddy bottoms.\n\n'
    monkeypatch.setattr(at, 'stage_draft', lambda *a, **k: at.pages(draft))

    def no_model(*a, **k):
        raise AssertionError('默认流程不该调模型')
    monkeypatch.setattr(le, 'call', no_model)
    at.main(['run', str(src), '-o', str(tmp_path / 'w'), '--sl', 'ja', '--tl', 'en', '--no-memory', '--no-entities'])
    assert 'engine=\'none\'' in capsys.readouterr().out
