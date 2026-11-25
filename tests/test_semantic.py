"""#25：语义偏离检测（Tier1 确定性特征、Tier2 缓存与对照抽样、校准、覆盖诚实）。"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from transqa import check_all  # noqa: E402
from transqa import semantic as sem  # noqa: E402
from transqa.segments import Segment  # noqa: E402


def pair(src, tgt, page=1):
    return sem.Pair(f"p{page}_s1", page, src, tgt, "1-1")


def kinds(src, tgt):
    return {f.type for f in sem.tier1([pair(src, tgt)], "en", "zh")[0]}


GOOD = ("The jaws usually bear five teeth on each side of the pharynx, and the dorsal cirri are present "
        "on all parapodia (Hartman, 1948; Fig. 3).")
GOOD_ZH = "咽部两侧的颚通常各具五枚齿，所有疣足均具背须（Hartman, 1948；图 3）。"


def test_faithful_pair_not_flagged():
    assert kinds(GOOD, GOOD_ZH) == set()


@pytest.mark.parametrize("src,tgt,expected", [
    ("Dorsal cirri are present on all parapodia of the specimens examined here.",
     "在此检视的标本中，所有疣足均缺失背须。", "presence.flip"),
    ("The jaws usually bear five teeth on each side of the pharynx in this species.",
     "该种咽部两侧的颚总是各具五枚齿。", "frequency.shift"),
    ("The body is 5–8 mm long and bears about forty segments in the adult specimens.",
     "成体体长 5–9 mm，具约四十个体节。", "range.shift"),
    ("The gill filaments are attached to the dorsal surface of each segment in the posterior region of the body.",
     "鳃丝着生于体后部每个体节的腹面。", "direction.swap"),
    ("*Nereis pelagica* is larger than *Nereis zonata* in all samples collected from the shore.",
     "在岸边采集的所有样品中，*Nereis zonata* 大于 *Nereis pelagica*。", "taxon.swap"),
    ("The species was first described by Hartman (Hartman, 1948) from the Pacific coast of America.",
     "该种最初由 Hartman（Hartman, 1984）描述自美洲太平洋沿岸。", "citation.year"),
    ("The pharynx does not bear paragnaths on any of the areas of the proboscis in this species.",
     "该种吻的所有区域咽部均具颚齿。", "negation.drop"),
    ("The setae may be absent in some of the posterior segments of small specimens collected here.",
     "小型标本后部若干体节的刚毛缺失。", "modality.drop"),
])
def test_fluent_wrong_sentences_flagged(src, tgt, expected):
    assert expected in kinds(src, tgt)


def test_omitted_clause_in_merged_paragraph_detected():
    src = ("The prostomium is rounded, bears two pairs of eyes, and has two long palps, which are "
           "directed forwards and, although slender, are clearly visible from above in preserved specimens. "
           "The peristomium is short.")
    full = "前口叶圆形，具两对眼和两个长触手，触手向前伸出，尽管纤细，但在保存标本中从背面清晰可见。围口节短。"
    omitted = "前口叶圆形，具两对眼。围口节短。"
    assert not [f for f in sem.tier1([pair(src, full)], "en", "zh")[0] if f.type.startswith("length")]
    assert any(f.type == "length.low" for f in sem.tier1([pair(src, omitted)], "en", "zh")[0])


def test_added_claim_reported_as_addition():
    src = "The prostomium is rounded and bears two pairs of eyes in the examined specimens here."
    tgt = "前口叶圆形，具两对眼。该种在深海热液喷口亦有分布，且为该区域的优势类群，这一点已被多次证实。"
    assert "addition" in kinds(src, tgt)


def test_long_complex_correct_sentence_not_flagged():
    src = ("Although the anterior parapodia are biramous, the notopodium is reduced in the posterior "
           "region, where only a few capillary setae remain, and the neuropodium bears compound falcigers "
           "with long blades that are finely serrated.")
    tgt = "虽然前部疣足为双叶型，但后部背足退化，仅留少数毛状刚毛；腹足具复型镰刀状刚毛，刀片长，边缘具细锯齿。"
    assert kinds(src, tgt) == set()


def test_back_translation_never_creates_issue():
    f = sem.Flag("p1_s1", 1, "range.shift", "major", "r", "5–8", "5–9", "needs_verification", 1)
    out = sem.attach_back_translation(f, "length 5-9 mm")
    assert out.evidence["back_translation"] == "length 5-9 mm"
    assert sem.attach_back_translation(None, "anything") is None


def test_unknown_language_pair_capability_missing():
    fl, cov = sem.tier1([pair("Der Körper ist lang und schmal im Querschnitt hier.", "x")], "de", "zh")
    assert fl == [] and cov.capability_missing
    iss = [i for i in check_all("<!-- PDF p.1 -->\n\nHallo Welt.\n", "<!-- PDF p.1 -->\n\n你好。\n", "de", "zh",
                                semantic=True) if i.code.startswith("semantic.")]
    assert [i.code for i in iss] == ["semantic.capability_missing"]


def test_coverage_counts_checked_and_unchecked():
    pairs = [pair(GOOD, GOOD_ZH), sem.Pair("p2_s1", 2, "Short.", "短。", "1-1"),
             sem.Pair("p3_s1", 3, "Only source text here with enough words to count.", "", "src_only")]
    _, cov = sem.tier1(pairs, "en", "zh")
    assert cov.pairs_total == 3 and cov.checked == 1
    assert cov.unchecked == {"too_short": 1, "unmatched": 1}
    assert "presence.flip" in cov.rules_not_fired
    assert cov.tier2_fraction == 0.0


def test_build_pairs_1to1_and_merge_and_unmatched():
    s = [Segment("p1_s1", 1, "a"), Segment("p1_s2", 1, "b"), Segment("p2_s1", 2, "c"), Segment("p4_s1", 4, "d")]
    t = [Segment("p1_s1", 1, "A"), Segment("p2_s1", 2, "C"), Segment("p2_s2", 2, "C2"), Segment("p3_s1", 3, "E")]
    ps = {p.id: p for p in sem.build_pairs(s, t)}
    assert ps["p1_s1"].kind == "n-m" and "a" in ps["p1_s1"].src and "b" in ps["p1_s1"].src   # 合并，不静默绕过
    assert ps["p2_s1"].kind == "n-m"
    assert ps["p4_s1"].kind == "src_only" and ps["p3_s1"].kind == "tgt_only"


JUDGE_OK = json.dumps({"page": 1, "segment": "p1_s1", "src_quote": "5–8 mm", "tgt_quote": "5–9 mm",
                       "type": "mistranslation", "reason": "range", "severity": "Major",
                       "confidence": "confirmed"}, ensure_ascii=False)


def _units(n):
    return [sem.Pair(f"p{i}_s1", i, f"The body is 5–8 mm long and bears forty segments number {i}.",
                     f"体长 5–9 mm，具四十体节 {i}。", "1-1") for i in range(1, n + 1)]


def test_tier2_requires_different_engine(tmp_path):
    with pytest.raises(ValueError):
        sem.tier2(_units(1), [], translator_engine="x", reviewer_engine="x", cache_dir=tmp_path, judge=lambda s, u: "")


def test_tier2_parse_cache_budget_and_control(tmp_path):
    calls: list[str] = []

    def judge(system, user):
        calls.append(user)
        return JUDGE_OK if "number 1." in user else "NO_ISSUES"

    pairs = _units(6)
    res = sem.tier2(pairs, [pairs[0]], translator_engine="a", reviewer_engine="b", cache_dir=tmp_path,
                    judge=judge, budget=3, control=2, seed=7)
    assert len(calls) == 3 and res.reviewed == 3 and res.controls == 2 and res.failed == 0
    assert [i["segment"] for i in res.issues] == ["p1_s1"] and res.issues[0]["severity"] == "Major"
    res2 = sem.tier2(pairs, [pairs[0]], translator_engine="a", reviewer_engine="b", cache_dir=tmp_path,
                     judge=judge, budget=3, control=2, seed=7)
    assert len(calls) == 3 and res2.reused == 3 and res2.issues == res.issues     # 幂等，复用缓存


def test_tier2_parse_failure_is_failed_not_clean(tmp_path):
    p = _units(1)
    res = sem.tier2(p, p, translator_engine="a", reviewer_engine="b", cache_dir=tmp_path, judge=lambda s, u: "looks fine",
                    budget=1, control=0)
    assert res.failed == 1 and res.reviewed == 0 and res.issues == []
    # 失败不缓存：修好后能重跑
    res = sem.tier2(p, p, translator_engine="a", reviewer_engine="b", cache_dir=tmp_path, judge=lambda s, u: "NO_ISSUES",
                    budget=1, control=0)
    assert res.failed == 0 and res.reviewed == 1


def test_tier2_rejects_issue_without_quotable_evidence(tmp_path):
    bad = json.dumps({"page": 1, "segment": "p1_s1", "src_quote": "not in source", "tgt_quote": "5–9 mm",
                      "type": "x", "reason": "r", "severity": "Major", "confidence": "confirmed"})
    p = _units(1)
    res = sem.tier2(p, p, translator_engine="a", reviewer_engine="b", cache_dir=tmp_path, judge=lambda s, u: bad,
                    budget=1, control=0)
    assert res.issues == [] and res.rejected == 1


def test_calibration_injects_eight_types_and_reports(tmp_path):
    base = [pair(GOOD, GOOD_ZH, 1),
            pair("The body is 5–8 mm long and usually bears about forty segments in adult specimens of this species.",
                 "该种成体体长 5–8 mm，通常具约四十个体节，*Nereis pelagica* 大于 *Nereis zonata*（Hartman, 1948）。", 2)]
    cal = sem.calibrate(base, "en", "zh", seed=1)
    assert set(sem.INJECTION_TYPES) == {"negation_flip", "clause_omission", "hedge_removal", "range_shift",
                                        "taxon_swap", "citation_swap", "direction_swap", "added_claim"}
    assert cal["approved"] is False and cal["controls"] == 2
    for t, r in cal["per_type"].items():
        assert {"n", "recall"} <= set(r)
    assert cal["per_type"]["range_shift"]["recall"] == 1.0
    assert "ratio_lo" in cal["thresholds"]
    assert sem.gate_allowed(cal) is False
    out = tmp_path / "cal.json"
    sem.save_calibration(cal, out)
    assert json.loads(out.read_text())["approved"] is False


def test_check_all_semantic_is_triage_not_blocking():
    s = "<!-- PDF p.1 -->\n\nThe body is 5–8 mm long and bears about forty segments in the adult specimens.\n"
    t = "<!-- PDF p.1 -->\n\n成体体长 5–9 mm，具约四十个体节。\n"
    iss = [i for i in check_all(s, t, "en", "zh", semantic=True) if i.code.startswith("semantic.")]
    assert any(i.code == "semantic.range.shift" for i in iss)
    assert any(i.code == "semantic.coverage" for i in iss)
    assert not any(i.blocking for i in iss)
