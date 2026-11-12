"""DeepSeek 闲时守卫：忙时不发请求，等到闲时再继续（闲时价格为忙时的一半）。

依据 DeepSeek 官方定价页（https://api-docs.deepseek.com/quick_start/pricing/，2026-11-12 查）：
忙时 = 周一至周五 UTC 01:00–04:00 与 06:00–10:00（北京时间 09–12 点、14–18 点），
其余时间（含周末、中国法定节假日全天）为闲时。节假日本模块不识别，按工作日处理（只会多等，不会多花钱）。

用法：
    from deepseek_offpeak import wait_offpeak
    wait_offpeak()          # 每次调用 DeepSeek API 前调用一次
命令行：python3 deepseek_offpeak.py  → 打印当前是否闲时、距闲时还要多久
"""
from __future__ import annotations

import datetime as dt
import time

PEAK_UTC = ((1, 4), (6, 10))  # 工作日忙时段（UTC 小时，左闭右开）


def is_peak(now: dt.datetime | None = None) -> bool:
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.weekday() >= 5:  # 周六、周日全天闲时
        return False
    return any(a <= now.hour < b for a, b in PEAK_UTC)


def seconds_to_offpeak(now: dt.datetime | None = None) -> int:
    now = now or dt.datetime.now(dt.timezone.utc)
    if not is_peak(now):
        return 0
    for a, b in PEAK_UTC:
        if a <= now.hour < b:
            end = now.replace(hour=b, minute=0, second=0, microsecond=0)
            return int((end - now).total_seconds()) + 5
    return 0


def wait_offpeak(log=print) -> None:
    s = seconds_to_offpeak()
    if s:
        log(f"DeepSeek 忙时，等待 {s // 60} 分钟到闲时再发请求")
        time.sleep(s)


if __name__ == "__main__":
    s = seconds_to_offpeak()
    bj = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%m-%d %H:%M")
    print(f"北京时间 {bj}：" + ("闲时（半价），可以跑" if not s else f"忙时，{s // 60} 分钟后进入闲时"))
