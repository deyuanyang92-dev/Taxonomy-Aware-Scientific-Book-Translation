"""Item 2: offline contents detection in ingest-native -> role toc_entry, page kind toc."""
import fitz

from booklayout import ingest_native
from booklayout.profile import validate_aligned

ENTRIES = [("Introduction", 1), ("Material and methods", 7), ("Results", 15), ("Discussion", 31),
           ("Acknowledgements", 44), ("References", 46)]


def _pdf(path, leaders=True):
    doc = fitz.open()
    p = doc.new_page(width=420, height=600)
    p.insert_text((50, 60), "Contents", fontname="hebo", fontsize=14)
    y = 100
    for t, n in ENTRIES:
        if leaders:
            dots = " " + ". " * 22
            p.insert_text((50, y), f"{t}{dots}", fontname="tiro", fontsize=10)
            p.insert_text((350, y), str(n), fontname="tiro", fontsize=10)
        else:
            p.insert_text((50, y), t, fontname="tiro", fontsize=10)
            p.insert_text((350, y), str(n), fontname="tiro", fontsize=10)
        y += 18
    q = doc.new_page(width=420, height=600)
    q.insert_text((50, 60), "1 Introduction", fontname="hebo", fontsize=14)
    for i in range(10):
        q.insert_text((50, 100 + 12 * i), f"Plain body sentence number {i} runs along the line here.",
                      fontname="tiro", fontsize=10)
    doc.save(str(path))
    doc.close()


def test_leader_contents_page_becomes_toc_entries(tmp_path):
    _pdf(tmp_path / "t.pdf")
    data = ingest_native.ingest(tmp_path / "t.pdf")
    p1, p2 = data["pages"]
    assert p1["kind"] == "toc"
    ents = [b for b in p1["blocks"] if b["role"] == "toc_entry"]
    assert [(b["text"], b["printed"]) for b in ents] == [(t, str(n)) for t, n in ENTRIES]
    assert all(b["style"] == "Contents" for b in ents)
    assert not [b for b in p1["blocks"] if b["role"] == "body"]
    assert p2["kind"] != "toc" and not [b for b in p2["blocks"] if b["role"] == "toc_entry"]
    assert validate_aligned(data) == []


def test_contents_without_leaders_needs_contents_title(tmp_path):
    _pdf(tmp_path / "t.pdf", leaders=False)
    data = ingest_native.ingest(tmp_path / "t.pdf")
    assert data["pages"][0]["kind"] == "toc"
    assert len([b for b in data["pages"][0]["blocks"] if b["role"] == "toc_entry"]) == len(ENTRIES)


def test_builder_renders_toc_entry_with_dot_leader():
    from docx import Document
    from docx.enum.text import WD_TAB_LEADER
    from booklayout import builder
    doc = Document()
    builder.render_toc_entry(doc, {"role": "toc_entry", "printed": "15", "toc_level": 1}, "Results", None)
    par = doc.paragraphs[-1]
    assert par.text.replace("\t", "|") == "Results|15"
    assert any(t.leader == WD_TAB_LEADER.DOTS for t in par.paragraph_format.tab_stops)
