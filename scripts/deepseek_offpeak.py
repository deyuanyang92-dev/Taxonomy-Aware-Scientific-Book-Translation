"""DeepSeek 闲时守卫：忙时不发请求，等到闲时再继续（闲时价格为忙时的一半）。

依据 DeepSeek 官方定价页（https://api-docs.deepseek.com/quick_start/pricing/，2026-11-12 查）：
忙时 = 周一至周五 UTC 01:00–04:00 与 06:00–10:00（北京时间 09–12 点、14–18 点），
其余时间（含周末、中国法定节假日全天）为闲时。
用户另有规定（2026-11-14）：只在晚上调用，默认北京时间 22:00–08:00（YZZ_DEEPSEEK_NIGHT 可改）。

用法：
    from deepseek_offpeak import wait_offpeak
    wait_offpeak()          # 每次调用 DeepSeek API 前调用一次
命令行：python3 deepseek_offpeak.py  → 打印当前是否闲时、距闲时还要多久
"""
from __future__ import annotations

import datetime as dt
import time

PEAK_UTC = ((1, 4), (6, 10))  # DeepSeek 官方工作日忙时段（UTC 小时，左闭右开），仅作参考

# 用户规定（2026-11-14）：DeepSeek 只在晚上调用。夜间窗口按北京时间，左闭右开，可跨零点；
# 环境变量 YZZ_DEEPSEEK_NIGHT="22-8" 可改。窗口外一律等待。
NIGHT_BJ = (22, 8)
BJ = dt.timezone(dt.timedelta(hours=8))


def _night() -> tuple[int, int]:
    import os
    v = os.environ.get("YZZ_DEEPSEEK_NIGHT", "")
    try:
        a, b = (int(x) for x in v.split("-"))
        return a % 24, b % 24
    except ValueError:
        return NIGHT_BJ


def is_peak(now: dt.datetime | None = None) -> bool:
    """True = 现在不许调用 DeepSeek（不在北京时间夜间窗口内）。"""
    now = now or dt.datetime.now(dt.timezone.utc)
    h = now.astimezone(BJ).hour
    a, b = _night()
    inside = (a <= h < b) if a < b else (h >= a or h < b)
    return not inside


def seconds_to_offpeak(now: dt.datetime | None = None) -> int:
    """距夜间窗口开始的秒数；已在窗口内返回 0。"""
    now = now or dt.datetime.now(dt.timezone.utc)
    if not is_peak(now):
        return 0
    bj = now.astimezone(BJ)
    start = bj.replace(hour=_night()[0], minute=0, second=0, microsecond=0)
    if start <= bj:
        start += dt.timedelta(days=1)
    return int((start - bj).total_seconds()) + 5


def wait_offpeak(log=print) -> None:
    s = seconds_to_offpeak()
    if s:
        log(f"DeepSeek 忙时，等待 {s // 60} 分钟到闲时再发请求")
        time.sleep(s)


if __name__ == "__main__":
    s = seconds_to_offpeak()
    bj = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%m-%d %H:%M")
    print(f"北京时间 {bj}：" + ("闲时（半价），可以跑" if not s else f"忙时，{s // 60} 分钟后进入闲时"))
