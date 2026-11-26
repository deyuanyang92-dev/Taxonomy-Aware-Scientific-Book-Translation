"""ocr_batch 测试：由项目脚本 paddle_batch 迁入（5 个）+ 版面保存 + backfill-layout。"""
import json
import os
import threading
import types
from pathlib import Path

import fitz
import pytest

from docstore import ocr_batch as ob
from docstore.engines import paddle_vl

H = ["time", "file", "page", "reason"]


def mkpaths(tmp_path: Path) -> ob.Paths:
    src = tmp_path / "src"
    src.mkdir(parents=True, exist_ok=True)
    root = src / "_PaddleOCR"
    root.mkdir(exist_ok=True)
    return ob.Paths(root, src)


def mkpdf(path: Path, n: int = 2, text: str = "hello world") -> None:
    d = fitz.open()
    for i in range(n):
        pg = d.new_page()
        pg.insert_text((72, 72), f"{text} {i + 1}")
    d.save(path)


def test_log_inside_lock_does_not_deadlock():
    done = threading.Event()

    def run():
        with ob._lock:
            ob.log("x")
        done.set()

    t = threading.Thread(target=run, daemon=True)
    t.start()
    assert done.wait(3), "log() 在持锁时死锁"


def test_quota_failures_do_not_consume_tries(tmp_path):
    p = mkpaths(tmp_path)
    for r in ["quota: HTTP 403 code=12001", "transient: x", "empty_suspect: y"]:
        ob.append_tsv(p.failed, ["t", "a.pdf", "1", r], H)
    assert ob.tries_by_page(p) == {("a.pdf", "1"): ob.MAX_TRIES}


def test_empty_return_blocks_resubmit_until_unblock(tmp_path):
    """2026-11-25 用户：空返回不要无脑重试。一次 empty_suspect 即封住，unblock 后才多 1 次。"""
    p = mkpaths(tmp_path)
    ob.append_tsv(p.failed, ["2026-11-24T01:00:00", "a.pdf", "5", "empty_suspect: y"], H)
    assert ob.tries_by_page(p)[("a.pdf", "5")] >= ob.MAX_TRIES
    ob.append_tsv(p.unblock, ["2026-11-25T10:00:00", "a.pdf", "5"], ["time", "file", "page"])
    assert ob.tries_by_page(p).get(("a.pdf", "5"), 0) < ob.MAX_TRIES
    ob.append_tsv(p.failed, ["2026-11-25T11:00:00", "a.pdf", "5", "empty_suspect: y"], H)
    assert ob.tries_by_page(p)[("a.pdf", "5")] >= ob.MAX_TRIES


def test_halt_file_stops_run(tmp_path, monkeypatch):
    p = mkpaths(tmp_path)
    p.manifest.write_text("file\tpages\n")
    p.halt.write_text("x")
    monkeypatch.setattr(ob, "cmd_reclassify", lambda p_, a: None)
    with pytest.raises(SystemExit) as e:
        ob.cmd_run(p, types.SimpleNamespace(ignore_window=True, limit=None, workers=1))
    assert e.value.code == 4


def test_preflight_flags_truly_empty_page(tmp_path):
    p = mkpaths(tmp_path)
    d = fitz.open()
    d.new_page()
    d.save(p.src / "e.pdf")
    r = ob.preflight(p, "e.pdf", [1])[0]
    assert "实为空页" in r["issues"]


def test_paths_defaults(tmp_path):
    p = ob.Paths.make(tmp_path / "root")
    assert p.src == (tmp_path / "root").resolve().parent
    assert p.halt.name == "空返回_已停跑.txt" and p.report.name == "失败清单.txt"


# ---- 版面保存

def _fake_run_pages(text="alpha beta gamma delta", imgs=None):
    def run(pdf_path, pages, *, log=print):
        ok = {}
        for n in pages:
            lay = {"width_px": 1, "height_px": 1, "pruned_result": {"x": 1}, "page": n,
                   "markdown": {"text": text, "images": imgs or {}}, "outputImages": {"a": "http://x/a.jpg"},
                   "inputImage": "http://x/in.jpg"}
            ok[n] = (text, {"model": "M", "job_id": "123", "trace_id": "t", "chunk": 1, "empty_reason": None,
                            "seconds": 1.0, "_layout": lay, "_raw_jsonl": '{"result":{}}\n'})
        return {"ok": ok, "failed": {}, "quota_hit": False}
    return run


