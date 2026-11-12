"""split_figures：图注/表注分离。真实章节回归素材不存在时 skip。"""
from pathlib import Path

import pytest

import split_figures as sf

HANDBOOK = Path("/mnt/p/翻译-译作/Handbook_Annelida/Handbook_译文/vol4/src/s7_13_3_3.txt")


def test_ends_sentence_and_abbreviations():
    assert sf.ends_sentence("Photos from A. Rose and C.J. Glasby.")
    assert sf.ends_sentence("From Mettam (1967, fig. 6a).")
    assert sf.ends_sentence("Hartman, 1954. ")
    assert not sf.ends_sentence("Hediste diversicolor (O.F.")
    assert not sf.ends_sentence("such as e.g.")
    assert not sf.ends_sentence("Nereis sp.")
    assert not sf.ends_sentence("see fig.")
    assert not sf.ends_sentence("no period here")


def test_caption_regex():
    for ok in ("Fig. 7.13.3.3.1: x", "◂ Fig. 7.13.3.3.18: x", "Table 3", "Table 2.1 Key", "Fig.3 x"):
        assert sf.CAPTION_START.match(ok), ok
    for no in ("Figs. 3 and 4", "The Fig. 3", "Figure 3", "table 3"):
        assert not sf.CAPTION_START.match(no), no


def test_caption_inside_sentence_is_removed_and_sentence_rejoined():
    text = (
        "Genera such as Ceratocephale have complex structures (Hylleberg and\n"
        "Fig. 7.13.3.3.1: General outline of Nereididae. Photos from Leon Altoff.\n"
        "Nateewathana 1988). The great variation in parapodial\n"
    )
    body, caps = sf.split_figures(text)
    assert caps == ["Fig. 7.13.3.3.1: General outline of Nereididae. Photos from Leon Altoff."]
    assert "Fig." not in body
    assert body.splitlines() == [
        "Genera such as Ceratocephale have complex structures (Hylleberg and",
        "Nateewathana 1988). The great variation in parapodial",
    ]


def test_narrow_caption_continues_until_period_not_abbreviation():
    text = (
        "Fig. 7.13.3.3.4: Spinigerous chaetae in Hediste diversicolor (O.F.\n"
        "Müller, 1776) and sp.\n"
        "nov. Photo from C.J.\n"
        "Wilson.\n"
        "Body text resumes here.\n"
    )
    body, caps = sf.split_figures(text)
    assert len(caps) == 1 and caps[0].endswith("Photo from C.J. Wilson.")
    assert "(O.F. Müller, 1776) and sp. nov." in caps[0]
    assert body.strip() == "Body text resumes here."


def test_wide_column_caption_continues_on_long_next_line():
    wide = "x " * 60 + "end."  # > 100 字符，以句号收尾
    text = f"Fig. 1: first sentence ends here.\n{wide}\nshort body\n"
    body, caps = sf.split_figures(text)
    assert len(caps) == 1 and "first sentence ends here." in caps[0] and "x x" in caps[0]
    assert body.strip() == "short body"


def test_next_caption_start_stops_block_and_block_length_capped():
    text = "Fig. 1: no period here\nFig. 2: second one.\nbody\n"
    body, caps = sf.split_figures(text)
    assert caps == ["Fig. 1: no period here", "Fig. 2: second one."]
    long = "Fig. 9: " + "\n".join(f"line{i} words" for i in range(30)) + "\n"
    body, caps = sf.split_figures(long)
    assert len(caps) == 1 and caps[0].count("line") == 14  # 14 行封顶
    assert body.count("line") == 16


def test_table_caption_and_arrow_marker():
    body, caps = sf.split_figures("◂ Fig. 3: marker removed.\nTable 2 Genera of Nereididae.\ntext\n")
    assert caps == ["Fig. 3: marker removed.", "Table 2 Genera of Nereididae."]
    assert body.strip() == "text"


def test_body_dehyphenation_keeps_line_structure():
    text = "characters has been useful in harvesting data for phy-\nlogenetic analyses, although homology of structures has\nbeen problematic.\n"
    body, _ = sf.split_figures(text)
    lines = body.splitlines()
    assert lines[0] == "characters has been useful in harvesting data for phylogenetic"
    assert lines[1] == "analyses, although homology of structures has"
    assert all(len(ln) < 100 for ln in lines)
    # 下一行大写开头（真连字符，如 Villalobos-Guerrero 断在行末）不并
    assert sf.split_figures("Villalobos-\nGuerrero\n")[0] == "Villalobos-\nGuerrero\n"


def test_dehyphenation_across_removed_caption_and_soft_hyphen():
    text = "chem-\nFig. 1: cap.\nosensory nuchal organs, and Cera­\ntocephale and more\n"
    body, caps = sf.split_figures(text)
    assert caps == ["Fig. 1: cap."]
    assert "chemosensory" in body and "Ceratocephale" in body and "­" not in body


def test_caption_keeps_real_hyphen_and_crlf_handled():
    text = "Fig. 5: Crescent-\r\nshaped organ.\r\nbody\r\n"
    body, caps = sf.split_figures(text)
    assert caps == ["Fig. 5: Crescent- shaped organ."] and body == "body\n"


def test_cli_writes_two_files(tmp_path):
    src = tmp_path / "ch.txt"
    src.write_text("Fig. 1: cap.\nbody text\n", encoding="utf8")
    assert sf.main([str(src), "-o", str(tmp_path / "out")]) == 0
    assert (tmp_path / "out" / "图注.txt").read_text(encoding="utf8") == "Fig. 1: cap.\n"
    assert (tmp_path / "out" / "正文.txt").read_text(encoding="utf8") == "body text\n"


@pytest.mark.skipif(not HANDBOOK.exists(), reason="Handbook 第4卷 沙蚕科 回归素材不在本机")
def test_handbook_nereididae_regression():
    body, caps = sf.split_figures(HANDBOOK.read_text(encoding="utf8"))
    assert len(caps) == 23
    assert [c.split(":")[0] for c in caps][:3] == ["Fig. 7.13.3.3.1", "Fig. 7.13.3.3.2", "Fig. 7.13.3.3.3"]
    assert max(len(ln) for ln in body.splitlines()) <= 100
    assert not any(sf.CAPTION_START.match(ln) for ln in body.splitlines())
    assert "From Schmidtberg and Dorresteijn (2010, fig. 1)." in caps[17]
    assert "phylogenetic analyses" in body
