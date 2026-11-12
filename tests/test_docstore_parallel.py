"""textify 的并行 OCR、--pages 选页、--no-fix：用桩引擎，不依赖真实 OCR。"""

import fitz
import pytest

from docstore import cli, open_store, textify

# 测试里用 fork 让子进程继承桩函数；Python 3.12+ 对「多线程进程 fork」发 DeprecationWarning，这里无影响
pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

# 桩识别的文本里含 lexicon 会「纠错」的词（沙蚕/沙虫），用来区分 fix 开关
STUB_TEXT = "，环带沙虫，第{n}页，Lopadorhynthus brevis"


def stub_ocr(pdf, n, dpi):
    return STUB_TEXT.format(n=n) * 3, 0.9


def make_scan(path, npages):
    doc = fitz.open()
    for _ in range(npages):
        pg = doc.new_page(width=300, height=400)
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 60, 60), 0)
        pix.clear_with(200)
        pg.insert_image(fitz.Rect(20, 20, 280, 380), pixmap=pix)
    doc.save(str(path))
    return path


@pytest.fixture
def scan_lib(tmp_path, monkeypatch):
    monkeypatch.setattr(textify, "OCR_FUNC", stub_ocr)
    monkeypatch.setattr(textify, "MP_START", "fork")  # 子进程继承桩函数
    monkeypatch.setenv("DOCSTORE_AGENT", "pytest")
    pdf = make_scan(tmp_path / "scan.pdf", 8)
    st = open_store(tmp_path / "lib")
    key, _ = st.register(pdf, key="scan")
    return st, key


def snapshot(st, key):
    out = {}
    for p in st.pages(key):
        out[p["page"]] = (p["text"], p["verify_level"], p["producer"], len(p.get("alternates", [])))
    return out


def test_parallel_equals_serial(tmp_path, monkeypatch):
    monkeypatch.setattr(textify, "OCR_FUNC", stub_ocr)
    monkeypatch.setattr(textify, "MP_START", "fork")
    pdf = make_scan(tmp_path / "scan.pdf", 8)
    res = {}
    for w in (1, 3):
        st = open_store(tmp_path / f"lib{w}")
        key, _ = st.register(pdf, key="scan")
        logs: list[str] = []
        r = textify.textify(st, key, workers=w, engines=["rapidocr"], log=logs.append)
        assert r["ocr"] == 8 and r["pages_done"] == 8 and r["workers"] == w
        assert any("OCR 8/8" in m and "s/页(墙钟)" in m and "预计剩余" in m for m in logs)
        assert st.con.execute("SELECT count(*) FROM pages").fetchone()[0] == 8
        res[w] = snapshot(st, key)
    assert res[1] == res[3]
    assert sorted(res[3]) == list(range(1, 9))


def test_parallel_index_searchable_and_resumable(scan_lib):
    st, key = scan_lib
    textify.textify(st, key, workers=3, engines=["rapidocr"], limit=5, log=lambda m: None)
    assert len(st.page_numbers(key)) == 5
    assert [h["page"] for h in st.search("第4页")] == [4]  # FTS 逐页即时可查
    r = textify.textify(st, key, workers=3, engines=["rapidocr"], log=lambda m: None)
    assert r["ocr"] == 3 and r["pages_done"] == 8  # 只补剩下的页
    assert st.doc(key)["status"] == "text_done"


def test_parallel_error_propagates_and_keeps_done_pages(scan_lib, monkeypatch):
    st, key = scan_lib

    def flaky(pdf, n, dpi):
        if n == 6:
            raise RuntimeError("boom")
        return stub_ocr(pdf, n, dpi)

    monkeypatch.setattr(textify, "OCR_FUNC", flaky)
    with pytest.raises(RuntimeError, match="boom"):
        textify.textify(st, key, workers=2, engines=["rapidocr"], log=lambda m: None)
    assert 6 not in st.page_numbers(key)
    monkeypatch.setattr(textify, "OCR_FUNC", stub_ocr)
    r = textify.textify(st, key, workers=2, engines=["rapidocr"], log=lambda m: None)
    assert r["pages_done"] == 8


def test_pages_selection(scan_lib):
    st, key = scan_lib
    r = textify.textify(st, key, workers=1, engines=["rapidocr"], pages=[2, 3, 7, 99], log=lambda m: None)
    assert r["ocr"] == 3
    assert st.page_numbers(key) == [2, 3, 7]
    assert st.doc(key)["status"].startswith("text_partial 3/8")
    # 再选已做过的页 + 一个新页：只做新页
    r = textify.textify(st, key, workers=1, engines=["rapidocr"], pages=[3, 4], log=lambda m: None)
    assert r["ocr"] == 1 and st.page_numbers(key) == [2, 3, 4, 7]


def test_no_fix_keeps_engine_text(scan_lib, tmp_path):
    st, key = scan_lib
    textify.textify(st, key, workers=1, engines=["rapidocr"], pages=[1], log=lambda m: None)
    textify.textify(st, key, workers=1, engines=["rapidocr"], pages=[2], fix=False, log=lambda m: None)
    p1, p2 = st.page(key, 1), st.page(key, 2)
    assert "Lopadorhynthus" in p2["text"] and p2["producer"].startswith("consensus(")
    assert "Lopadorhynchus" in p1["text"]  # 默认会按 lexicon 纠成已知学名


def test_cli_pages_and_workers(scan_lib, capsys):
    st, key = scan_lib
    rc = cli.main(["--root", str(st.root), "text", key, "--engines", "rapidocr", "--workers", "2",
                   "--pages", "2-3,6", "--no-fix"])
    assert rc in (0, None)
    assert open_store(st.root).page_numbers(key) == [2, 3, 6]
    assert '"workers": 2' in capsys.readouterr().out


def test_unknown_engine_rejected_before_pool(scan_lib):
    st, key = scan_lib
    with pytest.raises(ValueError, match="未知 OCR 引擎"):
        textify.textify(st, key, workers=3, engines=["nope"], log=lambda m: None)
