import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import auto_translate as at  # noqa: E402

SRC = """<!-- PDF p.1 | x -->

Тялото късо. 4 очи. *Exogone gemmifera* Pagenstecher, 1863.

1(2) Хоботът със зъбче …… 2. *G. limbata* Claparède

<!-- PDF p.2 | x -->

Дължина. 2—3 mm.
"""

TGT = """<!-- PDF p.1 | x -->

Body short. 4 eyes. *Exogone gemmifera* Pagenstecher, 1863.

1(2) Proboscis with a small tooth …… 2. *G. limbata* Claparède

<!-- PDF p.2 | x -->

Length. 2—3 mm.
"""


def test_pages_and_chunks():
    pg = at.pages(SRC)
    assert sorted(pg) == [1, 2]
    assert pg[2].startswith("<!-- PDF p.2")
    assert at.chunks_of({i: "" for i in range(1, 8)}, 3) == [[1, 2, 3], [4, 5, 6], [7]]


def test_pages_keeps_text_before_first_marker():
    assert at.pages("preface\n\n<!-- PDF p.5 -->\nx")[0].strip() == "preface"


def test_guard_passes_clean_translation():
    assert at.guard(SRC, TGT) == []


def test_guard_catches_lost_number_name_couplet_and_script():
    bad = TGT.replace("4 eyes", "Four eyes").replace("*G. limbata* ", "").replace("1(2)", "1.")
    bad = bad.replace("Body", "Bोdy")
    probs = " | ".join(at.guard(SRC, bad, ["setae"]))
    assert "缺数字" in probs and "缺学名" in probs and "缺检索表编号" in probs and "异常文字" in probs


def test_guard_bad_terms_and_page_mismatch():
    assert any("禁用词 setae" in p for p in at.guard(SRC, TGT.replace("eyes", "eyes setae"), ["setae"]))
    assert any("页标记" in p for p in at.guard(SRC, TGT.replace("<!-- PDF p.2 | x -->", "")))


def test_relevant_glossary_filters_and_tolerates_inflection():
    table = [("четинка", "chaeta"), ("хобот", "proboscis"), ("анални цируси", "anal cirri")]
    got = at.relevant(table, "Хоботът със зъбче. Четинките прости.")
    assert ("хобот", "proboscis") in got and ("четинка", "chaeta") in got
    assert ("анални цируси", "anal cirri") not in got


def test_load_table_markdown(tmp_path):
    f = tmp_path / "g.md"
    f.write_text("| Български | English |\n| --- | --- |\n| четинка | chaeta |\n", encoding="utf-8")
    assert at.load_table(str(f)) == [("Български", "English"), ("четинка", "chaeta")]


def test_apply_edits_rules():
    edits = [
        {"pdf_page": 1, "old": "Body short.", "new": "Body short and thin.", "reason": "ok"},
        {"pdf_page": 1, "old": "4 eyes", "new": "several eyes", "reason": "drops number"},
        {"pdf_page": 2, "old": "Length.", "new": "Length " * 40, "reason": "too long"},
        {"pdf_page": 9, "old": "x", "new": "y"},
        {"pdf_page": 1, "old": "small tooth", "new": "tooth 7", "reason": "adds number"},
    ]
    new, log = at.apply_edits(SRC, TGT, edits)
    res = [x["result"] for x in log]
    assert res[0] == "applied" and "Body short and thin." in new
    assert res[1].startswith("rejected") and "丢数字" in res[1]
    assert "过长" in res[2] and "无此页" in res[3] and "引入" in res[4]


def test_parse_json_array_tolerates_wrapping():
    assert at.parse_json_array('Here:\n```json\n[{"pdf_page": 1, "old": "a", "new": "b"}]\n```') == [
        {"pdf_page": 1, "old": "a", "new": "b"}]
    assert at.parse_json_array("no errors") is None
    assert at.parse_json_array('[{"pdf_page": 1, "old": "bad", "new":') is None
    assert at.parse_json_array("[]") == []


def test_engine_router_by_beijing_time():
    night = dt.datetime(2026, 11, 14, 15, 0, tzinfo=dt.timezone.utc)  # 23:00 北京
    day = dt.datetime(2026, 11, 14, 3, 0, tzinfo=dt.timezone.utc)  # 11:00 北京
    assert at.is_night(night) and not at.is_night(day)
    assert at.pick_engine("revise", night) == "deepseek-flash"
    assert at.pick_engine("revise", day) == "codex-luna"
    assert at.pick_engine("check", day) == "deepseek-flash"
    assert at.pick_engine("check", day, day_engine="codex-sol") == "codex-sol"


def test_pages_rejects_duplicate_marker():
    import pytest
    with pytest.raises(ValueError):
        at.pages("<!-- PDF p.1 -->\nA\n<!-- PDF p.1 -->\nB\n")