def test_process_saves_layout(tmp_path, monkeypatch):
    p = mkpaths(tmp_path)
    mkpdf(p.src / "a.pdf", 2, "alpha beta gamma delta " * 5)
    monkeypatch.setattr(paddle_vl, "run_pages", _fake_run_pages())
    ob.stop_evt.clear()
    ob.process(p, "a.pdf", 2)
    j = json.loads((p.out / "a.pdf.json").read_text())
    assert j["pages"]["1"]["layout"] == "layout/a.pdf/p0001.json"
    for k in ("model", "job_id", "trace_id", "chunk", "empty_reason", "seconds", "text"):
        assert k in j["pages"]["1"]
    assert (p.out / "layout/a.pdf/p0001.json").exists() and (p.out / "layout/a.pdf/p0002.json").exists()
    assert (p.out / "layout/a.pdf/jobs/123.jsonl").exists()
    rec = json.loads((p.out / "layout/a.pdf/p0001.json").read_text())
    assert rec["markdown"]["text"] and rec["outputImages"] and rec["inputImage"]


def test_process_partial_submit_at_cap(tmp_path, monkeypatch):
    p = mkpaths(tmp_path)
    mkpdf(p.src / "a.pdf", 5, "alpha beta gamma delta " * 5)
    p.quota.write_text(json.dumps({str(ob.dt.date.today()): ob.DAILY_CAP - 2}))
    seen = []
    inner = _fake_run_pages()

    def run(pdf_path, pages, *, log=print):
        seen.append(list(pages))
        return inner(pdf_path, pages, log=log)
    monkeypatch.setattr(paddle_vl, "run_pages", run)
    ob.stop_evt.clear()
    ob.process(p, "a.pdf", 5)
    assert seen == [[1, 2]]
    assert ob.quota_today(p) == ob.DAILY_CAP
    assert ob.stop_evt.is_set()
    seen.clear()
    ob.process(p, "a.pdf", 5)  # 额度已满：不再提交
    assert seen == []
    ob.stop_evt.clear()


def test_process_without_layout_gives_none(tmp_path, monkeypatch):
    p = mkpaths(tmp_path)
    mkpdf(p.src / "a.pdf", 1, "alpha beta gamma delta " * 5)

    def run(pdf_path, pages, *, log=print):
        return {"ok": {1: ("alpha beta gamma delta", {"model": "M", "job_id": "9"})}, "failed": {}, "quota_hit": False}
    monkeypatch.setattr(paddle_vl, "run_pages", run)
    ob.stop_evt.clear()
    ob.process(p, "a.pdf", 1)
    assert json.loads((p.out / "a.pdf.json").read_text())["pages"]["1"]["layout"] is None


def test_old_format_resumes_without_resubmit(tmp_path, monkeypatch):
    p = mkpaths(tmp_path)
    mkpdf(p.src / "a.pdf", 3, "alpha beta gamma delta " * 5)
    (p.out).mkdir()
    old = {"file": "a.pdf", "pages": {"1": {"text": "alpha", "model": "M", "job_id": "1", "trace_id": None,
                                            "chunk": 1, "empty_reason": None, "seconds": 1.0}},
           "source": "x", "model": "M", "page_count": 3}
    (p.out / "a.pdf.json").write_text(json.dumps(old))
    asked = []
    inner = _fake_run_pages()

    def run(pdf_path, pages, *, log=print):
        asked.append(list(pages))
        return inner(pdf_path, pages, log=log)
    monkeypatch.setattr(paddle_vl, "run_pages", run)
    ob.stop_evt.clear()
    ob.process(p, "a.pdf", 3)
    assert asked == [[2, 3]]
    j = json.loads((p.out / "a.pdf.json").read_text())
    assert "layout" not in j["pages"]["1"] and j["pages"]["2"]["layout"]
    # audit 不把 out/layout/ 下文件当作未登记结果
    p.manifest.write_text("file\tpages\tbytes\ttext_layer\terror\na.pdf\t3\t1\t0\t\n")
    assert not [i for i in ob.audit(p) if "layout" in i and "不在 manifest" in i]


class FakeResp:
    def __init__(self, status=200, content=b"IMG", text="", js=None):
        self.status_code, self.content, self.text, self._js = status, content, text, js

    def json(self):
        return self._js


