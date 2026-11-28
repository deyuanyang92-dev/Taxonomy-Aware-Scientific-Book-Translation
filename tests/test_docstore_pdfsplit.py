from pypdf import PdfReader, PdfWriter

from docstore import pdfsplit
from docstore.cli import main


def _mk(p, n):
    w = PdfWriter()
    for _ in range(n):
        w.add_blank_page(width=100, height=100)
    with open(p, "wb") as f:
        w.write(f)


def test_plan_and_tag():
    assert pdfsplit.plan(120, 50) == [(1, 50), (51, 100), (101, 120)]
    assert pdfsplit.plan(50, 50) == [(1, 50)]
    assert pdfsplit.volume_tag(__import__("pathlib").Path("FAUNA IBERICA（Vol.36).pdf")) == "Vol36"


def test_tag_keeps_cjk_and_profile_10mb():
    from pathlib import Path
    assert pdfsplit.volume_tag(Path("中国近海沙蚕科研究.pdf")) == "中国近海沙蚕科研究"
    assert pdfsplit.load_profile("gemini-10mb")["max_bytes"] < 10_000_000


def test_oversize_block_is_replanned(tmp_path):
    src = tmp_path / "x.pdf"
    _mk(src, 12)
    out = tmp_path / "o"
    rows = pdfsplit.split_pdf(src, out, size=None, max_bytes=3000, encode="none")
    assert all(r["ok"] for r in rows) or all(r["pages"] == 1 for r in rows if not r["ok"])
    assert sum(r["pages"] for r in rows) == 12
    assert [r["block"] for r in rows] == list(range(1, len(rows) + 1))


def test_split_cli_resume(tmp_path, capsys):
    src = tmp_path / "FAUNA IBERICA（Vol.25）.pdf"
    _mk(src, 120)
    out = tmp_path / "out"
    assert main(["split", str(src), "--out", str(out)]) == 0
    d = out / "Vol25"
    names = sorted(p.name for p in d.glob("*.pdf"))
    assert names == ["Vol25_B01_p001-050.pdf", "Vol25_B02_p051-100.pdf", "Vol25_B03_p101-120.pdf"]
    assert sum(len(PdfReader(str(d / n)).pages) for n in names) == 120
    assert len((d / "manifest.tsv").read_text().splitlines()) == 4
    rows = pdfsplit.split_pdf(src, out)
    assert all(r["status"] == "skipped" for r in rows)


# ---- profile / 体积装块 / 无损重编码 ----
import random  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402


def _mk_noise(p, n, w=300, h=400, seed=1):
    """n 页，每页一张随机噪声灰度图（体积大、可预期），页面 300x400 pt。"""
    import fitz

    rnd = random.Random(seed)
    doc = fitz.open()
    for _ in range(n):
        pg = doc.new_page(width=w, height=h)
        pix = fitz.Pixmap(fitz.csGRAY, fitz.IRect(0, 0, 100, 130), False)
        pix.set_rect(pix.irect, (255,))
        pix.samples_mv[:] = bytes(rnd.getrandbits(8) for _ in range(100 * 130))
        pg.insert_image(pg.rect, pixmap=pix)
    doc.save(str(p), deflate=True)
    doc.close()


def test_plan_by_size_edges():
    f = pdfsplit.plan_by_size
    assert f([], 100) == []
    assert f([10] * 5, None, None, None) == [(1, 5)]
    assert f([10] * 5, None, None, 2) == [(1, 2), (3, 4), (5, 5)]
    assert f([10] * 5, None, 3, 4) == [(1, 3), (4, 5)]  # 取最严
    assert f([40, 40, 40], 100) == [(1, 2), (3, 3)]
    assert f([40, 40, 20], 100) == [(1, 3)]  # 恰好等于上限可装
    assert f([500, 10, 10], 100) == [(1, 1), (2, 3)]  # 单页超限独占一块


def test_profiles_load():
    names = pdfsplit.load_profiles()
    for k in ("gemini-api-inline", "gemini-app-free", "gemini-app-pro", "vertex-console",
              "google-translate-web", "cloud-translate-scanned", "drive-ocr"):
        assert k in names
        assert names[k]["checked"] == "2026-11-26" and names[k]["source"] and names[k]["render_dpi"] == 200
    assert "不翻译" in names["google-translate-web"]["note"]
    assert "无损不可行" in names["drive-ocr"]["note"]
    assert pdfsplit.load_profile("cloud-translate-scanned")["max_pages"] == 20
    with pytest.raises(KeyError):
        pdfsplit.load_profile("nope")


def test_pages_range_and_profile_override(tmp_path):
    src = tmp_path / "A.pdf"
    _mk(src, 30)
    out = tmp_path / "o"
    assert main(["split", str(src), "--out", str(out), "--pages", "5-24", "--target", "cloud-translate-scanned",
                 "--size", "7", "--render-dpi", "50"]) == 0
    names = sorted(p.name for p in (out / "A").glob("*.pdf"))
    assert names == ["A_B01_p005-011.pdf", "A_B02_p012-018.pdf", "A_B03_p019-024.pdf"]
    man = (out / "A" / "manifest.tsv").read_text().splitlines()
    assert man[0].endswith("bytes\ttarget\tok") and man[1].split("\t")[8] == "cloud-translate-scanned"
    with pytest.raises(ValueError):
        pdfsplit.split_pdf(src, out, pages_range=(5, 31))


