import json
import shutil
import sqlite3

import fitz
import pytest

from docstore import adapters, cli, open_store, textify

CJK_FONT = "china-s"


def make_pdf(path, pages):
    """pages: 文本列表；None 表示图片页（无文字层）。"""
    doc = fitz.open()
    for t in pages:
        pg = doc.new_page(width=300, height=400)
        if t is None:
            pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 60, 60), 0)
            pix.clear_with(200)
            pg.insert_image(fitz.Rect(20, 20, 280, 380), pixmap=pix)
        else:
            pg.insert_textbox(fitz.Rect(20, 20, 280, 380), t, fontname=CJK_FONT, fontsize=10)
    doc.save(str(path))
    return path


@pytest.fixture
def lib(tmp_path, monkeypatch):
    monkeypatch.setattr(textify, "OCR_FUNC", lambda pdf, n, dpi: (f"桩识别文字第{n}页 刚毛与疣足", 0.91))
    monkeypatch.setenv("DOCSTORE_AGENT", "pytest")
    src = tmp_path / "src"
    src.mkdir()
    pdf = make_pdf(src / "中国动物志_测试卷.pdf",
                   ["欧努菲虫科 Onuphidae 体长形，口前叶具五个后头触手，背须指状。" * 2,
                    "矶沙蚕科 Eunicidae 的颚器由上颚和下颚组成，上颚多对。" * 2,
                    None])
    st = open_store(tmp_path / "lib")
    return st, pdf, tmp_path


def test_register_dedup_and_rename(lib):
    st, pdf, tmp = lib
    k1, new1 = st.register(pdf, by="pytest")
    k2, new2 = st.register(pdf)
    assert new1 and not new2 and k1 == k2
    d = st.doc(k1)
    assert d["kind"] == "志书" and d["domain"] == "分类学" and "待确认" in d["note"] and d["pages"] == "3"
    assert d["added_by"] == "pytest"
    moved = tmp / "改名.pdf"
    shutil.move(str(pdf), moved)
    k3, new3 = st.register(moved)
    assert not new3 and k3 == k1 and st.doc(k1)["path"] == str(moved)
    assert len(st.docs()) == 1


def test_text_layer_ocr_search_rebuild(lib):
    st, pdf, _ = lib
    key, _ = st.register(pdf)
    r = textify.textify(st, key, workers=1, engines=["rapidocr"], log=lambda m: None)
    assert r["text_layer"] == 2 and r["ocr"] == 1
    p1, p3 = st.page(key, 1), st.page(key, 3)
    assert p1["verify_level"] == "text_layer" and "欧努菲虫科" in p1["text"]
    assert p3["verify_level"] in ("ocr_raw", "ocr_sampled") and p3["dpi"] == 300 and p3["quality"]["ocr_conf"] == 0.91
    assert p3["producer"] and p3["engine"].endswith("300dpi")
    # 断点续跑：再跑不重复
    assert textify.textify(st, key, workers=1, engines=["rapidocr"], log=lambda m: None)["ocr"] == 0
    hits = st.search("欧努菲虫")
    assert [(h["key"], h["page"]) for h in hits] == [(key, 1)]
    assert st.search("颚器", kind="志书")[0]["page"] == 2      # 两字词走 LIKE
    assert p3["text"] and "页" in p3["text"]
    before = st.con.execute("SELECT key,page,text,verify_level FROM pages ORDER BY 1,2").fetchall()
    st.con.execute("DELETE FROM pages")
    st.con.commit()
    st.rebuild()
    after = st.con.execute("SELECT key,page,text,verify_level FROM pages ORDER BY 1,2").fetchall()
    assert before == after and st.search("欧努菲虫")
    assert st.status()[0]["done"] == 3