class FakeSession:
    def __init__(self, routes=None):
        self.routes, self.calls = routes or {}, []

    def get(self, url, **kw):
        self.calls.append(url)
        r = self.routes.get(url)
        if r is None:
            raise OSError("no route")
        return r


def test_save_images_downloads_and_rejects_traversal(tmp_path):
    lay = {"markdown": {"images": {"imgs/a.jpg": "http://x/a", "../evil.jpg": "http://x/e", "/abs.jpg": "http://x/f",
                                   "imgs/bad.jpg": "http://x/bad", "imgs/net.jpg": "http://x/net"}}}
    s = FakeSession({"http://x/a": FakeResp(content=b"AAA"), "http://x/e": FakeResp(), "http://x/f": FakeResp(),
                     "http://x/bad": FakeResp(status=404)})
    d = tmp_path / "d"
    res = paddle_vl.save_images(d, lay, s)
    assert res["imgs/a.jpg"] == "img/imgs/a.jpg" and (d / "img/imgs/a.jpg").read_bytes() == b"AAA"
    assert res["../evil.jpg"].startswith("ERR") and res["/abs.jpg"].startswith("ERR")
    assert res["imgs/bad.jpg"].startswith("ERR") and res["imgs/net.jpg"].startswith("ERR")
    assert not (tmp_path / "evil.jpg").exists()
    assert "http://x/e" not in s.calls and "http://x/f" not in s.calls
    assert paddle_vl.save_images(d, {"markdown": None}, s) == {}


def test_save_layout_download_images(tmp_path):
    lay = {"page": 1, "markdown": {"images": {"imgs/a.jpg": "http://x/a"}}}
    meta = {"_layout": lay, "_raw_jsonl": "{}\n", "job_id": "7"}
    paddle_vl.save_layout(tmp_path, "k.pdf", 1, meta, download_images=True,
                          session=FakeSession({"http://x/a": FakeResp(content=b"Z")}))
    rec = json.loads((tmp_path / "layout/k.pdf/p0001.json").read_text())
    assert rec["images_local"] == {"imgs/a.jpg": "p0001/img/imgs/a.jpg"}
    assert (tmp_path / "layout/k.pdf/p0001/img/imgs/a.jpg").read_bytes() == b"Z"
    paddle_vl.save_layout(tmp_path, "k.pdf", 2, {"_layout": {"page": 2}, "_raw_jsonl": "{}\n", "job_id": "7"})
    assert "images_local" not in json.loads((tmp_path / "layout/k.pdf/p0002.json").read_text())


# ---- backfill-layout

def test_parse_label_roundtrip():
    assert ob.parse_label("5") == [5]
    assert ob.parse_label("1-5") == [1, 2, 3, 4, 5]
    assert ob.parse_label("1-5,7") == [1, 2, 3, 4, 5, 7]
    assert ob.parse_label("1,3,7") == [1, 3, 7]
    for ps in ([4], [1, 2, 3], [1, 3, 7]):
        assert ob.parse_label(paddle_vl._label(ps)) == ps
    with pytest.raises(ValueError):
        ob.parse_label("a-b")


def test_parse_run_logs(tmp_path):
    p = mkpaths(tmp_path)
    p.logs.mkdir()
    (p.logs / "run_1.log").write_text(
        "2026-11-23 23:45:29   [Tax/A [x], 1907.pdf] [paddle] 块1 页1-5,7 通过 6/6 10.3s job=111\n"
        "junk line\n2026-11-23 23:45:30   [b.pdf] [paddle] 块2 页2 通过 0/1 155.2s job=222\n")
    m = ob.parse_run_logs(p)
    assert m["111"] == ("Tax/A [x], 1907.pdf", [1, 2, 3, 4, 5, 7]) and m["222"] == ("b.pdf", [2])


def _jsonl(texts):
    items = [{"markdown": {"text": t, "images": {}}, "prunedResult": {"i": i}, "outputImages": None,
              "inputImage": "u"} for i, t in enumerate(texts)]
    pages = [{"width": 1224, "height": 1584} for _ in texts]
    return json.dumps({"result": {"layoutParsingResults": items, "dataInfo": {"pages": pages}}}) + "\n"


