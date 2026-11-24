from pathlib import Path

from keykit.tabkey import avoid_chars, drop_columns


def test_avoid_and_drop(tmp_path: Path) -> None:
    p = tmp_path / "cb.csv"
    p.write_text("character,raw,state,key_policy\na,,,ok\nb,,,avoid (user: tail)\n", encoding="utf-8")
    av = avoid_chars(p)
    assert av == {"b"}
    rows = [["taxon", "a", "b"], ["X", "1", "2"]]
    assert drop_columns(rows, av) == [["taxon", "a"], ["X", "1"]]
