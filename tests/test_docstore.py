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
    r = textify.textify(st, key, workers=1, log=lambda m: None)
    assert r["text_layer"] == 2 and r["ocr"] == 1
    p1, p3 = st.page(key, 1), st.page(key, 3)
    assert p1["verify_level"] == "text_layer" and "欧努菲虫科" in p1["text"]
    assert p3["verify_level"] == "ocr_raw" and p3["dpi"] == 300 and p3["quality"]["ocr_conf"] == 0.91
    assert p3["producer"] and p3["engine"].endswith("300dpi")
    # 断点续跑：再跑不重复
    assert textify.textify(st, key, workers=1, log=lambda m: None)["ocr"] == 0
    hits = st.search("欧努菲虫")
    assert [(h["key"], h["page"]) for h in hits] == [(key, 1)]
    assert st.search("颚器", kind="志书")[0]["page"] == 2      # 两字词走 LIKE
    assert st.search("刚毛与疣足")[0]["verify_level"] == "ocr_raw"
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
    textify.textify(st, key, workers=1, log=lambda m: None)
    fix = tmp / "fix.json"
    fix.write_text(json.dumps({"replace": {"桩识别": "人工核对"}}, ensure_ascii=False), encoding="utf-8")
    cli.main(["--root", str(st.root), "--by", "claude-opus", "verify", key, "3", "--fix", str(fix)])
    st2 = open_store(st.root)
    p = st2.page(key, 3)
    assert p["verify_level"] == "ocr_verified" and p["text"].startswith("人工核对")
    assert p["producer"] == "claude-opus"
    assert p["alternates"][0]["verify_level"] == "ocr_raw"            # 旧版本保留
    h = p["history"][-1]
    assert h["by"] == "claude-opus" and h["from_level"] == "ocr_raw" and h["fixes"] == {"桩识别": "人工核对"}


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
    textify.textify(st, key, workers=1, log=lambda m: None)
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
