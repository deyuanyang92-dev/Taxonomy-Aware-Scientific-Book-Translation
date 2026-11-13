"""species_format：有中文名的种，按原书页，首次「中文名（*Genus species*）」，同页再现只写中文名。合成页面，不联网。"""
import subprocess
import sys
from pathlib import Path

import pytest

import species_format as sf

REPO = Path(__file__).resolve().parent.parent
NAMES = {"Sabella crassicornis": "厚角缨鳃虫", "Diopatra cuprea": "铜色巢沙蚕"}


def fix(text, unit="page", names=NAMES, **kw):
    return sf.fix_text(text, names, unit, **kw)


def test_first_on_page_gets_latin_added_to_bare_chinese():
    out, ch = fix("<!-- p.13 -->\n厚角缨鳃虫的鳃丝很长。\n")
    assert out == "<!-- p.13 -->\n厚角缨鳃虫（*Sabella crassicornis*）的鳃丝很长。\n"
    assert [(c.kind, c.name, c.unit) for c in ch] == [("add-latin", "厚角缨鳃虫", "13")]


def test_latin_only_first_occurrence_gets_chinese_name():
    out, ch = fix("<!-- p.13 -->\n如 *Sabella crassicornis* 的鳃丝。\n")
    assert out == "<!-- p.13 -->\n如厚角缨鳃虫（*Sabella crassicornis*）的鳃丝。\n"   # 中文间的空格一并去掉
    assert ch[0].kind == "add-latin"


def test_repeated_latin_on_same_page_dropped_in_every_form():
    text = ("<!-- p.13 -->\n厚角缨鳃虫（*Sabella crassicornis*）有鳃丝；厚角缨鳃虫（*Sabella crassicornis*）又有眼；"
            "*Sabella crassicornis* 与 *S. crassicornis* 相似；厚角缨鳃虫。\n")
    out, ch = fix(text)
    assert out == ("<!-- p.13 -->\n厚角缨鳃虫（*Sabella crassicornis*）有鳃丝；厚角缨鳃虫又有眼；"
                   "厚角缨鳃虫与厚角缨鳃虫相似；厚角缨鳃虫。\n")
    assert [c.kind for c in ch] == ["drop-latin"] * 3


def test_next_page_first_occurrence_gets_latin_again():
    text = ("<!-- p.13 -->\n厚角缨鳃虫（*Sabella crassicornis*）有鳃丝。厚角缨鳃虫很常见。\n\n"
            "<!-- p.14 -->\n厚角缨鳃虫的管。厚角缨鳃虫（*Sabella crassicornis*）。\n")
    out, ch = fix(text)
    assert out == ("<!-- p.13 -->\n厚角缨鳃虫（*Sabella crassicornis*）有鳃丝。厚角缨鳃虫很常见。\n\n"
                   "<!-- p.14 -->\n厚角缨鳃虫（*Sabella crassicornis*）的管。厚角缨鳃虫。\n")
    assert [(c.unit, c.kind) for c in ch] == [("14", "add-latin"), ("14", "drop-latin")]


def test_names_without_chinese_are_never_touched():
    text = "<!-- p.1 -->\n*Gyptis vittata* 与 *Gyptis vittata* 共栖；*Nereis falsa*（沙蚕科）。\n"
    assert fix(text) == (text, [])


def test_chinese_followed_by_bare_latin_is_one_occurrence():
    out, ch = fix("<!-- p.4 -->\n厚角缨鳃虫 *Sabella crassicornis* 的鳃丝；厚角缨鳃虫 *Sabella crassicornis*（缨鳃虫科）。\n")
    assert out == "<!-- p.4 -->\n厚角缨鳃虫（*Sabella crassicornis*）的鳃丝；厚角缨鳃虫（缨鳃虫科）。\n"
    assert [c.kind for c in ch] == ["add-latin", "drop-latin"]


