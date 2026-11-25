"""专名解析：解析顺序（yiku > Wikidata > 无通行名）、网络失败状态、核对规则（不联网）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import entities as en  # noqa: E402


def test_resolve_order_and_failure(monkeypatch):
    monkeypatch.setattr(en, "yiku_zh", lambda n, d: ("《物种起源》", "已核") if "Origin" in n else None)
    monkeypatch.setattr(en, "wikidata_zh", lambda n: ("华莱士", "Q1") if "Wallace" in n else ("", "FAILED"))
    res = en.resolve([{"surface": "the Origin", "canonical": "On the Origin of Species", "type": "book"},
                      {"surface": "Wallace", "canonical": "Alfred Russel Wallace", "type": "person"},
                      {"surface": "Pernau", "canonical": "F. A. Pernau", "type": "person"}], "进化生物学")
    assert [r["status"] for r in res] == ["已核", "候选", "查询失败"]


def test_check_rules():
    res = [{"surface": "the Origin", "zh": "《物种起源》", "status": "已核", "type": "book", "source": "yiku"},
           {"surface": "A. R. Wallace", "zh": "阿尔弗雷德·拉塞尔·华莱士", "status": "候选", "type": "person", "source": "WD"},
           {"surface": "Pernau", "zh": None, "status": "无通行名", "type": "person"}]
    src = "The publication of the Origin ... A. R. Wallace ... Pernau"
    bad = en.check(src, "《起源》的问世……华莱士……Pernau", res)
    assert [(i["severity"], i["surface"]) for i in bad] == [("major", "the Origin")]   # 人名用姓或原文都算合格
    assert en.check(src, "《物种起源》的问世……A. R. Wallace……", res) == []


def test_table_md_marks_candidates():
    md = en.table_md([{"surface": "Ray", "canonical": "John Ray", "zh": "约翰·雷", "status": "候选"},
                      {"surface": "Pernau", "zh": None, "status": "无通行名", "type": "person"}])
    assert "候选" in md and "保留原文" in md
