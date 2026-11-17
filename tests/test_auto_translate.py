import datetime as dt
import json
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
    night = dt.datetime(2026, 11, 16, 17, 0, tzinfo=dt.timezone.utc)  # 周二 01:00 北京（折扣时段）
    day = dt.datetime(2026, 11, 16, 3, 0, tzinfo=dt.timezone.utc)  # 周一 11:00 北京（官方忙时）
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

    def fake(engine, system, user, tag, usage_file, **kwargs):
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

    def fake(engine, system, user, tag, usage_file, **kwargs):
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

    def fake(engine, system, user, tag, usage_file, **kwargs):
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


def test_same_model_allowed_with_explicit_flag(tmp_path, monkeypatch):
    """用户 2026-11-17：只在 DeepSeek 折扣窗口跑，第二模型也用 deepseek-flash。"""
    monkeypatch.setattr(at, "llm", lambda *a_, **k: ("[]", {}))
    out = at.stage_check(at.pages(SRC), at.pages(TGT), tmp_path,
                         _ns(verify_engine="deepseek-flash", allow_same_verify=True))
    assert "Body short." in out


SRC2 = """<!-- PDF p.1 -->

Тялото късо. 4 очи.

*Ph. tuberculata* Bobretzky, 1868, стр. 15; Зернов, 1913, стр. 220

<!-- PDF p.2 -->

Дължина 2—3 mm.

<!-- PDF p.3 -->

Цвят белезникав.

<!-- PDF p.4 -->

Без хриле.
"""


def test_stage_revise_ids_protected_blocks_stable_prefix_and_resume(tmp_path, monkeypatch):
    import argparse
    import re as _re
    g = tmp_path / "g.tsv"
    g.write_text("хриле\tgills\nчетинка\tchaeta\n", encoding="utf-8")
    nm = tmp_path / "n.tsv"
    nm.write_text("Зернов\tZernov\n", encoding="utf-8")
    calls = []

    def fake(engine, system, user, tag, usage_file, **kwargs):
        calls.append((tag, system, user))
        ids = _re.findall(r"⟦(p\d+_s\d+)⟧", user)
        en = {"p1_s1": "Body short. 4 eyes.", "p2_s1": "Length 2—3 mm.", "p3_s1": "Colour whitish.",
              "p4_s1": "Gills absent."}
        if tag.endswith("/0") and "p2_s1" in ids:      # 第一次漏掉一个 ID → 须重试
            ids = [i for i in ids if i != "p2_s1"]
        return "\n".join(f"⟦{i}⟧\n{en[i]}" for i in ids), {}

    monkeypatch.setattr(at, "llm", fake)
    a = argparse.Namespace(sl="bg", tl="en", glossary=str(g), names=str(nm), bad_terms="", engine="deepseek-flash",
                           day_engine=None, abbr=None, entities=False)
    src_pg = at.pages(SRC2)
    out = at.stage_revise(src_pg, src_pg, tmp_path, a)       # 初稿=原文即可
    assert "*Ph. tuberculata* Bobretzky, 1868, p. 15; Zernov, 1913, p. 220" in out   # 确定性处理
    assert all("Bobretzky" not in u for _, _, u in calls)                           # 异名录没送模型
    assert len({s for _, s, _ in calls}) == 1 and "chaeta" in calls[0][1]           # system 全书一致、含全书术语
    assert any(t.endswith("c000/1") for t, _, _ in calls)                           # 漏 ID 触发重试
    assert "Length 2—3 mm." in out and "Gills absent." in out
    n = len(calls)
    at.stage_revise(src_pg, src_pg, tmp_path, a)                                    # 续跑命中缓存
    assert len(calls) == n


