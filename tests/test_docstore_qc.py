"""Tests for docstore qc risk routing."""

from __future__ import annotations

from docstore import open_store, qc, textify
from docstore.store import make_version
from tests.test_docstore import make_pdf


def test_score_page_routes(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCSTORE_AGENT", "pytest")
    cfg = {
        "thresholds": {
            "pass_max": 2.0,
            "human_min": 5.0,
            "min_ocr_conf": 0.85,
            "min_chars": 30,
            "max_garble": 0,
            "max_unknown_latin": 99,
            "max_unknown_zh_taxon": 99,
            "prefer_dpi": 300,
        },
        "weights": {
            "low_conf": 2.0,
            "low_chars": 2.0,
            "garble": 3.0,
            "low_dpi": 2.5,
            "unknown_latin": 0.5,
            "unknown_zh": 0.3,
            "no_consensus": 1.0,
            "digit_dense_anomaly": 1.0,
        },
        "yiku": {"db": str(tmp_path / "missing.db")},
    }
    yiku = qc.YikuIndex(tmp_path / "missing.db")
    good = make_version(
        "欧努菲虫科 Onuphidae 口前叶具触手。" * 3,
        "ocr",
        producer="rapidocr",
        engine="rapidocr 300dpi",
        dpi=300,
        conf=0.95,
        level="ocr_raw",
    )
    good.update(key="k", page=1)
    r = qc.score_page(good, cfg=cfg, yiku=yiku, has_multi_ocr=True)
    assert r.action == "pass", r

    low = make_version(
        "少",
        "ocr",
        producer="rapidocr",
        engine="rapidocr 200dpi",
        dpi=200,
        conf=0.5,
        level="ocr_raw",
    )
    low.update(key="k", page=2)
    r2 = qc.score_page(low, cfg=cfg, yiku=yiku, has_multi_ocr=False)
    assert r2.action in ("redo", "human"), r2
    assert r2.score >= 2.0

    garb = make_version("x\ufffd\u25a1", "ocr", producer="rapidocr", dpi=300, conf=0.9, level="ocr_raw")
    garb.update({"key": "k", "page": 3})
    r3 = qc.score_page(garb, cfg=cfg, yiku=yiku, has_multi_ocr=True)
    assert r3.action == "human"

    verified = make_version("已核", "verified", producer="glm", level="ocr_verified")
    verified.update(key="k", page=4)
    assert qc.score_page(verified, cfg=cfg, yiku=yiku).action == "skip"


def test_run_qc_apply_pass_keeps_alt(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCSTORE_AGENT", "pytest")
    monkeypatch.setattr(textify, "OCR_FUNC", lambda pdf, n, dpi: (f"桩字{n}" * 20, 0.96))
    src = tmp_path / "src"
    src.mkdir()
    pdf = make_pdf(src / "qc书.pdf", [None, None])
    st = open_store(tmp_path / "lib")
    key, _ = st.register(pdf, by="pytest")
    # force ocr_raw pages
    for n in (1, 2):
        st.put_version(
            key,
            n,
            make_version(
                f"内容页{n}" * 20,
                "ocr",
                producer="rapidocr",
                engine="rapidocr 300dpi",
                dpi=300,
                conf=0.96,
                level="ocr_raw",
            ),
        )
    cfg = qc.load_config()
    cfg.setdefault("thresholds", {})["max_unknown_latin"] = 99
    cfg.setdefault("thresholds", {})["max_unknown_zh_taxon"] = 99
    cfg.setdefault("yiku", {})["db"] = str(tmp_path / "no.db")
    r = qc.run_qc(st, key, by="cursor", apply=True, redo=False, cfg=cfg, log=lambda m: None)
    assert r["counts"]["pass"] >= 1
    assert r["counts"]["applied_pass"] >= 1
    p = st.page(key, 1)
    assert p["verify_level"] == "ocr_sampled"
    assert p["producer"] == "cursor"
    assert p["alternates"]
    assert p["history"][-1]["action"] == "qc_pass"
    # resume: second run should not duplicate apply for same sha
    r2 = qc.run_qc(st, key, by="cursor", apply=True, cfg=cfg, log=lambda m: None)
    assert r2["counts"]["applied_pass"] == 0
    log = (st.root / "quality" / "qc" / f"{key}.jsonl").read_text(encoding="utf-8")
    assert "pass" in log


def test_cli_qc_calibrate_flag(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCSTORE_AGENT", "pytest")
    st = open_store(tmp_path / "lib")
    # empty store calibrate returns zeros
    out = qc.calibrate(st, cfg=qc.load_config())
    assert out["scored_pages"] == 0
    assert "dpi_ge_prefer" in out and "recall" in out["dpi_ge_prefer"]