def _setup_backfill(tmp_path, texts, lib_texts, job="500", log_label="1-2", with_log=True):
    p = mkpaths(tmp_path)
    mkpdf(p.src / "a.pdf", len(texts))  # 612x792 pt
    p.out.mkdir()
    pages = {str(i + 1): {"text": t, "model": "M", "job_id": job, "trace_id": "T", "chunk": 1,
                          "empty_reason": None, "seconds": 1} for i, t in enumerate(lib_texts) if t is not None}
    (p.out / "a.pdf.json").write_text(json.dumps({"file": "a.pdf", "pages": pages, "page_count": len(texts)}))
    if with_log:
        p.logs.mkdir()
        (p.logs / "run_1.log").write_text(f"x   [a.pdf] [paddle] 块1 页{log_label} 通过 2/2 1s job={job}\n")
    return p


def _routes(job, body, state="done", status=200, code=0):
    q = f"{paddle_vl.URL}/{job}"
    data = {"jobId": job, "state": state, "resultUrl": {"jsonUrl": "http://r/" + job}}
    return {q: FakeResp(status=status, js={"code": code, "data": data}), "http://r/" + job: FakeResp(text=body)}


def _args(**kw):
    return types.SimpleNamespace(limit=kw.get("limit"), dry_run=kw.get("dry_run", False))


@pytest.fixture(autouse=True)
def _tok(monkeypatch):
    monkeypatch.setenv("PADDLEOCR_TOKEN", "tok")
    monkeypatch.setattr(ob.time, "sleep", lambda s: None)


def test_backfill_ok_and_resume(tmp_path):
    texts = ["alpha one", "beta two"]
    p = _setup_backfill(tmp_path, texts, texts)
    s = FakeSession(_routes("500", _jsonl(texts)))
    r = ob.cmd_backfill_layout(p, _args(), s)
    assert [x[3] for x in r] == ["ok"]
    j = json.loads((p.out / "a.pdf.json").read_text())
    assert j["pages"]["1"]["layout"] == "layout/a.pdf/p0001.json" and j["pages"]["2"]["layout"]
    assert (p.out / "layout/a.pdf/jobs/500.jsonl").exists()
    rec = json.loads((p.out / "layout/a.pdf/p0002.json").read_text())
    assert rec["pdf_w_pt"] == 595 and rec["markdown"]["text"] == "beta two"
    assert ob.read_tsv(p.backfill)[0]["status"] == "ok"
    n = len(s.calls)
    assert ob.cmd_backfill_layout(p, _args(), s) == [] and len(s.calls) == n  # 续跑：已 ok / 已有版面不再请求


def test_backfill_dry_run_writes_nothing(tmp_path):
    texts = ["alpha one", "beta two"]
    p = _setup_backfill(tmp_path, texts, texts)
    r = ob.cmd_backfill_layout(p, _args(dry_run=True), FakeSession(_routes("500", _jsonl(texts))))
    assert r[0][3] == "ok" and not p.backfill.exists() and not (p.out / "layout").exists()
    assert "layout" not in json.loads((p.out / "a.pdf.json").read_text())["pages"]["1"]


def test_backfill_count_mismatch(tmp_path):
    texts = ["alpha one", "beta two"]
    p = _setup_backfill(tmp_path, texts, texts)
    r = ob.cmd_backfill_layout(p, _args(), FakeSession(_routes("500", _jsonl(["alpha one"]))))
    assert r[0][3] == "mismatch" and not (p.out / "layout").exists()


def test_backfill_text_mismatch(tmp_path):
    texts = ["alpha one", "beta two"]
    p = _setup_backfill(tmp_path, texts, texts)
    r = ob.cmd_backfill_layout(p, _args(), FakeSession(_routes("500", _jsonl(["alpha one", "DIFFERENT"]))))
    assert r[0][3] == "text_mismatch" and not (p.out / "layout").exists()
    assert ob.read_tsv(p.backfill)[0]["status"] == "text_mismatch"


def test_backfill_expired(tmp_path):
    texts = ["alpha one", "beta two"]
    p = _setup_backfill(tmp_path, texts, texts)
    r = ob.cmd_backfill_layout(p, _args(), FakeSession(_routes("500", "", status=400, code=11002)))
    assert r[0][3] == "expired"
    p2 = _setup_backfill(tmp_path / "b", texts, texts)
    q = f"{paddle_vl.URL}/500"
    r = ob.cmd_backfill_layout(p2, _args(), FakeSession({q: FakeResp(status=200, js={"code": 11002, "data": None})}))
    assert r[0][3] == "expired"


