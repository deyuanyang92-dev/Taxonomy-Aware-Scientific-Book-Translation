"""Issue #35 and #36: identification-key layout and lost-marker gate."""
from __future__ import annotations

import pytest
from docx import Document
from docx.enum.text import WD_TAB_ALIGNMENT, WD_TAB_LEADER

from booklayout.builder import TEXT_W, key_para, setup, split_key_target


@pytest.mark.parametrize("right,expected", [
    ("O. farensis (p. 76)", ("O. farensis", "(p. 76)")),
    ("2", ("", "2")),
    ("Syllis spongicola (Fig. 63) 12", ("Syllis spongicola (Fig. 63)", "12")),
    ("Syllis spongicola (Fig. 63)", ("Syllis spongicola (Fig. 63)", "")),
    ("Syllis spongicola Fig. 63", ("Syllis spongicola Fig. 63", "")),
    ("4'", ("", "4'")),
])
def test_split_key_target(right: str, expected: tuple[str, str]) -> None:
    assert split_key_target(right) == expected


def _stops(par):
    return list(par.paragraph_format.tab_stops)


def test_key_line_has_no_indent_and_two_aligned_slots() -> None:
    doc = Document()
    setup(doc)
    key_para(doc, "5. Gills present from setiger 1 ...... O. farensis (p. 76)", set())
    par = doc.paragraphs[0]
    pf = par.paragraph_format
    assert not pf.first_line_indent
    assert not pf.left_indent
    left_tab, right_tab = _stops(par)
    assert left_tab.alignment == WD_TAB_ALIGNMENT.LEFT
    assert left_tab.leader == WD_TAB_LEADER.DOTS
    assert 0 < left_tab.position.mm < TEXT_W - 20
    assert right_tab.alignment == WD_TAB_ALIGNMENT.RIGHT
    assert right_tab.position.mm == pytest.approx(TEXT_W, abs=0.01)
    texts = [r.text for r in par.runs]
    assert texts.count("\t") == 2
    assert texts[-1].replace(" ", " ") == "(p. 76)"
    assert "O. farensis" in "".join(texts).replace(" ", " ")


def test_name_column_is_shared_between_couplets() -> None:
    doc = Document()
    setup(doc)
    key_para(doc, "5. Short ...... A. a (p. 1)", set())
    key_para(doc, "6. A much longer couplet text goes here ...... Long name b (p. 22)", set())
    first, second = (_stops(p)[0].position.mm for p in doc.paragraphs)
    assert first == pytest.approx(second)


def test_number_target_keeps_single_right_slot() -> None:
    doc = Document()
    setup(doc)
    key_para(doc, "1. Gills present from setiger 1 … 2", set())
    par = doc.paragraphs[0]
    assert len(_stops(par)) == 1
    assert _stops(par)[0].alignment == WD_TAB_ALIGNMENT.RIGHT
    assert not par.paragraph_format.first_line_indent


def test_wrapped_name_line_gets_leader_from_left_margin() -> None:
    from booklayout.builder import key_signature
    doc = Document()
    setup(doc)
    left = "12. Parapodia with long dorsal cirri"
    right = "Syllis anthorgogicola (Fig. 48) 40"
    key_para(doc, left + " ...... " + right, set(), {key_signature(left, right)})
    par = doc.paragraphs[0]
    xml = par._element.xml
    assert xml.count("<w:br/>") == 1
    # break, then a tab (leader from margin to name column), name, tab, target
    texts = [r.text for r in par.runs]
    assert texts[-1].replace(" ", " ") == "40"
    assert texts.count("\t") == 2


def test_headings_inside_key_have_no_indent() -> None:
    doc = Document()
    setup(doc)
    key_para(doc, "Key to the genera of the family", set())
    assert not doc.paragraphs[0].paragraph_format.first_line_indent


def test_key_audit_accepts_name_and_target_columns() -> None:
    from booklayout.cli import _key_layout_problems

    def line(y: int, blk: int, marker: str) -> list[tuple]:
        return [
            (50, y, 62, y + 12, marker, blk, 0, 0),
            (65, y, 150, y + 12, "Gills", blk, 0, 1),
            (160, y, 300, y + 12, "..........", blk, 0, 2),
            (305, y, 360, y + 12, "O.", blk, 0, 3),
            (362, y, 400, y + 12, "farensis", blk, 0, 4),
            (470, y, 490, y + 12, "(p.", blk, 0, 5),
            (492, y, 510, y + 12, "76)", blk, 0, 6),
        ]
    words = line(100, 0, "1.") + line(130, 1, "2.")
    problems = _key_layout_problems(words, 595)
    assert not [p for p in problems if p["reason"] == "wide gaps"]


# ---- issue #36: suspected lost couplet markers -------------------------------
from booklayout.keymarkers import check_lost_markers, lost_marker_pages  # noqa: E402


def test_walled_key_paragraph_is_flagged() -> None:
    wall = " ".join(f"側感触手がある ...... {n}" for n in range(8))  # leaders, no markers
    found = check_lost_markers({6: [wall, "診断。", "別の段落。"]})
    assert [f["page"] for f in found] == [6]
    assert found[0]["reason"] == "walled_paragraph"
    assert found[0]["leaders"] == 8


def test_page_with_leader_lines_but_no_markers_is_flagged() -> None:
    lines = ["体は短い ...... 3", "疣足は二叉型 ...... 4", "触手あり ...... 5", "刺毛あり ...... 6"]
    found = check_lost_markers({7: lines})
    assert found and found[0]["reason"] == "leaders_without_markers"


def test_intact_key_page_is_clean() -> None:
    lines = ["1. 体は短い ...... 3", "— 体は長い ...... 4", "3. 触手あり ...... 5", "— 触手なし ...... 6"]
    assert check_lost_markers({7: lines}) == []


def test_prose_ellipsis_is_not_a_key() -> None:
    assert check_lost_markers({1: ["He paused… and then left.", "More text here."]}) == []


def test_lost_marker_pages_reads_aligned_json_both_sides() -> None:
    wall = " ".join(f"text ...... {n}" for n in range(5))
    data = {"pages": [
        {"page": 3, "blocks": [{"role": "key", "text": wall, "translation": ""}]},
        {"page": 4, "blocks": [{"role": "key", "text": "1. a ...... 2", "translation": "1. a ...... 2"}]},
    ]}
    found = lost_marker_pages(data)
    assert [f["page"] for f in found] == [3]
