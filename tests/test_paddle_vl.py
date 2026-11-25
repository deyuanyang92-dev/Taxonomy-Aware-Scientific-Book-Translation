"""PaddleOCR 云 API 改造（docs/ocr_eval/paddle_cloud_design.md 3.6）。全部离线：假 Session，不联网。"""

import json

import fitz
import pytest
import requests

from docstore import open_store, textify
from docstore.engines import ENGINE_MAP, paddle_vl
from docstore.engines.paddle_vl import PaddleConfigError, PaddleJobError, PaddleQuotaError

BAD = object()  # 标记 extractProgress 缺失


class Resp:
    def __init__(self, status=200, body=None, text=None):
        self.status_code = status
        self._body = body
        self.text = text if text is not None else json.dumps(body or {})

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


def err(status, code, msg="x"):
    return Resp(status, {"traceId": "tr", "code": code, "msg": msg})


class FakeSession:
    """模拟云端：按上传 PDF 的页宽识别页号（宽 = 300 + 页号），每 4 页一行 JSONL。"""

    def __init__(self, overrides=None):
        self.trust_env = False
        self.posts: list[bytes] = []
        self.polls = 0
        self.post_replies: list = []  # Resp / Exception / None(默认成功)
        self.poll_replies: list = []  # Resp / Exception / callable(jid) / None
        self.mutate = None  # fn(lines) -> lines
        self.progress = "auto"  # "auto" | BAD | dict
        self.overrides = overrides or {}
        self.jobs: dict[str, list[tuple[float, float]]] = {}
        self.post_pages: list[list[int]] = []  # 每次上传的页号序列（宽 - 300）
        self.hook = None  # fn(pages) 在回复前调用，可返回 Resp 覆盖默认回复
        self.raw_text = None  # fn(jid, default_text) -> 下载正文

    def post(self, url, headers=None, data=None, files=None, timeout=None):
        blob = files["file"][1]
        self.posts.append(blob)
        with paddle_vl._FITZ_LOCK, fitz.open(stream=blob, filetype="pdf") as d0:
            pgs = [round(p.rect.width) - 300 for p in d0]
        self.post_pages.append(pgs)
        if self.hook:
            hr = self.hook(pgs)
            if hr is not None:
                return hr
        if self.post_replies:
            r = self.post_replies.pop(0)
            if isinstance(r, Exception):
                raise r
            if r is not None:
                return r
        jid = str(100 + len(self.posts))
        with paddle_vl._FITZ_LOCK, fitz.open(stream=blob, filetype="pdf") as d:
            self.jobs[jid] = [(p.rect.width, p.rect.height) for p in d]
        return Resp(200, {"code": 0, "msg": "Success", "data": {"jobId": jid}})

    def lines(self, jid):
        sizes = self.jobs[jid]
        out = []
        for i in range(0, len(sizes), 4):
            grp = sizes[i:i + 4]
            mds = [self.overrides.get(round(w) - 300, f"cloud page {round(w) - 300}") for w, _ in grp]
            out.append({"logId": f"{jid}-{i}", "errorCode": 0, "errorMsg": "Success", "result": {
                "layoutParsingResults": [{"markdown": {"text": m}, "prunedResult": {"parsing_res_list": [
                    {"block_bbox": [1, 2, 3, 4], "block_label": "text", "block_content": m}]}} for m in mds],
                "dataInfo": {"numPages": len(grp), "pages": [{"width": w * 2, "height": h * 2} for w, h in grp],
                             "type": "pdf"}}})
        return self.mutate(out) if self.mutate else out

    def get(self, url, headers=None, timeout=None):
        jid = url.rsplit("/", 1)[1]
        if url.startswith(paddle_vl.URL + "/"):
            self.polls += 1
            if self.poll_replies:
                r = self.poll_replies.pop(0)
                if isinstance(r, Exception):
                    raise r
                if callable(r):
                    return r(jid)
                if r is not None:
                    return r
            n = len(self.jobs[jid])
            d = {"jobId": jid, "state": "done", "resultUrl": {"jsonUrl": "https://bos/" + jid}}
            if self.progress == "auto":
                d["extractProgress"] = {"totalPages": n, "extractedPages": n}
            elif self.progress is not BAD:
                d["extractProgress"] = self.progress
            return Resp(200, {"traceId": "t-" + jid, "code": 0, "msg": "Success", "data": d})
        txt = "\n".join(json.dumps(x, ensure_ascii=False) for x in self.lines(jid))
        return Resp(200, None, self.raw_text(jid, txt) if self.raw_text else txt)


def failed_state(jid):
    return Resp(200, {"code": 0, "data": {"jobId": jid, "state": "failed", "errorMsg": "OCR服务请求失败，状态码 500"}})


def make_pdf(path, kinds):
    """kinds[i] in text|image|blank；第 i+1 页宽 300+(i+1)。"""
    doc = fitz.open()
    for i, k in enumerate(kinds, 1):
        pg = doc.new_page(width=300 + i, height=400)
        if k == "text":
            pg.insert_text((20, 50), "Page text layer " * 4, fontsize=10)
        elif k == "image":
            pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 60, 60), 0)
            pix.clear_with(200)
            pg.insert_image(fitz.Rect(20, 20, 280, 380), pixmap=pix)
    doc.save(str(path))
    return str(path)


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setenv("PADDLEOCR_TOKEN", "tok")
    monkeypatch.delenv("DOCSTORE_PADDLE_MAX_PAGES", raising=False)
    monkeypatch.delenv("PADDLEOCR_USE_PROXY", raising=False)
    monkeypatch.setattr(paddle_vl, "_sleep", lambda s: None)
    monkeypatch.setattr(paddle_vl, "BACKOFF_S", (0, 0, 0))
    monkeypatch.setattr(paddle_vl, "POLL_INTERVAL_S", 0)


def use(monkeypatch, fs):
    monkeypatch.setattr(paddle_vl, "_new_session", lambda: fs)
    return fs


# ---------------------------------------------------------------- 分块

def test_plan_chunks_250_pages(tmp_path):
    pdf = make_pdf(tmp_path / "a.pdf", ["blank"] * 250)
    chunks, over = paddle_vl.plan_chunks(pdf, list(range(1, 251)))
    assert [len(c[0]) for c in chunks] == [100, 100, 50] and not over


