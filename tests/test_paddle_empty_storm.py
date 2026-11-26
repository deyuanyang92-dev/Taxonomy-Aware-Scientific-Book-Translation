"""Empty-response guard: systematic empty_suspect failures stop the run (no blind retry)."""
from docstore.engines import paddle_vl as pv


def test_storm_on_ten_empty_suspects():
    assert pv.empty_storm(["empty_suspect: x"] * 10)


def test_no_storm_below_minimum():
    assert not pv.empty_storm(["empty_suspect: x"] * 9)


def test_no_storm_when_mixed_with_other_failures():
    reasons = ["empty_suspect: x"] * 10 + ["timeout: y"] * 11
    assert not pv.empty_storm(reasons)


def test_no_storm_on_no_failures():
    assert not pv.empty_storm([])
