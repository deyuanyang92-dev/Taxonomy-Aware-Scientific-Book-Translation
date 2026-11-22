"""scripts/bench/run.py：统一评测台入口。引擎调用全部 mock。"""
import csv

import pytest

import run as benchrun

FIELDS = ["id", "lang", "stage", "pdf", "page", "gold_path", "gold_source", "gold_level", "split"]


def _manifest(tmp_path, rows):
    p = tmp_path / "samples.csv"
    with open(p, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    return p


def _row(tmp_path, i, lang="ja", split="dev", gold="多毛類の分類"):
    g = tmp_path / f"{i}.txt"
    g.write_text(gold, encoding="utf-8")
    return dict(id=i, lang=lang, stage="ocr", pdf="x.pdf", page=1, gold_path=str(g),
                gold_source="test", gold_level="G0", split=split)


def test_run_ocr_returns_fields_and_appends_ledger(tmp_path):
    m = _manifest(tmp_path, [_row(tmp_path, "a"), _row(tmp_path, "b")])
    ledger = tmp_path / "LEDGER.tsv"
    ledger.write_text("date\tengine_params\tset\tmetric\tresult\tcost\tsource\n", encoding="utf-8")
    texts = {"a": "多毛類の分類", "b": "多毛類の分頬"}
    r = benchrun.run("ocr", "ja", "fake", manifest=m, ledger=ledger,
                     runner=lambda row: (texts[row["id"]], 0.0))
    assert r["n"] == 2 and r["cost"] == 0
    assert r["cer"] == pytest.approx((0 + 1 / 6) / 2)
    assert r["split"] == "dev"
    lines = ledger.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2 and "fake" in lines[1] and "n=2" in lines[1]


def test_run_filters_lang_and_split(tmp_path):
    m = _manifest(tmp_path, [_row(tmp_path, "a"), _row(tmp_path, "b", lang="de"),
                             _row(tmp_path, "c", split="sealed")])
    r = benchrun.run("ocr", "ja", "fake", manifest=m, ledger=None, runner=lambda row: ("x", 0.0))
    assert r["n"] == 1


def test_sealed_split_requires_explicit_flag(tmp_path):
    m = _manifest(tmp_path, [_row(tmp_path, "c", split="sealed")])
    with pytest.raises(ValueError, match="sealed"):
        benchrun.run("ocr", "ja", "fake", manifest=m, ledger=None, split="sealed",
                     runner=lambda row: ("x", 0.0))
    r = benchrun.run("ocr", "ja", "fake", manifest=m, ledger=None, split="sealed",
                     runner=lambda row: ("x", 0.0), allow_sealed=True)
    assert r["n"] == 1


def test_no_samples_reports_n0_not_nan(tmp_path):
    m = _manifest(tmp_path, [_row(tmp_path, "a")])
    r = benchrun.run("ocr", "ru", "fake", manifest=m, ledger=None, runner=lambda row: ("x", 0.0))
    assert r["n"] == 0 and r["cer"] is None and "样本不足" in r["note"]