def test_verify_upgrade_keeps_trail(lib):
    st, pdf, tmp = lib
    key, _ = st.register(pdf)
    textify.textify(st, key, workers=1, engines=["rapidocr"], log=lambda m: None)
    fix = tmp / "fix.json"
    fix.write_text(json.dumps({"replace": {"桩识别": "人工核对"}}, ensure_ascii=False), encoding="utf-8")
    cli.main(["--root", str(st.root), "--by", "claude-opus", "verify", key, "3", "--fix", str(fix)])
    st2 = open_store(st.root)
    p = st2.page(key, 3)
    assert p["verify_level"] == "ocr_verified" and p["text"].startswith("人工核对")
    assert p["producer"] == "claude-opus"
    assert p["alternates"][0]["verify_level"] in ("ocr_raw", "ocr_sampled")  # 旧版本保留
    h = p["history"][-1]
    assert h["by"] == "claude-opus" and h["from_level"] in ("ocr_raw", "ocr_sampled") \
        and h["fixes"] == {"桩识别": "人工核对"}


def test_concurrent_versions_coexist(lib):
    st, pdf, _ = lib
    key, _ = st.register(pdf)
    from docstore.store import make_version
    st.put_version(key, 3, make_version("二百dpi识别", "ocr", producer="codex", dpi=200))
    st.put_version(key, 3, make_version("三百dpi识别", "ocr", producer="claude-haiku", dpi=300))
    st.put_version(key, 3, make_version("其他识别", "ocr", producer="deepseek"))
    p = st.page(key, 3)
    assert p["text"] == "三百dpi识别" and p["producer"] == "claude-haiku"
    assert {v["producer"] for v in p["alternates"]} == {"codex", "deepseek"}


def test_detect_and_import_txt_pages(lib):
    st, pdf, tmp = lib
    key, _ = st.register(pdf)
    ext = tmp / "外部OCR" / "某书"
    ext.mkdir(parents=True)
    for n in (1, 2, 3):
        (ext / f"p{n:04d}.txt").write_text(f"外部识别第{n}页 疣足", encoding="utf-8")
    (ext / "来源.json").write_text(json.dumps({"key": "某书", "path": str(pdf)}, ensure_ascii=False), encoding="utf-8")
    found = adapters.detect(st, tmp / "外部OCR")
    assert found and found[0]["format"] == "txt_pages" and found[0]["books"][0]["match"] == key
    assert not found[0]["imported"]
    r = adapters.run_import(st, tmp / "外部OCR", "txt_pages", by="pytest", dpi=200, log=lambda m: None)
    assert r["docs"] == [key] and r["versions"] == 3
    p = st.page(key, 2)
    assert p["producer"] == "claude-script" and p["dpi"] == 200
    assert adapters.detect(st, tmp / "外部OCR")[0]["imported"]
    # 再导一次不重复
    adapters.run_import(st, tmp / "外部OCR", "txt_pages", by="pytest", dpi=200, log=lambda m: None)
    assert len(st.page(key, 2)["alternates"]) == 0


def test_import_sqlite_and_codex_kb(lib):
    st, pdf, tmp = lib
    db = tmp / "旧库" / "知识库.sqlite"
    db.parent.mkdir()
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE sources(key TEXT PRIMARY KEY,title TEXT,path TEXT,pages INTEGER,sha256 TEXT,note TEXT)")
    con.execute("CREATE TABLE pages(source TEXT,page INTEGER,text TEXT,search_text TEXT,method TEXT,quality TEXT)")
    con.execute("INSERT INTO sources VALUES('志测','测试卷',?,3,'','')", (str(pdf),))
    con.execute("INSERT INTO pages VALUES('志测',3,'旧库识别第三页','', 'RapidOCR/PP-OCRv3','{}')")
    con.commit()
    con.close()
    assert adapters.detect(st, tmp / "旧库")[0]["format"] == "sqlite_pages"
    r = adapters.run_import(st, db, "sqlite_pages", by="pytest", log=lambda m: None)
    key = r["docs"][0]
    assert st.page(key, 3)["producer"] == "codex"
    # codex_kb：approved_pages 升级为 ocr_verified，并记录 confirmed_fixes
    kb = tmp / "kb"
    (kb / "原始证据" / "志测" / "pages").mkdir(parents=True)
    (kb / "OCR初识" / "志测").mkdir(parents=True)
    (kb / "原始证据" / "志测" / "来源.json").write_text(json.dumps({"key": "志测", "path": str(pdf)}), encoding="utf-8")
    (kb / "原始证据" / "志测" / "pages" / "p0003.json").write_text(
        json.dumps({"page": 3, "text": "", "method": "原PDF文本层（空文本，未判空白）"}), encoding="utf-8")
    (kb / "OCR初识" / "志测" / "p0003.json").write_text(
        json.dumps({"page": 3, "text": "盘首垂 Lopadorhynthus", "avg_score": 0.8}), encoding="utf-8")
    (kb / "校正规则.json").write_text(json.dumps({
        "confirmed_fixes": {"盘首垂": "盘首蚕", "Lopadorhynthus": "Lopadorhynchus", "无关": "x"},
        "approved_pages": ["志测:p0003"]}, ensure_ascii=False), encoding="utf-8")
    adapters.run_import(st, kb, "codex_kb", by="pytest", log=lambda m: None)
    p = st.page(key, 3)
    assert p["verify_level"] == "ocr_verified" and p["text"] == "盘首蚕 Lopadorhynchus"
    assert p["history"][-1]["fixes"] == {"盘首垂": "盘首蚕", "Lopadorhynthus": "Lopadorhynchus"}
    assert len(p["alternates"]) >= 2      # 旧库版本 + OCR初识原文 + 空文本层都在


