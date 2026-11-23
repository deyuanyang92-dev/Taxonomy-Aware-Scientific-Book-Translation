"""Heading styles, taxon levels, caption/heading promotion, scan figure detection,
restyle linkage and DOCX/HTML consistency (Fauna Iberica typesetting delivery)."""
from __future__ import annotations

import argparse
import re
import zipfile
from pathlib import Path

import numpy as np
import pytest
from docx import Document

from booklayout import builder
from booklayout.headings import promote_captions, promote_headings, taxon_level, toc_title
from booklayout.profile import StyleProfile
from booklayout.scanfigures import find_figures


@pytest.mark.parametrize("text,level", [
    ("Familia SYLLIDAE Grube, 1850", 1),
    ("Género Branchiosyllis Ehlers, 1887", 2),
    ("Subfamilia Exogoninae Langerhans, 1879", 2),
    ("Clave de géneros", 3),
    ("Branchiosyllis exilis (Gravier, 1900)（图184）", 3),
    ("Sphaerosyllis cryptica Ben-Eliahu, 1977. Isr. J. Zool., 26: 273", 4),
    ("Erinaceusyllis cryptica (Ben-Eliahu, 1977) comb. n.（图124）Sphaerosyllis x Ben-Eliahu, 1977. Isr. J. Zool., 26: 273", 3),
    ("Branchiosyllis 属 Ehlers, 1887", 2),
    ("Syllidae 科 Grube, 1850", 1),
    ("Exogoninae 亚科 Langerhans", 2),
])
def test_taxon_level(text, level):
    assert taxon_level(text) == level


def test_toc_title_cuts_after_figure_reference():
    t = "Erinaceusyllis cryptica (B, 1977) comb. n.（图124）Sphaerosyllis x B, 1977. Isr. J. Zool., 26: 273"
    assert toc_title(t) == "Erinaceusyllis cryptica (B, 1977) comb. n.（图124）"
    assert toc_title("A\nB") == "A"


def _page(blocks):
    return {"pages": [{"page": 1, "chapter": "c", "kind": "text", "blocks": blocks}]}


def test_promote_captions_merges_continuation_without_newlines():
    data = _page([
        {"role": "body", "label": "vision_footnote", "text": "Fig. 3. Foo (A)", "translation": "图3. 甲（A）"},
        {"role": "body", "label": "vision_footnote", "text": "e inferior\n(B)", "translation": "及下方\n（B）。"},
        {"role": "body", "label": "text", "text": "Body.", "translation": "正文。"},
    ])
    promote_captions(data)
    blocks = data["pages"][0]["blocks"]
    assert [b["role"] for b in blocks] == ["caption", "body"]
    assert "\n" not in blocks[0]["translation"] and blocks[0]["translation"].endswith("（B）。")


def test_promote_headings_splits_rank_line():
    data = _page([{"role": "body", "label": "text",
                   "text": "Género Branchiosyllis Ehlers, 1887\nBranchiosyllis Ehlers, 1887. Mem.: 148",
                   "translation": "Branchiosyllis 属 Ehlers, 1887\nBranchiosyllis Ehlers, 1887. Mem.: 148"}])
    assert promote_headings(data) == 1
    b = data["pages"][0]["blocks"]
    assert [x["role"] for x in b] == ["heading", "body"]
    assert b[0]["translation"] == "Branchiosyllis 属 Ehlers, 1887"


def test_find_figures_ignores_text_lines_and_keeps_panels():
    import cv2
    img = np.full((1200, 900), 255, np.uint8)
    cv2.rectangle(img, (150, 200), (450, 500), 0, -1)       # panel A
    cv2.rectangle(img, (480, 200), (760, 500), 0, -1)       # panel B, side by side -> one plate
    for row in range(5):                                      # caption-like text line of small glyphs
        for k in range(30):
            cv2.rectangle(img, (120 + k * 22, 800 + row * 30), (120 + k * 22 + 10, 800 + row * 30 + 12), 0, -1)
    boxes = find_figures(img, dpi=150)
    assert len(boxes) == 1
    b = boxes[0]
    assert b.x0 <= 155 and b.x1 >= 755 and b.y1 < 600


def test_profile_level4_and_validation():
    p = StyleProfile()
    assert p.heading_style(4)["size"] > 0
    with pytest.raises(ValueError):
        StyleProfile(heading_levels="bogus").validate()


def _small_doc(path: Path, prof: StyleProfile):
    builder.apply_profile(prof)
    d = Document()
    d.add_paragraph("Chapter one", style="Heading 1")
    d.add_paragraph("Genus Foo", style="Heading 2")
    d.add_paragraph("Body text with 12 mm width.")
    d.add_paragraph("Another genus", style="Heading 2")
    builder.define_heading_styles(d, prof)
    d.save(str(path))


def _parts(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as z:
        return {n: z.read(n) for n in z.namelist()}


def test_restyle_changes_only_styles_xml_and_all_same_level_headings(tmp_path):
    from booklayout.cli import cmd_restyle
    base = StyleProfile()
    src = tmp_path / "a.docx"
    _small_doc(src, base)
    import json
    styles = {k: dict(v) for k, v in base.heading_styles.items()}
    styles["2"].update({"size": 17, "before": 20, "after": 9})
    prof_json = tmp_path / "p.json"
    prof_json.write_text(json.dumps({"heading_styles": styles}), encoding="utf-8")
    out = tmp_path / "b.docx"
    cmd_restyle(argparse.Namespace(docx=src, profile=prof_json, out=out, pdf=False, pdf_out=None, html=None))
    a, b = _parts(src), _parts(out)
    changed = sorted(n for n in a if a[n] != b.get(n))
    assert changed == ["word/styles.xml"]
    sty = Document(str(out)).styles["Heading 2"]
    assert round(sty.font.size.pt) == 17
    # the Heading 1 definition is untouched by a Heading 2 edit
    assert Document(str(src)).styles["Heading 1"].font.size == Document(str(out)).styles["Heading 1"].font.size


def test_html_contains_every_docx_paragraph_in_order(tmp_path):
    from booklayout.htmlout import docx_to_html
    prof = StyleProfile()
    src = tmp_path / "a.docx"
    _small_doc(src, prof)
    res = docx_to_html(src, tmp_path / "a.html", prof)
    text = (tmp_path / "a.html").read_text(encoding="utf-8")
    body = re.sub(r"<[^>]+>", "|", text.split("<body>")[1])
    texts = [p.text for p in Document(str(src)).paragraphs if p.text]
    pos = -1
    for t in texts:
        i = body.find(t, pos + 1)
        assert i > pos, t
        pos = i
    assert "<h2>Genus Foo</h2>" in text and res["paragraphs"] == len(texts)
    assert "h2{font-size:" in text
