"""split_check：正文流里混入的图注残段、图注尾巴、仅有图号的图注。合成文本，不联网。"""
import subprocess
import sys
from pathlib import Path

import split_check as sc

REPO = Path(__file__).resolve().parent.parent
BODY = "The worm is small.\n\nIt lives in sand.\n"
CAPS = "Fig. 1. The worm. Scale bar = 1 mm.\n\nFig. 2. Another worm.\n"


def kinds(body, caps=CAPS):
    return [(s.file, s.line, s.kind) for s in sc.check_text(body, caps)]


def test_clean_input_has_no_suspects():
    assert kinds(BODY) == []


def test_abbreviation_key_in_body_is_flagged_with_line_number():
    body = "Intro.\n\nbr, brain; cc, ciliary cell; ne, nerve; mo, mouth;\n\nOutro.\n"
    assert kinds(body) == [("body", 3, "abbr-key")]


def test_two_abbreviation_pairs_are_not_enough():
    assert kinds("The structures (br, brain; cc, ciliary cell.) differ.\n") == []


def test_paragraph_starting_with_one_abbreviation_pair():
    assert kinds("Text.\n\nbr, brain; the rest.\n") == [("body", 3, "abbr-key-start")]


def test_scale_bar_paragraph_in_body():
    assert kinds("Text.\n\nScale bar = 10 µm.\n") == [("body", 3, "scale-bar")]


def test_long_paragraph_mentioning_scale_bar_late_is_not_flagged():
    long = "x " * 200 + "Scale bar = 10 µm."
    assert kinds(long + "\n") == []


def test_caption_label_paragraph_in_body_but_not_ordinary_figure_sentence():
    assert kinds("Fig. 3. Dorsal view.\n") == [("body", 1, "caption-start")]
    assert kinds("Figs 4A–C. Details.\n") == [("body", 1, "caption-start")]
    assert kinds("Fig. 3 shows the head.\n") == []


def test_lowercase_start_after_hyphen_ending_paragraph():
    body = "The sup-\n\nports are long.\n"
    assert kinds(body) == [("body", 3, "hyphen-continuation")]


def test_lowercase_start_after_normal_paragraph_is_not_flagged():
    assert kinds("Text.\n\nde Beauchamp (1900) said so.\n") == []


def test_caption_ending_with_hyphen_is_incomplete():
    caps = "Fig. 1. The anterior seg-\n\nFig. 2. Fine.\n"
    assert kinds(BODY, caps) == [("captions", 1, "caption-hyphen-end")]


def test_bare_figure_label_caption_is_flagged_whatever_follows():
    caps = "Fig. 1.\n\nFig. 2. Fine.\n\nFig. 3, 4.\n\nDetached text of fig. 3.\n"
    assert kinds(BODY, caps) == [("captions", 1, "bare-caption"), ("captions", 5, "bare-caption")]


def test_bare_caption_message_says_whether_text_may_be_detached():
    caps = "Fig. 1.\n\nFig. 2.\n\nDetached text.\n"
    first, second = sc.check_text(BODY, caps)
    assert "下一段" not in first.detail and "下一段" in second.detail


def test_page_markers_are_ignored_but_line_numbers_are_file_lines():
    body = "Text.\n<!-- p.5 -->\n\nbr, brain; cc, cell; ne, nerve;\n"
    assert kinds(body) == [("body", 4, "abbr-key")]


def run(*args):
    return subprocess.run([sys.executable, str(REPO / "scripts" / "split_check.py"), *map(str, args)],
                          capture_output=True, text=True)


def test_cli_exit_codes(tmp_path):
    (tmp_path / "caps.txt").write_text(CAPS, encoding="utf8")
    (tmp_path / "ok.txt").write_text(BODY, encoding="utf8")
    r = run(tmp_path / "ok.txt", tmp_path / "caps.txt")
    assert r.returncode == 0 and "0 处" in r.stdout
    (tmp_path / "bad.txt").write_text("Text.\n\nScale bar = 10 µm.\n", encoding="utf8")
    r = run(tmp_path / "bad.txt", tmp_path / "caps.txt")
    assert r.returncode == 1
    assert "bad.txt:3" in r.stdout and "scale-bar" in r.stdout


def test_cli_missing_file_is_usage_error(tmp_path):
    assert run(tmp_path / "x.txt", tmp_path / "y.txt").returncode == 2
