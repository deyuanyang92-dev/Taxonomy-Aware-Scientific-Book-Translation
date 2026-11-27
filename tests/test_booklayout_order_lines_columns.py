"""order_lines must report 1 column when one side of the gutter holds no lines."""
from booklayout import ingest_native


def _lines(xs):
    return [{"x0": x0, "x1": x1, "y0": 50.0 + 12 * i, "y1": 60.0 + 12 * i, "text": f"l{i}"}
            for i, (x0, x1) in enumerate(xs)]


def test_one_sided_gutter_is_single_column(monkeypatch):
    import docstore.layout as dl
    monkeypatch.setattr(dl, "_find_gutter", lambda boxes: (300.0, 310.0))
    ordered, ncol = ingest_native.order_lines(_lines([(50, 280)] * 6))
    assert ncol == 1
    assert [ln["text"] for ln in ordered] == [f"l{i}" for i in range(6)]
    assert all(ln["col"] == 0 for ln in ordered)


def test_two_sided_gutter_stays_two_columns(monkeypatch):
    import docstore.layout as dl
    monkeypatch.setattr(dl, "_find_gutter", lambda boxes: (300.0, 310.0))
    _, ncol = ingest_native.order_lines(_lines([(50, 280), (330, 560)] * 3))
    assert ncol == 2
