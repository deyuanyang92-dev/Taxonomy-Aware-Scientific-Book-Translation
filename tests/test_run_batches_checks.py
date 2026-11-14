"""run_batches --mode split / cite：不调模型的书级检查，包住 split_check 与 cite_diff。合成书目录。"""
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def run_cli(book, *args):
    return subprocess.run([sys.executable, str(REPO / "scripts" / "run_batches.py"), str(book), *args],
                          capture_output=True, text=True)


@pytest.fixture
def book(tmp_path):
    (tmp_path / "src_en").mkdir()
    (tmp_path / "译文").mkdir()
    (tmp_path / "src_en" / "body.txt").write_text("Smith (1978) said (Fig. 2).\n", encoding="utf8")
    (tmp_path / "src_en" / "captions.txt").write_text("Fig. 2. Jones and Lee (1980).\n", encoding="utf8")
    return tmp_path


def test_split_clean_and_dirty(book):
    r = run_cli(book, "--mode", "split", "--chapters", "body,captions")
    assert r.returncode == 0, r.stdout + r.stderr
    assert (book / "核译" / "split_check.txt").read_text(encoding="utf8") == ""
    (book / "src_en" / "body.txt").write_text("Text.\n\nScale bar = 10 µm.\n", encoding="utf8")
    r = run_cli(book, "--mode", "split", "--chapters", "body,captions")
    assert r.returncode == 1 and "scale-bar" in r.stdout
    assert "scale-bar" in (book / "核译" / "split_check.txt").read_text(encoding="utf8")


def test_split_needs_two_chapters(book):
    assert run_cli(book, "--mode", "split", "--chapters", "body").returncode != 0


def test_cite_ok_then_changed_year_then_noise_file(book):
    (book / "译文" / "body_直译初译.md").write_text("Smith（1978）说（图2）。\n", encoding="utf8")
    (book / "译文" / "captions_直译初译.md").write_text("图2. Jones 与 Lee（1980）。\n", encoding="utf8")
    r = run_cli(book, "--mode", "cite", "--chapters", "body,captions")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "真差异合计 0" in r.stdout
    (book / "译文" / "body_直译初译.md").write_text("Smith（1979）说（图2）。\n", encoding="utf8")
    r = run_cli(book, "--mode", "cite", "--chapters", "body,captions")
    assert r.returncode == 1 and "真差异合计 2" in r.stdout
    assert "smith, 1979" in (book / "核译" / "cite_diff.tsv").read_text(encoding="utf8")
    (book / "核译" / "cite_noise.tsv").write_text(
        "类型\t对象\t英文次数\t中文次数\t原因\n"
        "citation\tsmith, 1978\t1\t0\t人工核实\ncitation\tsmith, 1979\t0\t1\t人工核实\n", encoding="utf8")
    r = run_cli(book, "--mode", "cite", "--chapters", "body,captions")
    assert r.returncode == 0 and "已确认噪声2" in r.stdout


def test_cite_missing_translation_is_an_error(book):
    r = run_cli(book, "--mode", "cite", "--chapters", "body,captions")
    assert r.returncode == 2
