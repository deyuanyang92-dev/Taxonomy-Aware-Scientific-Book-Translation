"""#23：中文目标文本术语感知错字检测与受保护 apply。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import apply_issues as ai  # noqa: E402
from transqa import check_all, zh_typo  # noqa: E402


def rules(text, **kw):
    return {f.rule for f in zh_typo.scan(text, **kw)}


def test_u3000_flagged_and_removed():
    t = "多毛类　环节动物"
    assert "zh.u3000" in rules(t)
    assert zh_typo.fix_mechanical(t)[0] == "多毛类环节动物"


def test_fullwidth_latin_digits_in_chinese_prose():
    t = "体长约１９ｍｍ的Ａ型"
    new, fs = zh_typo.fix_mechanical(t)
    assert new == "体长约19mm的A型" and any(f.rule == "zh.fullwidth_alnum" for f in fs)


def test_halfwidth_period_before_closing_quote_is_punct_not_typo():
    t = "他说：“样本很好.”"
    fs = zh_typo.scan(t)
    assert [f.rule for f in fs] == ["zh.punct_halfwidth"]
    assert zh_typo.fix_mechanical(t)[0] == "他说：“样本很好。”"


def test_duplicates_never_legit_vs_reduplication_allowlist():
    assert zh_typo.fix_mechanical("这是的的错误，，然后。。")[0] == "这是的错误，然后。"
    for ok in ("常常", "渐渐", "个个", "人人", "谢谢"):
        assert zh_typo.scan(f"他{ok}来") == []


def test_stray_space_before_punct():
    assert zh_typo.fix_mechanical("刚毛 ，疣足")[0] == "刚毛，疣足"


def test_unpaired_suppressed_when_source_unbalanced():
    from transqa.segments import Segment
    src = [Segment("s1", 1, "neu beschrieben‘)"), Segment("s2", 1, "ok (a)")]
    tgt = [Segment("s1", 1, "再次描述物种）。"), Segment("s2", 1, "好（甲。")]
    rules = [i.code for i in zh_typo.check(src, tgt, {"tl": "zh"})]
    assert rules.count("zh_typo.zh.unpaired") == 1   # 只剩 s2：原文平衡而译文不成对


def test_halfwidth_parens_fixed_but_latin_kept():
    out, ap = zh_typo.fix_mechanical("疣足(2对 触须)，Typosyllis anoculata (Hartmann, 1962)。")
    assert out.startswith("疣足（2对 触须）") and "(Hartmann, 1962)" in out and len(ap) == 1


def test_unpaired_quotes_review_only():
    fs = zh_typo.scan("他说“样本很好。")
    assert [f.rule for f in fs] == ["zh.unpaired"] and fs[0].kind == "review"
    assert zh_typo.fix_mechanical("他说“样本很好。")[0] == "他说“样本很好。"


def test_kangxi_radical_and_circle_zero():
    assert zh_typo.fix_mechanical("⼀个")[0] == "一个"
    assert zh_typo.fix_mechanical("二○二四年")[0] == "二〇二四年"


def test_mixed_traditional_review():
    t = "这个样本" * 6 + "環節"
    fs = [f for f in zh_typo.scan(t) if f.rule == "zh.mixed_script"]
    assert fs and all(f.kind == "review" for f in fs)


def test_term_near_miss_proposed_not_applied():
    t = "具有钢毛。"
    fs = zh_typo.scan(t, terms={"刚毛", "疣足"})
    nm = [f for f in fs if f.rule == "zh.term_near_miss"]
    assert nm and nm[0].new == "刚毛" and nm[0].kind == "review"
    assert zh_typo.fix_mechanical(t, terms={"刚毛"})[0] == t


def test_defined_term_itself_never_flagged():
    assert zh_typo.scan("具有刚毛。", terms={"刚毛", "钢毛"}) == []


def test_near_miss_other_valid_name_is_decision():
    fs = zh_typo.scan("属于多毛类。", terms={"多毛纲"}, protected_names={"多毛类"})
    d = [f for f in fs if f.rule == "zh.term_decision"]
    assert d and d[0].kind == "decision" and d[0].new == "多毛纲"
    assert zh_typo.fix_mechanical("属于多毛类。", terms={"多毛纲"}, protected_names={"多毛类"})[0] == "属于多毛类。"


def test_ambiguous_near_miss_not_proposed_as_single():
    fs = zh_typo.scan("钢毛", terms={"刚毛", "纲毛"})
    assert all(f.kind == "review" for f in fs)
    assert not [f for f in fs if f.rule == "zh.term_near_miss" and f.new]


def test_context_dependent_review_only():
    fs = zh_typo.scan("他做为代表，好象很高兴，跑的很快。")
    assert {f.rule for f in fs} >= {"zh.ctx_review"}
    assert all(f.kind == "review" for f in fs)
    assert zh_typo.fix_mechanical("他做为代表")[0] == "他做为代表"


def test_latin_names_untouched():
    t = "多毛类　*Nereis diversicolor* (Müller, 1776)，，钢毛,Nereis diversicolor O. F. Müller, 1776"
    new, _ = zh_typo.fix_mechanical(t)
    assert "*Nereis diversicolor* (Müller, 1776)" in new
    assert new.endswith("钢毛，Nereis diversicolor O. F. Müller, 1776")


def test_zero_finding_report_is_explicit():
    s = "<!-- PDF p.1 -->\n\nEnglish text only.\n"
    t = "<!-- PDF p.1 -->\n\n多毛类是环节动物。\n"
    out = [i.code for i in check_all(s, t, "en", "zh")]
    assert "zh_typo.none" in out
    assert not [c for c in out if c.startswith("zh_typo.") and c != "zh_typo.none"]


def test_check_all_reports_counts_by_rule():
    s = "<!-- PDF p.1 -->\n\nText.\n"
    t = "<!-- PDF p.1 -->\n\n多毛类　环节动物，，\n"
    iss = [i for i in check_all(s, t, "en", "zh") if i.code.startswith("zh_typo.")]
    assert {i.code for i in iss} >= {"zh_typo.zh.u3000", "zh_typo.zh.dup", "zh_typo.summary"}
    summ = [i for i in iss if i.code == "zh_typo.summary"][0]
    assert summ.evidence["by_rule"]["zh.u3000"] == 1
    assert not any(i.blocking for i in iss)


def test_not_run_for_non_chinese_target():
    s = "<!-- PDF p.1 -->\n\nx\n"
    assert not [i for i in check_all(s, s, "es", "en") if i.code.startswith("zh_typo.")]


def test_queue_rows_pass_apply_issues_gate(tmp_path):
    text = "多毛类　环节动物。刚毛，，疣足。\n"
    rows = zh_typo.queue_rows(text, file="ch1.md", terms=None, auto_only=True)
    assert rows and all({"file", "old", "new", "type", "reason", "en"} <= set(r) for r in rows)
    f = tmp_path / "译文"
    f.mkdir()
    (f / "ch1.md").write_text(text, encoding="utf-8")
    jl = tmp_path / "issues.jsonl"
    jl.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    res = ai.apply(tmp_path, jl, dry=False) if hasattr(ai, "apply") else None
    assert res is not None and not res.bad
    assert (f / "ch1.md").read_text(encoding="utf-8") == "多毛类环节动物。刚毛，疣足。\n"


def test_queue_old_is_unique_in_file():
    text = "的的。的的。\n"
    rows = zh_typo.queue_rows(text, file="x.md")
    for r in rows:
        assert text.count(r["old"]) == 1
