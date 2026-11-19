"""DeepSeek 闲时守卫：不在折扣时段不发请求，等到下一个折扣时段再继续。

DeepSeek 官方折扣时段为北京时间 00:30–08:30（UTC 16:30–00:30，每天，含周末）。
2026-11-17 用户改定：只在 DeepSeek 打折/优惠期间调用，窗口固定为 00:30–08:30；
窗口外一律不发请求，任务延期到下一个窗口。早期规则「22:00–08:00」已作废。
环境变量 YZZ_DEEPSEEK_NIGHT 可覆盖窗口，支持 "22-8"（整点）与 "0:30-8:30"（含分钟）。

用法：
    from deepseek_offpeak import wait_offpeak
    wait_offpeak()          # 每次调用 DeepSeek API 前调用一次
命令行：python3 deepseek_offpeak.py  → 打印当前是否折扣时段、距下一窗口还有多久
"""
from __future__ import annotations

import datetime as dt
import os
import time

BJ = dt.timezone(dt.timedelta(hours=8))
# 用户 2026-11-17 定的全局窗口：DeepSeek 折扣时段（北京时间，左闭右开），单位分钟。
DEFAULT_WINDOW = (30, 8 * 60 + 30)


def _parse_hm(s: str) -> int:
    h, sep, m = s.partition(":")
    return int(h) * 60 + (int(m) if sep and m else 0)


def _night() -> tuple[int, int]:
    v = os.environ.get("YZZ_DEEPSEEK_NIGHT", "")
    if not v:
        return DEFAULT_WINDOW
    try:
        a, b = v.split("-")
        return _parse_hm(a) % (24 * 60), _parse_hm(b) % (24 * 60)
    except ValueError:
        return DEFAULT_WINDOW


def is_peak(now: dt.datetime | None = None) -> bool:
    """True = 现在不许调用 DeepSeek（折扣窗口外）。"""
    bj = (now or dt.datetime.now(dt.timezone.utc)).astimezone(BJ)
    m = bj.hour * 60 + bj.minute
    a, b = _night()
    inside = (a <= m < b) if a < b else (m >= a or m < b)
    return not inside


def seconds_to_offpeak(now: dt.datetime | None = None) -> int:
    """距下一个折扣窗口开始的秒数；现在就可调用返回 0。"""
    now = now or dt.datetime.now(dt.timezone.utc)
    if not is_peak(now):
        return 0
    bj = now.astimezone(BJ)
    a, _ = _night()
    start = bj.replace(hour=a // 60, minute=a % 60, second=0, microsecond=0)
    if start <= bj:
        start += dt.timedelta(days=1)
    return int((start - bj).total_seconds()) + 5


def wait_offpeak(log=print) -> None:
    s = seconds_to_offpeak()
    if s:
        log(f"DeepSeek 折扣窗口外，等待 {s // 60} 分钟到 00:30–08:30 窗口再发请求")
        time.sleep(s)


if __name__ == "__main__":
    s = seconds_to_offpeak()
    bj = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%m-%d %H:%M")
    print(f"北京时间 {bj}：" + ("折扣窗口内，可以跑" if not s else f"窗口外，{s // 60} 分钟后进入 00:30–08:30"))
