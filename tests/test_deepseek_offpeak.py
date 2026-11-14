import datetime as dt

import deepseek_offpeak as d

BJ = dt.timezone(dt.timedelta(hours=8))


def t(h, m=0):
    return dt.datetime(2026, 11, 14, h, m, tzinfo=BJ)


def test_night_window(monkeypatch):
    monkeypatch.delenv("YZZ_DEEPSEEK_NIGHT", raising=False)
    assert not d.is_peak(t(23)) and not d.is_peak(t(3)) and not d.is_peak(t(22))
    assert d.is_peak(t(8)) and d.is_peak(t(14)) and d.is_peak(t(21, 59))


def test_seconds_to_night(monkeypatch):
    monkeypatch.delenv("YZZ_DEEPSEEK_NIGHT", raising=False)
    assert d.seconds_to_offpeak(t(23)) == 0
    assert d.seconds_to_offpeak(t(21)) == 3600 + 5


def test_env_override(monkeypatch):
    monkeypatch.setenv("YZZ_DEEPSEEK_NIGHT", "0-6")
    assert not d.is_peak(t(1)) and d.is_peak(t(23))