def test_bracket_with_family_keeps_family_and_merges_on_first_occurrence():
    out, _ = fix("<!-- p.2 -->\n图：*Sabella crassicornis*（缨鳃虫科 Sabellidae）体前端；铜色巢沙蚕（欧努菲虫科）。\n")
    assert "厚角缨鳃虫（*Sabella crassicornis*，缨鳃虫科 Sabellidae）体前端" in out
    assert "铜色巢沙蚕（*Diopatra cuprea*，欧努菲虫科）" in out
    out2, _ = fix("<!-- p.2 -->\n厚角缨鳃虫（*Sabella crassicornis*，缨鳃虫科 Sabellidae）；"
                  "厚角缨鳃虫（*Sabella crassicornis*，缨鳃虫科 Sabellidae）。\n")
    assert out2.endswith("；厚角缨鳃虫（缨鳃虫科 Sabellidae）。\n")


def test_non_family_bracket_after_name_is_left_alone():
    out, _ = fix("<!-- p.2 -->\n厚角缨鳃虫（见图 3）很常见。\n")
    assert out == "<!-- p.2 -->\n厚角缨鳃虫（*Sabella crassicornis*）（见图 3）很常见。\n"


def test_abbreviated_latin_first_occurrence_is_expanded():
    out, _ = fix("<!-- p.3 -->\n*S. crassicornis* 的鳃丝。\n")
    assert out == "<!-- p.3 -->\n厚角缨鳃虫（*Sabella crassicornis*）的鳃丝。\n"


def test_idempotent_and_compliant_text_unchanged():
    text = "<!-- p.1 -->\n铜色巢沙蚕（*Diopatra cuprea*）与铜色巢沙蚕。\n\n<!-- p.2 -->\n铜色巢沙蚕（*Diopatra cuprea*）。\n"
    assert fix(text) == (text, [])
    messy = "<!-- p.1 -->\n铜色巢沙蚕与 *Diopatra cuprea*。\n"
    once, _ = fix(messy)
    assert fix(once) == (once, [])


def test_text_before_first_marker_is_its_own_page_and_markers_preserved():
    text = "厚角缨鳃虫。\n<!-- p.5 -->\n厚角缨鳃虫。\n"
    out, ch = fix(text)
    assert out == "厚角缨鳃虫（*Sabella crassicornis*）。\n<!-- p.5 -->\n厚角缨鳃虫（*Sabella crassicornis*）。\n"
    assert [c.unit for c in ch] == ["（首个页码标记之前）", "5"]


def test_page_unit_without_markers_is_refused_but_whole_works():
    with pytest.raises(sf.NoPageMarkers):
        fix("厚角缨鳃虫。厚角缨鳃虫（*Sabella crassicornis*）。\n")
    out, _ = fix("厚角缨鳃虫。厚角缨鳃虫（*Sabella crassicornis*）。\n", unit="whole")
    assert out == "厚角缨鳃虫（*Sabella crassicornis*）。厚角缨鳃虫。\n"


def test_paragraph_unit_each_caption_is_its_own_page():
    text = ("图 1. 厚角缨鳃虫（*Sabella crassicornis*，缨鳃虫科）体前端。示厚角缨鳃虫的眼点。\n\n"
            "图 2. *Sabella crassicornis* 的管。\n\n"
            "图 3. 铜色巢沙蚕（*Diopatra cuprea*）。\n")
    out, ch = fix(text, unit="paragraph")
    assert out == ("图 1. 厚角缨鳃虫（*Sabella crassicornis*，缨鳃虫科）体前端。示厚角缨鳃虫的眼点。\n\n"
                   "图 2. 厚角缨鳃虫（*Sabella crassicornis*）的管。\n\n"
                   "图 3. 铜色巢沙蚕（*Diopatra cuprea*）。\n")
    assert [(c.unit, c.kind) for c in ch] == [("段 2", "add-latin")]


def test_report_lines_name_page_and_change():
    _, ch = fix("<!-- p.13 -->\n厚角缨鳃虫的鳃丝。\n")
    line = ch[0].line()
    assert "p.13" in line and "厚角缨鳃虫" in line and "补" in line and "*Sabella crassicornis*" in line


