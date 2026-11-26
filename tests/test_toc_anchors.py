"""scripts/publish/toc_anchors: 三级目录判定、锚点、书签。合成数据，不需要 Word。"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "publish"))
import toc_anchors as T  # noqa: E402

SEC = re.compile(r"^7\.\d+(?![\d.])")


def test_classify_levels():
    assert T.classify_title("第 3 章 X", 1) == 1 and T.classify_title("附录 A", 1) == 1
    assert T.classify_title("7.12 游走类", 1, SEC) == 2 and T.classify_title("7.12 游走类", 1) is None
    assert T.classify_title("7.12.1 形态", 1, SEC) is None
    assert T.classify_title("7.3.2 海稚虫科 Spionidae", 2) == 3
    assert T.classify_title("7.3.2 形态", 2) is None          # numbered but not a family
    assert T.classify_title("海稚虫科 Spionidae", 2) is None  # family without number stays out of TOC


def test_label():
    assert T.toc_label("第 3 章 海稚虫") == "3  海稚虫" and T.toc_label("7.4 X") == "7.4 X"


def test_vol_units_and_collect(tmp_path):
    man = [{"key": "a", "parts": [{"vol": "vol1"}]}, {"key": "b", "parts": [{"vol": "vol2"}]},
           {"key": "c", "parts": [{"vol": "vol2"}, {"vol": "vol1"}]}]
    mp = tmp_path / "m.json"
    mp.write_text(json.dumps(man), encoding="utf-8")
    assert T.vol_units(mp, "vol1") == ["a", "c"]
    (tmp_path / "a.md").write_text("# 第 1 章 甲\n## 1.1 引言\n", encoding="utf-8")
    (tmp_path / "c.md").write_text("# 7.4 乙\n## 7.4.1 丙科 Cirratulidae\n", encoding="utf-8")
    es = T.collect_entries(tmp_path, ["a", "c"], SEC, "HB_")
    assert [(e["level"], e["anchor"]) for e in es] == [(1, "HB_0001"), (2, "HB_0002"), (3, "HB_0003")]


def test_bookmark_roundtrip(tmp_path):
    import docx
    d = docx.Document()
    p = d.add_paragraph("标题")
    T.add_bookmark(p, "HB_0001", 1)
    f = tmp_path / "t.docx"
    d.save(str(f))
    assert T.bookmark_names(f, "HB_") == ["HB_0001"]
