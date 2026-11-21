"""qa_estimate：运行前按字符估算 + 默认开启的预算上限（#42）。不调真实 API。"""
import pytest

import qa_estimate as qa
import token_economy as te


@pytest.fixture(autouse=True)
def _clear_budget():
    te.set_budget(None)
    te.reset_spent(0)
    yield
    te.set_budget(None)
    te.reset_spent(0)


def test_estimate_counts_characters_not_bytes():
    src = {1: "あ" * 3000}
    tgt = {1: "a" * 3000}
    e = qa.estimate(src, tgt)
    assert e["chars_src"] == 3000 and e["chars_tgt"] == 3000


def test_estimate_scales_linearly_with_pages():
    # 调用按「块」（3 页一块）计，每次有固定开销：整块倍增才线性；1 页 vs 2 页同在一块里，不该翻倍
    three = {p: "あ" * 3000 for p in range(1, 4)}, {p: "a" * 3000 for p in range(1, 4)}
    six = {p: "あ" * 3000 for p in range(1, 7)}, {p: "a" * 3000 for p in range(1, 7)}
    one, two = qa.estimate(*three), qa.estimate(*six)
    assert abs(two["usd"] / one["usd"] - 2) < 0.15
    assert abs(two["billable_tokens"] / one["billable_tokens"] - 2) < 0.15


def test_estimate_lists_pages_missing_on_either_side():
    e = qa.estimate({1: "x" * 50, 2: "x" * 50}, {2: "y" * 50, 3: "y" * 50})
    assert e["pages_missing_in_tgt"] == [1] and e["pages_missing_in_src"] == [3] and e["pages"] == 1


def test_arm_budget_default_is_twice_the_estimate_and_override_wins(monkeypatch):
    monkeypatch.delenv("YZZ_TOKEN_BUDGET", raising=False)
    e = qa.estimate({1: "あ" * 3000}, {1: "a" * 3000})
    assert qa.arm_budget(e) == e["budget_tokens"] == int(e["billable_tokens"] * 2.0)
    assert qa.arm_budget(e, override_tokens=777) == 777 and te.budget_limit() == 777


def test_armed_budget_stops_the_run():
    te.set_budget(100)
    with pytest.raises(te.BudgetExceeded):
        te.record_usage({"input_tokens": 500, "output_tokens": 0, "cache_read_tokens": 0})


# 2026-11-19 的 40 页实测（日译英，两遍 check + 复核 + 对齐）。用新术语表使前缀缓存失效的「冷」跑：
# check 62,583 + verify 10,310 + align 9,412 = 82,305 billable。同数据同文本量的另外两次：
# 植入译文那次 77,157（与 cold 同时跑，缓存部分命中）、干净基线热跑 45,010（缓存全命中）。
COLD_RUN = {"billable": 82_305, "check": 62_583, "verify": 10_310, "align": 9_412}


def _pages40():
    # 每页 600 个假名 + 1848 个拉丁字符 ≈ 864 token，40 页 ≈ 实测的 34,482 token 文本量
    return {p: "あ" * 600 for p in range(1, 41)}, {p: "a" * 1848 for p in range(1, 41)}


def test_estimate_has_a_verify_stage_and_stages_sum_to_total():
    """旧估算漏掉复核阶段（实测 10k–32k billable，占总量的 13%–42%）。"""
    e = qa.estimate(*_pages40())
    assert set(e["stages"]) == {"check", "verify", "align"}
    assert all(v["billable_tokens"] > 0 and v["calls"] > 0 for v in e["stages"].values())
    assert abs(sum(v["billable_tokens"] for v in e["stages"].values()) - e["billable_tokens"]) <= 3
    assert e["calls"] == sum(v["calls"] for v in e["stages"].values())


def test_estimate_is_within_35_percent_of_the_measured_cold_run():
    e = qa.estimate(*_pages40())
    assert abs(e["billable_tokens"] / COLD_RUN["billable"] - 1) <= 0.35, e["billable_tokens"]
    for stage in ("check", "verify", "align"):       # 分阶段也不能靠相互抵消凑数
        got = e["stages"][stage]["billable_tokens"]
        assert abs(got / COLD_RUN[stage] - 1) <= 0.35, (stage, got)


def test_estimate_stays_an_upper_bound_for_the_warm_run_and_default_budget_covers_it():
    """热跑（缓存全命中）实测 45,010：估算须不低于实测，2 倍上限也须覆盖冷跑的 82,305。"""
    e = qa.estimate(*_pages40())
    assert e["billable_tokens"] >= 45_010
    assert e["budget_tokens"] >= COLD_RUN["billable"]