def test_backfill_partial_library_pages_uses_log_pages(tmp_path):
    """job 提交 2 页，库里只入了第 2 页（第 1 页失败）：仍可按日志页映射补第 2 页。"""
    texts = ["alpha one", "beta two"]
    p = _setup_backfill(tmp_path, texts, [None, "beta two"])
    r = ob.cmd_backfill_layout(p, _args(), FakeSession(_routes("500", _jsonl(texts))))
    assert r[0][3] == "ok"
    assert (p.out / "layout/a.pdf/p0002.json").exists() and not (p.out / "layout/a.pdf/p0001.json").exists()


def test_backfill_no_log_text_fallback(tmp_path):
    texts = ["alpha one", "beta two"]
    p = _setup_backfill(tmp_path, texts, texts, with_log=False)
    r = ob.cmd_backfill_layout(p, _args(), FakeSession(_routes("500", _jsonl(texts))))
    assert r[0][3] == "ok" and (p.out / "layout/a.pdf/p0001.json").exists()
    p2 = _setup_backfill(tmp_path / "b", ["same", "same"], ["same", "same"], with_log=False)
    r = ob.cmd_backfill_layout(p2, _args(), FakeSession(_routes("500", _jsonl(["same", "same"]))))
    assert r[0][3] == "unmapped"


def test_backfill_never_posts(tmp_path):
    texts = ["alpha one", "beta two"]
    p = _setup_backfill(tmp_path, texts, texts)

    class NoPost(FakeSession):
        def post(self, *a, **k):
            raise AssertionError("backfill 不得 POST")
    ob.cmd_backfill_layout(p, _args(), NoPost(_routes("500", _jsonl(texts))))


def test_report_first_line(tmp_path, capsys):
    p = mkpaths(tmp_path)
    p.manifest.write_text("file\tpages\tbytes\ttext_layer\terror\n")
    ob.cmd_report(p, types.SimpleNamespace())
    first = capsys.readouterr().out.splitlines()[0]
    assert first.startswith("run 进程：") and "停跑文件" in first


def _empty_fixture(tmp_path, n_pages: int, blank_pages: set[int]):
    p = mkpaths(tmp_path)
    rel = "a.pdf"
    mkpdf(p.src / rel, n_pages, "x")
    p.out.mkdir(parents=True, exist_ok=True)
    (p.out / (rel + ".json")).write_text(json.dumps({"pages": {}, "page_count": n_pages}))
    for n in range(1, n_pages + 1):
        ob.append_tsv(p.failed, ["t", rel, str(n), "empty_suspect: x"], ob.FAILED_HDR)
    return p, rel


def test_empty_audit_halts_at_threshold(tmp_path, monkeypatch):
    monkeypatch.setattr(paddle_vl, "_is_blank", lambda src, n: False)
    monkeypatch.setattr(paddle_vl, "local_ocr_chars", lambda src, n: 500)
    monkeypatch.setattr(ob, "_write_md", lambda *a, **k: None)
    p, _ = _empty_fixture(tmp_path, 3, set())
    assert ob.empty_audit(p, threshold=3) == 3
    assert p.halt.exists()
    assert "有内容" in p.halt.read_text() or "3" in p.halt.read_text()
    assert len((p.root / "empty_audit.tsv").read_text().splitlines()) == 4


def test_empty_audit_below_threshold_no_halt(tmp_path, monkeypatch):
    monkeypatch.setattr(paddle_vl, "_is_blank", lambda src, n: False)
    monkeypatch.setattr(paddle_vl, "local_ocr_chars", lambda src, n: 500)
    monkeypatch.setattr(ob, "_write_md", lambda *a, **k: None)
    p, _ = _empty_fixture(tmp_path, 3, set())
    assert ob.empty_audit(p, threshold=100) == 3
    assert not p.halt.exists()


def test_empty_audit_fixes_blank_and_no_text(tmp_path, monkeypatch):
    monkeypatch.setattr(paddle_vl, "_is_blank", lambda src, n: n == 1)
    monkeypatch.setattr(paddle_vl, "local_ocr_chars", lambda src, n: 0 if n == 2 else 500)
    monkeypatch.setattr(ob, "_write_md", lambda *a, **k: None)
    p, rel = _empty_fixture(tmp_path, 3, set())
    assert ob.empty_audit(p, threshold=1) == 1
    j = json.loads((p.out / (rel + ".json")).read_text())
    assert j["pages"]["1"]["empty_reason"] == "blank"
    assert j["pages"]["2"]["empty_reason"] == "no_text_local"
    assert "3" not in j["pages"]
    assert p.halt.exists()


