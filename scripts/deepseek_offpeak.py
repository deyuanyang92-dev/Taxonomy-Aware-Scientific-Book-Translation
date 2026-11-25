"""DeepSeek 闲时守卫：只在官方折扣时段发请求，任务在高峰时段延期。

依据官方定价页 https://api-docs.deepseek.com/quick_start/pricing/ 注(2)（2026-11-17 核对）：
    Peak hours are 01:00 - 04:00 and 06:00 - 10:00 UTC, Monday through Friday,
    excluding Chinese public holidays. All other hours are off-peak, including
    weekends and Chinese public holidays.
换算北京时间（UTC+8）：高峰 = 周一至周五 09:00–12:00、14:00–18:00；
其余都算折扣时段：18:00–次日 09:00、工作日 12:00–14:00、周末、中国法定节假日。
用户 2026-11-17 晚、2026-11-19 两次确认：北京时间 18:00 到次日 09:00 都可以调用；
本模块即按此放行（另按官方放行周末、工作日 12:00–14:00、法定节假日）。

中国法定节假日官方排除在高峰外。本机用 YZZ_DEEPSEEK_HOLIDAYS 指向的日期表
（默认 ~/.config/yzz/deepseek_holidays.txt，每行 YYYY-MM-DD，# 注释）判定；
文件不存在时，工作日节假日按高峰处理（保守：少跑，不按高峰价跑）。
环境变量 YZZ_DEEPSEEK_PEAK 可覆盖高峰时段，如 "9-12,14-18"（北京时间，整点）。
旧变量 YZZ_DEEPSEEK_NIGHT 仍可覆盖为「允许调用窗口」，如 "22-8"、"0:30-8:30"。

用法：
    from deepseek_offpeak import wait_offpeak
    wait_offpeak()          # 每次调用 DeepSeek API 前调用一次
命令行：python3 deepseek_offpeak.py  → 打印当前是否折扣时段、距下一窗口还有多久
"""
from __future__ import annotations

import datetime as dt
import os
import pathlib
import time

BJ = dt.timezone(dt.timedelta(hours=8))
# 官方高峰（北京时间，左闭右开），单位分钟：UTC 01:00–04:00、06:00–10:00 +8h。
DEFAULT_PEAK = ((9 * 60, 12 * 60), (14 * 60, 18 * 60))
HOLIDAY_FILE = pathlib.Path.home() / ".config" / "yzz" / "deepseek_holidays.txt"

_holiday_cache: tuple[str, float, frozenset[str]] | None = None


def _parse_hm(s: str) -> int:
    h, sep, m = s.partition(":")
    return int(h) * 60 + (int(m) if sep and m else 0)


def _parse_span(s: str) -> tuple[int, int]:
    a, b = s.split("-")
    return _parse_hm(a) % (24 * 60), _parse_hm(b) % (24 * 60)


def _peak_spans() -> tuple[tuple[int, int], ...]:
    v = os.environ.get("YZZ_DEEPSEEK_PEAK", "").strip()
    if not v:
        return DEFAULT_PEAK
    try:
        return tuple(_parse_span(x) for x in v.split(",") if x.strip())
    except ValueError:
        return DEFAULT_PEAK


def _legacy_window() -> tuple[int, int] | None:
    """旧变量 YZZ_DEEPSEEK_NIGHT：只允许该窗口内调用；设了就用它，忽略官方高峰表。"""
    v = os.environ.get("YZZ_DEEPSEEK_NIGHT", "").strip()
    if not v:
        return None
    try:
        return _parse_span(v)
    except ValueError:
        return None


def _holidays() -> frozenset[str]:
    global _holiday_cache
    path = pathlib.Path(os.environ.get("YZZ_DEEPSEEK_HOLIDAYS", str(HOLIDAY_FILE))).expanduser()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return frozenset()
    if _holiday_cache and _holiday_cache[0] == str(path) and _holiday_cache[1] == mtime:
        return _holiday_cache[2]
    try:
        days = {ln.strip() for ln in path.read_text(encoding="utf8").splitlines()
                if ln.strip() and not ln.lstrip().startswith("#")}
    except OSError:
        return frozenset()
    out = frozenset(days)
    _holiday_cache = (str(path), mtime, out)
    return out


def _inside(m: int, a: int, b: int) -> bool:
    return (a <= m < b) if a < b else (m >= a or m < b)


def is_peak(now: dt.datetime | None = None) -> bool:
    """True = 现在不许调用 DeepSeek（高峰时段）。"""
    bj = (now or dt.datetime.now(dt.timezone.utc)).astimezone(BJ)
    m = bj.hour * 60 + bj.minute
    legacy = _legacy_window()
    if legacy is not None:
        return not _inside(m, *legacy)
    if bj.weekday() >= 5:  # 官方：周末全天折扣
        return False
    if bj.date().isoformat() in _holidays():  # 官方：中国法定节假日全天折扣
        return False
    return any(_inside(m, a, b) for a, b in _peak_spans())


def seconds_to_offpeak(now: dt.datetime | None = None) -> int:
    """距下一个折扣时段开始的秒数；现在就可调用返回 0。"""
    now = now or dt.datetime.now(dt.timezone.utc)
    if not is_peak(now):
        return 0
    bj = now.astimezone(BJ)
    m = bj.hour * 60 + bj.minute
    sec = bj.second + bj.microsecond / 1e6
    legacy = _legacy_window()
    spans = (legacy,) if legacy is not None else _peak_spans()
    for a, b in spans:
        if _inside(m, a, b):
            return int((b - m) * 60 - sec) + 5
    # 自定义高峰表跨午夜等情形：退化为找下一个高峰结束点
    best = min(((b - m) % (24 * 60)) * 60 for a, b in spans)
    return int(best - sec) + 5


def wait_offpeak(log=print) -> None:
    s = seconds_to_offpeak()
    if s:
        log(f"DeepSeek 高峰时段，等待 {s // 60} 分钟到折扣时段再发请求")
        time.sleep(s)


if __name__ == "__main__":
    s = seconds_to_offpeak()
    bj = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%m-%d %H:%M")
    print(f"北京时间 {bj}：" + ("折扣时段，可以跑" if not s else f"高峰时段，{s // 60} 分钟后进入折扣时段"))
