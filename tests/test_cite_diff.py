"""cite_diff：英文 (Author, year) 引文与图号的多重集对照，只报真差异。合成文本，不联网。"""
import subprocess
import sys
from pathlib import Path

import cite_diff as cd

REPO = Path(__file__).resolve().parent.parent


def real(rep):
    return [(r.kind, r.obj, r.verdict) for r in rep.rows if r.status == "real"]


def cmp(en, zh, **kw):
    return cd.compare([en], [zh], **kw)


def test_identical_citations_have_no_diff():
    rep = cmp("It was shown (Smith, 1978; Jones 1985).", "已有研究（Smith, 1978；Jones 1985）。")
    assert rep.real == 0 and rep.n_cite_en == 2 and rep.n_cite_zh == 2


def test_invented_citation_is_flagged_as_zh_extra():
    rep = cmp("Gills occur (Smith 1978).", "鳃（Smith 1978；Brown 1990）。")
    assert [(k, o) for k, o, _ in real(rep)] == [("citation", "brown, 1990")]
    assert "多出" in real(rep)[0][2]
    assert rep.real == 1


def test_missing_citation_is_flagged():
    rep = cmp("Gills occur (Smith 1978; Jones 1985).", "鳃（Smith 1978）。")
    assert [(k, o) for k, o, _ in real(rep)] == [("citation", "jones, 1985")]
    assert "缺失" in real(rep)[0][2]


def test_changed_year_gives_missing_and_extra():
    rep = cmp("As in Smith (1978).", "如 Smith（1979）。")
    assert sorted(o for _, o, _ in real(rep)) == ["smith, 1978", "smith, 1979"]


def test_ocr_hyphenation_noise_is_ignored():
    rep = cmp("as shown by Gar-\ndiner (1978) and Gar- diner (1978).", "如 Gardiner（1978）与 Gardiner（1978）所示。")
    assert rep.real == 0 and rep.n_cite_en == 2


def test_and_vs_chinese_conjunction():
    rep = cmp("Smith and Jones (1980) reported", "Smith 与 Jones（1980）报道")
    assert rep.real == 0 and rep.n_cite_en == 1
    for conj in ("和", "及", "、", "&"):
        assert cmp("Smith & Jones, 1980", f"Smith {conj} Jones，1980").real == 0


def test_changed_second_author_is_flagged_by_strict_layer():
    rep = cmp("Smith and Jones (1980)", "Smith 与 Brown（1980）")
    assert [k for k, _, _ in real(rep)] == ["citation-strict"] * 2


def test_et_al_vs_chinese_deng_and_ocr_etal():
    assert cmp("Smith et al. (1980)", "Smith 等（1980）").real == 0
    assert cmp("Smith et al. (1980)", "Smith 等人（1980）").real == 0
    assert cmp("Smith etal. (1980) and Lee et al., 1981", "Smith 等（1980）与 Lee 等，1981").real == 0


def test_year_lists_and_suffix_letters_and_fullwidth_brackets():
    assert cmp("Smith (1980a,b)", "Smith（1980a，b）").real == 0
    assert cmp("Smith 1980a, 1980b", "Smith（1980a、1980b）").real == 0
    assert cmp("Smith's (1980) data", "Smith［1980］的数据").real == 0


def test_year_letter_change_is_strict_diff():
    rep = cmp("Smith (1980a)", "Smith（1980b）")
    assert [k for k, _, _ in real(rep)] == ["citation-strict"] * 2


def test_non_author_capitalised_words_are_not_citations():
    rep = cmp("In 1980 the larva (Fig. 3) of May 1981 appeared.", "1980年幼虫（图3）出现。")
    assert rep.n_cite_en == 0 and rep.real == 0


def test_figure_range_matches_chinese_range_and_list():
    assert cmp("see Figs. 3–5", "见图 3–5").real == 0
    assert cmp("see Figs. 3-5 and 7", "见图 3–5 和 7").real == 0
    rep = cmp("see Figs. 3–5", "见图 3、4")
    assert [(k, o) for k, o, _ in real(rep)] == [("figure", "Fig. 5")]


