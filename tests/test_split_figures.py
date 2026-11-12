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


def test_wide_column_caption_continues_across_mid_caption_period():
    """双栏书的宽栏长图注：中间行常恰好以句号收尾（如「…(Horst, 1924).」），后面还有宽行，不能在那里断开。"""
    narrow = "\n".join(f"narrow body column line number {i} of ordinary text here" for i in range(10))
    w1 = "Fig. 1: " + "wide caption words " * 6 + "Shield-shaped bars in Pseudonereis trimaculata (Horst, 1924)."
    w2 = "H, " + "more wide words " * 8 + "end of second wide line"
    text = f"{narrow}\n{w1}\n{w2}\nPhotos from A. Rose.\nbody resumes with a narrow line\n"
    assert len(w1) > 100 and len(w2) > 100 and w1.endswith("1924).")
    body, caps = sf.split_figures(text)
    assert len(caps) == 1 and caps[0].endswith("Photos from A. Rose.") and "(Horst, 1924). H, more wide" in caps[0]
    assert body.splitlines()[-1] == "body resumes with a narrow line" and "Fig." not in body


def test_wide_continuation_requires_wide_first_line():
    """首行是窄行且已句末结束：后面碰到长行也不续（长行是正文）。"""
    wide = "x " * 60 + "end."
    body, caps = sf.split_figures(f"Fig. 1: first sentence ends here.\n{wide}\nshort body\n")
    assert caps == ["Fig. 1: first sentence ends here."]
    assert body.splitlines() == [wide, "short body"]


def body_line(i):  # 单栏书的正文行：本身就有 130+ 字符
    return f"Sentence {i} of the running text in a single wide column, which is long enough that every body line exceeds one hundred characters."


def test_single_column_book_body_is_not_swallowed_after_caption():
    """单栏书正文行也 >100 字符。图注句末结束后，下一行再长也不能并入图注。"""
    assert len(body_line(0)) > 120
    short_cap = "Fig. 3: A short one-line caption."
    wide_cap = "Fig. 4: " + "A caption line in the single column that is even wider than the running text around it, " * 2 + "ends here."
    two_line_first = ("Table 2 " + "A caption whose first line is wide and has no final period so that it must continue " * 2).rstrip()
    lines = [body_line(i) for i in range(4)] + [short_cap] + [body_line(i) for i in range(4, 8)] \
        + [wide_cap] + [body_line(i) for i in range(8, 12)] \
        + [two_line_first, "and ends on a second line."] + [body_line(i) for i in range(12, 16)]
    body, caps = sf.split_figures("\n".join(lines) + "\n")
    assert caps == [short_cap, wide_cap, two_line_first + " and ends on a second line."]
    assert body.splitlines() == [body_line(i) for i in range(16)]  # 16 行正文原样保留，没有被吞，也没有丢


def test_wide_cutoff_adapts_to_body_line_length():
    narrow_doc = ["a" * 57] * 50
    wide_doc = ["a" * 130] * 50
    assert sf.wide_cutoff(narrow_doc) == 100
    assert sf.wide_cutoff(wide_doc) == pytest.approx(169)
    assert sf.wide_cutoff([]) == 100


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