def test_apply_edits_allows_removing_surplus_number_and_blocks_new_one():
    src = "<!-- PDF p.1 -->\n4 очи.\n"
    tgt = "<!-- PDF p.1 -->\n4 eyes. 4 legs.\n"
    new, log = at.apply_edits(src, tgt, [{"pdf_page": 1, "old": "4 legs.", "new": "legs."}])
    assert log[0]["result"] == "applied"
    _, log = at.apply_edits(src, tgt, [{"pdf_page": 1, "old": "4 eyes.", "new": "4 eyes, 999 hairs."}])
    assert "引入" in log[0]["result"]


def test_guard_decimals():
    assert any("缺数字" in p for p in at.guard("<!-- PDF p.1 -->\n1,2 mm\n", "<!-- PDF p.1 -->\n1.3 mm\n"))


def test_stage_check_applies_only_verified_and_caches(tmp_path, monkeypatch):
    import argparse
    calls = []

    def fake(engine, system, user, tag, usage_file):
        calls.append(engine)
        if "/check/" in tag:
            return ('[{"pdf_page": 1, "old": "Body short.", "new": "Body short and thin."},'
                    ' {"pdf_page": 1, "old": "4 eyes", "new": "4 big eyes"}]'), {}
        return '[{"id": 0, "verdict": "ACCEPT"}, {"id": 1, "verdict": "REJECT", "why": "no"}]', {}

    monkeypatch.setattr(at, "llm", fake)
    a = argparse.Namespace(sl="bg", tl="en", glossary=None, engine="deepseek-flash", day_engine=None,
                           verify_engine="codex-sol")
    out = at.stage_check(at.pages(SRC), at.pages(TGT), tmp_path, a)
    assert "Body short and thin." in out and "big eyes" not in out
    assert calls == ["deepseek-flash", "codex-sol"]
    at.stage_check(at.pages(SRC), at.pages(TGT), tmp_path, a)  # 续跑：命中缓存，不再调用
    assert len(calls) == 2
    at.stage_check(at.pages(SRC), at.pages(TGT.replace("Length", "Size")), tmp_path, a)  # 译文变了：重新核对
    assert len(calls) == 4


def test_stage_check_parse_failure_is_not_success(tmp_path, monkeypatch):
    import argparse
    monkeypatch.setattr(at, "llm", lambda *a_, **k: ("I could not do it", {}))
    a = argparse.Namespace(sl="bg", tl="en", glossary=None, engine="deepseek-flash", day_engine=None,
                           verify_engine="codex-sol")
    at.stage_check(at.pages(SRC), at.pages(TGT), tmp_path, a)
    import json
    assert json.loads((tmp_path / "check_failed.json").read_text(encoding="utf-8"))
    assert json.loads((tmp_path / "check/c000.json").read_text(encoding="utf-8"))["status"] == "parse_failed"


def test_report_sample_with_short_pages(tmp_path):
    txt = at.report(tmp_path, at.pages(SRC), TGT)
    assert "抽检页" in txt