def test_load_names_tsv_with_comments_and_swapped_columns(tmp_path):
    f = tmp_path / "n.tsv"
    f.write_text("# 拉丁名\t中文名\nSabella crassicornis\t厚角缨鳃虫\n铜色巢沙蚕\tDiopatra cuprea\nBad line\n", encoding="utf8")
    names, bad = sf.load_names(f)
    assert names == NAMES and len(bad) == 1


def test_names_from_yiku_only_hard_binomials(tmp_path):
    from yiku import db as D
    con = D.connect(tmp_path / "t.db")
    D.add_source(con, "dzz", "动物志", "authority", domain="分类学", year=2004)
    D.add_term(con, "Sabella crassicornis", "厚角缨鳃虫", "dzz", domain="分类学", status="已核")
    D.add_term(con, "Diopatra cuprea", "铜色巢沙蚕", "dzz", domain="分类学", status="已核")
    D.add_term(con, "Diopatra cuprea", "铜巢沙蚕", "dzz", domain="分类学", status="已核")   # 译名分歧：不是 HARD
    D.add_term(con, "Nereis falsa", "假沙蚕", "dzz", domain="分类学")                       # 候选、tier 以上：HARD? 见 classify
    text = "*Sabella crassicornis*, *Diopatra cuprea*, *Gyptis vittata*, *S. crassicornis*"
    got = sf.yiku_names(text, "分类学", con=con)
    assert got["Sabella crassicornis"] == "厚角缨鳃虫"
    assert "Diopatra cuprea" not in got and "Gyptis vittata" not in got


def run_cli(*args, cwd=None):
    return subprocess.run([sys.executable, str(REPO / "scripts" / "species_format.py"), *args],
                          capture_output=True, text=True, cwd=cwd)


def test_cli_check_reports_and_exits_1_without_writing(tmp_path):
    f = tmp_path / "t.md"
    f.write_text("<!-- p.13 -->\n厚角缨鳃虫的鳃丝。\n", encoding="utf8")
    n = tmp_path / "n.tsv"
    n.write_text("Sabella crassicornis\t厚角缨鳃虫\n", encoding="utf8")
    r = run_cli(str(f), "--names", str(n), "--no-yiku")
    assert r.returncode == 1 and "p.13" in r.stdout
    assert f.read_text(encoding="utf8") == "<!-- p.13 -->\n厚角缨鳃虫的鳃丝。\n"


def test_cli_fix_backs_up_original_once_and_writes_fixed_copy(tmp_path):
    f = tmp_path / "译文_图注.md"
    f.write_text("图 1. *Sabella crassicornis* 体前端。\n\n图 2. 厚角缨鳃虫。\n", encoding="utf8")
    n = tmp_path / "n.tsv"
    n.write_text("Sabella crassicornis\t厚角缨鳃虫\n", encoding="utf8")
    r = run_cli(str(f), "--names", str(n), "--no-yiku", "--fix")   # 文件名含「图注」：自动按段落当作单元
    assert r.returncode == 0, r.stderr
    assert f.read_text(encoding="utf8") == "图 1. 厚角缨鳃虫（*Sabella crassicornis*）体前端。\n\n图 2. 厚角缨鳃虫（*Sabella crassicornis*）。\n"
    bak = tmp_path / "译文_图注.md.bak-species"
    assert bak.read_text(encoding="utf8").startswith("图 1. *Sabella crassicornis* 体前端")
    run_cli(str(f), "--names", str(n), "--no-yiku", "--fix")           # 再跑：无改动，备份不被覆盖
    assert bak.read_text(encoding="utf8").startswith("图 1. *Sabella crassicornis* 体前端")
    assert run_cli(str(f), "--names", str(n), "--no-yiku").returncode == 0


