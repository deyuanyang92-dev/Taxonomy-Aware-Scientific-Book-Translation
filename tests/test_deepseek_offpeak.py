import datetime as dt

import deepseek_offpeak as d

BJ = dt.timezone(dt.timedelta(hours=8))


def t(h, m=0, day=16):  # 2026-11-16 周一；11-14 周六；11-15 周日
    return dt.datetime(2026, 11, day, h, m, tzinfo=BJ)


def clear(monkeypatch):
    for name in ("YZZ_DEEPSEEK_PEAK", "YZZ_DEEPSEEK_NIGHT", "YZZ_DEEPSEEK_HOLIDAYS"):
        monkeypatch.delenv(name, raising=False)


def test_default_peak_windows(monkeypatch):
    # 官方注(2)：UTC 01:00–04:00、06:00–10:00，周一至周五 → 北京 09–12、14–18。
    clear(monkeypatch)
    assert d.is_peak(t(9)) and d.is_peak(t(11, 59)) and d.is_peak(t(14)) and d.is_peak(t(17, 59))
    assert not d.is_peak(t(8, 59)) and not d.is_peak(t(12)) and not d.is_peak(t(13, 59))
    assert not d.is_peak(t(18)) and not d.is_peak(t(23, 59)) and not d.is_peak(t(3))


def test_weekend_all_offpeak(monkeypatch):
    # 官方：周末全天折扣，包括白天。
    clear(monkeypatch)
    for h in (0, 9, 10, 12, 15, 18, 23):
        assert not d.is_peak(t(h, day=14)) and not d.is_peak(t(h, day=15))


def test_holiday_file_marks_weekday_offpeak(monkeypatch, tmp_path):
    # 官方：中国法定节假日全天折扣；日期表由本机文件提供。
    clear(monkeypatch)
    hf = tmp_path / "holidays.txt"
    hf.write_text("# 测试\n2026-11-16\n", encoding="utf8")
    monkeypatch.setenv("YZZ_DEEPSEEK_HOLIDAYS", str(hf))
    assert not d.is_peak(t(10))
    assert d.is_peak(t(10, day=17))


def test_seconds_to_offpeak(monkeypatch):
    clear(monkeypatch)
    assert d.seconds_to_offpeak(t(3)) == 0
    assert d.seconds_to_offpeak(t(12)) == 0
    assert d.seconds_to_offpeak(t(18)) == 0
    assert d.seconds_to_offpeak(t(9)) == 3 * 3600 + 5          # 09:00 → 12:00
    assert d.seconds_to_offpeak(t(10)) == 2 * 3600 + 5         # 10:00 → 12:00
    assert d.seconds_to_offpeak(t(14)) == 4 * 3600 + 5         # 14:00 → 18:00
    assert d.seconds_to_offpeak(t(17, 59)) == 60 + 5           # 17:59 → 18:00


def test_peak_env_override(monkeypatch):
    clear(monkeypatch)
    monkeypatch.setenv("YZZ_DEEPSEEK_PEAK", "9-12")
    assert d.is_peak(t(10)) and not d.is_peak(t(15)) and not d.is_peak(t(10, day=14))


def test_legacy_night_window(monkeypatch):
    clear(monkeypatch)
    monkeypatch.setenv("YZZ_DEEPSEEK_NIGHT", "22-8")
    assert not d.is_peak(t(23)) and not d.is_peak(t(7, 59)) and d.is_peak(t(19)) and d.is_peak(t(10, day=15))
    monkeypatch.setenv("YZZ_DEEPSEEK_NIGHT", "0:30-8:30")
    assert not d.is_peak(t(0, 30)) and d.is_peak(t(0, 29))
