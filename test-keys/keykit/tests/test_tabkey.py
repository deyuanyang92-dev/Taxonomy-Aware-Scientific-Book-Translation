import csv
from pathlib import Path

from keykit.tabkey import choose_cuts, encode, is_numeric_col, load_table, md_tables, merge_halves, run

ROWS = [
    ["taxon", "size", "colour", "free"],
    ["A", "1-3", "red", "alpha one"],
    ["B", "2 (1-4)", "red | blue", "beta two"],
    ["C", "10-12", "blue", "gamma"],
    ["D", "11", "n.r.", "delta"],
    ["E", "5", "-", "eps"],
]


def test_numeric_detect_and_cuts():
    assert is_numeric_col([r[1] for r in ROWS[1:]])
    assert not is_numeric_col([r[2] for r in ROWS[1:]])
    assert choose_cuts([(1, 3), (1, 4), (10, 12), (11, 11)], 2) in ([10.0], [11.0])


def test_encode_excludes_free_text():
    res = encode(ROWS)
    assert [c.name for c in res.matrix.characters] == ["size", "colour"]
    assert any(n == "free" for n, _ in res.excluded)


def test_run_key():
    key, rep, _ = run(ROWS)
    assert rep["taxa"] == 5 and "size" in key


def test_md_merge_halves():
    left = "| sp | a |\n|--|--|\n| X (Au, 1900) | 1 |\n| Y | 2 |\n| Z | 3 |\n"
    right = "| sp | b |\n|--|--|\n| X | u |\n| Y | v |\n| Z | w |\n"
    rows = merge_halves(md_tables(left + "\ntext\n\n" + right))
    assert rows[0] == ["sp", "a", "b"] and rows[1][0] == "X" and rows[3][2] == "w"


def test_codebook_map_and_drop():
    rows = [["t", "c"], ["A", "red-ish"], ["B", "crimson"], ["C", "blue"], ["D", "weird"]]
    cb = {("c", "red-ish"): "red", ("c", "crimson"): "red|dark", ("c", "weird"): "~"}
    m = encode(rows, codebook=cb, include_free=True).matrix
    assert m.characters[0].states == ["blue", "dark", "red"]
    assert m.taxa[3].values[0] == "?" and m.taxa[1].values[0] == frozenset({1, 2})


def test_csv_load(tmp_path: Path):
    p = tmp_path / "t.csv"
    with p.open("w", newline="") as f:
        csv.writer(f).writerows(ROWS)
    assert load_table(p)[1][0] == "A"