def test_cli_page_mode_without_markers_exits_2_with_hint(tmp_path):
    f = tmp_path / "body.md"
    f.write_text("厚角缨鳃虫。\n", encoding="utf8")
    n = tmp_path / "n.tsv"
    n.write_text("Sabella crassicornis\t厚角缨鳃虫\n", encoding="utf8")
    r = run_cli(str(f), "--names", str(n), "--no-yiku")
    assert r.returncode == 2 and "页码标记" in r.stderr and "--unit whole" in r.stderr
    assert run_cli(str(f), "--names", str(n), "--no-yiku", "--unit", "whole").returncode == 1


def test_harvest_pairs_from_translation():
    t = "其一为暗蛇潜虫（*Podarke obscura*）。另见暗蛇潜虫（*Podarke obscura*）与甲（*Aa bb*）、乙（*Aa bb*）。"
    got = sf.harvest_pairs(t)
    assert got == {"Podarke obscura": "暗蛇潜虫"}  # 一名多译的不收


def test_harvest_pairs_single_occurrence_strips_leading_words():
    for pre, zh, latin in [("另见", "暗蛇潜虫", "Podarke obscura"), ("为", "覆瓦哈鳞虫", "Harmothoe imbricata"),
                           ("检查了", "微怪鳞虫", "Paralepidonotus ampulliferus"), ("例如", "厚角缨鳃虫", "Pseudopotamilla crassa"),
                           ("", "铜色巢沙蚕", "Nereis aenea")]:
        assert sf.harvest_pairs(f"{pre}{zh}（*{latin}*）。") == {latin: zh}
    assert sf.harvest_pairs("为暗（*Aa bb*）。") == {}              # 剥完不足 2 字，不收


def test_harvest_pairs_common_suffix_across_occurrences():
    t = "我们发现了暗蛇潜虫（*Podarke obscura*），后文再提到暗蛇潜虫（*Podarke obscura*）。"
    assert sf.harvest_pairs(t) == {"Podarke obscura": "暗蛇潜虫"}   # 公共后缀恰是第二次的整串
    t2 = "该种暗蛇潜虫（*Podarke obscura*）与此暗蛇潜虫（*Podarke obscura*）。"
    assert sf.harvest_pairs(t2) == {"Podarke obscura": "暗蛇潜虫"}


def test_harvest_pairs_conflicting_chinese_skipped_and_reported():
    t = "铜色巢沙蚕（*Nereis aenea*）与另一种沙蚕（*Nereis aenea*）。甲乙丙（*Cc dd*）、丁戊己（*Cc dd*）。"
    skipped: dict[str, list[str]] = {}
    assert sf.harvest_pairs(t, skipped=skipped) == {}
    assert set(skipped) == {"Nereis aenea", "Cc dd"}


def test_harvest_pairs_prefers_known_names():
    t = "我们发现了暗蛇潜虫（*Podarke obscura*）。"
    assert sf.harvest_pairs(t, known={"暗蛇潜虫", "潜虫"}) == {"Podarke obscura": "暗蛇潜虫"}   # 取最长的已知后缀
    assert sf.harvest_pairs("见暗蛇潜虫（*Podarke obscura*）。", known={"覆瓦哈鳞虫"}) == {"Podarke obscura": "暗蛇潜虫"}


def test_collect_names_priority_harvested_yiku_tsv(tmp_path, monkeypatch):
    monkeypatch.setattr(sf, "yiku_names", lambda text, domain="分类学", con=None, db=None: {"Podarke obscura": "YIKU", "Aa bb": "YIKU乙"})
    f = tmp_path / "n.tsv"
    f.write_text("Aa bb\tTSV乙\n", encoding="utf8")
    t = "暗蛇潜虫（*Podarke obscura*）、乙乙（*Aa bb*）、丙丙（*Cc dd*）。"
    got = sf.collect_names(t, f, "分类学")
    assert got == {"Podarke obscura": "YIKU", "Aa bb": "TSV乙", "Cc dd": "丙丙"}
    assert sf.collect_names(t, None, None) == {"Podarke obscura": "暗蛇潜虫", "Aa bb": "乙乙", "Cc dd": "丙丙"}