def test_repair_draft_pages_rebuilds_only_mismatched_pages(tmp_path, monkeypatch):
    import argparse

    class FakeGoogle:
        def __init__(self, *args, **kwargs):
            pass

        def one(self, text):
            return "EN:" + text

    monkeypatch.setattr(at, "Google", FakeGoogle)
    a = argparse.Namespace(sl="bg", tl="en")
    src = at.pages("<!-- PDF p.1 -->\n\nПърви.\n\nВтори.\n\n<!-- PDF p.2 -->\n\nТрети.\n")
    draft = at.pages("<!-- PDF p.1 -->\n\nFirst.\n\n<!-- PDF p.2 -->\n\nThird.\n")
    assert at.repair_draft_pages(src, draft, [1, 2], tmp_path, a) == [1]
    assert len(at.segments_from_pages(draft[1])) == 2
    assert len(at.segments_from_pages(draft[2])) == 1       # 正常页不动
    assert (tmp_path / "draft.md").exists()


def test_stage_draft_does_not_send_synonymy_to_google(tmp_path, monkeypatch):
    import json as _json
    import urllib.parse

    import gtrans
    sent = []

    def http_get(url, timeout=30):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["q"][0]
        sent.append(q)
        return _json.dumps([[[f"EN<{q}>", "x"]]])

    monkeypatch.setattr(gtrans, "http_get", http_get)
    monkeypatch.setattr(gtrans, "_sleep", lambda s: None)
    monkeypatch.setattr(at.Path, "home", staticmethod(lambda: tmp_path))
    out = at.stage_draft(at.pages(SRC2), tmp_path, "bg", "en")
    assert all("Bobretzky" not in q for q in sent) and "Bobretzky, 1868, стр. 15" in out[1]


def test_whole_keeps_page_markers_on_own_lines():
    pg = at.pages("<!-- PDF p.1 -->\nA\n<!-- PDF p.2 -->\nB")
    assert sorted(at.pages(at.whole(pg))) == [1, 2]


def test_parse_segments_reports_duplicates():
    got, dups = at.parse_segments("⟦p1_s1⟧\nA\n⟦p1_s2⟧\nB\n⟦p1_s1⟧\nC")
    assert got == {"p1_s1": "A", "p1_s2": "B"} and dups == ["p1_s1"]


def test_tier0_engine_none_uses_draft_plus_local_terms(tmp_path, monkeypatch):
    import argparse
    g = tmp_path / "g.tsv"
    g.write_text("очи\teyes\tpeepers=eyes\n", encoding="utf-8")
    monkeypatch.setattr(at, "llm", lambda *a_, **k: (_ for _ in ()).throw(AssertionError("no LLM in tier 0")))
    a = argparse.Namespace(sl="bg", tl="en", glossary=str(g), names=None, bad_terms="", engine="none",
                           day_engine=None, abbr=None, entities=False)
    src = at.pages("<!-- PDF p.1 -->\n\nТялото късо. 4 очи.\n")
    draft = at.pages("<!-- PDF p.1 -->\n\nBody short. 4 peepers.\n")
    out = at.stage_revise(src, draft, tmp_path, a)
    assert "4 eyes." in out


def test_engine_none_skips_entity_llm_even_if_entities_on(tmp_path, monkeypatch):
    """零模型档不得因专名抽取暗调 deepseek（曾导致 anthropic 缺失时卡 3 次×30s）。"""
    import argparse
    monkeypatch.setattr(at, "llm", lambda *a_, **k: (_ for _ in ()).throw(AssertionError("no LLM")))
    a = argparse.Namespace(sl="de", tl="en", engine="none", entities=True, domain="分类学")
    assert at.chunk_entities("Prostomium mit 4 Augen.", "c000", tmp_path, a) == []


