"""人工小样包：写 CSV、人工填 verdict、读回算残余错误率。"""
from __future__ import annotations

import csv

import pytest
import qa_sample

SRC = {1: "<!-- PDF p.1 | x -->\n\n甲\n\n乙\n\n丙", 2: "<!-- PDF p.2 | x -->\n\n甲\n\n乙"}
TGT = {1: "<!-- PDF p.1 | x -->\n\nA\n\nB\n\nC", 2: "<!-- PDF p.2 | x -->\n\nA\n\nB\n\nC"}   # 第 2 页段数不等


def _sample(n):
    return [{"page": 1, "para": i % 3, "stratum": "description", "text": "x"} for i in range(n)]


def _read(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def test_package_roundtrip_and_score(tmp_path):
    q = [{"page": 1, "para": 0, "reason": "GUARDRAIL"}]
    path = qa_sample.write_package(tmp_path, q, _sample(40), SRC, TGT)
    rows = _read(path)
    assert path == tmp_path / "qa_sample.csv" and len(rows) == 41
    assert list(rows[0]) == ["source", "page", "para", "stratum", "reason", "text_src", "text_tgt", "verdict", "note"]
    assert rows[0]["source"] == "queue" and rows[0]["reason"] == "GUARDRAIL" and rows[1]["source"] == "sample"
    samp = [r for r in rows if r["source"] == "sample"]
    for i, r in enumerate(samp):
        r["verdict"] = "error" if i < 5 else ("unsure" if i < 7 else "ok")
    # 40 行 sample：5 error + 2 unsure + 33 ok → n = 38（unsure 不计入 n）
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    s = qa_sample.score_package(path)
    assert s["n"] == 38 and s["k_error"] == 5 and s["unsure"] == 2
    assert s["rate"] == pytest.approx(5 / 38) and s["by_stratum"]["description"] == {"n": 38, "k_error": 5}


def test_score_matches_brief_numbers_n40_k5_unsure2(tmp_path):
    path = qa_sample.write_package(tmp_path, [], _sample(42), SRC, TGT)
    rows = _read(path)
    for i, r in enumerate(rows):
        r["verdict"] = "error" if i < 5 else ("unsure" if i < 7 else "ok")
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    s = qa_sample.score_package(path)
    assert (s["n"], s["k_error"], s["unsure"]) == (40, 5, 2)
    assert s["wilson"][0] == pytest.approx(0.0546, abs=0.002) and s["wilson"][1] == pytest.approx(0.2611, abs=0.002)


def test_score_ignores_queue_rows_and_unfilled_rows(tmp_path):
    path = qa_sample.write_package(tmp_path, [{"page": 1, "para": 0, "reason": "r"}], _sample(3), SRC, TGT)
    rows = _read(path)
    rows[0]["verdict"] = "error"                 # queue 行的 verdict 不算
    rows[1]["verdict"] = "ok"                    # 只填了 1 个 sample 行
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    s = qa_sample.score_package(path)
    assert (s["n"], s["k_error"], s["unsure"]) == (1, 0, 0)


def test_score_rejects_unknown_verdict_loudly(tmp_path):
    path = qa_sample.write_package(tmp_path, [], _sample(1), SRC, TGT)
    rows = _read(path)
    rows[0]["verdict"] = "wrong"
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    with pytest.raises(ValueError, match="verdict"):
        qa_sample.score_package(path)


def test_score_empty_sample_gives_whole_interval(tmp_path):
    path = qa_sample.write_package(tmp_path, [], [], SRC, TGT)
    s = qa_sample.score_package(path)
    assert s["n"] == 0 and s["rate"] is None and s["wilson"] == (0.0, 1.0)


def test_text_src_is_same_index_paragraph_when_counts_equal(tmp_path):
    path = qa_sample.write_package(tmp_path, [], [{"page": 1, "para": 1, "stratum": "key", "text": "B"}], SRC, TGT)
    r = _read(path)[0]
    assert r["text_src"] == "乙" and r["text_tgt"] == "B"


def test_text_src_is_whole_page_when_paragraph_counts_differ(tmp_path):
    path = qa_sample.write_package(tmp_path, [], [{"page": 2, "para": 1, "stratum": "key", "text": "B"}], SRC, TGT)
    r = _read(path)[0]
    assert "甲" in r["text_src"] and "乙" in r["text_src"] and r["text_tgt"] == "B"


def test_chinese_and_quotes_survive_csv_roundtrip(tmp_path):
    src = {1: '<!-- PDF p.1 | x -->\n\n体は"細長い"。\n第二行'}
    path = qa_sample.write_package(tmp_path, [], [{"page": 1, "para": 0, "stratum": "key", "text": 'a, "b"\nc'}],
                                   src, {1: "<!-- PDF p.1 | x -->\n\nx"})
    r = _read(path)[0]
    assert r["text_src"] == '体は"細長い"。\n第二行' and r["text_tgt"] == 'a, "b"\nc'
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")        # BOM：Excel 直接打开不乱码
