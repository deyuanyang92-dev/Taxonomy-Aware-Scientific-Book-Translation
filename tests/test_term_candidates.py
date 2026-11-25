import term_candidates as tc


def test_extract_ja_counts_and_pages():
    pages = [("K", 1, "疣足と剛毛、疣足"), ("K", 2, "疣足")]
    c = tc.extract(pages, "ja")
    assert c["疣足"]["freq"] == 3
    assert len(c["疣足"]["pages"]) == 2
    assert c["疣足"]["first"] == ("K", 1)


def test_rank_filters_and_orders():
    c = {
        "a": {"freq": 9, "pages": {("K", 1), ("K", 2)}, "first": ("K", 1)},
        "b": {"freq": 9, "pages": {("K", 1)}, "first": ("K", 1)},
        "c": {"freq": 2, "pages": {("K", 1), ("K", 2)}, "first": ("K", 1)},
    }
    rows = tc.rank(c, min_freq=5, min_pages=2)
    assert [r[0] for r in rows] == ["a"]


def test_extract_ru_lowercases():
    c = tc.extract([("K", 1, "Семейство семейство")], "ru")
    assert list(c.values())[0]["freq"] == 2
