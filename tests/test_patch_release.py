"""patch_release（docx / PDF 定点替换）与 share_pdf.sh。PDF 字形替换需要本机有 CJK 字体，没有则 skip。"""
import shutil
import subprocess
import zipfile
from pathlib import Path

import fitz
import pytest

import patch_release as pr

REPO = Path(__file__).resolve().parent.parent
FONTS = ["/mnt/c/Windows/Fonts/simkai.ttf", "/mnt/c/Windows/Fonts/simhei.ttf", "C:/Windows/Fonts/simkai.ttf"]
FONT = next((f for f in FONTS if Path(f).exists()), None)

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def make_docx(path, body, header=""):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("word/document.xml", f'<?xml version="1.0" encoding="UTF-8"?><w:document {W}><w:body>{body}</w:body></w:document>')
        if header:
            z.writestr("word/header1.xml", f'<?xml version="1.0" encoding="UTF-8"?><w:hdr {W}>{header}</w:hdr>')
    return path


def doc_xml(path, part="word/document.xml"):
    with zipfile.ZipFile(path) as z:
        return z.read(part).decode("utf8")


def para(*runs):
    return "<w:p>" + "".join(f"<w:r><w:rPr><w:i/></w:rPr><w:t>{r}</w:t></w:r>" for r in runs) + "</w:p>"


def test_read_table(tmp_path):
    t = tmp_path / "t.tsv"
    t.write_text("# 注释\n\n磷虫科\t燐虫科\n甲\t乙\t多余列忽略\n", encoding="utf8")
    assert pr.read_table(t) == [("磷虫科", "燐虫科"), ("甲", "乙")]
    t.write_text("只有一列\n", encoding="utf8")
    with pytest.raises(ValueError):
        pr.read_table(t)


def test_replace_in_texts_across_runs():
    texts = ["磷", "虫", "科和磷虫科"]
    assert pr.replace_in_texts(texts, "磷虫科", "燐虫科") == (2, 1)
    assert texts == ["燐", "", "和燐虫科"] or "".join(texts) == "燐虫科和燐虫科"
    assert "".join(texts) == "燐虫科和燐虫科"


def test_docx_single_and_cross_run_and_header(tmp_path):
    src = make_docx(
        tmp_path / "a.docx",
        para("磷虫科是一科。") + para("磷", "虫科", "与磷虫科") + para("A &amp; B 磷虫科"),
        header=para("磷虫科 页眉"),
    )
    out = tmp_path / "b.docx"
    res = pr.patch_docx(src, out, [("磷虫科", "燐虫科"), ("不存在", "x")])
    assert res[0].count == 5 and res[0].cross == 1 and res[0].ok
    assert res[1].count == 0 and res[1].note == "未命中" and not res[1].ok
    x = doc_xml(out)
    assert "磷" not in x and x.count("燐虫科") == 4
    assert "A &amp; B 燐虫科" in x  # 实体原样回写
    assert "<w:i/>" in x  # 格式保留
    assert "燐虫科 页眉" in doc_xml(out, "word/header1.xml")
    assert "磷虫科" in doc_xml(src)  # 原文件不动


def test_docx_not_across_paragraph_or_tab(tmp_path):
    body = "<w:p><w:r><w:t>磷</w:t></w:r></w:p><w:p><w:r><w:t>虫科</w:t></w:r></w:p>" \
           "<w:p><w:r><w:t>磷</w:t></w:r><w:r><w:tab/></w:r><w:r><w:t>虫科</w:t></w:r></w:p>"
    src = make_docx(tmp_path / "a.docx", body)
    res = pr.patch_docx(src, None, [("磷虫科", "燐虫科")])
    assert res[0].count == 0


def test_docx_adds_space_preserve_and_escapes(tmp_path):
    src = make_docx(tmp_path / "a.docx", "<w:p><w:r><w:t>甲乙</w:t></w:r></w:p>")
    out = tmp_path / "o.docx"
    pr.patch_docx(src, out, [("甲", " A<B ")])
    x = doc_xml(out)
    assert '<w:t xml:space="preserve"> A&lt;B 乙</w:t>' in x


def test_docx_cli_dry_exit_codes_and_no_overwrite(tmp_path, capsys):
    src = make_docx(tmp_path / "a.docx", para("磷虫科"))
    tsv = tmp_path / "t.tsv"
    tsv.write_text("磷虫科\t燐虫科\n", encoding="utf8")
    assert pr.main([str(src), str(tsv), "--dry"]) == 0
    assert not (tmp_path / "a_patched.docx").exists()
    assert pr.main([str(src), str(tsv)]) == 0
    assert "燐虫科" in doc_xml(tmp_path / "a_patched.docx")
    tsv.write_text("没有\t有\n", encoding="utf8")
    assert pr.main([str(src), str(tsv), "-o", str(tmp_path / "z.docx")]) == 1
    assert pr.main([str(src), str(tsv), "-o", str(src)]) == 2
    assert pr.main([str(tmp_path / "x.txt"), str(tsv)]) == 2
    assert "未命中" in capsys.readouterr().out


# ---------------- PDF ----------------

needs_font = pytest.mark.skipif(FONT is None, reason="本机没有可嵌入的 CJK 字体")


def make_pdf(path, text):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_font(fontname="kai", fontfile=FONT)
    page.insert_text((72, 100), text, fontname="kai", fontsize=20)
    doc.subset_fonts()
    doc.save(path)
    doc.close()
    return path


