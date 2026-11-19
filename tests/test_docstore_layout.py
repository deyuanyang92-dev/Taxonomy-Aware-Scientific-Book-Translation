"""分栏阅读顺序：纯函数 order_rows 的合成框测试 + 真实页（p661）框坐标测试。"""

import json
from pathlib import Path

from docstore.engines.rapidocr import rows_to_text
from docstore.layout import order_rows


def row(x0, y0, x1, y1, text):
    return [[[x0, y0], [x1, y0], [x1, y1], [x0, y1]], text, "0.9"]


def texts(rows):
    return [r[1] for r in rows]


def two_col(n=10, *, lx=(100, 700), rx=(800, 1400), y0=200, pitch=40, h=30):
    """检测顺序（按行交错）：L0 R0 L1 R1 ..."""
    rows = []
    for i in range(n):
        y = y0 + i * pitch
        rows.append(row(lx[0], y, lx[1], y + h, f"L{i}"))
        rows.append(row(rx[0], y, rx[1], y + h, f"R{i}"))
    return rows


def test_empty_and_tiny_unchanged():
    assert order_rows([]) == []
    one = [row(0, 0, 10, 10, "a")]
    assert order_rows(one) == one


def test_single_column_unchanged():
    rows = [row(100, 100 + i * 40, 1400 - (i % 3) * 5, 130 + i * 40, f"S{i}") for i in range(30)]
    assert order_rows(rows) == rows


def test_single_column_with_short_lines_unchanged():
    # 段末短行（只到页面 40%）不会形成中缝：中线处仍被多数行覆盖
    rows = []
    for i in range(30):
        x1 = 600 if i % 5 == 4 else 1400
        rows.append(row(100, 100 + i * 40, x1, 130 + i * 40, f"S{i}"))
    assert order_rows(rows) == rows


def test_text_only_in_left_half_unchanged():
    rows = [row(100, 100 + i * 40, 700, 130 + i * 40, f"S{i}") for i in range(20)]
    rows.append(row(1300, 120, 1400, 150, "pgno"))  # 右侧只有 1 个框，不成栏
    assert order_rows(rows) == rows


def test_two_columns_left_then_right():
    out = order_rows(two_col(10))
    assert texts(out) == [f"L{i}" for i in range(10)] + [f"R{i}" for i in range(10)]


def test_two_columns_shuffled_input_still_sorted_by_y():
    rows = two_col(10)
    rows.reverse()
    out = order_rows(rows)
    assert texts(out) == [f"L{i}" for i in range(10)] + [f"R{i}" for i in range(10)]


def test_full_width_heading_and_footer():
    rows = [row(100, 60, 1400, 100, "TITLE")] + two_col(10) + [row(100, 1000, 1400, 1030, "FOOTER")]
    out = order_rows(rows)
    assert texts(out) == ["TITLE"] + [f"L{i}" for i in range(10)] + [f"R{i}" for i in range(10)] + ["FOOTER"]


def test_mid_page_spanning_caption_splits_bands():
    top = two_col(6)  # y 200..430
    cap = [row(100, 520, 1400, 550, "CAPTION")]
    bottom = two_col(6, y0=600)
    for r in bottom:
        r[1] = r[1].replace("L", "l").replace("R", "r")
    out = order_rows(top + cap + bottom)
    assert texts(out) == (
        [f"L{i}" for i in range(6)] + [f"R{i}" for i in range(6)] + ["CAPTION"]
        + [f"l{i}" for i in range(6)] + [f"r{i}" for i in range(6)]
    )


def test_running_header_in_right_half_comes_first():
    # 真实版面：页眉「术语汇编 641」只在右半，位于左栏首行之上
    rows = [row(1284, 66, 1390, 97, "HDR-A"), row(1462, 65, 1521, 97, "HDR-B")] + two_col(10)
    out = order_rows(rows)
    assert texts(out)[:2] == ["HDR-A", "HDR-B"]
    assert texts(out)[2:] == [f"L{i}" for i in range(10)] + [f"R{i}" for i in range(10)]