def test_rename_moves_pages(lib):
    st, pdf, _ = lib
    key, _ = st.register(pdf)
    textify.textify(st, key, workers=1, engines=["rapidocr"], log=lambda m: None)
    st.rename(key, "志测2")
    assert st.page("志测2", 1)["key"] == "志测2" and st.search("欧努菲虫")[0]["key"] == "志测2"
    assert "曾用 key" in st.doc("志测2")["note"]


def test_registry_roundtrip_quotes_tabs(lib):
    st, pdf, _ = lib
    key, _ = st.register(pdf)
    title = 'A "quoted"\ttitle, with tab'
    st.update_doc(key, title=title, note='说"明"')
    st2 = open_store(st.root)
    assert st2.doc(key)["title"] == title and st2.doc(key)["note"] == '说"明"'
    assert len(st2.docs()) == 1


def test_key_validation(lib):
    from docstore.store import check_key
    st, pdf, tmp = lib
    for bad in ("../x", ".hidden", "a/b", "a..b", ""):
        with pytest.raises(ValueError):
            check_key(bad)
    with pytest.raises(ValueError):
        adapters.run_import(st, tmp, "txt_pages", key="../evil", log=lambda m: None)
    m = tmp / "map.tsv"
    m.write_text("dir\tkey\toffset\tdpi\nx\t../evil\t0\t200\n", encoding="utf-8")
    with pytest.raises(ValueError):
        adapters.run_import(st, tmp, "txt_pages", map_file=str(m), log=lambda m: None)
    with pytest.raises(ValueError):
        st.rename("nope", "..")
    key, _ = st.register(pdf, key="..evil/../k")
    check_key(key)


def test_map_key_reuses_registered_doc(lib):
    st, pdf, tmp = lib
    key, _ = st.register(pdf, key="志测")
    d = tmp / "R" / "志测叶须"
    d.mkdir(parents=True)
    for n in (1, 2, 3):
        (d / f"p{n:04d}.txt").write_text(f"缓存第{n}页", encoding="utf-8")
    m = tmp / "map.tsv"
    m.write_text("dir\tkey\toffset\tdpi\n志测叶须\t志测\t0\t200\n", encoding="utf-8")
    r = adapters.run_import(st, tmp / "R", "txt_pages", map_file=str(m), log=lambda m: None)
    assert r["docs"] == ["志测"] and len(st.docs()) == 1


