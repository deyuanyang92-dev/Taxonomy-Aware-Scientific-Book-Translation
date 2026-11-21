"""qa_align.stage_align：每页至多一次调用，产物只进人工队列，不改译文。"""
from __future__ import annotations

import json
from types import SimpleNamespace

import auto_translate as at
import pytest
import qa_align
import token_economy as te
from transqa import aligner as al

SRC = {1: "<!-- PDF p.1 | x -->\n\n体は細長い。背剛毛は足刺状で多数ある。", 2: "<!-- PDF p.2 | x -->\n\n体長は２mm。"}
TGT = {1: "<!-- PDF p.1 | x -->\n\nBody slender.", 2: "<!-- PDF p.2 | x -->\n\nLength 2 mm."}


def _a(**kw):
    base = dict(sl="ja", tl="en", engine="deepseek-flash", workers=2)
    base.update(kw)
    return SimpleNamespace(**base)


def _fake(calls, out_for=None):
    def fake(engine, system, user, tag, usage_file, **kw):
        calls.append(tag)
        if out_for is not None:
            return out_for(tag), {}
        return ('[{"para": 0, "type": "omitted", "quote": "背剛毛は足刺状で多数", "reason": "r"}]' if "p001" in tag
                else "[]"), {}
    return fake


def test_stage_align_one_call_per_page_and_writes_outputs(tmp_path, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(at, "llm", _fake(calls))
    items = qa_align.stage_align(SRC, TGT, tmp_path, _a())
    assert sorted(c.rsplit("/", 1)[0] for c in calls) == ["auto/align/p001", "auto/align/p002"]
    assert [(i["page"], i["type"]) for i in items] == [(1, "omitted")]
    assert json.loads((tmp_path / "qa_align.json").read_text(encoding="utf-8"))[0]["quote"] == "背剛毛は足刺状で多数"
    assert json.loads((tmp_path / "qa_align_dropped.json").read_text(encoding="utf-8")) == []
    assert json.loads((tmp_path / "qa_align_failed.json").read_text(encoding="utf-8")) == []
    assert all(c.startswith("auto/align/") for c in calls)


def test_stage_align_drops_fake_quote_into_dropped_file(tmp_path, monkeypatch):
    monkeypatch.setattr(at, "llm", _fake([], lambda tag: '[{"para": 0, "type": "omitted", "quote": "原文にない文章です", "reason": "r"}]'))
    assert qa_align.stage_align(SRC, TGT, tmp_path, _a()) == []
    d = json.loads((tmp_path / "qa_align_dropped.json").read_text(encoding="utf-8"))
    assert len(d) == 2 and d[0]["drop_reason"]


def test_stage_align_records_missing_target_page_as_failed(tmp_path, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(at, "llm", _fake(calls))
    qa_align.stage_align(SRC, {1: TGT[1]}, tmp_path, _a())
    f = json.loads((tmp_path / "qa_align_failed.json").read_text(encoding="utf-8"))
    assert {"page": 2, "reason": "missing_in_tgt"} in f and len(calls) == 1


def test_stage_align_blank_pages_are_not_called(tmp_path, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(at, "llm", _fake(calls))
    qa_align.stage_align({1: "<!-- PDF p.1 | x -->\n", 2: SRC[2]}, {1: "<!-- PDF p.1 | x -->\n", 2: "<!-- PDF p.2 | x -->\n"},
                         tmp_path, _a())
    assert calls == []
    f = json.loads((tmp_path / "qa_align_failed.json").read_text(encoding="utf-8"))
    assert f == [{"page": 2, "reason": "empty_in_tgt"}]


def test_stage_align_never_modifies_target(tmp_path, monkeypatch):
    monkeypatch.setattr(at, "llm", _fake([]))
    tgt = dict(TGT)
    qa_align.stage_align(SRC, tgt, tmp_path, _a())
    assert tgt == TGT


def test_stage_align_cache_hit_then_invalidated_by_prompt_change(tmp_path, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(at, "llm", _fake(calls))
    qa_align.stage_align(SRC, TGT, tmp_path, _a())
    assert len(calls) == 2
    qa_align.stage_align(SRC, TGT, tmp_path, _a())
    assert len(calls) == 2                                   # 命中缓存，零调用
    monkeypatch.setattr(al, "PROMPT_DIGEST", "other")
    qa_align.stage_align(SRC, TGT, tmp_path, _a())
    assert len(calls) == 4


def test_stage_align_failed_parse_is_listed(tmp_path, monkeypatch):
    monkeypatch.setattr(at, "llm", _fake([], lambda tag: "garbage" if "p002" in tag else "[]"))
    qa_align.stage_align(SRC, TGT, tmp_path, _a())
    f = json.loads((tmp_path / "qa_align_failed.json").read_text(encoding="utf-8"))
    assert f == [{"page": 2, "reason": "parse_failed"}]


def test_stage_align_budget_exceeded_propagates_and_keeps_finished_pages(tmp_path, monkeypatch):
    def out(tag):
        if "p002" in tag:
            raise te.BudgetExceeded("over")
        return '[{"para": 0, "type": "omitted", "quote": "背剛毛は足刺状で多数", "reason": "r"}]'

    monkeypatch.setattr(at, "llm", _fake([], out))
    with pytest.raises(te.BudgetExceeded):
        qa_align.stage_align(SRC, TGT, tmp_path, _a(workers=1))
    assert (tmp_path / "align" / "p001.json").exists()
    kept = json.loads((tmp_path / "qa_align.json").read_text(encoding="utf-8"))
    assert [i["page"] for i in kept] == [1]
    f = json.loads((tmp_path / "qa_align_failed.json").read_text(encoding="utf-8"))
    assert {"page": 2, "reason": "budget_exceeded"} in f
