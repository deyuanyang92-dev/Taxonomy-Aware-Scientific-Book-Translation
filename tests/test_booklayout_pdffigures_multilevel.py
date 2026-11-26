"""Issue #62: multi-level figure numbers (Fig. 7.11.2.3) in CAPTION_RE."""
from __future__ import annotations

import fitz
import pytest

from booklayout import pdffigures
from booklayout.pdffigures import CAPTION_RE


@pytest.mark.parametrize("text,label", [
    ("Fig. 12. Worm.", "12"),
    ("Figs. 3-5. Three worms.", "3-5"),
    ("Fig. 3A, B. Panels.", "3A"),
    ("Fig. 7.11.2.3: Prostomium.", "7.11.2.3"),
    ("Fig. 7.4.1 Anterior end.", "7.4.1"),
    ("Figs 7.1.2-7.1.4. Series.", "7.1.2-7.1.4"),
    ("Figure 2.5a. Detail.", "2.5a"),
])
def test_label(text, label):
    m = CAPTION_RE.match(text)
    assert m and m.group("label") == label


def test_sentence_period_not_in_label():
    assert CAPTION_RE.match("Fig. 12. Worm.").group("label") == "12"


def test_page_captions_multilevel(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=420, height=600)
    page.insert_text((50, 100), "Fig. 7.11.2.3: Prostomium of a worm.", fontsize=9)
    page.insert_text((50, 200), "Fig. 7.11.2.4: Pygidium of a worm.", fontsize=9)
    caps = pdffigures.page_captions(page)
    assert [c["label"] for c in caps] == ["7.11.2.3", "7.11.2.4"]
