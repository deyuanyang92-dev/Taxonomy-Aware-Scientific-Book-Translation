"""Item 3b: ingest-native emits role=figure blocks; the builder prefers them over caption matching."""
import fitz
from docx import Document

from booklayout import builder, ingest_native
from booklayout.profile import validate_aligned


def _pdf(path):
    doc = fitz.open()
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 300, 200), False)
    pix.set_rect(pix.irect, (200, 200, 200))
    p = doc.new_page(width=420, height=600)
    for i in range(8):
        p.insert_text((50, 60 + 12 * i), f"Body text line {i} of the paragraph above the figure.",
                      fontname="tiro", fontsize=10)
    p.insert_image(fitz.Rect(60, 200, 360, 400), stream=pix.tobytes("png"))
    p.insert_text((60, 420), "Figure 1. A worm.", fontname="tiro", fontsize=9)
    p.insert_text((60, 480), "Text after the figure runs on here.", fontname="tiro", fontsize=10)
    doc.save(str(path))


def test_ingest_emits_figure_block_paired_with_caption(tmp_path):
    _pdf(tmp_path / "f.pdf")
    data = ingest_native.ingest(tmp_path / "f.pdf")
    blocks = data["pages"][0]["blocks"]
    figs = [b for b in blocks if b["role"] == "figure"]
    caps = [b for b in blocks if b["role"] == "caption"]
    assert len(figs) == 1 and len(caps) == 1
    f, c = figs[0], caps[0]
    assert f["crop"] == "source_figure_crops/fig_source_p001_01.png"
    assert f["label"] == "1" and len(f["src"]["bbox"]) == 4
    assert f["caption_block_id"] == c["block_id"] and c["figure_id"] == f["crop"]
    order = [b["role"] for b in blocks]
    assert order.index("body") < order.index("figure") < order.index("caption")
    assert validate_aligned(data) == []


def _record(monkeypatch):
    seen = []
    monkeypatch.setattr(builder, "image_para", lambda doc, path, **kw: seen.append(path.name))
    monkeypatch.setattr(builder, "caption", lambda doc, text, genera: None)
    return seen


def test_place_figure_prefers_figure_id_over_label(tmp_path, monkeypatch):
    seen = _record(monkeypatch)
    for n in ("a.png", "b.png"):
        (tmp_path / n).write_bytes(b"x")
    page_figs = [{"crop": "a.png", "source_label": "1"}, {"crop": "b.png", "source_label": "2"}]
    cap = {"role": "caption", "translation": "Figure 1. Caption", "figure_id": "b.png"}
    builder.place_figure(Document(), cap, page_figs, None, figs_dir=tmp_path)
    assert seen == ["b.png"]


def test_place_figure_without_figure_id_keeps_label_matching(tmp_path, monkeypatch):
    seen = _record(monkeypatch)
    for n in ("a.png", "b.png"):
        (tmp_path / n).write_bytes(b"x")
    page_figs = [{"crop": "a.png", "source_label": "1"}, {"crop": "b.png", "source_label": "2"}]
    cap = {"role": "caption", "translation": "Fig. 2. Caption"}
    builder.place_figure(Document(), cap, page_figs, None, figs_dir=tmp_path)
    assert seen == ["b.png"]


def test_unpaired_figure_block_is_rendered_in_place(tmp_path, monkeypatch):
    seen = _record(monkeypatch)
    (tmp_path / "a.png").write_bytes(b"x")
    page_figs = [{"crop": "a.png", "source_label": ""}]
    blk = {"role": "figure", "crop": "source_figure_crops/a.png"}
    assert builder.render_figure_block(Document(), blk, page_figs, tmp_path) is True
    assert seen == ["a.png"] and page_figs[0]["_placed"]
    assert builder.render_figure_block(Document(), blk, page_figs, tmp_path) is False   # never twice
