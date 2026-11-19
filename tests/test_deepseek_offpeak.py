import datetime as dt

import deepseek_offpeak as d

BJ = dt.timezone(dt.timedelta(hours=8))


def t(h, m=0, day=16):  # 2026-11-16 周一；11-15 周日
    return dt.datetime(2026, 11, day, h, m, tzinfo=BJ)


def test_default_discount_window(monkeypatch):
    # 用户 2026-11-17：只在 DeepSeek 折扣时段 00:30–08:30 调用。
    monkeypatch.delenv("YZZ_DEEPSEEK_NIGHT", raising=False)
    assert not d.is_peak(t(0, 30)) and not d.is_peak(t(3)) and not d.is_peak(t(8, 29))
    assert d.is_peak(t(0, 29)) and d.is_peak(t(8, 30)) and d.is_peak(t(9))
    assert d.is_peak(t(19)) and d.is_peak(t(23, 59))


def test_window_applies_on_weekend(monkeypatch):
    # 折扣每天都有，但窗口外（含周末白天）不发请求。
    monkeypatch.delenv("YZZ_DEEPSEEK_NIGHT", raising=False)
    assert d.is_peak(t(10, day=15)) and d.is_peak(t(15, day=14))
    assert not d.is_peak(t(2, day=15))


def test_seconds_to_offpeak(monkeypatch):
    monkeypatch.delenv("YZZ_DEEPSEEK_NIGHT", raising=False)
    assert d.seconds_to_offpeak(t(3)) == 0
    assert d.seconds_to_offpeak(t(8, 30)) == 16 * 3600 + 5      # 到次日 00:30
    assert d.seconds_to_offpeak(t(23)) == 90 * 60 + 5          # 23:00 → 00:30
    assert d.seconds_to_offpeak(t(0, 0)) == 30 * 60 + 5        # 00:00 → 00:30


def test_env_night_window(monkeypatch):
    monkeypatch.setenv("YZZ_DEEPSEEK_NIGHT", "22-8")
    assert not d.is_peak(t(23)) and not d.is_peak(t(7, 59)) and d.is_peak(t(19)) and d.is_peak(t(10, day=15))
    monkeypatch.setenv("YZZ_DEEPSEEK_NIGHT", "0:30-8:30")
    assert not d.is_peak(t(0, 30)) and d.is_peak(t(0, 29))