def test_engine_error_marks_chunk_failed_without_crash(tmp_path, monkeypatch):
    import argparse
    import json

    def boom(*a_, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(at, "llm", boom)
    monkeypatch.setattr(at.time, "sleep", lambda s: None)
    a = argparse.Namespace(sl="bg", tl="en", glossary=None, engine="deepseek-flash", day_engine=None,
                           verify_engine="codex-sol")
    out = at.stage_check(at.pages(SRC), at.pages(TGT), tmp_path, a)
    assert " ".join(out.split()) == " ".join(TGT.split())
    assert json.loads((tmp_path / "check_failed.json").read_text(encoding="utf-8"))


def test_key_structure_detects_wrong_lead():
    src = "<!-- PDF p.1 -->\n1(2) Хоботът …… 3\n2(1) Без хобот …… 2. *G. limbata*\n"
    good = "<!-- PDF p.1 -->\n1(2) Proboscis …… 3\n2(1) No proboscis …… 2. *G. limbata*\n"
    bad = good.replace("…… 3", "…… 4")
    assert not any("检索表结构" in p for p in at.guard(src, good, sl="bg"))
    assert any("检索表结构" in p for p in at.guard(src, bad, sl="bg"))


def test_residue_ignores_figure_labels_and_italics():
    tgt = "<!-- PDF p.1 -->\nPlate IV, 1а—1г; *Ph. mucosa* Тялото remains.\n"
    left = at.residue(tgt, "bg")
    assert left == ["Тялото"]
    assert at.residue("<!-- PDF p.1 -->\nKörper lang.\n", "de") == []


def test_negation_risk_generic_languages():
    src = "<!-- PDF p.1 -->\nБез хриле. Очи няма.\n<!-- PDF p.2 -->\nKeine Kiemen.\n"
    tgt = "<!-- PDF p.1 -->\nGills present. Eyes present.\n<!-- PDF p.2 -->\nNo gills.\n"
    assert at.negation_risk(src.split("<!-- PDF p.2")[0], tgt.split("<!-- PDF p.2")[0], "bg") == [1]
    assert at.negation_risk("<!-- PDF p.2 -->\nKeine Kiemen.\n", "<!-- PDF p.2 -->\nNo gills.\n", "de") == []
    assert at.negation_risk("<!-- PDF p.1 -->\n鰓を欠く。\n", "<!-- PDF p.1 -->\nGills present.\n", "ja") == [1]
    assert at.negation_risk("<!-- PDF p.1 -->\nSine branchiis.\n", "<!-- PDF p.1 -->\n有鳃。\n", "la", "zh-CN") == [1]


def test_critical_fix_goes_to_human_queue(tmp_path, monkeypatch):
    import argparse

    def fake(engine, system, user, tag, usage_file):
        if "/check/" in tag:
            return ('[{"pdf_page": 1, "old": "4 eyes", "new": "4 large eyes", "severity": "critical"},'
                    ' {"pdf_page": 1, "old": "Body short.", "new": "Body short and thin.", "severity": "minor"}]'), {}
        return '[{"id": 0, "verdict": "ACCEPT"}, {"id": 1, "verdict": "ACCEPT"}]', {}

    monkeypatch.setattr(at, "llm", fake)
    a = argparse.Namespace(sl="bg", tl="en", glossary=None, engine="deepseek-flash", day_engine=None,
                           verify_engine="codex-sol")
    out = at.stage_check(at.pages(SRC), at.pages(TGT), tmp_path, a)
    assert "Body short and thin." in out and "large eyes" not in out
    q = (tmp_path / "human_review_queue.csv").read_text(encoding="utf-8")
    assert "4 large eyes" in q and "critical" in q


def test_stage_draft_keeps_order_and_skips_markers(tmp_path, monkeypatch):
    import json as _json
    import urllib.parse

    import gtrans
    calls = []

    def http_get(url, timeout=30):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        calls.append((q["sl"][0], q["tl"][0]))
        return _json.dumps([[[f"EN<{q['q'][0]}>", "x"]]])

    monkeypatch.setattr(gtrans, "http_get", http_get)
    monkeypatch.setattr(gtrans, "_sleep", lambda s: None)
    monkeypatch.setattr(at.Path, "home", staticmethod(lambda: tmp_path))
    out = at.stage_draft(at.pages(SRC), tmp_path, "bg", "en")
    assert out[1].startswith("<!-- PDF p.1") and "EN<Тялото късо." in out[1]
    assert "EN<Дължина. 2—3 mm.>" in out[2]
    assert list(out) == [1, 2]
    assert calls and set(calls) == {("bg", "en")}
    n = len(calls)
    at.stage_draft(at.pages(SRC), tmp_path, "bg", "en")   # 重跑：全部命中缓存，不再请求
    assert len(calls) == n


def _ns(**kw):
    import argparse
    base = dict(sl="bg", tl="en", glossary=None, engine="deepseek-flash", day_engine=None, verify_engine="codex-sol")
    base.update(kw)
    return argparse.Namespace(**base)


def test_second_model_reviews_full_text_receipt_and_extras(tmp_path, monkeypatch):
    import json

    def fake(engine, system, user, tag, usage_file):
        if "/check/" in tag:
            return "[]", {}
        return ('[{"new_fix": true, "pdf_page": 1, "old": "Body short.", "new": "Body short and thin.",'
                ' "severity": "major", "reason": "missed"}, {"receipt": true, "pages": [1]}]'), {}

    monkeypatch.setattr(at, "llm", fake)
    out = at.stage_check(at.pages(SRC), at.pages(TGT), tmp_path, _ns())
    assert "Body short and thin." not in out                        # 单模型发现不自动落实
    assert "Body short and thin." in (tmp_path / "human_review_queue.csv").read_text(encoding="utf-8")
    failed = json.loads((tmp_path / "check_failed.json").read_text(encoding="utf-8"))
    assert any("回执缺页 [2]" in f for f in failed)                  # 回执只覆盖 p.1


def test_same_model_for_check_and_verify_is_refused(tmp_path, monkeypatch):
    import pytest
    monkeypatch.setattr(at, "llm", lambda *a_, **k: ("[]", {}))
    with pytest.raises(ValueError, match="异模型"):
        at.stage_check(at.pages(SRC), at.pages(TGT), tmp_path, _ns(verify_engine="deepseek-flash"))
