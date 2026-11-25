import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "bench"))
import zh_run  # noqa: E402


def test_strip_english_caption():
    s = "A detailed scientific illustration showing the dorsal view of an insect.\n\n图 122 双管阔沙蚕"
    out, n = zh_run.strip_gold_artifacts(s)
    assert n == 1 and "图 122" in out and "illustration" not in out


def test_keep_latin_name_paragraph():
    out, n = zh_run.strip_gold_artifacts("Platynereis bicanaliculata (Baird)")
    assert n == 0 and out


def test_strip_header():
    assert zh_run.strip_header("212 中国动物志 环节动物门\n正文").strip() == "正文"