def test_engine_none_full_pipeline_never_calls_llm(tmp_path, monkeypatch):
    """draft→revise→check 全程 --engine none 时 llm() 一次都不得调用。"""
    import argparse
    calls = []

    def boom(*a_, **k):
        calls.append((a_, k))
        raise AssertionError(f"unexpected LLM: {a_[:1]}")

    monkeypatch.setattr(at, "llm", boom)
    g = tmp_path / "g.tsv"
    g.write_text("source\ttarget\tvariants\tnote\nAugen\teyes\t\t\n", encoding="utf-8")
    a = argparse.Namespace(
        sl="de", tl="en", glossary=str(g), names=None, bad_terms="", engine="none",
        day_engine=None, abbr=None, entities=True, lean=True, rewrite_kinds="narrative,remarks,caption",
        risky_only=True, verify_engine="none", verify_mode="review", workers=1, pitfalls=None,
        domain="分类学", allow_same_verify=False,
    )
    from token_economy import apply_lean
    apply_lean(a)
    src = at.pages(
        "<!-- PDF p.1 -->\nProstomium mit 4 Augen.\n\n"
        "Bemerkung. Die Art ist neu.\n"
    )
    draft = at.pages(
        "<!-- PDF p.1 -->\nProstomium with 4 peepers.\n\n"
        "Remark. The species is new.\n"
    )
    revised = at.stage_revise(src, draft, tmp_path, a)
    assert "eyes" in revised.lower() or "peepers" in revised  # 术语表或保留稿
    checked = at.stage_check(src, at.pages(revised), tmp_path, a)
    assert "<!-- PDF p.1 -->" in checked
    assert calls == []
    stats = json.loads((tmp_path / "revise_stats.json").read_text(encoding="utf-8"))
    assert stats.get("llm_calls", 0) == 0
    assert stats.get("sent_to_model", 0) == 0


def test_prefilter_drops_edits_whose_old_is_not_on_page_before_verify(tmp_path, monkeypatch):
    sent = []

    def fake(engine, system, user, tag, usage_file, **kwargs):
        if "/check/" in tag:
            return ('[{"pdf_page": 1, "old": "Body short.", "new": "Body short and thin."},'
                    ' {"pdf_page": 1, "old": "not in text", "new": "x"},'
                    ' {"pdf_page": 2, "old": "Body short.", "new": "y"}]'), {}
        sent.append(user)
        return '[{"id": 0, "verdict": "ACCEPT"}, {"receipt": true, "pages": [1, 2]}]', {}

    monkeypatch.setattr(at, "llm", fake)
    out = at.stage_check(at.pages(SRC), at.pages(TGT), tmp_path, _ns())
    assert "Body short and thin." in out
    assert "not in text" not in sent[0] and '"id": 2' not in sent[0]   # 预过滤掉的不送复核
    log = (tmp_path / "check_log.jsonl").read_text(encoding="utf-8")
    assert log.count("预过滤") == 2


def test_parallel_check_keeps_chunk_order(tmp_path, monkeypatch):
    import time as _t
    src = "".join(f"<!-- PDF p.{i} | x -->\n\nТекст {i}.\n\n" for i in range(1, 10))
    tgt = "".join(f"<!-- PDF p.{i} | x -->\n\nText {i}.\n\n" for i in range(1, 10))

    def fake(engine, system, user, tag, usage_file, **kwargs):
        _t.sleep(0.05 if "c000" in tag else 0)     # 第一块最慢：并行时最后返回
        if "/check/" in tag:
            return "[]", {}
        pg = [int(x) for x in __import__("re").findall(r"PDF p\.(\d+)", user)]
        return '[{"receipt": true, "pages": %s}]' % sorted(set(pg)), {}

    monkeypatch.setattr(at, "llm", fake)
    monkeypatch.setattr(at, "CHUNK_PAGES", 3)
    out = at.stage_check(at.pages(src), at.pages(tgt), tmp_path, _ns(workers=3))
    assert [int(p) for p in __import__("re").findall(r"PDF p\.(\d+)", out)] == list(range(1, 10))


def test_pitfalls_loaded_into_both_prompts(tmp_path, monkeypatch):
    systems = []
    pf = tmp_path / "pf.md"
    pf.write_text("- PROJECT-TRAP: foo = bar", encoding="utf-8")

    def fake(engine, system, user, tag, usage_file, **kwargs):
        systems.append(system)
        return ("[]" if "/check/" in tag else '[{"receipt": true, "pages": [1, 2]}]'), {}

    monkeypatch.setattr(at, "llm", fake)
    at.stage_check(at.pages(SRC), at.pages(TGT), tmp_path, _ns(pitfalls=str(pf)))
    assert all("PROJECT-TRAP" in s for s in systems) and len(systems) == 2
    assert all("чифт" in s for s in systems)                       # 语言对默认陷阱表 skill/pitfalls/bg-en.md


