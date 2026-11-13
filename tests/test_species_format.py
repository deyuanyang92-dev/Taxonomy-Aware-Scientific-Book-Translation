"""species_format：有中文名的种，按原书页，首次「中文名（*Genus species*）」，同页再现只写中文名。合成页面，不联网。"""
import subprocess
import sys
from pathlib import Path

import pytest

import species_format as sf

REPO = Path(__file__).resolve().parent.parent
NAMES = {"Sabella crassicornis": "厚角缨鳃虫", "Diopatra cuprea": "铜色巢沙蚕"}


def fix(text, unit="page", names=NAMES):
    return sf.fix_text(text, names, unit)


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
