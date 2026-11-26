"""回归测试：无版面重提（远程 OCR）期间，其他线程的 log() 不得阻塞（2026-11-26 卡死根因）。"""
import threading

from docstore import ocr_batch as ob


def test_layout_fallback_does_not_block_log(monkeypatch, tmp_path):
    started = threading.Event()
    release = threading.Event()

    def slow_fallback(p, src, rel, res, qc_bad, remaining, log):
        started.set()
        release.wait(5)
        return remaining

    monkeypatch.setattr(ob, "layout_fallback", slow_fallback)
    monkeypatch.setattr(ob, "quota_today", lambda p: 0)
    monkeypatch.setattr(ob, "quota_add", lambda p, n: None)
    res = {"ok": {}}
    qc_bad = {1: "qc_short: x"}
    worker = threading.Thread(target=ob._layout_fallback_locked,
                              args=(None, tmp_path / "a.pdf", "a.pdf", res, qc_bad, lambda m: None))
    worker.start()
    try:
        assert started.wait(2)
        done = threading.Event()

        def other():
            ob.log("probe")
            done.set()

        threading.Thread(target=other, daemon=True).start()
        assert done.wait(2), "log() 被无版面重提阻塞：layout_fallback 仍在全局锁内"
    finally:
        release.set()
        worker.join(5)


def test_layout_fallback_reserves_quota_and_caps(monkeypatch, tmp_path):
    added = []
    monkeypatch.setattr(ob, "quota_today", lambda p: 28998)
    monkeypatch.setattr(ob, "quota_add", lambda p, n: added.append(n))
    monkeypatch.setattr(ob, "DAILY_CAP", 29000)
    seen = {}

    def fake(p, src, rel, res, qc_bad, remaining, log):
        seen["remaining"] = remaining
        return remaining

    monkeypatch.setattr(ob, "layout_fallback", fake)
    qc_bad = {n: "qc_short: x" for n in range(1, 6)}
    remaining, used = ob._layout_fallback_locked(object(), tmp_path / "a.pdf", "a.pdf", {"ok": {}}, qc_bad, lambda m: None)
    assert remaining == 2 and used == 2 and seen["remaining"] == 2
    assert added == [2]