def test_plan_chunks_noncontiguous_keeps_order(tmp_path):
    pdf = make_pdf(tmp_path / "a.pdf", ["blank"] * 10)
    chunks, _ = paddle_vl.plan_chunks(pdf, [9, 2, 5, 7, 3], max_pages_=2)
    assert [c[0] for c in chunks] == [[9, 2], [5, 7], [3]]
    with fitz.open(stream=chunks[0][1], filetype="pdf") as d:  # 块内页序 = 给定顺序
        assert [round(p.rect.width) for p in d] == [309, 302]


@pytest.mark.parametrize("v", ["0", "101", "abc", "-3"])
def test_max_pages_env_out_of_range(monkeypatch, tmp_path, v):
    monkeypatch.setenv("DOCSTORE_PADDLE_MAX_PAGES", v)
    pdf = make_pdf(tmp_path / "a.pdf", ["blank"] * 3)
    with pytest.raises(ValueError):
        paddle_vl.plan_chunks(pdf, [1, 2, 3])


def test_max_pages_env_respected(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCSTORE_PADDLE_MAX_PAGES", "2")
    pdf = make_pdf(tmp_path / "a.pdf", ["blank"] * 5)
    chunks, _ = paddle_vl.plan_chunks(pdf, [1, 2, 3, 4, 5])
    assert [len(c[0]) for c in chunks] == [2, 2, 1]


def test_oversize_chunk_halves_and_single_page_fails(monkeypatch):
    monkeypatch.setattr(paddle_vl, "_build_pdf", lambda p, ps: b"x" * (10 * len(ps)))
    chunks, over = paddle_vl.plan_chunks("x.pdf", [1, 2, 3, 4], max_bytes=25)
    assert [c[0] for c in chunks] == [[1, 2], [3, 4]] and not over
    chunks, over = paddle_vl.plan_chunks("x.pdf", [1, 2], max_bytes=5)
    assert not chunks and set(over) == {1, 2} and "oversize" in over[1]


# ---------------------------------------------------------------- 闸口 a-e

def _attempt(fs, pdf, pages):
    sizes = paddle_vl._page_sizes(pdf, pages)
    return paddle_vl._attempt(fs, paddle_vl._build_pdf(pdf, pages), pdf, pages, sizes, lambda s: None)


def test_gate_happy_path_and_progress_string_ok(tmp_path):
    pdf = make_pdf(tmp_path / "a.pdf", ["image"] * 5)
    fs = FakeSession()
    fs.progress = {"totalPages": "5", "extractedPages": "5"}  # 数字字符串可接受
    ok, failed, info = _attempt(fs, pdf, [1, 2, 3, 4, 5])
    assert not failed and ok[3][0] == "cloud page 3" and info["job_id"] == "101" and info["trace_id"] == "t-101"


def test_gate_progress_missing_only_warns(tmp_path):
    pdf = make_pdf(tmp_path / "a.pdf", ["image"] * 2)
    fs = FakeSession()
    fs.progress = BAD
    logs: list[str] = []
    ok, _, _ = paddle_vl._attempt(fs, paddle_vl._build_pdf(pdf, [1, 2]), pdf, [1, 2],
                                  paddle_vl._page_sizes(pdf, [1, 2]), logs.append)
    assert set(ok) == {1, 2} and any("extractProgress" in m for m in logs)


@pytest.mark.parametrize("prog", [{"totalPages": 2, "extractedPages": 3}, {"totalPages": "x", "extractedPages": 3},
                                  {"totalPages": 3, "extractedPages": 2}])
def test_gate_a_progress_mismatch(tmp_path, prog):
    pdf = make_pdf(tmp_path / "a.pdf", ["image"] * 3)
    fs = FakeSession()
    fs.progress = prog
    with pytest.raises(PaddleJobError, match="extractProgress"):
        _attempt(fs, pdf, [1, 2, 3])


def test_gate_c_missing_page(tmp_path):
    pdf = make_pdf(tmp_path / "a.pdf", ["image"] * 3)
    fs = FakeSession()

    def drop(lines):
        r = lines[-1]["result"]
        r["layoutParsingResults"].pop()
        r["dataInfo"]["pages"].pop()
        r["dataInfo"]["numPages"] -= 1
        return lines

    fs.mutate = drop
    with pytest.raises(PaddleJobError, match="返回 2 页 != 提交 3 页"):
        _attempt(fs, pdf, [1, 2, 3])


def test_gate_c_inconsistent_numpages(tmp_path):
    pdf = make_pdf(tmp_path / "a.pdf", ["image"] * 2)
    fs = FakeSession()

    def bad(lines):
        lines[0]["result"]["dataInfo"]["numPages"] = 5
        return lines

    fs.mutate = bad
    with pytest.raises(PaddleJobError, match="行内页数不一致"):
        _attempt(fs, pdf, [1, 2])


def test_gate_b_errorcode_nonzero(tmp_path):
    pdf = make_pdf(tmp_path / "a.pdf", ["image"] * 2)
    fs = FakeSession()

    def bad(lines):
        lines[0]["errorCode"] = 7
        return lines

    fs.mutate = bad
    with pytest.raises(PaddleJobError, match="errorCode=7"):
        _attempt(fs, pdf, [1, 2])


def test_gate_b_duplicate_logid_and_bad_json(tmp_path):
    pdf = make_pdf(tmp_path / "a.pdf", ["image"] * 6)
    fs = FakeSession()

    def dup(lines):
        lines[1]["logId"] = lines[0]["logId"]
        return lines

    fs.mutate = dup
    with pytest.raises(PaddleJobError, match="logId 重复"):
        _attempt(fs, pdf, [1, 2, 3, 4, 5, 6])
    with pytest.raises(PaddleJobError, match="无法解析"):
        paddle_vl._parse_result("{not json", pdf, [1], [(301, 400)])


def test_gate_d_swapped_rows_detected_by_size(tmp_path):
    pdf = make_pdf(tmp_path / "a.pdf", ["image"] * 8)
    fs = FakeSession()
    fs.mutate = lambda lines: [lines[1], lines[0]]
    with pytest.raises(PaddleJobError, match="页身份不符"):
        _attempt(fs, pdf, list(range(1, 9)))


def test_gate_d_tolerance_and_rotation(tmp_path):
    doc = fitz.open()
    pg = doc.new_page(width=300, height=500)
    pg.insert_text((20, 50), "rot")
    pg.set_rotation(90)  # page.rect 含旋转：宽高互换
    doc.save(str(tmp_path / "r.pdf"))
    sizes = paddle_vl._page_sizes(str(tmp_path / "r.pdf"), [1])
    assert sizes == [(500.0, 300.0)]

    def line(w, h):
        return json.dumps({"logId": "a", "errorCode": 0, "result": {
            "layoutParsingResults": [{"markdown": {"text": "t"}}],
            "dataInfo": {"numPages": 1, "pages": [{"width": w, "height": h}]}}})

    assert paddle_vl._parse_result(line(1001, 599), "x", [1], sizes) == ["t"]  # ±2 px
    with pytest.raises(PaddleJobError):
        paddle_vl._parse_result(line(1003, 600), "x", [1], sizes)
    with pytest.raises(PaddleJobError):  # 未旋转尺寸
        paddle_vl._parse_result(line(600, 1000), "x", [1], sizes)


def test_gate_e_markdown_not_str(tmp_path):
    pdf = make_pdf(tmp_path / "a.pdf", ["image"])
    fs = FakeSession()

    def bad(lines):
        lines[0]["result"]["layoutParsingResults"][0]["markdown"]["text"] = None
        return lines

    fs.mutate = bad
    with pytest.raises(PaddleJobError, match="不是字符串"):
        _attempt(fs, pdf, [1])


def test_bad_chunk_returns_nothing_partial(monkeypatch, tmp_path):
    pdf = make_pdf(tmp_path / "a.pdf", ["image"] * 3)
    fs = use(monkeypatch, FakeSession())
    fs.progress = {"totalPages": 99, "extractedPages": 99}  # 永远不符
    ok, failed = paddle_vl.run_chunk(pdf, [1, 2, 3], session=fs, log=lambda s: None)
    assert ok == {} and set(failed) == {1, 2, 3}


# ---------------------------------------------------------------- 空页三态

def test_empty_page_three_states(tmp_path):
    pdf = make_pdf(tmp_path / "a.pdf", ["text", "image", "blank", "image"])
    fs = FakeSession(overrides={1: "", 2: "![](img.png)", 3: "", 4: ""})
    ok, failed, _ = _attempt(fs, pdf, [1, 2, 3, 4])
    assert 1 in failed and "empty_suspect" in failed[1]  # 文本层页云端返回空 = 漏识
    assert ok[2][1]["empty_reason"] == "image_only" and ok[2][0] == ""
    assert ok[3][1]["empty_reason"] == "blank"
    assert 4 in failed and "empty_suspect" in failed[4]  # 图像页空文本且无图片块 = 漏识


def test_nonempty_text_passes_with_none_reason(tmp_path):
    pdf = make_pdf(tmp_path / "a.pdf", ["image"])
    ok, failed, _ = _attempt(FakeSession(overrides={1: "# **Title**"}), pdf, [1])
    assert ok[1][0] == "Title" and ok[1][1]["empty_reason"] is None and not failed
    assert ok[1][1]["_layout"]["pruned_result"] and ok[1][1]["_raw_jsonl"]  # 版面随结果带出


# ---------------------------------------------------------------- 错误分类

@pytest.mark.parametrize("status,code", [(401, 401), (400, 10007), (400, 10008), (400, 10009), (403, 11001),
                                         (403, 99999)])
def test_config_errors_raise_valueerror_no_retry(monkeypatch, tmp_path, status, code):
    pdf = make_pdf(tmp_path / "a.pdf", ["image"] * 2)
    fs = use(monkeypatch, FakeSession())
    fs.post_replies = [err(status, code)] * 5
    with pytest.raises(ValueError):
        paddle_vl.run_chunk(pdf, [1, 2], session=fs, log=lambda s: None)
    assert len(fs.posts) == 1
    with pytest.raises(PaddleConfigError):
        paddle_vl.run_pages(pdf, [1, 2], log=lambda s: None)


def test_config_error_not_swallowed_by_fallback(monkeypatch, tmp_path):
    pdf = make_pdf(tmp_path / "a.pdf", ["image"])
    fs = use(monkeypatch, FakeSession())
    fs.post_replies = [err(401, 401)] * 3
    monkeypatch.setitem(ENGINE_MAP, "ppocr", lambda p, n, d: ("local", 0.9))
    with pytest.raises(ValueError):
        textify._run_with_fallback("paddle_vl", ("ppocr",), pdf, 1, 300)


@pytest.mark.parametrize("status,code", [(403, 12001), (429, 12001), (429, 0)])
def test_quota_stops_cloud(monkeypatch, tmp_path, status, code):
    pdf = make_pdf(tmp_path / "a.pdf", ["image"] * 6)
    fs = use(monkeypatch, FakeSession())
    fs.post_replies = [err(status, code)] * 9
    monkeypatch.setenv("DOCSTORE_PADDLE_MAX_PAGES", "2")
    monkeypatch.setenv("DOCSTORE_PADDLE_CONCURRENCY", "1")
    with pytest.raises(PaddleQuotaError):
        paddle_vl.run_chunk(pdf, [1, 2], session=fs, log=lambda s: None)
    fs.posts.clear()
    fs.post_replies = [err(status, code)] * 9
    res = paddle_vl.run_pages(pdf, [1, 2, 3, 4, 5, 6], log=lambda s: None)
    assert res["quota_hit"] and res["ok"] == {} and set(res["failed"]) == {1, 2, 3, 4, 5, 6}
    assert len(fs.posts) == 1  # 第一块撞配额后，后两块不再提交


def test_429_with_12002_is_transient_not_quota(monkeypatch, tmp_path):
    pdf = make_pdf(tmp_path / "a.pdf", ["image"])
    fs = FakeSession()
    fs.post_replies = [err(429, 12002), None]
    ok, failed = paddle_vl.run_chunk(pdf, [1], session=fs, log=lambda s: None)
    assert 1 in ok and not failed and len(fs.posts) == 2


@pytest.mark.parametrize("status,code", [(400, 10006), (400, 10003), (413, 0)])
def test_shrink_splits_block(tmp_path, status, code):
    pdf = make_pdf(tmp_path / "a.pdf", ["image"] * 4)
    fs = FakeSession()
    fs.post_replies = [err(status, code)]
    ok, failed = paddle_vl.run_chunk(pdf, [1, 2, 3, 4], session=fs, log=lambda s: None)
    assert set(ok) == {1, 2, 3, 4} and not failed and len(fs.posts) == 3  # 1 次被拒 + 两半


def test_file_error_no_retry_pages_fail(tmp_path):
    pdf = make_pdf(tmp_path / "a.pdf", ["image"] * 2)
    fs = FakeSession()
    fs.post_replies = [err(400, 10004)] * 5
    ok, failed = paddle_vl.run_chunk(pdf, [1, 2], session=fs, log=lambda s: None)
    assert ok == {} and set(failed) == {1, 2} and len(fs.posts) == 1


def test_job_failed_state_then_retry_succeeds(tmp_path):
    pdf = make_pdf(tmp_path / "a.pdf", ["image"] * 3)
    fs = FakeSession()
    fs.poll_replies = [failed_state]
    ok, failed = paddle_vl.run_chunk(pdf, [1, 2, 3], session=fs, log=lambda s: None)
    assert set(ok) == {1, 2, 3} and not failed and len(fs.posts) == 2  # 重新提交一次


def test_transient_exhausted_splits_once_then_fails(tmp_path):
    pdf = make_pdf(tmp_path / "a.pdf", ["image"] * 2)
    fs = FakeSession()
    fs.post_replies = [Resp(500, None, "boom")] * 20
    ok, failed = paddle_vl.run_chunk(pdf, [1, 2], session=fs, log=lambda s: None)
    assert ok == {} and set(failed) == {1, 2}
    assert len(fs.posts) == 4 + 4 + 4  # 整块 4 次 + 对半拆后每页各 4 次，不再继续拆


def test_poll_error_retries_same_job_without_resubmit(tmp_path):
    pdf = make_pdf(tmp_path / "a.pdf", ["image"] * 2)
    fs = FakeSession()
    fs.poll_replies = [requests.ConnectionError("reset"), Resp(503, None, "busy"), None]
    ok, failed = paddle_vl.run_chunk(pdf, [1, 2], session=fs, log=lambda s: None)
    assert set(ok) == {1, 2} and len(fs.posts) == 1 and fs.polls == 3


def test_download_error_retries_same_job(tmp_path):
    pdf = make_pdf(tmp_path / "a.pdf", ["image"])
    fs = FakeSession()
    real_get = fs.get
    state = {"n": 0}

    def get(url, **kw):
        if not url.startswith(paddle_vl.URL):
            state["n"] += 1
            if state["n"] == 1:
                return Resp(502, None, "bad gateway")
        return real_get(url, **kw)

    fs.get = get
    ok, _ = paddle_vl.run_chunk(pdf, [1], session=fs, log=lambda s: None)
    assert 1 in ok and len(fs.posts) == 1 and state["n"] == 2


def test_poll_wrong_jobid_is_error(tmp_path):
    pdf = make_pdf(tmp_path / "a.pdf", ["image"])
    fs = FakeSession()
    fs.poll_replies = [lambda jid: Resp(200, {"code": 0, "data": {"jobId": "other", "state": "done"}})] * 40
    ok, failed = paddle_vl.run_chunk(pdf, [1], session=fs, log=lambda s: None)
    assert ok == {} and 1 in failed and len(fs.posts) == 1  # 已有 jobId：轮询耗尽后块失败，不重新上传
    assert failed[1].startswith("job:")


def test_chunk_log_line_per_chunk(tmp_path):
    pdf = make_pdf(tmp_path / "a.pdf", ["image"] * 3)
    logs: list[str] = []
    paddle_vl.run_chunk(pdf, [1, 2, 3], session=FakeSession(), log=logs.append, chunk_no=7)
    line = [m for m in logs if "块7" in m]
    assert len(line) == 1 and "页1-3" in line[0] and "3/3" in line[0] and "job=101" in line[0]


# ---------------------------------------------------------------- 单页 / 网络 / clean_md

def test_single_page_run_and_failure(monkeypatch, tmp_path):
    pdf = make_pdf(tmp_path / "a.pdf", ["image", "image"])
    fs = use(monkeypatch, FakeSession(overrides={2: ""}))
    assert paddle_vl.paddle_vl_run(pdf, 1, 300) == ("cloud page 1", None)
    with pytest.raises(PaddleJobError, match="empty_suspect"):  # 空文本漏识 -> 抛错 -> 降级
        paddle_vl.paddle_vl_run(pdf, 2, 300)
    assert fs.posts


def test_session_trust_env_default_false(monkeypatch):
    assert paddle_vl._new_session().trust_env is False
    monkeypatch.setenv("PADDLEOCR_USE_PROXY", "1")
    assert paddle_vl._new_session().trust_env is True


def test_missing_token_run_pages_marks_all_failed(monkeypatch, tmp_path):
    monkeypatch.delenv("PADDLEOCR_TOKEN", raising=False)
    monkeypatch.setattr(paddle_vl.Path, "home", staticmethod(lambda: tmp_path))
    res = paddle_vl.run_pages(make_pdf(tmp_path / "a.pdf", ["image"]), [1], log=lambda s: None)
    assert res["ok"] == {} and "no_token" in res["failed"][1] and not res["quota_hit"]


def test_clean_md_kept():
    assert paddle_vl.clean_md("# **Title**\n![x](a.png)\n<div>t</div>") == "Title\n\nt"


# ---------------------------------------------------------------- textify 集成

@pytest.fixture
def lib(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCSTORE_AGENT", "pytest")
    monkeypatch.setenv("DOCSTORE_PPOCR_MODEL", "x")  # 路由会写 os.environ，借此在结束时还原
    monkeypatch.setenv("DOCSTORE_TESS_LANG", "x")
    pdf = make_pdf(tmp_path / "scan.pdf", ["image"] * 3)
    st = open_store(tmp_path / "lib")
    key, _ = st.register(pdf)
    st.update_doc(key, lang="la")  # 路由：paddle_vl，降级 ppocr
    local: list[int] = []

    def ppocr(p, n, d):
        local.append(n)
        return f"本地第{n}页", 0.8

    monkeypatch.setitem(ENGINE_MAP, "ppocr", ppocr)
    return st, key, local


def test_textify_cloud_ok_and_failed_pages_fall_back(monkeypatch, lib):
    st, key, local = lib
    fs = use(monkeypatch, FakeSession(overrides={2: ""}))  # 第 2 页云端漏识
    r = textify.textify(st, key, workers=1, log=lambda m: None)
    assert r["cloud_ok"] == 2 and r["cloud_failed"] == 1 and list(r["cloud_failed_reasons"]) == [2]
    assert local == [2]  # 只有失败页走本地
    assert "cloud page 1" in st.page(key, 1)["text"] and "cloud page 3" in st.page(key, 3)["text"]
    assert "本地第2页" in st.page(key, 2)["text"]
    assert r["pages_done"] == 3
    assert fs.post_pages == [[1, 2, 3]]  # 只有一次批量上传；失败页不再逐页调云
    pg2 = st.page(key, 2)
    # 存储把首个写入的版本（此处即降级引擎 ppocr）的非标准字段放在页面 extra
    assert any(v.get("producer") == "ppocr" for v in pg2["alternates"] + [pg2])
    assert pg2["extra"]["cloud_failed_reason"].startswith("empty_suspect")
    assert "cloud_failed_reason" not in st.page(key, 1)["extra"]


def test_textify_records_job_meta_on_version(monkeypatch, lib):
    st, key, _ = lib
    use(monkeypatch, FakeSession())
    textify.textify(st, key, workers=1, log=lambda m: None)
    pg = st.page(key, 1)
    assert sum(1 for v in pg["alternates"] + [pg] if v.get("producer") == "paddle_vl") == 1
    ex = pg["extra"]  # 首个写入版本（paddle_vl）的字段
    assert ex["job_id"] == "101" and ex["trace_id"] == "t-101" and ex["chunk"] == 1 and ex["empty_reason"] is None


def test_textify_quota_switches_remaining_pages_to_fallback(monkeypatch, lib):
    st, key, local = lib
    fs = use(monkeypatch, FakeSession())
    fs.post_replies = [err(403, 12001)] * 9
    r = textify.textify(st, key, workers=1, log=lambda m: None)
    assert r["cloud_ok"] == 0 and r["cloud_failed"] == 3
    assert local == [1, 2, 3] and fs.post_pages == [[1, 2, 3]]  # 配额后不再调云（POST 次数 = 1）
    assert r["pages_done"] == 3


def test_textify_quota_without_fallback_stays_visible(monkeypatch, lib):
    st, key, local = lib
    fs = use(monkeypatch, FakeSession())
    fs.post_replies = [err(403, 12001)] * 9
    with pytest.raises(PaddleQuotaError):
        textify.textify(st, key, workers=1, engines=["paddle_vl"], log=lambda m: None)
    assert local == []


def test_textify_config_error_propagates(monkeypatch, lib):
    st, key, local = lib
    fs = use(monkeypatch, FakeSession())
    fs.post_replies = [err(401, 401)] * 9
    with pytest.raises(ValueError):
        textify.textify(st, key, workers=1, log=lambda m: None)
    assert local == []


def test_textify_non_paddle_engine_unchanged(monkeypatch, lib):
    st, key, local = lib
    called = []
    monkeypatch.setattr(paddle_vl, "run_pages", lambda *a, **k: called.append(1))
    r = textify.textify(st, key, workers=1, engines=["ppocr"], log=lambda m: None)
    assert not called and local == [1, 2, 3] and r["cloud_ok"] == 0 and r["cloud_failed"] == 0


# ---------------------------------------------------------------- r2 审查修复

class Clock:
    def __init__(self):
        self.t = 0.0
        self.sleeps: list[float] = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(paddle_vl, "_now", c.now)
    monkeypatch.setattr(paddle_vl, "_sleep", c.sleep)
    return c


def _done(fs, jid):
    n = len(fs.jobs[jid])
    return Resp(200, {"traceId": "t", "code": 0, "data": {
        "jobId": jid, "state": "done", "resultUrl": {"jsonUrl": "https://bos/" + jid},
        "extractProgress": {"totalPages": n, "extractedPages": n}}})


def _rec(**over):
    rec = {"logId": "x", "errorCode": 0, "result": {
        "layoutParsingResults": [{"markdown": {"text": "a"}}],
        "dataInfo": {"numPages": 1, "pages": [{"width": 602.0, "height": 800.0}]}}}
    rec.update(over)
    return rec


def test_download_429_is_quota_and_401_is_config(tmp_path):
    pdf = make_pdf(tmp_path / "a.pdf", ["image"])
    for status, exc in ((429, PaddleQuotaError), (401, PaddleConfigError)):
        fs = FakeSession()
        real = fs.get
        fs.get = lambda url, _r=real, _s=status, **kw: (
            err(_s, None) if not url.startswith(paddle_vl.URL) else _r(url, **kw))
        with pytest.raises(exc):
            paddle_vl.run_chunk(pdf, [1], session=fs, log=lambda s: None)
        assert len(fs.posts) == 1  # 不重提


def test_download_exhausted_fails_block_without_resubmit(tmp_path):
    pdf = make_pdf(tmp_path / "a.pdf", ["image"] * 2)
    fs = FakeSession()
    real = fs.get
    fs.get = lambda url, **kw: Resp(502, None, "bad") if not url.startswith(paddle_vl.URL) else real(url, **kw)
    ok, failed = paddle_vl.run_chunk(pdf, [1, 2], session=fs, log=lambda s: None)
    assert ok == {} and set(failed) == {1, 2} and len(fs.posts) == 1  # 块失败，不重新上传，不拆块


def test_poll_exhausted_no_resubmit(tmp_path):
    pdf = make_pdf(tmp_path / "a.pdf", ["image"] * 2)
    fs = FakeSession()
    fs.poll_replies = [Resp(503, None, "busy")] * 10
    ok, failed = paddle_vl.run_chunk(pdf, [1, 2], session=fs, log=lambda s: None)
    assert ok == {} and set(failed) == {1, 2} and len(fs.posts) == 1


def test_deadline_rejects_done_after_timeout(monkeypatch, tmp_path, clock):
    monkeypatch.setenv("DOCSTORE_PADDLE_JOB_TIMEOUT", "100")
    pdf = make_pdf(tmp_path / "a.pdf", ["image"])
    fs = FakeSession()

    def late_done(jid):
        clock.t += 500  # 响应到达时已超截止时间
        return _done(fs, jid)

    fs.poll_replies = [late_done]
    ok, failed = paddle_vl.run_chunk(pdf, [1], session=fs, log=lambda s: None)
    assert ok == {} and "超时" in failed[1] and len(fs.posts) == 1


def test_deadline_bounds_backoff(monkeypatch, tmp_path, clock):
    monkeypatch.setenv("DOCSTORE_PADDLE_JOB_TIMEOUT", "5")
    monkeypatch.setattr(paddle_vl, "BACKOFF_S", (10, 30, 90))
    pdf = make_pdf(tmp_path / "a.pdf", ["image"])
    fs = FakeSession()
    fs.poll_replies = [Resp(503, None, "busy")] * 5
    ok, failed = paddle_vl.run_chunk(pdf, [1], session=fs, log=lambda s: None)
    assert ok == {} and 10 not in clock.sleeps and "截止" in failed[1] and len(fs.posts) == 1


def test_deadline_bounds_poll_loop(monkeypatch, tmp_path, clock):
    monkeypatch.setenv("DOCSTORE_PADDLE_JOB_TIMEOUT", "10")
    monkeypatch.setattr(paddle_vl, "POLL_INTERVAL_S", 3.0)
    pdf = make_pdf(tmp_path / "a.pdf", ["image"])
    fs = FakeSession()
    def running(jid):
        return Resp(200, {"code": 0, "data": {"jobId": jid, "state": "running"}})

    fs.poll_replies = [running] * 50
    ok, failed = paddle_vl.run_chunk(pdf, [1], session=fs, log=lambda s: None)
    assert ok == {} and "超时" in failed[1] and clock.t <= 10 and len(fs.posts) == 1


def test_jsonl_u2028_inside_string_and_crlf_ok(tmp_path):
    pdf = make_pdf(tmp_path / "a.pdf", ["image"] * 2)
    ls = chr(0x2028)
    fs = FakeSession(overrides={1: "line" + ls + "two", 2: "b"})
    fs.raw_text = lambda jid, t: t.replace("\n", "\r\n")
    ok, failed = paddle_vl.run_chunk(pdf, [1, 2], session=fs, log=lambda s: None)
    assert not failed and ok[1][0] == "line" + ls + "two"
    assert ls in fs.get(paddle_vl.URL.replace("api/v2/ocr/jobs", "x") + "/101").text  # 确认线上正文含原始 U+2028


@pytest.mark.parametrize("bad", [float("nan"), 0, -5, float("inf"), True, "602"])
def test_parse_bad_dimensions_rejected(tmp_path, bad):
    pdf = make_pdf(tmp_path / "a.pdf", ["image"])
    rec = _rec()
    rec["result"]["dataInfo"]["pages"][0]["width"] = bad
    with pytest.raises(PaddleJobError, match="页身份"):
        paddle_vl._parse_result(json.dumps(rec), pdf, [1], [(301.0, 400.0)])


@pytest.mark.parametrize("mut,pat", [
    (lambda r: r.__setitem__("result", [1, 2]), "result"),
    (lambda r: r["result"].__setitem__("dataInfo", [1]), "dataInfo"),
    (lambda r: r["result"]["layoutParsingResults"].__setitem__(0, {"markdown": "str"}), "markdown"),
    (lambda r: r["result"]["layoutParsingResults"].__setitem__(0, 5), "markdown"),
    (lambda r: r.__setitem__("logId", [1]), "logId"),
    (lambda r: r.__setitem__("logId", None), "logId"),
])
def test_parse_type_checks_raise_job_error(tmp_path, mut, pat):
    pdf = make_pdf(tmp_path / "a.pdf", ["image"])
    rec = _rec()
    mut(rec)
    with pytest.raises(PaddleJobError, match=pat):
        paddle_vl._parse_result(json.dumps(rec), pdf, [1], [(301.0, 400.0)])


def test_extract_progress_string_fails_block(tmp_path):
    pdf = make_pdf(tmp_path / "a.pdf", ["image"])
    fs = FakeSession()
    real = fs.get

    def get(url, **kw):
        r = real(url, **kw)
        if url.startswith(paddle_vl.URL + "/"):
            r._body["data"]["extractProgress"] = "1/1"
        return r

    fs.get = get
    ok, failed = paddle_vl.run_chunk(pdf, [1], session=fs, log=lambda s: None)
    assert ok == {} and "extractProgress" in failed[1]


@pytest.mark.parametrize("prog", [{"totalPages": "x", "extractedPages": 1}, {"totalPages": 1, "extractedPages": -1},
                                  {"totalPages": 1}, {"totalPages": float("nan"), "extractedPages": 1}, None, [1]])
def test_extract_progress_bad_values_fail_block(tmp_path, prog):
    pdf = make_pdf(tmp_path / "a.pdf", ["image"])
    fs = FakeSession()
    fs.progress = prog
    ok, failed = paddle_vl.run_chunk(pdf, [1], session=fs, log=lambda s: None)
    assert ok == {} and "extractProgress" in failed[1]


def test_log_label_noncontiguous_pages(tmp_path):
    assert paddle_vl._label([13, 40]) == "13,40"
    assert paddle_vl._label([3, 4, 5]) == "3-5" and paddle_vl._label([7]) == "7"
    pdf = make_pdf(tmp_path / "a.pdf", ["image"] * 5)
    logs: list[str] = []
    paddle_vl.run_chunk(pdf, [2, 5], session=FakeSession(), log=logs.append)
    assert any("页2,5" in m for m in logs) and not any("页2-5" in m for m in logs)


def test_run_pages_keeps_left_half_when_right_half_hits_quota(monkeypatch, tmp_path):
    pdf = make_pdf(tmp_path / "a.pdf", ["image"] * 4)
    fs = use(monkeypatch, FakeSession())
    fs.post_replies = [Resp(500, None, "x")] * 4 + [None, err(403, 12001)]
    res = paddle_vl.run_pages(pdf, [1, 2, 3, 4], log=lambda s: None)
    assert set(res["ok"]) == {1, 2} and res["quota_hit"]
    assert set(res["failed"]) == {3, 4} and all(v.startswith("quota") for v in res["failed"].values())
    assert fs.post_pages[-2:] == [[1, 2], [3, 4]]


def test_run_pages_quota_stops_other_thread_before_next_post(monkeypatch, tmp_path):
    """双线程交错：A 块命中配额；B 块首次 POST 暂时失败，须在 A 置位停止后不再重试 POST。"""
    import threading
    import time as _t
    monkeypatch.setenv("DOCSTORE_PADDLE_MAX_PAGES", "2")
    monkeypatch.setenv("DOCSTORE_PADDLE_CONCURRENCY", "2")
    pdf = make_pdf(tmp_path / "a.pdf", ["image"] * 4)
    fs = use(monkeypatch, FakeSession())
    b_posted, a_replied = threading.Event(), threading.Event()

    def hook(pgs):
        if pgs == [1, 2]:
            assert b_posted.wait(5)
            a_replied.set()
            return err(403, 12001)
        b_posted.set()
        assert a_replied.wait(5)
        _t.sleep(0.3)  # 让 A 线程完成 stop.set()
        return Resp(500, None, "boom")

    fs.hook = hook
    res = paddle_vl.run_pages(pdf, [1, 2, 3, 4], log=lambda s: None)
    assert sorted(fs.post_pages) == [[1, 2], [3, 4]]  # 每块恰好 1 次 POST，B 不重试
    assert res["quota_hit"] and res["ok"] == {} and set(res["failed"]) == {1, 2, 3, 4}


def test_run_pages_unstarted_chunks_cancelled_after_quota(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCSTORE_PADDLE_MAX_PAGES", "1")
    monkeypatch.setenv("DOCSTORE_PADDLE_CONCURRENCY", "1")
    pdf = make_pdf(tmp_path / "a.pdf", ["image"] * 4)
    fs = use(monkeypatch, FakeSession())
    fs.post_replies = [err(403, 12001)]
    res = paddle_vl.run_pages(pdf, [1, 2, 3, 4], log=lambda s: None)
    assert len(fs.posts) == 1 and res["quota_hit"] and set(res["failed"]) == {1, 2, 3, 4}
    assert res["failed"][3].startswith("cancelled")


def test_run_pages_config_error_stops_others_and_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCSTORE_PADDLE_MAX_PAGES", "1")
    monkeypatch.setenv("DOCSTORE_PADDLE_CONCURRENCY", "1")
    pdf = make_pdf(tmp_path / "a.pdf", ["image"] * 4)
    fs = use(monkeypatch, FakeSession())
    fs.post_replies = [err(401, 401)]
    with pytest.raises(PaddleConfigError):
        paddle_vl.run_pages(pdf, [1, 2, 3, 4], log=lambda s: None)
    assert len(fs.posts) == 1


def test_fitz_ops_hold_global_lock(monkeypatch, tmp_path):
    pdf = make_pdf(tmp_path / "a.pdf", ["image", "blank"])
    seen = []
    real_open = fitz.open

    def spy(*a, **k):
        seen.append(paddle_vl._FITZ_LOCK.locked())
        return real_open(*a, **k)

    monkeypatch.setattr(paddle_vl.fitz, "open", spy)
    paddle_vl._build_pdf(pdf, [1])
    paddle_vl._page_sizes(pdf, [1, 2])
    paddle_vl._is_blank(pdf, 2)
    assert seen and all(seen)


def test_is_blank_tinted_paper_and_text(tmp_path):
    """泛黄空白页（灰度 <250 但均匀）必须判空白；有文字页必须判非空白。"""
    doc = fitz.open()
    pg = doc.new_page(width=200, height=280)
    pg.draw_rect(pg.rect, color=None, fill=(0.96, 0.92, 0.82))  # 米黄底
    pg2 = doc.new_page(width=200, height=280)
    pg2.draw_rect(pg2.rect, color=None, fill=(0.96, 0.92, 0.82))
    pg2.draw_rect(fitz.Rect(20, 20, 180, 120), color=None, fill=(0, 0, 0))  # 大块墨迹
    p = str(tmp_path / "t.pdf")
    doc.save(p)
    assert paddle_vl._is_blank(p, 1) is True
    assert paddle_vl._is_blank(p, 2) is False


def test_textify_failed_pages_not_retried_in_cloud_and_no_fallback_raises(monkeypatch, lib):
    st, key, local = lib
    fs = use(monkeypatch, FakeSession(overrides={2: ""}))
    with pytest.raises(RuntimeError, match="第2页 empty_suspect"):
        textify.textify(st, key, workers=1, engines=["paddle_vl"], log=lambda m: None)
    assert fs.post_pages == [[1, 2, 3]] and local == []


def test_textify_explicit_multi_engine_skips_batch(monkeypatch, lib):
    st, key, local = lib
    called = []
    monkeypatch.setattr(paddle_vl, "run_pages", lambda *a, **k: called.append(1))
    fs = use(monkeypatch, FakeSession())
    textify.textify(st, key, workers=1, engines=["paddle_vl", "ppocr"], log=lambda m: None)
    assert not called and fs.post_pages == [[1], [2], [3]] and local == [1, 2, 3]


class _InlinePool:
    def __init__(self, *a, **k):
        pass

    def submit(self, fn, *a):
        import concurrent.futures as cf
        f = cf.Future()
        f.set_result(fn(*a))
        return f

    def shutdown(self, *a, **k):
        pass


def test_textify_process_pool_path_records_reason(monkeypatch, lib):
    st, key, local = lib
    use(monkeypatch, FakeSession(overrides={2: ""}))
    monkeypatch.setattr(textify, "ProcessPoolExecutor", _InlinePool)
    monkeypatch.setattr(textify, "as_completed", lambda futs: list(futs))
    textify.textify(st, key, workers=2, log=lambda m: None)
    pg2 = st.page(key, 2)
    assert any(v.get("producer") == "ppocr" for v in pg2["alternates"] + [pg2])
    assert pg2["extra"]["cloud_failed_reason"].startswith("empty_suspect")


# ---------------------------------------------------------------- r3 审查修复

def test_textify_degrade_tries_fallbacks_in_order(monkeypatch, lib):
    st, key, local = lib
    tess: list[int] = []

    def bad_ppocr(p, n, d):
        local.append(n)
        raise RuntimeError("ppocr down")

    def tesseract(p, n, d):
        tess.append(n)
        return f"tess第{n}页", 0.7

    monkeypatch.setitem(ENGINE_MAP, "ppocr", bad_ppocr)
    monkeypatch.setitem(ENGINE_MAP, "tesseract", tesseract)
    use(monkeypatch, FakeSession(overrides={2: ""}))
    textify.textify(st, key, workers=1, log=lambda m: None)
    assert local == [2] and tess == [2]
    pg = st.page(key, 2)
    assert any(v.get("producer") == "tesseract" for v in pg["alternates"] + [pg])
    assert "tess第2页" in pg["text"]


def test_textify_degrade_ppocr_ok_does_not_run_tesseract(monkeypatch, lib):
    st, key, local = lib
    tess: list[int] = []
    monkeypatch.setitem(ENGINE_MAP, "tesseract", lambda p, n, d: (tess.append(n), ("t", 0.5))[1])
    use(monkeypatch, FakeSession(overrides={2: ""}))
    textify.textify(st, key, workers=1, log=lambda m: None)
    assert local == [2] and tess == []


def test_textify_degrade_empty_reading_on_nonblank_page_tries_next(monkeypatch, lib):
    st, key, local = lib
    monkeypatch.setitem(ENGINE_MAP, "ppocr", lambda p, n, d: (local.append(n), ("", 0.9))[1])
    monkeypatch.setitem(ENGINE_MAP, "tesseract", lambda p, n, d: (f"tess第{n}页", 0.7))
    use(monkeypatch, FakeSession(overrides={2: ""}))
    textify.textify(st, key, workers=1, log=lambda m: None)
    pg = st.page(key, 2)
    assert local == [2] and "tess第2页" in pg["text"]
    assert not any(v.get("producer") == "ppocr" for v in pg["alternates"] + [pg])


def test_textify_degrade_all_empty_raises_and_keeps_other_pages(monkeypatch, lib):
    st, key, local = lib
    monkeypatch.setitem(ENGINE_MAP, "ppocr", lambda p, n, d: ("", 0.9))
    monkeypatch.setitem(ENGINE_MAP, "tesseract", lambda p, n, d: ("  ", 0.9))
    use(monkeypatch, FakeSession(overrides={2: ""}))
    with pytest.raises(RuntimeError, match="第2页.*读数为空"):
        textify.textify(st, key, workers=1, log=lambda m: None)
    assert st.page(key, 2) is None
    assert "cloud page 1" in st.page(key, 1)["text"] and "cloud page 3" in st.page(key, 3)["text"]


def test_textify_degrade_empty_on_blank_page_is_accepted(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCSTORE_AGENT", "pytest")
    monkeypatch.setenv("DOCSTORE_PPOCR_MODEL", "x")
    monkeypatch.setenv("DOCSTORE_TESS_LANG", "x")
    pdf = make_pdf(tmp_path / "b.pdf", ["image", "blank"])
    st = open_store(tmp_path / "lib")
    key, _ = st.register(pdf)
    st.update_doc(key, lang="la")
    monkeypatch.setitem(ENGINE_MAP, "ppocr", lambda p, n, d: ("", 0.9))
    use(monkeypatch, FakeSession(overrides={2: ""}))
    r = textify.textify(st, key, workers=1, log=lambda m: None)
    assert r["pages_done"] == 2


def test_poll_failed_after_deadline_is_job_timeout_no_resubmit(monkeypatch, tmp_path, clock):
    monkeypatch.setenv("DOCSTORE_PADDLE_JOB_TIMEOUT", "10")
    pdf = make_pdf(tmp_path / "a.pdf", ["image"])
    fs = FakeSession()

    def late_failed(jid):
        clock.t += 11
        return failed_state(jid)

    fs.poll_replies = [late_failed]
    ok, failed = paddle_vl.run_chunk(pdf, [1], session=fs, log=lambda s: None)
    assert ok == {} and failed[1].startswith("job:") and "超时" in failed[1] and len(fs.posts) == 1


@pytest.mark.parametrize("bad", [["bad"], "x", None, {"jobId": ["a"]}, {"jobId": {"a": 1}}, {"jobId": 1.5}, {"jobId": True}])
def test_submit_malformed_data_is_job_error(monkeypatch, tmp_path, bad):
    pdf = make_pdf(tmp_path / "a.pdf", ["image"])
    fs = FakeSession()
    fs.post_replies = [Resp(200, {"code": 0, "data": bad})] * 5
    ok, failed = paddle_vl.run_chunk(pdf, [1], session=fs, log=lambda s: None)
    assert ok == {} and 1 in failed


def test_submit_data_not_dict_raises_job_error_from_attempt(tmp_path):
    pdf = make_pdf(tmp_path / "a.pdf", ["image"])
    fs = FakeSession()
    fs.post_replies = [Resp(200, {"code": 0, "data": ["bad"]})]
    blob = paddle_vl._build_pdf(pdf, [1])
    with pytest.raises(PaddleJobError, match="data 不是对象"):
        paddle_vl._attempt(fs, blob, pdf, [1], paddle_vl._page_sizes(pdf, [1]), lambda s: None)


def test_textify_redo_adds_alternate_with_model_and_keeps_primary(monkeypatch, lib):
    st, key, _ = lib
    for n in (1, 2, 3):
        st.put_version(key, n, {"text": f"人工校正第{n}页", "method": "verified", "producer": "claude-opus",
                                "engine": "人工", "verify_level": "ocr_verified", "dpi": 300})
    fs = use(monkeypatch, FakeSession(overrides={2: ""}))
    monkeypatch.setenv("DOCSTORE_PADDLE_VL_MODEL", "PaddleOCR-VL-1.6")
    r = textify.textify(st, key, workers=1, engines=["paddle_vl"], redo=True, log=lambda m: None)
    assert fs.post_pages == [[1, 2, 3]]
    assert r["cloud_ok"] == 2 and list(r["cloud_failed_reasons"]) == [2]
    for n in (1, 3):
        pg = st.page(key, n)
        assert pg["text"] == f"人工校正第{n}页"  # 主版本不变
        alt = [v for v in pg["alternates"] if v.get("producer") == "paddle_vl"]
        assert len(alt) == 1 and f"cloud page {n}" in alt[0]["text"]
        assert alt[0]["verify_level"] == "ocr_raw" and "PaddleOCR-VL-1.6" in alt[0]["engine"]
        assert alt[0]["model"] == "PaddleOCR-VL-1.6" and alt[0]["redo"] is True and alt[0]["job_id"]
    assert not [v for v in st.page(key, 2)["alternates"] if v.get("producer") == "paddle_vl"]


def test_textify_redo_requires_paddle_only(lib):
    st, key, _ = lib
    with pytest.raises(ValueError, match="redo-ocr"):
        textify.textify(st, key, workers=1, engines=["ppocr"], redo=True, log=lambda m: None)


def test_layout_saved_per_page_and_raw_jsonl(tmp_path):
    """版面必须随 OCR 一次落盘：每页 prunedResult + 页尺寸 + job_id，且保留整任务原始 JSONL。"""
    pdf = make_pdf(tmp_path / "a.pdf", ["image"] * 3)
    ok, failed = paddle_vl.run_chunk(pdf, [1, 2, 3], session=FakeSession(), log=lambda s: None)
    assert not failed and sorted(ok) == [1, 2, 3]
    root = tmp_path / "lib"
    for n in ok:
        paddle_vl.save_layout(root, "K", n, ok[n][1])
    rec = json.loads((root / "layout" / "K" / "p0002.json").read_text(encoding="utf-8"))
    assert rec["page"] == 2 and rec["job_id"] and rec["pruned_result"]["parsing_res_list"][0]["block_bbox"] == [1, 2, 3, 4]
    assert rec["width_px"] == rec["pdf_w_pt"] * 2
    raw = root / "layout" / "K" / rec["raw_jsonl"]
    assert raw.exists() and json.loads(raw.read_text(encoding="utf-8").splitlines()[0])["errorCode"] == 0