# ---------------------------------------------------------------- 2026-11-13 Harrison ch2.2 试跑暴露的误改（合成句，不含书中原文）

GENERIC = {"Nereis pelagica": "沙蚕", "Owenia fusiformis": "欧文虫", "Chaetopterus variopedatus": "燐虫",
           "Sabella penicillus": "缨鳃虫"}
OCR_NAMES = {"Magelona papilliorni": "乳突长手沙蚕", "Magelona papillicornis": "乳突长手沙蚕"}


def test_never_match_inside_longer_taxon_name_with_rank_suffix():
    text = ("<!-- p.1 -->\n如索沙蚕属、吻沙蚕科、沙蚕科、长手沙蚕科、缨鳃虫科、欧文虫属、燐虫属、欧文虫亚科、"
            "沙蚕目、缨鳃虫类、缨鳃虫总科（Sabelloidea）。\n")
    assert fix(text, names=GENERIC) == (text, [])


def test_rank_suffix_lookalikes_are_not_ranks():
    out, _ = fix("<!-- p.1 -->\n缨鳃虫属于多毛类；欧文虫目前已知一种；缨鳃虫类似于燐虫。\n", names=GENERIC)
    assert "缨鳃虫（*Sabella penicillus*）属于多毛类" in out
    assert "欧文虫（*Owenia fusiformis*）目前已知一种" in out


def test_hit_inside_longer_known_name_is_skipped_longest_match():
    names = {"Nereis pelagica": "沙蚕"}
    text = "<!-- p.1 -->\n突变花索沙蚕很常见。\n"
    assert fix(text, names=names, known={"突变花索沙蚕"}) == (text, [])
    assert fix(text, names={**names, "Arabella mutans": "突变花索沙蚕"})[0] == \
        "<!-- p.1 -->\n突变花索沙蚕（*Arabella mutans*）很常见。\n"


def test_generic_name_never_gets_a_species_binomial():
    text = "<!-- p.1 -->\n沙蚕的体壁。\n"
    assert fix(text, names={"Nereis pelagica": "沙蚕"}, generic={"沙蚕"}) == (text, [])


def test_latin_must_appear_on_the_source_page():
    src = "<!-- p.1 -->\nThe Sabella crassicornis gill.\n\n<!-- p.2 -->\nNothing here.\n\n<!-- p.3 -->\nSabella\ncrassicornis again.\n"
    text = "<!-- p.1 -->\n厚角缨鳃虫的鳃。\n\n<!-- p.2 -->\n厚角缨鳃虫的管。\n\n<!-- p.3 -->\n厚角缨鳃虫。\n"
    out, ch = fix(text, src=src)
    assert out == ("<!-- p.1 -->\n厚角缨鳃虫（*Sabella crassicornis*）的鳃。\n\n<!-- p.2 -->\n厚角缨鳃虫的管。\n\n"
                   "<!-- p.3 -->\n厚角缨鳃虫（*Sabella crassicornis*）。\n")
    assert [c.unit for c in ch] == ["1", "3"]


def test_name_absent_from_source_page_is_not_added_but_unlisted_names_still_untouched():
    names = {"Nereis pelagica": "沙蚕", "Diopatra cuprea": "铜色巢沙蚕"}
    src = "<!-- p.1 -->\nDiopatra cuprea is a tube worm.\n"
    out, ch = fix("<!-- p.1 -->\n沙蚕与铜色巢沙蚕。\n", names=names, src=src)
    assert out == "<!-- p.1 -->\n沙蚕与铜色巢沙蚕（*Diopatra cuprea*）。\n" and len(ch) == 1


def test_ocr_close_variant_on_source_counts_as_present():
    src = "<!-- p.1 -->\nthe Sabella crassicornls gill.\n"
    out, _ = fix("<!-- p.1 -->\n厚角缨鳃虫的鳃。\n", src=src)
    assert out == "<!-- p.1 -->\n厚角缨鳃虫（*Sabella crassicornis*）的鳃。\n"


