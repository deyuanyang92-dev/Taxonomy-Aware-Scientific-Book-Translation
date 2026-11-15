"""PP-OCRv5 引擎的版面重排（不调模型，只用合成行框）。"""

from docstore.engines.ppocr import _lines, is_two_column, junk_line, rows_to_text

W = 1900.0


def row(x0, y0, x1, y1, text, conf=0.95):
    return [[[x0, y0], [x1, y0], [x1, y1], [x0, y1]], text, conf]


def two_col_rows():
    rows = []
    for i in range(8):
        y = 100 + i * 60
        rows.append(row(70, y, 840, y + 40, f"左栏第{i}行の本文です"))
        rows.append(row(960, y, 1800, y + 40, f"右栏第{i}行の本文です"))
    return rows


def test_two_column_left_then_right():
    rows = two_col_rows()
    assert is_two_column(rows, W)
    text, _ = rows_to_text(rows, W)
    lines = text.splitlines()
    assert lines[:8] == [f"左栏第{i}行の本文です" for i in range(8)]
    assert lines[8:] == [f"右栏第{i}行の本文です" for i in range(8)]


def test_full_width_line_splits_bands():
    rows = two_col_rows()
    rows.append(row(70, 600, 1800, 640, "図37 通栏の図注"))
    for i in range(3):
        y = 700 + i * 60
        rows.append(row(70, y, 840, y + 40, f"下左{i}の本文です"))
        rows.append(row(960, y, 1800, y + 40, f"下右{i}の本文です"))
    lines = rows_to_text(rows, W)[0].splitlines()
    assert lines.index("図37 通栏の図注") == 16
    assert lines[17:20] == [f"下左{i}の本文です" for i in range(3)]


def test_key_page_is_single_column_and_joins_leader():
    """检索表：右端「属名……跳转号」起点参差，不能判成双栏；同一视觉行合并。"""
    rows = []
    for i, x0 in enumerate([1000, 1080, 1170, 1250, 1320, 1400, 1500, 1600]):
        y = 100 + i * 60
        rows.append(row(70, y, 900, y + 40, f"{i + 1}. 疣足は単一剛毛のみをもつ"))
        rows.append(row(x0, y + 2, 1800, y + 38, "Syllis ……14"))
    assert not is_two_column(rows, W)
    lines = rows_to_text(rows, W)[0].splitlines()
    assert lines[0] == "1. 疣足は単一剛毛のみをもつ Syllis ……14"
    assert len(lines) == 8


def test_leader_number_box_kept():
    rows = [row(70, 100, 900, 140, "11. 疣足は複剛毛束の上下に各1本の単一剛毛をもつ"), row(1640, 102, 1800, 138, "...17", 0.76)]
    assert rows_to_text(rows, W)[0] == "11. 疣足は複剛毛束の上下に各1本の単一剛毛をもつ ...17"


def test_junk_line():
    import docstore.engines.ppocr as pp
    pp._JA_PAGE = True
    assert junk_line("斄🕠耮弚➠勖∩団鞯🌆赟珲墼ʭ毉✱鄻式")
    assert not junk_line("体長25mm，体幅9mm，38体節からなる")
    assert not junk_line("Paralepidonotus ampulliferus (Grube, 1878)")


def test_lines_merges_same_visual_row():
    rows = [row(500, 100, 900, 140, "Paralepidonotus"), row(70, 102, 300, 138, "図37")]
    assert _lines(rows)[0][0] == "図37 Paralepidonotus"


def test_chinese_page_not_filtered():
    """简体中文页（无假名）不按日文字集过滤：「颚」「刚」等不在 cp932 也要保留。"""
    rows = [row(70, 100 + i * 60, 1800, 140 + i * 60, "口前叶具颚片，刚毛为复型刚毛，颚齿数目") for i in range(6)]
    assert len(rows_to_text(rows, W)[0].splitlines()) == 6


def test_japanese_page_filters_junk():
    rows = [row(70, 100 + i * 60, 1800, 140 + i * 60, "体長25mm，体幅9mmからなる。前口葉は") for i in range(6)]
    rows.append(row(70, 600, 1800, 640, "斄🕠耮弚➠勖∩団鞯🌆赟珲墼ʭ毉✱鄻式"))
    assert len(rows_to_text(rows, W)[0].splitlines()) == 6