def pixels(path):
    with fitz.open(path) as d:
        return d[0].get_pixmap(dpi=100).samples


def page_text(path):
    with fitz.open(path) as d:
        return d[0].get_text().strip()


def test_parse_tounicode():
    cmap = (b"begincodespacerange <0000> <FFFF> endcodespacerange\n"
            b"1 beginbfchar <0003> <0020> endbfchar\n"
            b"2 beginbfrange <0010> <0012> <4E00> <0020> <0021> [<0041> <0042>] endbfrange")
    m = pr.parse_tounicode(cmap)
    assert m[3] == " " and m[0x10] == "一" and m[0x12] == "丂" and m[0x20] == "A" and m[0x21] == "B"


@needs_font
def test_pdf_same_length_glyph_replaced_in_place(tmp_path):
    src = make_pdf(tmp_path / "a.pdf", "磷虫科 燐虫科 ABC")
    out = tmp_path / "b.pdf"
    res = pr.patch_pdf(src, out, [("磷虫科", "燐虫科")])
    assert res[0].ok and res[0].count == 1
    assert page_text(out) == "燐虫科 燐虫科 ABC"
    # 与直接排「燐虫科 燐虫科 ABC」的页面逐像素一致：说明用的是同一字体里的同一字形
    ref = make_pdf(tmp_path / "ref.pdf", "燐虫科 燐虫科 ABC")
    assert pixels(out) == pixels(ref)
    assert page_text(src) == "磷虫科 燐虫科 ABC"  # 原文件不动


@needs_font
def test_pdf_cross_segment_inside_tj_array(tmp_path):
    src = make_pdf(tmp_path / "a.pdf", "磷虫科 燐虫科")
    with fitz.open(src) as d:
        page = d[0]
        cx = page.get_contents()[0]
        data = d.xref_stream(cx)
        import re
        m = re.search(rb"\[<([0-9a-f]+)>\]\s*TJ", data)
        h = m.group(1).decode()
        split = f"[<{h[:4]}>-3<{h[4:8]}>5<{h[8:]}>]TJ".encode()  # 把一个十六进制串拆成带字距调整的三段
        d.update_stream(cx, data[:m.start()] + split + data[m.end():])
        d.save(tmp_path / "split.pdf")
    out = tmp_path / "o.pdf"
    res = pr.patch_pdf(tmp_path / "split.pdf", out, [("磷虫科", "燐虫科")])
    assert res[0].ok and res[0].count == 1 and res[0].cross == 1
    assert page_text(out) == "燐虫科 燐虫科"


@needs_font
def test_pdf_refuses_length_change_missing_glyph_and_non_wide(tmp_path):
    src = make_pdf(tmp_path / "a.pdf", "磷虫科 燐虫科 ABC")
    out = tmp_path / "o.pdf"
    res = pr.patch_pdf(src, out, [("磷虫科", "燐虫"), ("磷", "磺"), ("ABC", "CBA"), ("不在页面", "不再页面")])
    assert "新旧字数不同" in res[0].note and "word_render" in res[0].note
    assert "不在嵌入字体子集" in res[1].note and "word_render" in res[1].note
    assert "字宽不同" in res[2].note
    assert "未在单个文本串内命中" in res[3].note
    assert not any(r.ok for r in res)
    assert page_text(out) == "磷虫科 燐虫科 ABC"


@needs_font
def test_pdf_cli_exit_code_and_hint(tmp_path, capsys):
    src = make_pdf(tmp_path / "a.pdf", "磷虫科 燐虫科")
    tsv = tmp_path / "t.tsv"
    tsv.write_text("磷虫科\t燐虫科\n磷\t磺\n", encoding="utf8")
    assert pr.main([str(src), str(tsv), "-o", str(tmp_path / "o.pdf")]) == 1
    o = capsys.readouterr().out
    assert "OK    磷虫科 -> 燐虫科" in o and "请用 word_render 由改后 docx 重渲染" in o


# ---------------- share_pdf.sh ----------------

@pytest.mark.skipif(shutil.which("gs") is None, reason="没有 Ghostscript")
def test_share_pdf_shrinks_images_and_keeps_text(tmp_path):
    import os
    doc = fitz.open()
    page = doc.new_page()
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 1600, 1200), 0)
    pix.set_rect(pix.irect, (10, 120, 200))
    for i in range(0, 1200, 3):  # 加噪声，让大图体积够大
        pix.set_rect(fitz.IRect(0, i, 1600, i + 1), ((i * 7) % 255, (i * 13) % 255, (i * 29) % 255))
    page.insert_image(fitz.Rect(20, 100, 560, 500), pixmap=pix)
    page.insert_text((72, 60), "Nereididae share", fontname="helv", fontsize=14)
    src = tmp_path / "formal.pdf"
    doc.save(src)
    out = tmp_path / "share.pdf"
    r = subprocess.run(["bash", str(REPO / "scripts/publish/share_pdf.sh"), str(src), str(out)],
                       capture_output=True, text=True, env={**os.environ})
    assert r.returncode == 0, r.stderr
    assert out.stat().st_size < src.stat().st_size
    assert "Nereididae" in fitz.open(out)[0].get_text()
    # 不允许覆盖正式版、缺参数
    assert subprocess.run(["bash", str(REPO / "scripts/publish/share_pdf.sh"), str(src), str(src)],
                          capture_output=True, text=True).returncode == 2
    assert subprocess.run(["bash", str(REPO / "scripts/publish/share_pdf.sh")], capture_output=True, text=True).returncode == 2