def test_fit_old_tolerates_quote_style_and_whitespace():
    seg = "the so-called “the edge of constant warming”  zone"
    assert at.fit_old(seg, '"the edge of constant warming" zone') == "“the edge of constant warming”  zone"
    assert at.fit_old(seg, "absent text") is None


def test_check_cache_depends_on_engine(tmp_path, monkeypatch):
    calls = []

    def fake(engine, system, user, tag, usage_file, **kwargs):
        calls.append(engine)
        return ("[]" if "/check/" in tag else '[{"receipt": true, "pages": [1, 2]}]'), {}

    monkeypatch.setattr(at, "llm", fake)
    at.stage_check(at.pages(SRC), at.pages(TGT), tmp_path, _ns(engine="codex-luna"))
    at.stage_check(at.pages(SRC), at.pages(TGT), tmp_path, _ns(engine="deepseek-flash"))
    assert calls.count("codex-luna") == 1 and calls.count("deepseek-flash") == 1   # 换找错模型：不复用旧结果


def test_judge_mode_narrow_verdicts_unsure_to_human(tmp_path, monkeypatch):
    systems = {}

    def fake(engine, system, user, tag, usage_file, **kwargs):
        systems[tag.split("/")[1]] = system
        if "/check/" in tag:
            return ('[{"pdf_page": 1, "old": "Body short.", "new": "Body short and thin."},'
                    ' {"pdf_page": 1, "old": "4 eyes", "new": "four eyes"},'
                    ' {"receipt": true, "pages": [1, 2]}]'), {}
        return ('[{"id": 0, "quote": "Тялото късо", "key": "късо = short", "old_faithful": false,'
                ' "new_faithful": true}, {"id": 1, "quote": "4 очи", "old_faithful": null, "new_faithful": null}]'), {}

    monkeypatch.setattr(at, "llm", fake)
    out = at.stage_check(at.pages(SRC), at.pages(TGT), tmp_path, _ns(verify_mode="judge", engine="codex-sol",
                                                                    verify_engine="codex-luna"))
    assert "Body short and thin." in out and "four eyes" not in out
    assert "four eyes" in (tmp_path / "human_review_queue.csv").read_text(encoding="utf-8")
    assert "do NOT search for new" in systems["verify"]
    assert (tmp_path / "check_failed.json").read_text(encoding="utf-8").strip() == "[]"


def test_judge_verdict_is_derived_by_script():
    src = "Дорзалните четинки са винаги прости, а вентралните — прости и сложни."
    q = "вентралните — прости и сложни"
    assert at.judge_verdict({"quote": q, "old_faithful": False, "new_faithful": True}, src) == "ACCEPT"
    assert at.judge_verdict({"quote": q, "old_faithful": True, "new_faithful": True}, src) == "REJECT"
    assert at.judge_verdict({"quote": q, "old_faithful": False, "new_faithful": False}, src) == "UNSURE"
    assert at.judge_verdict({"quote": "не е в оригинала", "old_faithful": False, "new_faithful": True}, src) == "UNSURE"


def test_risky_filter_numbers_clean_description_and_stats():
    src = {1: '<!-- PDF p.1 -->\n\nProstomium mit 4 Augen.\n\nProstomium mit Palpen.',
           2: '<!-- PDF p.2 -->\n\nProstomium mit Palpen.'}
    tgt = {1: '<!-- PDF p.1 -->\n\nProstomium with 2 eyes.\n\nProstomium with palps.',
           2: '<!-- PDF p.2 -->\n\nProstomium with palps.'}
    s, t, stats = at.risky_filter(src, tgt, 'de', 'en')
    assert list(s) == list(t) == [1]
    assert '4 Augen' in s[1] and '2 eyes' in t[1]
    assert 'Palpen' not in s[1] and 'palps' not in t[1]
    assert stats == dict(pages_in=2, pages_kept=1, paras_in=3, paras_kept=1,
                         chars_in=len('Prostomium mit 4 Augen.') + 2 * len('Prostomium mit Palpen.'),
                         chars_kept=len('Prostomium mit 4 Augen.'), by_reason={'number': 1})


