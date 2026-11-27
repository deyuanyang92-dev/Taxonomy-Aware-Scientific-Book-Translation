"""Item 3a: vector clustering must not report table grids or header/footer rules as figures."""
import fitz

from booklayout import pdffigures


def _page():
    doc = fitz.open()
    return doc, doc.new_page(width=420, height=600)


def test_table_grid_is_not_a_figure():
    doc, p = _page()
    for r in range(7):
        y = 100 + 22 * r
        p.draw_line((50, y), (370, y), color=(0, 0, 0), width=0.5)
    for c in range(5):
        x = 50 + 80 * c
        p.draw_line((x, 100), (x, 232), color=(0, 0, 0), width=0.5)
    for r in range(6):
        for c in range(4):
            p.insert_text((56 + 80 * c, 115 + 22 * r), f"cell{r}{c}", fontsize=9)
    assert [x for x in pdffigures.image_placements(p, vector=True)] == []


def test_header_and_footer_rules_are_not_figures():
    doc, p = _page()
    p.draw_line((50, 40), (370, 40), color=(0, 0, 0), width=0.5)
    p.draw_rect(fitz.Rect(50, 36, 370, 80), color=(0, 0, 0), width=0.5)    # boxed running head
    p.insert_text((60, 60), "RUNNING HEAD", fontsize=9)
    p.draw_line((50, 560), (370, 560), color=(0, 0, 0), width=0.5)
    p.insert_text((200, 580), "12", fontsize=9)
    assert pdffigures.image_placements(p, vector=True) == []


def test_real_vector_drawing_is_kept():
    doc, p = _page()
    for i in range(6):
        p.draw_circle((100 + 30 * i, 250), 25, color=(0, 0, 0), fill=(0.6, 0.6, 0.9))
    p.insert_text((60, 400), "Fig. 1. A drawing.", fontsize=9)
    got = pdffigures.image_placements(p, vector=True)
    assert len(got) == 1 and got[0]["kind"] == "vector"
