"""DeepSeek 闲时守卫：忙时不发请求，等到闲时再继续（闲时价格为忙时的一半）。

依据 DeepSeek 官方定价页（https://api-docs.deepseek.com/quick_start/pricing/，2026-11-12 查）：
忙时 = 周一至周五 UTC 01:00–04:00 与 06:00–10:00（北京时间 09–12 点、14–18 点），
其余时间（含周末）为闲时。中国法定节假日官方也算闲时，本模块未内置节假日表（节假日会多等，不会多花钱）。
用户规定沿革：2026-11-14「只在晚上调用，22:00–08:00」；2026-11-15 改为「晚上都可以用」→ 默认只避开官方忙时。
环境变量 YZZ_DEEPSEEK_NIGHT="22-8" 仍可把窗口收紧为北京时间夜间段。

用法：
    from deepseek_offpeak import wait_offpeak
    wait_offpeak()          # 每次调用 DeepSeek API 前调用一次
命令行：python3 deepseek_offpeak.py  → 打印当前是否闲时、距闲时还要多久
"""
from __future__ import annotations

import datetime as dt
import os
import time

PEAK_BJ = ((9, 12), (14, 18))  # 官方工作日忙时段（北京时间小时，左闭右开）
BJ = dt.timezone(dt.timedelta(hours=8))


def _night() -> tuple[int, int] | None:
    v = os.environ.get("YZZ_DEEPSEEK_NIGHT", "")
    try:
        a, b = (int(x) for x in v.split("-"))
        return a % 24, b % 24
    except ValueError:
        return None


def is_peak(now: dt.datetime | None = None) -> bool:
    """True = 现在不许调用 DeepSeek。默认：官方工作日忙时；设了 YZZ_DEEPSEEK_NIGHT 则窗口外一律不许。"""
    bj = (now or dt.datetime.now(dt.timezone.utc)).astimezone(BJ)
    h = bj.hour
    win = _night()
    if win is not None:
        a, b = win
        inside = (a <= h < b) if a < b else (h >= a or h < b)
        return not inside
    if bj.weekday() >= 5:
        return False
    return any(a <= h < b for a, b in PEAK_BJ)


def seconds_to_offpeak(now: dt.datetime | None = None) -> int:
    """距可调用时刻的秒数（按整点推进）；现在就可调用返回 0。"""
    now = now or dt.datetime.now(dt.timezone.utc)
    if not is_peak(now):
        return 0
    t = now.astimezone(BJ).replace(minute=0, second=0, microsecond=0)
    for _ in range(24 * 8):
        t += dt.timedelta(hours=1)
        if not is_peak(t):
            return int((t - now).total_seconds()) + 5
    return 3600


def wait_offpeak(log=print) -> None:
    s = seconds_to_offpeak()
    if s:
        log(f"DeepSeek 忙时，等待 {s // 60} 分钟到闲时再发请求")
        time.sleep(s)


if __name__ == "__main__":
    s = seconds_to_offpeak()
    bj = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%m-%d %H:%M")
    print(f"北京时间 {bj}：" + ("闲时（半价），可以跑" if not s else f"忙时，{s // 60} 分钟后进入闲时"))
