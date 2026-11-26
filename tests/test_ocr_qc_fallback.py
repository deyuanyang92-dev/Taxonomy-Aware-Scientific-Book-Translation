from docstore import ocr_batch
from docstore.engines import paddle_vl


def test_layout_fallback_only_qc_short_and_respects_remaining(monkeypatch, tmp_path):
    calls = {}

    def fake_run_pages(pdf, pages, *, log=print, opt=None):
        calls["pages"] = list(pages)
        calls["opt"] = opt
        return {"ok": {n: ("脚注文本" * 50, {}) for n in pages}, "failed": {}, "quota_hit": False}

    monkeypatch.setattr(paddle_vl, "run_pages", fake_run_pages)
    monkeypatch.setattr(ocr_batch, "qc_pages", lambda src, ok: {})
    added = []
    monkeypatch.setattr(ocr_batch, "quota_add", lambda p, n: added.append(n))

    res = {"ok": {1: ("短", {}), 2: ("短", {}), 3: ("正常文本", {})}, "failed": {}}
    qc_bad = {1: "qc_short: a", 2: "qc_short: b", 4: "qc_empty: c"}
    used = ocr_batch.layout_fallback(None, tmp_path / "x.pdf", "x.pdf", res, qc_bad, 1, lambda m: None)

    assert used == 1 and added == []  # p=None: 不记额度
    assert calls["pages"] == [1]  # 额度只够 1 页，按页码升序取前 1 页，且只取 qc_short
    assert calls["opt"] == ocr_batch.LAYOUT_OFF_OPT
    assert res["ok"][1][1]["ocr_opt"] == "layout_off"
    assert 1 not in qc_bad and 2 in qc_bad and 4 in qc_bad


def test_layout_fallback_no_call_without_quota_or_candidates(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise AssertionError("must not submit")

    monkeypatch.setattr(paddle_vl, "run_pages", boom)
    res = {"ok": {}, "failed": {}}
    assert ocr_batch.layout_fallback(None, tmp_path / "x.pdf", "x.pdf", res, {1: "qc_short: a"}, 0, print) == 0
    assert ocr_batch.layout_fallback(None, tmp_path / "x.pdf", "x.pdf", res, {1: "qc_empty: a"}, 5, print) == 0


def test_run_pages_passes_opt_to_chunks(monkeypatch):
    seen = {}
    monkeypatch.setattr(paddle_vl, "_token", lambda: "t")
    monkeypatch.setattr(paddle_vl, "_is_blank", lambda pdf, p: False)
    monkeypatch.setattr(paddle_vl, "plan_chunks", lambda pdf, pages: ([(list(pages), b"x")], {}))

    def fake_chunk(pdf, ps, *, out=None, opt=None, **kw):
        seen["opt"] = opt
        out[0].update({n: ("t", {}) for n in ps})

    monkeypatch.setattr(paddle_vl, "run_chunk", fake_chunk)
    r = paddle_vl.run_pages("x.pdf", [1], log=lambda m: None, opt=ocr_batch.LAYOUT_OFF_OPT)
    assert seen["opt"] == ocr_batch.LAYOUT_OFF_OPT
    assert r["ok"][1][0] == "t"
