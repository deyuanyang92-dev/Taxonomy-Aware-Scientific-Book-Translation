"""join_page_breaks：页码标记不得把一句话切成两段。合成文本，不联网。"""
import subprocess
import sys
from pathlib import Path

import join_page_breaks as jp

REPO = Path(__file__).resolve().parent.parent


def test_sentence_split_by_marker_is_merged_and_marker_moved_after():
    text = "前文。\n\n甲与乙（1986）并未观察到\n\n<!-- p.34 -->\n\n神经成分与腺细胞之间的突触。\n\n下一段。\n"
    out, ch = jp.join_text(text)
    assert out == "前文。\n\n甲与乙（1986）并未观察到神经成分与腺细胞之间的突触。\n\n<!-- p.34 -->\n\n下一段。\n"
    assert len(ch) == 1 and ch[0].marker == "34"


def test_finished_paragraph_is_not_merged():
    text = "甲。\n\n<!-- p.5 -->\n\n乙。\n"
    assert jp.join_text(text) == (text, [])
    for tail in ("。", "！", "？", "…", "。）", "。」", "。[OCR?]", "."):
        t = f"甲乙{tail}\n\n<!-- p.5 -->\n\n丙。\n"
        assert jp.join_text(t) == (t, []), tail


def test_closing_bracket_without_period_is_unfinished():
    out, ch = jp.join_text("见 Gelder（1986）\n\n<!-- p.9 -->\n\n并未观察到。\n")
    assert out == "见 Gelder（1986）并未观察到。\n\n<!-- p.9 -->\n"
    assert len(ch) == 1


def test_headings_captions_tables_and_lists_are_never_merged():
    for first, second in [("#### 角质层", "神经成分。"), ("甲乙丙", "#### 角质层"), ("甲乙丙", "图 5 欧文虫。"),
                          ("甲乙丙", "**图5.** 欧文虫。"), ("图 5 欧文虫", "接着是说明。"), ("**图5.** 欧文虫", "说明。"),
                          ("| 种 | 数 |", "|---|---|"), ("甲乙丙", "| 种 | 数 |"), ("- 背血管", "神经成分。"),
                          ("甲乙丙", "- 背血管"), ("**材料与方法**", "神经成分。")]:
        t = f"{first}\n\n<!-- p.5 -->\n\n{second}\n"
        assert jp.join_text(t) == (t, []), (first, second)


def test_italic_start_is_continuation_not_list_bullet():
    out, ch = jp.join_text("如图所示的\n\n<!-- p.5 -->\n\n*Owenia fusiformis* 的鳃。\n")
    assert out == "如图所示的*Owenia fusiformis* 的鳃。\n\n<!-- p.5 -->\n"
    assert len(ch) == 1


def test_latin_words_joined_with_a_space():
    out, _ = jp.join_text("as in Smith\n\n<!-- p.5 -->\n\nand Jones (1980)。\n")
    assert out.startswith("as in Smith and Jones (1980)。\n\n<!-- p.5 -->")


def test_consecutive_markers_move_together_and_chain_merges_across_three_pages():
    text = "甲乙\n\n<!-- p.1 -->\n\n丙丁\n\n<!-- p.2 -->\n\n戊己。\n\n庚。\n"
    out, ch = jp.join_text(text)
    assert out == "甲乙丙丁戊己。\n\n<!-- p.1 -->\n\n<!-- p.2 -->\n\n庚。\n"
    assert [c.marker for c in ch] == ["1", "2"]
    out2, _ = jp.join_text("甲乙\n\n<!-- p.1 -->\n\n<!-- p.2 -->\n\n戊己。\n")
    assert out2 == "甲乙戊己。\n\n<!-- p.1 -->\n\n<!-- p.2 -->\n"


def test_marker_at_end_without_following_paragraph_and_start_without_paragraph_untouched():
    t = "甲乙\n\n<!-- p.1 -->\n"
    assert jp.join_text(t) == (t, [])
    t2 = "<!-- p.1 -->\n\n甲乙。\n\n<!-- p.2 -->\n\n丙。\n"
    assert jp.join_text(t2) == (t2, [])


def test_idempotent():
    text = "甲乙\n\n<!-- p.34 -->\n\n丙丁。\n\n戊\n\n<!-- p.35 -->\n\n己。\n"
    once, ch = jp.join_text(text)
    assert len(ch) == 2
    assert jp.join_text(once) == (once, [])


def test_marker_stays_between_the_same_pages():
    """合并后标记仍在「第 N-1 页内容」与「第 N 页后续内容」之间：标记之后只剩原来排在 Q 之后的段落。"""
    out, _ = jp.join_text("<!-- p.33 -->\n\n甲乙\n\n<!-- p.34 -->\n\n丙丁。\n\n戊己。\n")
    assert out == "<!-- p.33 -->\n\n甲乙丙丁。\n\n<!-- p.34 -->\n\n戊己。\n"
    assert out.index("<!-- p.33 -->") < out.index("甲乙") < out.index("<!-- p.34 -->") < out.index("戊己")


def test_cli_dry_run_then_fix_with_backup(tmp_path):
    f = tmp_path / "t.md"
    f.write_text("甲乙\n\n<!-- p.34 -->\n\n丙丁。\n", encoding="utf8")
    cmd = [sys.executable, str(REPO / "scripts" / "join_page_breaks.py")]
    r = subprocess.run([*cmd, str(f)], capture_output=True, text=True)
    assert r.returncode == 1 and "p.34" in r.stdout and "1" in r.stdout
    assert f.read_text(encoding="utf8") == "甲乙\n\n<!-- p.34 -->\n\n丙丁。\n"
    r = subprocess.run([*cmd, str(f), "--fix"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert f.read_text(encoding="utf8") == "甲乙丙丁。\n\n<!-- p.34 -->\n"
    assert (tmp_path / "t.md.bak-joinpages").read_text(encoding="utf8").startswith("甲乙\n\n<!-- p.34")
    assert subprocess.run([*cmd, str(f)], capture_output=True, text=True).returncode == 0


def test_italic_name_split_across_pages_becomes_one_italic_span_and_connector_gets_space():
    out, _ = jp.join_text("见 *Flabelliderma*\n\n<!-- p.50 -->\n\n*commensalis* (Spies, 1973)。\n")
    assert out.startswith("见 *Flabelliderma commensalis* (Spies, 1973)。\n\n<!-- p.50 -->")
    out, _ = jp.join_text("（见 Gardiner\n\n<!-- p.46 -->\n\n与 Rieger, 1980）。\n")
    assert out.startswith("（见 Gardiner 与 Rieger, 1980）。")