def test_attach_binds_original(lib, capsys):
    st, pdf, tmp = lib
    key, _ = st.register(None, key="论文_缺", status="原件缺失")
    for n in (1, 2, 3):
        st.put_version(key, n, __import__("docstore.store", fromlist=["x"]).make_version(
            "欧努菲虫科 Onuphidae 体长形，口前叶具五个后头触手，背须指状。" * 2 if n == 1 else f"第{n}页",
            "ocr", producer="claude-script", dpi=200))
    cli.main(["--root", str(st.root), "--by", "pytest", "attach", key, str(pdf), "--check"])
    out = capsys.readouterr().out
    st2 = open_store(st.root)
    d = st2.doc(key)
    assert d["status"] == "registered" and d["pages"] == "3" and len(d["sha256"]) == 64 and d["path"] == str(pdf)
    assert "PDF p" in out
    with pytest.raises(ValueError):          # 同一原件不能绑到第二个 key
        k2, _ = st2.register(None, key="另一", status="原件缺失")
        st2.attach(k2, pdf)
    assert pdf.exists()                       # 不移动原件


def test_consensus_with_dual_engine_and_fix_rules(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCSTORE_AGENT", "pytest")
    src = tmp_path / "src"
    src.mkdir()
    pdf = make_pdf(src / "动物志33_测试.pdf", [None])
    st = open_store(tmp_path / "lib2")
    key, _ = st.register(pdf, key="动物志33")

    monkeypatch.setattr(textify, "OCR_FUNC", lambda *_: ("Lopadorhynthus 12一34", 0.8))
    monkeypatch.setitem(textify.ENGINE_MAP, "tesseract", lambda *_: ("Lopadorhynchus 12一34", 0.9))
    r = textify.textify(st, key, workers=1, engines=["rapidocr", "tesseract"], log=lambda m: None)
    assert r["ocr"] == 1
    p = st.page(key, 1)
    assert p["verify_level"] in ("ocr_sampled", "ocr_raw")
    assert "12—34" in (p.get("text") or "")           # 固定规则纠错
    assert p["producer"].startswith("consensus(")


def test_consensus_recompute_uses_existing_versions(tmp_path):
    st = open_store(tmp_path / "lib3")
    key, _ = st.register(None, key="卷33", status="原件缺失")
    from docstore.store import make_version

    st.put_version(key, 1, make_version("Heteropodark xiamenensis", "ocr", producer="a", conf=0.7))
    st.put_version(key, 1, make_version("Heteropodarke xiamenensis", "ocr", producer="b", conf=0.9))
    out = textify.consensus(st, key, pages=[1], by="pytest")
    assert out["recomputed"] == 1
    p = st.page(key, 1)
    vars_ = [p] + p.get("alternates", [])
    assert any(v.get("producer") == "consensus(rebuild)" for v in vars_)


def test_export_marked_pages_with_printed_page_markers(lib):
    st, pdf, _ = lib
    key, _ = st.register(pdf)
    textify.textify(st, key, workers=1, engines=["rapidocr"], log=lambda m: None)
    marked = st.export(key, "marked", [1, 2])
    assert marked.startswith("<!-- p.pdf1 -->\n") and "<!-- p.pdf2 -->\n" in marked and "pdf3" not in marked
    st.update_doc(key, page_offset=-13)                       # PDF 第 n 页 = 印刷页 n-13
    marked = st.export(key, "marked", [2, 3])
    assert marked.startswith("<!-- p.-11 -->\n") and "<!-- p.-10 -->\n" in marked and "欧努菲虫科" not in marked
    assert marked.count("<!-- p.") == 2 and marked.endswith("\n") and not marked.endswith("\n\n")
    assert "==== p" in st.export(key, "txt", [2]) and "==== p0001" not in st.export(key, "txt", [2])


def test_cli_export_marked_with_pages(lib, capsys):
    st, pdf, tmp = lib
    key, _ = st.register(pdf)
    textify.textify(st, key, workers=1, engines=["rapidocr"], log=lambda m: None)
    st.update_doc(key, page_offset=10)
    assert cli.main(["--root", str(st.root), "export", key, "--marked", "--pages", "1-2"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("<!-- p.11 -->\n") and "<!-- p.12 -->" in out and "p.13" not in out


def test_text_layer_only_skips_ocr(lib, monkeypatch):
    st, pdf, tmp = lib
    called = []
    monkeypatch.setattr(textify, "OCR_FUNC", lambda *a: called.append(a) or ("x", 0.9))
    key, _ = st.register(pdf, by="pytest")
    r = textify.textify(st, key, workers=1, layer_only=True, log=lambda s: None)
    assert r["layer_only"] and r["text_layer"] == 2 and r["pending_ocr"] == 1 and not called
    assert st.page_numbers(key) == [1, 2]


def test_attest_word_boundary(tmp_path, monkeypatch):
    from docstore.attest import attest, prefer
    from docstore.store import make_version
    monkeypatch.setenv("DOCSTORE_AGENT", "pytest")
    st = open_store(tmp_path / "lib")
    pdf = tmp_path / "Day, 1967-A monograph.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    key, _ = st.register(pdf, by="pytest")
    st.update_doc(key, lang="en")
    st.put_version(key, 1, make_version("Compound setae with falcigerous blades; tentacular cirri long.", "text_layer",
                                        producer="t"))
    st.put_version(key, 2, make_version("Setae simple. Tentacular\ncirri short.", "text_layer", producer="t"))
    assert attest(st, "tentacular cirri")["pages"] == 2
    assert attest(st, "seta")["pages"] == 0          # 不把 setae 算作 seta
    assert attest(st, "falcigerous blades", lang="de")["pages"] == 0
    assert prefer(st, ["end phalanges", "falcigerous blades"])[0][0] == "falcigerous blades"


def test_registry_survives_transient_absence(tmp_path):
    """回归（2026-11-16）：别的进程原子替换 registry.tsv 时文件瞬时不存在，读取方不得崩或读成空表。"""
    import threading

    from docstore import open_store

    st = open_store(tmp_path / "lib")
    pdf = tmp_path / "Muster, 1970-Die Polychaeten der Nordsee.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    key, _ = st.register(pdf, by="pytest")
    assert key in st._load_registry()
    saved = st.registry_path.read_bytes()
    st.registry_path.unlink()
    threading.Timer(0.6, lambda: st.registry_path.write_bytes(saved)).start()
    assert key in st._load_registry()


def test_fresh_library_without_registry_is_empty_and_fast(tmp_path):
    """回归（2026-11-16）：新库空表（{}）曾被当成『已加载过』，缺登记表时白等 10 秒再抛错。"""
    import time

    from docstore import open_store

    st = open_store(tmp_path / "lib")
    t = time.time()
    assert st._load_registry() == {}
    assert st._load_registry() == {}
    assert time.time() - t < 2


# ---------------------------------------------------------------- issue #3：导出缺页要明确报告

def test_export_reports_missing_pages_not_silent(lib, capsys):
    st, pdf, _ = lib
    key, _ = st.register(pdf)
    textify.textify(st, key, workers=1, layer_only=True, log=lambda m: None)   # 第 3 页（图片页）仍待 OCR
    assert st.missing_pages(key) == [3]
    assert st.missing_pages(key, [1, 2]) == []
    assert cli.main(["--root", str(st.root), "export", key, "--translate"]) == 0
    cap = capsys.readouterr()
    assert "<!-- PDF p.2" in cap.out and "PDF p.3" not in cap.out
    assert "缺页" in cap.err and "3" in cap.err and key in cap.err


def test_export_strict_fails_on_missing_pages(lib, capsys):
    st, pdf, _ = lib
    key, _ = st.register(pdf)
    textify.textify(st, key, workers=1, layer_only=True, log=lambda m: None)
    with pytest.raises(SystemExit) as e:
        cli.main(["--root", str(st.root), "export", key, "--translate", "--strict"])
    assert e.value.code != 0
    assert "缺页" in capsys.readouterr().err


def test_export_after_ocr_pending_pages_has_no_missing(lib, capsys):
    """text（文本层）→ 待 OCR 页补做 → export：全部页标记齐全，无缺页警告。"""
    st, pdf, _ = lib
    key, _ = st.register(pdf)
    textify.textify(st, key, workers=1, layer_only=True, log=lambda m: None)
    textify.textify(st, key, workers=1, engines=["rapidocr"], log=lambda m: None)
    assert st.missing_pages(key) == []
    assert cli.main(["--root", str(st.root), "export", key, "--translate", "--strict"]) == 0
    cap = capsys.readouterr()
    assert cap.out.count("<!-- PDF p.") == 3 and "缺页" not in cap.err