def test_source_page_missing_means_no_addition():
    src = "<!-- p.1 -->\nSabella crassicornis.\n"
    text = "<!-- p.9 -->\n厚角缨鳃虫的鳃。\n"
    assert fix(text, src=src) == (text, [])


def test_paragraph_unit_uses_source_page_of_the_preceding_marker():
    src = "<!-- p.1 -->\nFig. 1. Sabella crassicornis.\n\n<!-- p.2 -->\nFig. 2. Diopatra.\n"
    text = "<!-- p.1 -->\n\n图 1 厚角缨鳃虫。\n\n<!-- p.2 -->\n\n图 2 厚角缨鳃虫。\n"
    out, ch = fix(text, unit="paragraph", src=src)
    assert out == "<!-- p.1 -->\n\n图 1 厚角缨鳃虫（*Sabella crassicornis*）。\n\n<!-- p.2 -->\n\n图 2 厚角缨鳃虫。\n"
    assert len(ch) == 1


def test_existing_latin_after_chinese_name_is_never_doubled():
    text = "<!-- p.1 -->\n和乳突长手沙蚕（*Magelona papillicornis*）与乳突长手沙蚕（*Magelona papilliorni*）。\n"
    out, ch = fix(text, names=OCR_NAMES)
    assert out == "<!-- p.1 -->\n和乳突长手沙蚕（*Magelona papillicornis*）与乳突长手沙蚕。\n"   # 同页第二次去拉丁名，没有叠加括号
    assert [c.kind for c in ch] == ["drop-latin"]
    unk = "<!-- p.1 -->\n乳突长手沙蚕（*Magelona foo*）与乳突长手沙蚕 *Magelona bar*。\n"
    assert fix(unk, names=OCR_NAMES) == (unk, [])                       # 中文名后已有别的拉丁名：不插入


def test_latin_inside_existing_parentheses_is_not_nested():
    text = "<!-- p.1 -->\n厚度约 1.5 µm（欧文虫 *Owenia fusiformis*）至 0.1 µm。\n"
    out, ch = fix(text, names=GENERIC)
    assert "（（" not in out and out == text and ch == []
    out2, _ = fix("<!-- p.1 -->\n欧文虫（*Owenia fusiformis*）长；（欧文虫 *Owenia fusiformis*）短。\n", names=GENERIC)
    assert out2 == "<!-- p.1 -->\n欧文虫（*Owenia fusiformis*）长；（欧文虫）短。\n"
    out3, _ = fix("<!-- p.1 -->\n（见 *Owenia fusiformis*）和欧文虫。\n", names=GENERIC)
    assert "（（" not in out3 and out3.count("*Owenia fusiformis*") == 1


def test_bare_chinese_inside_parentheses_does_not_get_nested_bracket():
    out, _ = fix("<!-- p.1 -->\n体壁（在欧文虫中较厚）。欧文虫的鳃。\n", names=GENERIC)
    assert out == "<!-- p.1 -->\n体壁（在欧文虫中较厚）。欧文虫（*Owenia fusiformis*）的鳃。\n"


def test_ocr_variants_one_candidate_per_occurrence_preferring_source_variant():
    src = "<!-- p.1 -->\nMagelona papillicornis (Bailey 1977).\n"
    out, ch = fix("<!-- p.1 -->\n见乳突长手沙蚕的心脏。\n", names=OCR_NAMES, src=src)
    assert out == "<!-- p.1 -->\n见乳突长手沙蚕（*Magelona papillicornis*）的心脏。\n" and len(ch) == 1
    both = "<!-- p.1 -->\n*Magelona papillicornis* 与 *Magelona papilliorni* 及乳突长手沙蚕。\n"
    out2, _ = fix(both, names=OCR_NAMES, src="<!-- p.1 -->\nMagelona papillicornis; Magelona papilliorni.\n")
    assert out2 == "<!-- p.1 -->\n乳突长手沙蚕（*Magelona papillicornis*）与乳突长手沙蚕及乳突长手沙蚕。\n"
    assert out2.count("*Magelona") == 1


