"""Issue #18: linked figure/caption objects, geometric caption ends, oversize report."""
from __future__ import annotations

import split_figures as sf
from booklayout.figures import audit_placement, link_figures

PAGE = {"width": 595.0, "height": 842.0}


# ---- geometric caption end (scripts/split_figures.py) ------------------------

def blk(i: str, text: str, y0: float, y1: float, x0: float = 72.0, x1: float = 523.0) -> dict:
    return {"id": i, "text": text, "bbox": (x0, y0, x1, y1)}


def test_body_paragraph_after_caption_stays_body() -> None:
    blocks = [
        blk("b1", "Intro paragraph of the page.", 60, 100),
        blk("c1", "Fig. 3. Habitus of Alpha beta, dorsal view", 300, 312),
        blk("c1b", "and details of the pygidium", 314, 326),
        # caption text has no final full stop, but a clear gap and a new
        # indented paragraph start the body again
        blk("b2", "The pygidium bears two cirri and is rounded.", 345, 380, x0=85.0),
    ]
    body, caps = sf.split_blocks(blocks)
    assert [c["id"] for c in caps] == ["fig-3"]
    assert caps[0]["blocks"] == ["c1", "c1b"]
    assert caps[0]["bbox"] == (72.0, 300, 523.0, 326)
    assert [b["id"] for b in body] == ["b1", "b2"]


def test_caption_ending_with_sentence_stops_even_if_next_block_is_close() -> None:
    blocks = [
        blk("c1", "Fig. 4. Parapodium of Gamma delta.", 300, 312),
        blk("b1", "Remarks follow immediately.", 314, 326),
    ]
    body, caps = sf.split_blocks(blocks)
    assert caps[0]["blocks"] == ["c1"]
    assert [b["id"] for b in body] == ["b1"]


def test_next_caption_always_stops() -> None:
    blocks = [
        blk("c1", "Fig. 5. First, with a long", 300, 312),
        blk("c2", "Fig. 6. Second caption.", 314, 326),
    ]
    _, caps = sf.split_blocks(blocks)
    assert [c["id"] for c in caps] == ["fig-5", "fig-6"]


def test_oversize_caption_is_reported() -> None:
    long_text = "Fig. 7. " + "word " * 400
    _, caps = sf.split_blocks([blk("c1", long_text, 100, 400)], max_chars=1000)
    assert caps[0]["oversize"] is True


# ---- linked figure and caption objects ---------------------------------------

def test_two_figures_side_by_side_get_their_own_caption() -> None:
    figures = [
        {"id": "F-a", "page": 7, "bbox": (72, 100, 290, 300)},
        {"id": "F-b", "page": 7, "bbox": (305, 100, 523, 300)},
    ]
    captions = [  # deliberately in reversed order
        {"id": "fig-9", "page": 7, "label": "9", "bbox": (305, 310, 523, 340), "text": "Fig. 9. Right."},
        {"id": "fig-8", "page": 7, "label": "8", "bbox": (72, 310, 290, 340), "text": "Fig. 8. Left."},
    ]
    objs, unmatched = link_figures(figures, captions)
    assert unmatched == {"figures": [], "captions": []}
    assert {o.id: o.caption_id for o in objs} == {"F-a": "fig-8", "F-b": "fig-9"}
    assert all(o.caption_bbox for o in objs)


def test_label_wins_over_proximity() -> None:
    figures = [{"id": "F1", "page": 2, "bbox": (72, 100, 523, 300), "label": "2"},
               {"id": "F2", "page": 2, "bbox": (72, 400, 523, 600), "label": "1"}]
    captions = [{"id": "c1", "page": 2, "label": "1", "bbox": (72, 305, 523, 330), "text": "Fig. 1."},
                {"id": "c2", "page": 2, "label": "2", "bbox": (72, 605, 523, 630), "text": "Fig. 2."}]
    objs, _ = link_figures(figures, captions)
    assert {o.id: o.caption_id for o in objs} == {"F1": "c2", "F2": "c1"}


def test_unmatched_are_reported_not_hidden() -> None:
    objs, unmatched = link_figures(
        [{"id": "F1", "page": 1, "bbox": (72, 100, 523, 300)}],
        [{"id": "c9", "page": 3, "label": "9", "bbox": (72, 100, 523, 120), "text": "Fig. 9."}])
    assert unmatched == {"figures": ["F1"], "captions": ["c9"]}


def test_audit_flags_oversize_and_far_caption_and_overlap() -> None:
    figures = [
        {"id": "big", "page": 1, "bbox": (0, 0, 595, 800)},
        {"id": "far", "page": 2, "bbox": (72, 100, 523, 200)},
        {"id": "ok", "page": 3, "bbox": (72, 100, 523, 300)},
        {"id": "fx", "page": 4, "bbox": (72, 50, 523, 90)},
    ]
    captions = [
        {"id": "cb", "page": 1, "label": "1", "bbox": (72, 805, 523, 830), "text": "Fig. 1. x"},
        {"id": "cf", "page": 2, "label": "2", "bbox": (72, 700, 523, 720), "text": "Fig. 2. y"},
        {"id": "co", "page": 3, "label": "3", "bbox": (72, 306, 523, 330), "text": "Fig. 3. z", "chars": 9},
        {"id": "cx", "page": 4, "label": "4", "bbox": (72, 100, 523, 800), "text": "Fig. 4. " + "w " * 900,
         "chars": 1800},
        {"id": "orphan", "page": 9, "label": "9", "bbox": (72, 100, 523, 120), "text": "Fig. 9."},
    ]
    objs, unmatched = link_figures(figures, captions)
    problems = audit_placement(objs, unmatched, PAGE, body_bboxes={3: [(72, 301, 523, 305)]})
    reasons = {(p["reason"], p.get("id")) for p in problems}
    assert ("oversize_figure", "big") in reasons
    assert ("caption_not_adjacent", "far") in reasons
    assert ("body_between_figure_and_caption", "ok") in reasons
    assert ("unmatched_caption", "orphan") in reasons
    assert ("oversize_caption", "fx") in reasons


def test_clean_page_has_no_problems() -> None:
    objs, unmatched = link_figures(
        [{"id": "F", "page": 1, "bbox": (72, 100, 523, 300)}],
        [{"id": "c", "page": 1, "label": "1", "bbox": (72, 306, 523, 330), "text": "Fig. 1. ok"}])
    assert audit_placement(objs, unmatched, PAGE) == []
