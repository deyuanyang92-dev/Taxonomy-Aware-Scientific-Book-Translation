"""token_economy：档位、Lean、预算闸。不调真实 API。"""
import argparse

import pytest

import token_economy as te


def test_out_budget_profiles():
    assert te.out_budget("json") == 4096
    assert te.out_budget("default") == 8192
    assert te.out_budget("long") == 64000
    # revise：按 user 估，夹在 2048–16000
    n = te.out_budget("revise", "word " * 2000)
    assert 2048 <= n <= 16000


def test_system_blocks_cache_control():
    blocks = te.system_blocks("stable rules")
    assert isinstance(blocks, list)
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}
    assert blocks[0]["text"] == "stable rules"
    assert te.system_blocks("x", cache=False) == "x"


def test_apply_lean_sets_kinds_and_risky():
    a = argparse.Namespace(lean=True, rewrite_kinds="", risky_only=False)
    te.apply_lean(a)
    assert a.rewrite_kinds == te.LEAN_REWRITE_KINDS
    assert "caption" in a.rewrite_kinds.split(",")
    assert "narrative" in a.rewrite_kinds
    assert a.risky_only is True
    # 已显式设置的不覆盖
    b = argparse.Namespace(lean=True, rewrite_kinds="description", risky_only=True)
    te.apply_lean(b)
    assert b.rewrite_kinds == "description"


def test_guard_tier_release_requires_verify_and_chapters():
    te.guard_tier("draft", verify_engine="none", chaptered=False)
    te.guard_tier("release", verify_engine="codex-sol", chaptered=True)
    with pytest.raises(SystemExit, match="verify"):
        te.guard_tier("release", verify_engine="none", chaptered=True)
    with pytest.raises(SystemExit, match="章"):
        te.guard_tier("release", verify_engine="codex-sol", chaptered=False)


def test_budget_stops(monkeypatch):
    te.reset_spent(0)
    monkeypatch.setenv("YZZ_TOKEN_BUDGET", "100")
    te.record_usage({"input_tokens": 40, "output_tokens": 40, "cache_read_tokens": 0})
    assert te.spent() == 80
    with pytest.raises(te.BudgetExceeded):
        te.record_usage({"input_tokens": 30, "output_tokens": 0, "cache_read_tokens": 0})
    te.reset_spent(0)
    monkeypatch.delenv("YZZ_TOKEN_BUDGET")
