"""Empty-response guard: systematic empty_suspect failures stop the run (no blind retry)."""
from docstore.engines import paddle_vl as pv


def test_storm_on_three_empty_suspects():
    assert pv.empty_storm(["empty_suspect: x"] * 3)


def test_no_storm_below_minimum():
    assert not pv.empty_storm(["empty_suspect: x"] * 2)


def test_no_storm_when_mixed_with_other_failures():
    reasons = ["empty_suspect: x"] * 3 + ["timeout: y"] * 5
    assert not pv.empty_storm(reasons)


def test_no_storm_on_no_failures():
    assert not pv.empty_storm([])
