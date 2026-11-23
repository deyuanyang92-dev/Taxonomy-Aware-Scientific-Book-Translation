"""keyrender: each layout rule fails on the defect that once shipped (Imajima keys, 2026-11-23)."""
from booklayout.keyrender import Lead, Row, Span, check_page_leads, leads_of

W = 5.0  # pt per char in these synthetic rows
RIGHT = 400.0


def span(text, x0, italic=False):
    chars = [(c, x0 + i * W, x0 + (i + 1) * W) for i, c in enumerate(text)]
    return Span(text, x0, x0 + len(text) * W, italic, 10.5, chars)


def dots_to(x0, x1=RIGHT):
    return span("." * int((x1 - x0) / W), x0)


def row(*spans, y=0.0):
    return Row(0, y, list(spans))


def lead(marker, text_x, *rows):
    return Lead(list(rows), marker, text_x)


def rules(leads):
    return sorted({f["rule"] for f in check_page_leads(leads, RIGHT)})


def good(marker="1.", text_x=100.0, target="2"):
    body = span("背刚毛", text_x)
    tail = span(target, RIGHT - len(target) * W)
    return lead(marker, text_x, row(span(marker, 77), body, dots_to(body.x1, tail.x0), tail))


def test_clean_pair_passes():
    assert rules([good("1."), good("—")]) == []


def test_kr1_text_column_differs_by_marker():
    assert "KR1" in rules([good("1.", 100), good("10.", 100), good("—", 104)])


def test_kr2_wrapped_line_at_marker_column():
    tail = span("2", RIGHT - W)
    first = row(span("1.", 77), span("背" * 60, 100))
    wrap = row(span("背刚毛", 86), dots_to(101, tail.x0), tail, y=1)  # 86 < text column 100
    assert "KR2" in rules([lead("1.", 100, first, wrap), good("—")])


def test_kr3_blank_tail_before_leader_line():
    tail = span("2", RIGHT - W)
    ld = lead("1.", 100, row(span("1.", 77), span("背刚毛", 100)), row(dots_to(100, tail.x0), tail, y=1))
    assert "KR3" in rules([ld, good("—")])


def test_kr4_address_glued_or_unpaired():
    assert "KR4" in rules([good(target="Aphrodita3"), good("—")])
    assert "KR4" in rules([good(target="intermedia（McIntosh)"), good("—")])


def test_kr5_no_address():
    ld = lead("1.", 100, row(span("1.", 77), span("背刚毛", 100)))
    assert "KR5" in rules([ld, good("—")])


def test_kr6_roman_taxon_name():
    assert "KR6" in rules([good(target="M. fragilis"), good("—")])


def test_kr6_number_split_from_measure_word():
    ld = good("1.")
    first = row(span("1.", 77), span("背鳞13", 100))
    ld.rows = [first, Row(0, 1, [span("对", 100)] + ld.rows[0].spans[2:])]
    assert "KR6" in rules([ld, good("—")])


def test_leads_of_groups_wrapped_rows():
    rows = [row(span("1.", 77), span("背" * 10, 100)), row(span("背刚毛", 100), dots_to(115, 395), span("2", 395), y=1),
            row(span("—", 77), span("腹", 100), dots_to(105, 395), span("3", 395), y=2)]
    got = leads_of(rows)
    assert [len(ld.rows) for ld in got] == [2, 1]
    assert [ld.text_x for ld in got] == [100, 100]