def test_target_default_rec_pages_and_max_pages(tmp_path):
    src = tmp_path / "A.pdf"
    _mk(src, 45)
    rows = pdfsplit.split_pdf(src, tmp_path / "o", size=None, max_pages=20, rec_pages=18, target="cloud-translate-scanned")
    assert [r["pages"] for r in rows] == [18, 18, 9] and all(r["ok"] for r in rows)


def test_default_unchanged_manifest_ok(tmp_path):
    src = tmp_path / "A.pdf"
    _mk(src, 120)
    rows = pdfsplit.split_pdf(src, tmp_path / "o")
    assert [r["pages"] for r in rows] == [50, 50, 20] and all(r["ok"] and r["target"] == "" for r in rows)


def test_max_bytes_not_exceeded_none(tmp_path):
    src = tmp_path / "N.pdf"
    _mk_noise(src, 12)
    rows = pdfsplit.split_pdf(src, tmp_path / "o", size=None, max_bytes=40_000)
    assert len(rows) > 1
    for r in rows:
        assert r["bytes"] <= 40_000 and r["ok"]
        assert (tmp_path / "o" / "N" / r["file"]).stat().st_size == r["bytes"]
    assert sum(r["pages"] for r in rows) == 12


def test_reencode_bytes_size_and_oversize(tmp_path):
    import fitz

    src = tmp_path / "N.pdf"
    _mk_noise(src, 6, w=200, h=300)
    rows = pdfsplit.split_pdf(src, tmp_path / "o", size=None, max_bytes=60_000, render_dpi=100, encode="flate")
    assert sum(r["pages"] for r in rows) == 6 and len(rows) > 1
    assert all(r["bytes"] <= 60_000 and r["ok"] for r in rows)
    orig = fitz.open(str(src))
    for r in rows:
        d = fitz.open(str(tmp_path / "o" / "N" / r["file"]))
        assert d.page_count == r["pages"]
        for k in range(d.page_count):
            o = orig[r["start"] - 1 + k].rect
            assert (round(d[k].rect.width, 2), round(d[k].rect.height, 2)) == (round(o.width, 2), round(o.height, 2))
    # 单页超限：独占一块且 ok=false
    rows2 = pdfsplit.split_pdf(src, tmp_path / "o2", size=None, max_bytes=5_000, render_dpi=100, encode="flate")
    assert [r["pages"] for r in rows2] == [1] * 6 and not any(r["ok"] for r in rows2)


def _find_imajima2009():
    import glob

    c = glob.glob("/mnt/p/翻译-译作/日本-imajima/Imajima 2009*.pdf") + glob.glob("/mnt/p/翻译-译作/参考资料/**/Imajima*2009*.pdf", recursive=True)
    return Path(c[0]) if c else None


def test_reencode_pixels_identical_imajima(tmp_path):
    import fitz

    pdf = _find_imajima2009()
    if pdf is None:
        pytest.skip("找不到 Imajima2009 PDF")
    rows = pdfsplit.split_pdf(pdf, tmp_path / "o", size=None, pages_range=(20, 21), max_bytes=10_000_000,
                              render_dpi=200, encode="flate")
    assert len(rows) == 1 and rows[0]["pages"] == 2 and rows[0]["ok"]
    a, b = fitz.open(str(pdf)), fitz.open(str(tmp_path / "o" / rows[0]["tag"] / rows[0]["file"]))
    for k, p in enumerate((20, 21)):
        assert a[p - 1].rect == b[k].rect
        pa = a[p - 1].get_pixmap(dpi=200, colorspace=fitz.csGRAY)
        pb = b[k].get_pixmap(dpi=200, colorspace=fitz.csGRAY)
        assert (pa.width, pa.height) == (pb.width, pb.height) and pa.samples == pb.samples


def test_reencode_ppocr_rows_identical(tmp_path):
    """原页抽成独立 PDF（无 ppocr 缓存，与重编码块同引擎同环境各 OCR 一次）后逐字比对。
    不直接比原 PDF 的缓存：缓存可能来自 GPU 运行，CPU 重跑会差个别标点（实测 p20 一个 ，/,）。"""
    pdf = _find_imajima2009()
    if pdf is None:
        pytest.skip("找不到 Imajima2009 PDF")
    try:
        from docstore.engines.ppocr import ppocr_rows
    except Exception:
        pytest.skip("ppocr 不可用")
    rows = pdfsplit.split_pdf(pdf, tmp_path / "o", size=None, pages_range=(20, 21), max_bytes=10_000_000,
                              render_dpi=200, encode="flate")
    new = tmp_path / "o" / rows[0]["tag"] / rows[0]["file"]
    orig2 = pdfsplit.split_pdf(pdf, tmp_path / "orig", size=2, pages_range=(20, 21), tag="orig2")
    ref = tmp_path / "orig" / "orig2" / orig2[0]["file"]
    try:
        for k in (1, 2):
            r0, _ = ppocr_rows(str(ref), k, 200)
            r1, _ = ppocr_rows(str(new), k, 200)
            assert [x[1] for x in r0] == [x[1] for x in r1]
    except AssertionError:
        raise
    except Exception as e:
        pytest.skip(f"ppocr 运行失败：{e}")