def test_risky_filter_clean_narrative_kept():
    src, tgt = {1: 'Das Tier ist klein.'}, {1: 'The animal is small.'}
    assert at.taxoblocks.risk(src[1], tgt[1], 'de', 'en') == []
    assert at.taxoblocks.kind(src[1], 'de') == 'narrative'
    s, t, stats = at.risky_filter(src, tgt, 'de', 'en')
    assert s == src and t == tgt
    assert stats['paras_kept'] == 1 and not stats['by_reason']


def test_risky_filter_count_mismatch_keeps_whole_page():
    src = {1: '<!-- PDF p.1 -->\n\nProstomium mit Palpen.\n\nProstomium mit Augen.'}
    tgt = {1: '<!-- PDF p.1 -->\n\nProstomium with palps and eyes.'}
    s, t, stats = at.risky_filter(src, tgt, 'de', 'en')
    assert s == src and t == tgt
    assert stats['paras_in'] == stats['paras_kept'] == 2
    assert stats['chars_in'] == stats['chars_kept']


def test_risky_filter_term_and_rewritten_signals():
    src, tgt = {1: 'Prostomium mit Borsten.'}, {1: 'Prostomium with bristles.'}
    s, t, stats = at.risky_filter(src, tgt, 'de', 'en', terms=[('Borsten', 'setae')])
    assert s == src and t == tgt and stats['by_reason']['term'] == 1
    _, _, stats = at.risky_filter(src, tgt, 'de', 'en', rewritten_pages={1})
    assert stats['by_reason']['rewritten'] == 1


def test_risky_check_preserves_full_output_and_separates_caches(tmp_path, monkeypatch, capsys):
    calls = []
    src = {1: '<!-- PDF p.1 -->\n\nProstomium mit 4 Augen.\n\nProstomium mit Palpen.',
           2: '<!-- PDF p.2 -->\n\nProstomium mit Palpen.'}
    tgt = {1: '<!-- PDF p.1 -->\n\nProstomium with 2 eyes.\n\nProstomium with palps.',
           2: '<!-- PDF p.2 -->\n\nProstomium with palps.'}

    def fake(engine, system, user, tag, usage_file, **kwargs):
        calls.append(user)
        return ('[{"pdf_page": 1, "old": "2 eyes", "new": "4 eyes"}]' if '/check/' in tag else
                '[{"id": 0, "verdict": "ACCEPT"}, {"receipt": true, "pages": [1, 2]}]'), {}

    monkeypatch.setattr(at, 'llm', fake)
    a = _ns(sl='de', risky_only=True)
    out = at.stage_check(src, tgt, tmp_path, a)
    assert '4 eyes' in out and '2 eyes' not in out
    assert at.pages(out)[2].strip() == tgt[2]
    assert out.count('Prostomium with palps.') == 2
    assert all('palps' not in user and 'Palpen' not in user for user in calls)
    assert 'risky-only kept 1/3 paragraphs' in capsys.readouterr().out
    at.stage_check(src, tgt, tmp_path, a)
    assert len(calls) == 2
    at.stage_check(src, tgt, tmp_path, _ns(sl='de', risky_only=False))
    assert len(calls) == 4


def test_risky_check_empty_selection_skips_models(tmp_path, monkeypatch):
    monkeypatch.setattr(at, 'llm', lambda *args: (_ for _ in ()).throw(AssertionError('no LLM')))
    src = {1: '<!-- PDF p.1 -->\n\nProstomium mit Palpen.'}
    tgt = {1: '<!-- PDF p.1 -->\n\nProstomium with palps.'}
    assert at.pages(at.stage_check(src, tgt, tmp_path, _ns(sl='de', risky_only=True)))[1].strip() == tgt[1]