def test_empty_audit_writes_diag_at_threshold(tmp_path, monkeypatch):
    monkeypatch.setattr(paddle_vl, "_is_blank", lambda src, n: False)
    monkeypatch.setattr(paddle_vl, "local_ocr_chars", lambda src, n: 500)
    monkeypatch.setattr(ob, "_write_md", lambda *a, **k: None)
    monkeypatch.setattr(ob, "preflight", lambda p, rel, pages: [{"page": n, "issues": "x"} for n in pages])
    p, _ = _empty_fixture(tmp_path, 2, set())
    ob.empty_audit(p, threshold=2)
    diag = (p.root / "empty_diag.tsv").read_text().splitlines()
    assert diag[0].split("\t")[:2] == ["file", "issues"] or "page" in diag[0]
    assert len(diag) == 3
    assert "empty_diag.tsv" in p.halt.read_text()


def test_loop_stops_on_no_todo_and_reports(tmp_path, monkeypatch):
    p = mkpaths(tmp_path)
    p.logs.mkdir(parents=True, exist_ok=True)
    calls = []
    def fake_run(p_, a):
        calls.append(a.ignore_window)
        raise SystemExit(3)
    monkeypatch.setattr(ob, "cmd_run", fake_run)
    monkeypatch.setattr(ob, "cmd_report", lambda *a, **k: None)
    ob.cmd_loop(p, types.SimpleNamespace(workers=1))
    assert calls == [True]  # 只跑一轮，且不受 09–18 窗口限制


def test_loop_lock_prevents_second_instance(tmp_path, monkeypatch):
    import fcntl
    p = mkpaths(tmp_path)
    p.logs.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(ob, "cmd_run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not run")))
    held = open(ob._lock_path(p), "a+")
    fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        ob.cmd_loop(p, types.SimpleNamespace(workers=1))  # 锁被占用 -> 直接返回
    finally:
        fcntl.flock(held, fcntl.LOCK_UN)
        held.close()


def test_watchdog_ignores_fresh_log(tmp_path, monkeypatch):
    p = mkpaths(tmp_path)
    p.logs.mkdir(parents=True, exist_ok=True)
    ob._lock_path(p).write_text(str(os.getpid()))  # 当前进程存活
    (p.logs / "run_x.log").write_text("x")
    killed = []
    monkeypatch.setattr(ob.os, "kill", lambda pid, sig: killed.append(sig))
    ob.cmd_watchdog(p, None)
    assert killed == [0] or killed == []  # 仅存活探测，不发终止信号


def test_empty_status_counts_unresolved_and_alerts(tmp_path, monkeypatch):
    p, rel = _empty_fixture(tmp_path, 3, set())
    j = json.loads((p.out / (rel + ".json")).read_text())
    j["pages"]["1"] = {"text": "", "empty_reason": "blank"}  # 已解决
    (p.out / (rel + ".json")).write_text(json.dumps(j))
    import datetime as _dt
    today = _dt.datetime.now().isoformat(timespec="seconds")
    rows = [r for r in ob.read_tsv(p.failed)]
    with open(p.failed, "w") as fh:
        fh.write("\t".join(ob.FAILED_HDR) + "\n")
        for r in rows:
            fh.write("\t".join([today, r["file"], r["page"], r["reason"]]) + "\n")
    st = ob.empty_status(p)
    assert st["unresolved"] == 2 and st["new_today"] == 2
    monkeypatch.setattr(ob, "EMPTY_WARN_NEW", 2)
    assert ob.empty_alert_line(p) and "空返回预警" in ob.empty_alert_line(p)
    monkeypatch.setattr(ob, "EMPTY_WARN_NEW", 99)
    monkeypatch.setattr(ob, "EMPTY_AUDIT_N", 100)
    assert ob.empty_alert_line(p) is None


def test_render_page_writes_png(tmp_path):
    src = tmp_path / "a.pdf"
    mkpdf(src, 2, "hello")
    png = tmp_path / "p2.png"
    ob.render_page(src, 2, png, 50)
    assert png.exists() and png.read_bytes()[:4] == b"\x89PNG"