def test_ocr_marker_after_latin_is_preserved():
    out, _ = fix("<!-- p.1 -->\n在 *Owenia fusiformis*[OCR?] 中。\n", names=GENERIC)
    assert out == "<!-- p.1 -->\n在欧文虫（*Owenia fusiformis*[OCR?]）中。\n"
    assert fix(out, names=GENERIC) == (out, [])
    text = "<!-- p.1 -->\n欧文虫（*Owenia fusiformis*[OCR?]）；*Owenia fusiformis*[OCR?]；欧文虫（*Owenia fusiformis*[OCR?]）。\n"
    out2, _ = fix(text, names=GENERIC)
    assert out2 == "<!-- p.1 -->\n欧文虫（*Owenia fusiformis*[OCR?]）；欧文虫[OCR?]；欧文虫[OCR?]。\n"
    out3, _ = fix("<!-- p.1 -->\n欧文虫（*Owenia fusiformis*）长；欧文虫 *Owenia fusiformis*[OCR?]。\n", names=GENERIC)
    assert out3 == "<!-- p.1 -->\n欧文虫（*Owenia fusiformis*）长；欧文虫[OCR?]。\n"


def test_bare_chinese_followed_by_ocr_marker_keeps_marker_after_name_block():
    out, _ = fix("<!-- p.1 -->\n在欧文虫[OCR?]中。\n", names=GENERIC)
    assert "[OCR?]" in out and out.count("*Owenia fusiformis*") == 1 and "（（" not in out


def test_collect_names_known_taxon_names_from_yiku(tmp_path):
    from yiku import db as D
    con = D.connect(tmp_path / "t.db")
    D.add_source(con, "dzz", "动物志", "authority", domain="分类学", year=2004)
    D.add_term(con, "Nereis", "沙蚕属", "dzz", domain="分类学", status="已核")
    D.add_term(con, "Lumbrineris", "索沙蚕属", "dzz", domain="分类学", status="已核")
    D.add_term(con, "Glyceridae", "吻沙蚕科", "dzz", domain="分类学", status="已核")
    D.add_term(con, "Arabella mutans", "突变花索沙蚕", "dzz", domain="分类学", status="已核")
    D.add_term(con, "Nereis pelagica", "沙蚕", "dzz", domain="分类学", status="已核")
    D.add_term(con, "sand worm", "沙蚕", "dzz", domain="分类学", status="候选")
    D.add_term(con, "gill", "鳃", "dzz", domain="分类学", status="已核")
    known = sf.yiku_known_names(con, "分类学")
    assert {"沙蚕属", "索沙蚕属", "吻沙蚕科", "突变花索沙蚕", "索沙蚕", "吻沙蚕"} <= known     # 带阶元后缀者连同词干一并收
    assert "鳃" not in known
    assert sf.yiku_generic_names(con, "分类学", {"Nereis pelagica": "沙蚕"}) == {"沙蚕"}   # 同一中文名还对应非拉丁英文词：通名


def test_cli_auto_finds_src_en_and_only_adds_names_on_the_source_page(tmp_path):
    book = tmp_path / "书"
    (book / "译文").mkdir(parents=True)
    (book / "src_en").mkdir()
    (book / "src_en" / "body.txt").write_text("<!-- p.1 -->\nSabella crassicornis gill.\n\n<!-- p.2 -->\nNothing.\n", encoding="utf8")
    f = book / "译文" / "body_直译初译.md"
    f.write_text("<!-- p.1 -->\n厚角缨鳃虫的鳃与索沙蚕属。\n\n<!-- p.2 -->\n厚角缨鳃虫的管。\n", encoding="utf8")
    n = tmp_path / "n.tsv"
    n.write_text("Sabella crassicornis\t厚角缨鳃虫\n", encoding="utf8")
    r = run_cli(str(f), "--names", str(n), "--no-yiku")
    assert r.returncode == 1 and "[p.1]" in r.stdout and "[p.2]" not in r.stdout
    assert "待改 1 处" in r.stdout
