import datetime as dt

import deepseek_offpeak as d

BJ = dt.timezone(dt.timedelta(hours=8))


def t(h, m=0, day=16):  # 2026-11-16 周一；11-15 周日
    return dt.datetime(2026, 11, day, h, m, tzinfo=BJ)


def test_official_peak_weekday(monkeypatch):
    monkeypatch.delenv("YZZ_DEEPSEEK_NIGHT", raising=False)
    assert d.is_peak(t(9)) and d.is_peak(t(11, 59)) and d.is_peak(t(14)) and d.is_peak(t(17, 59))
    assert not d.is_peak(t(12)) and not d.is_peak(t(18)) and not d.is_peak(t(19)) and not d.is_peak(t(3))


def test_weekend_all_offpeak(monkeypatch):
    monkeypatch.delenv("YZZ_DEEPSEEK_NIGHT", raising=False)
    assert not d.is_peak(t(10, day=15)) and not d.is_peak(t(15, day=14))


def test_seconds_to_offpeak(monkeypatch):
    monkeypatch.delenv("YZZ_DEEPSEEK_NIGHT", raising=False)
    assert d.seconds_to_offpeak(t(19)) == 0
    assert d.seconds_to_offpeak(t(17)) == 3600 + 5
    assert d.seconds_to_offpeak(t(11, 30)) == 1800 + 5
    assert d.seconds_to_offpeak(t(9, 30)) == 9000 + 5


def test_env_night_window(monkeypatch):
    monkeypatch.setenv("YZZ_DEEPSEEK_NIGHT", "22-8")
    assert not d.is_peak(t(23)) and d.is_peak(t(19)) and d.is_peak(t(10, day=15))