def test_isolated_page_number_below_columns_goes_last():
    rows = two_col(10) + [row(1300, 900, 1400, 930, "PGNO")]  # 右栏下方孤立的页码
    out = order_rows(rows)
    assert texts(out)[-1] == "PGNO"
    assert texts(out)[:10] == [f"L{i}" for i in range(10)]


def test_left_column_longer_than_right_keeps_reading_order():
    rows = two_col(10)
    # 左栏再多 5 行（右栏较短）
    for i in range(10, 15):
        rows.append(row(100, 200 + i * 40, 700, 230 + i * 40, f"L{i}"))
    out = order_rows(rows)
    assert texts(out) == [f"L{i}" for i in range(15)] + [f"R{i}" for i in range(10)]


def test_same_line_boxes_in_a_column_ordered_left_to_right():
    rows = two_col(8)
    # 左栏第 3 行被切成两个框，检测顺序里「后半」在前
    rows[rows.index(next(r for r in rows if r[1] == "L3"))] = row(420, 320, 700, 350, "L3b")
    rows.append(row(100, 320, 400, 350, "L3a"))
    out = order_rows(rows)
    t = texts(out)
    assert t.index("L3a") + 1 == t.index("L3b")
    assert t.index("L2") < t.index("L3a") and t.index("L3b") < t.index("L4")


def test_page_with_gutter_but_columns_not_overlapping_vertically_unchanged():
    # 左半上部、右半下部各有一块文字，彼此不并排：不当作两栏
    rows = [row(100, 100 + i * 40, 700, 130 + i * 40, f"A{i}") for i in range(6)]
    rows += [row(800, 1500 + i * 40, 1400, 1530 + i * 40, f"B{i}") for i in range(6)]
    assert order_rows(rows) == rows


def test_real_page_p661_boxes_not_interleaved():
    d = json.loads((Path(__file__).parent / "data" / "rapidocr_boxes_two_column.json").read_text(encoding="utf-8"))
    rows = [row(x0, y0, x1, y1, f"b{i}") for i, (x0, y0, x1, y1) in enumerate(d["boxes"])]
    out = order_rows(rows)
    boxes = {f"b{i}": b for i, b in enumerate(d["boxes"])}
    seq = [boxes[t] for t in texts(out)]
    assert sorted(texts(out)) == sorted(texts(rows))  # 不丢不重
    # 页眉（右半，y<100）在最前
    assert [b[1] < 100 for b in seq[:2]] == [True, True]
    body = seq[2:]
    side = ["L" if b[2] < 790 else "R" for b in body]
    # 先全部左栏，再全部右栏
    k = side.index("R")
    assert set(side[:k]) == {"L"} and set(side[k:]) == {"R"}
    # 栏内自上而下
    left, right = body[:k], body[k:]
    assert [b[1] for b in left] == sorted(b[1] for b in left)
    assert [b[1] for b in right] == sorted(b[1] for b in right)
    assert len(left) > 30 and len(right) > 30


def test_rows_to_text_orders_columns_and_averages_conf():
    text, conf = rows_to_text(two_col(8))
    lines = text.split("\n")
    assert lines == [f"L{i}" for i in range(8)] + [f"R{i}" for i in range(8)]
    assert abs(conf - 0.9) < 1e-9


def test_rows_to_text_empty():
    assert rows_to_text(None) == ("", None)
    assert rows_to_text([]) == ("", None)


def test_column_pushed_down_by_figure_keeps_body_in_column():
    """右栏被图推后：左栏顶部多行是正文，不得当页眉摘出（Codex 2026-11-13 P2）。"""
    left = [row(100, 200 + 40 * i, 700, 230 + 40 * i, f"L{i}") for i in range(12)]
    right = [row(800, 400 + 40 * i, 1400, 430 + 40 * i, f"R{i}") for i in range(7)]
    out = texts(order_rows(left + right))
    assert out == [f"L{i}" for i in range(12)] + [f"R{i}" for i in range(7)]