def test_figure_panel_letters_strict_layer():
    assert cmp("(Fig. 3A–C)", "（图 3A–C）").real == 0
    rep = cmp("(Fig. 3A–C)", "（图 3A、B）")
    assert [(k, o) for k, o, _ in real(rep)] == [("figure-strict", "Fig. 3C")]


def test_missing_and_extra_figure_reference():
    rep = cmp("(Fig. 2). (Fig. 4)", "（图2）。（图4）（图9）")
    assert [(k, o) for k, o, _ in real(rep)] == [("figure", "Fig. 9")]


def test_ocr_fig_81_is_fig_8I_when_caption_defines_8():
    rep = cd.compare(["see Fig. 81", "Fig. 8. Caption text."], ["见图8I", "图8. 图注。"])
    assert rep.real == 0


def test_similar_name_same_year_is_variant_not_real():
    rep = cmp("Kuemmel (1960)", "Kummel（1960）")
    assert rep.real == 0 and rep.variants == 1


def test_alias_and_noise_file_confirm_residuals():
    rep = cmp("Kiimmel (1960)", "Kuemmel（1960）", alias={"kiimmel": "kuemmel"})
    assert rep.real == 0 and rep.variants == 0
    noise = cd.parse_noise("类型\t对象\t英文次数\t中文次数\t原因\ncitation\tbrown, 1990\t0\t1\t人工核实：中文据页图补\n")
    rep = cmp("Smith 1978", "Smith 1978; Brown 1990", noise=noise)
    assert rep.real == 0 and rep.noise == 1
    rep = cmp("Smith 1978", "Smith 1978; Brown 1990; Brown 1990", noise=noise)   # 次数变了：重新报警
    assert rep.real == 1


def test_title_and_references_and_comments_and_ocr_marks_ignored_on_zh_side():
    zh = "# 标题 Barnes & Harrison 1992\n\n正文 Smith（1980）<!-- p.3 Jones 1999 -->[OCR?]。\n\n## 文献表\n\nBrown 1990\n"
    rep = cd.compare(["Smith (1980)"], [zh], zh_stop=r"^## 文献表.*$")
    assert rep.real == 0


def run(*args):
    return subprocess.run([sys.executable, str(REPO / "scripts" / "cite_diff.py"), *map(str, args)],
                          capture_output=True, text=True)


def test_cli_exit_codes_tsv_and_multiple_en_files(tmp_path):
    (tmp_path / "body.txt").write_text("Smith (1978) said (Fig. 2).\n", encoding="utf8")
    (tmp_path / "captions.txt").write_text("Fig. 2. Jones and Lee (1980).\n", encoding="utf8")
    (tmp_path / "ok.md").write_text("Smith（1978）说（图2）。\n\n图2. Jones 与 Lee（1980）。\n", encoding="utf8")
    r = run("--en", tmp_path / "body.txt", "--en", tmp_path / "captions.txt", "--zh", tmp_path / "ok.md",
            "--out", tmp_path / "ok.tsv")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "真差异合计 0" in r.stdout
    assert (tmp_path / "ok.tsv").read_text(encoding="utf8").startswith("类型\t")
    (tmp_path / "bad.md").write_text("Smith（1979）说（图2）。\n\n图2. Jones 与 Lee（1980）。\n", encoding="utf8")
    r = run("--en", tmp_path / "body.txt", "--en", tmp_path / "captions.txt", "--zh", tmp_path / "bad.md",
            "--out", tmp_path / "bad.tsv")
    assert r.returncode == 1
    assert "真差异合计 2" in r.stdout
    tsv = (tmp_path / "bad.tsv").read_text(encoding="utf8")
    assert "smith, 1978" in tsv and "smith, 1979" in tsv


def test_cli_missing_file_is_usage_error(tmp_path):
    r = run("--en", tmp_path / "nope.txt", "--zh", tmp_path / "nope.md", "--out", tmp_path / "o.tsv")
    assert r.returncode == 2
