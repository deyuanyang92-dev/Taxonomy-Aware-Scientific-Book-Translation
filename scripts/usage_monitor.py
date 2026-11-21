"""DeepSeek / 多模型调用消耗监测：读 llm_engines 写下的 usage.tsv 账本，汇总、计价、告警、实时盯盘。

背景：`scripts/llm_engines.py` 每次调用往 usage.tsv 追加一行
（时间、engine、标签、输入token、输出token、缓存读token、耗时秒）。这些账本散在各书各工作目录
（`<书>/核译/usage.tsv`、`_work/translate/<key>/usage.tsv` …），过去只能靠 `auto_translate.py report`
单本看，跨书、跨流程、跨时间没人汇总。本脚本把它们统一扫起来：

  summary  按 engine / 流程（标签）/ 书 / 天 汇总 token 与费用，标出高峰时段多花的钱、缓存命中率、返工倾向
  watch    实时盯盘：新出现的调用逐条打印，按分钟统计 burn rate，用于正在跑的批量任务
  check    给 cron / CI 用：超预算、高峰调用、账本坏行则退出码非 0

用法：
  python3 scripts/usage_monitor.py summary
  python3 scripts/usage_monitor.py summary --root "P:/翻译-译作" --group stage --md u.md --csv u.csv
  python3 scripts/usage_monitor.py summary --root . --since 2026-11-16 --group book
  python3 scripts/usage_monitor.py watch --root . --interval 5
  python3 scripts/usage_monitor.py check --root . --budget-usd 5 --since-hours 24

计价口径（DeepSeek 官方定价页 2026-11-14 查，USD/百万 token）：
  闲时 输入未命中 0.15、缓存命中 0.003、输出 0.60；官方高峰（UTC 01:00–04:00、06:00–10:00，
  周一至周五，不含中国法定节假日 → 北京 09:00–12:00、14:00–18:00）翻倍，`--peak-mult` 可调。
  只对 PRICES 里登记过的引擎计价；codex / cursor / claude 走订阅额度，只统计调用数与耗时，不折钱。
  汇率默认 7.1（`--usd-cny` 可改），与 `_work/review_critical.py` 一致；仅作估算，不作账务凭据。

告警口径：
  - 高峰调用：同样 token 在高峰付两倍，时间戳落在官方高峰即计入「多花」；
  - 折扣窗口外调用：只判定最近 `--since-hours` 小时的 DeepSeek 调用，规则取 `deepseek_offpeak.is_peak()`
    （现行：官方高峰 09–12、14–18 点工作日之外都放行，即含 18:00–次日 09:00；`YZZ_DEEPSEEK_PEAK`/`YZZ_DEEPSEEK_NIGHT` 可覆盖），历史旧账不追溯；
  - 缓存命中率低：DeepSeek 缓存价约为输入价的 1/50，命中率长期偏低说明 system 前缀在变，钱白花；
  - 坏行：列数不足、时间解析失败的行计入 `坏行`，不参与合计，也不让整份账本失效。
"""
from __future__ import annotations

import argparse
import csv
import dataclasses
import datetime as dt
import json
import os
import pathlib
import re
import sys
import time
from collections import defaultdict
from typing import Callable, Iterable, Iterator, Sequence, TextIO

BJ = dt.timezone(dt.timedelta(hours=8))
USD_CNY = 7.1
LEDGER = "usage.tsv"
TS_FMT = "%Y-%m-%d %H:%M:%S"
# 资料库/图片/依赖目录里不会有账本，跳过能省掉绝大部分遍历时间
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "site-packages", "images"}
DEEPSEEK_PREFIX = "deepseek"


@dataclasses.dataclass(frozen=True)
class Price:
    """USD / 百万 token；inp 为未命中缓存的输入价。"""

    inp: float
    cache: float
    out: float


# 只登记有官方定价的引擎；未登记者按订阅额度处理（不折钱，只计调用数）
PRICES: dict[str, Price] = {
    "deepseek-flash": Price(0.15, 0.003, 0.60),
}
# 官方高峰（北京时间，左闭右开，单位分钟）；周一至周五，不含法定节假日
PEAK_WINDOWS = ((9 * 60, 12 * 60), (14 * 60, 18 * 60))
_ID_SEG = re.compile(r"^(?:c\d+|\d+|p\d+|seg\d+|attempt\d+|r\d+)$")


# ----------------------------------------------------------------- 时间与计价
def _parse_holidays(raw: str) -> frozenset[dt.date]:
    out: set[dt.date] = set()
    for s in raw.replace(";", ",").split(","):
        s = s.strip()
        if not s:
            continue
        try:
            out.add(dt.date.fromisoformat(s))
        except ValueError:
            continue
    return frozenset(out)


def holiday_set() -> frozenset[dt.date]:
    """官方节假日表：`YZZ_DEEPSEEK_HOLIDAYS=2026-01-01,2026-02-17`（逗号或分号分隔）。"""
    return _parse_holidays(os.environ.get("YZZ_DEEPSEEK_HOLIDAYS", ""))


def in_official_peak(ts: dt.datetime, holidays: frozenset[dt.date] | None = None) -> bool:
    bj = ts.astimezone(BJ)
    if bj.weekday() >= 5:
        return False
    if bj.date() in (holiday_set() if holidays is None else holidays):
        return False
    m = bj.hour * 60 + bj.minute
    return any(a <= m < b for a, b in PEAK_WINDOWS)


def peak_multiplier(ts: dt.datetime, mult: float = 2.0,
                    holidays: frozenset[dt.date] | None = None) -> float:
    return mult if in_official_peak(ts, holidays) else 1.0


# ----------------------------------------------------------------- 账本解析
@dataclasses.dataclass
class Row:
    """一条调用记录。token 缺失（命令行引擎记 `-`）时 trec=False。"""

    ts: dt.datetime
    engine: str
    tag: str
    inp: int
    out: int
    cache: int
    seconds: float
    source: str
    trec: bool = True

    @property
    def tokens(self) -> int:
        return self.inp + self.out + self.cache


def _int_or_none(v: str) -> int | None:
    v = v.strip()
    if v in ("", "-", "None", "null"):
        return None
    try:
        return int(float(v))
    except ValueError:
        return None


def _float_or_zero(v: str) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _ts(v: str) -> dt.datetime | None:
    v = v.strip()
    for fmt in (TS_FMT, "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S"):
        try:
            return dt.datetime.strptime(v, fmt).replace(tzinfo=BJ)
        except ValueError:
            continue
    return None


def parse_row(line: str, source: str = "") -> Row | None:
    """解析一行账本；表头、坏行、列数不足返回 None（由调用方计入坏行）。"""
    cells = line.rstrip("\r\n").split("\t")
    if len(cells) < 7:
        return None
    ts = _ts(cells[0])
    if ts is None:
        return None
    inp, out, cache = _int_or_none(cells[3]), _int_or_none(cells[4]), _int_or_none(cells[5])
    trec = not (inp is None and out is None and cache is None)
    return Row(ts=ts, engine=cells[1].strip(), tag=cells[2].strip(),
               inp=inp or 0, out=out or 0, cache=cache or 0,
               seconds=_float_or_zero(cells[6]), source=source, trec=trec)


def read_ledger(path: pathlib.Path) -> tuple[list[Row], int]:
    """读一份 usage.tsv（跳过表头与空行），返回 (记录, 坏行数)。"""
    rows: list[Row] = []
    bad = 0
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return rows, 0
    for line in text.splitlines():
        if not line.strip():
            continue
        if line.startswith("时间\t") or line.startswith("时间 "):
            continue
        r = parse_row(line, str(path))
        if r is None:
            bad += 1
        else:
            rows.append(r)
    return rows, bad


def find_ledgers(roots: Sequence[str | os.PathLike[str]]) -> list[pathlib.Path]:
    out: list[pathlib.Path] = []
    for raw in roots:
        p = pathlib.Path(raw).expanduser()
        if p.is_file():
            out.append(p)
            continue
        if not p.is_dir():
            continue
        for dp, dns, fns in os.walk(p):
            dns[:] = sorted(d for d in dns if d not in SKIP_DIRS)
            if LEDGER in fns:
                out.append(pathlib.Path(dp) / LEDGER)
    return out


# ----------------------------------------------------------------- 分组与统计
def stage_of(tag: str) -> str:
    """流程名：去掉标签末尾的块号/尝试号，`auto/revise/c000/0` → `auto/revise`。"""
    parts = [p for p in tag.split("/") if p]
    while len(parts) > 1 and _ID_SEG.match(parts[-1]):
        parts.pop()
    return "/".join(parts) if parts else "(空)"


def book_of(path: pathlib.Path, root: pathlib.Path | None = None) -> str:
    """账本所属工程：相对 root 的第一段；不在 root 下则用上一级目录名。"""
    try:
        rel = path.resolve().relative_to(root.resolve()) if root else None
    except (ValueError, OSError):
        rel = None
    if rel is not None and len(rel.parts) > 1:
        return rel.parts[0]
    return path.parent.name or str(path.parent)


@dataclasses.dataclass
class Bucket:
    key: str
    calls: int = 0
    inp: int = 0
    out: int = 0
    cache: int = 0
    seconds: float = 0.0
    usd: float = 0.0
    peak_extra: float = 0.0
    unpriced: int = 0
    peak: int = 0
    first: dt.datetime | None = None
    last: dt.datetime | None = None

    def add(self, r: Row, usd: float | None, extra: float = 0.0) -> None:
        self.calls += 1
        self.inp += r.inp
        self.out += r.out
        self.cache += r.cache
        self.seconds += r.seconds
        if usd is None:
            self.unpriced += 1
        else:
            self.usd += usd
        if extra:
            self.peak += 1
            self.peak_extra += extra
        self.first = self.first or r.ts
        self.last = r.ts if self.last is None or r.ts > self.last else self.last


def row_cost(r: Row, mult: float = 2.0, holidays: frozenset[dt.date] | None = None,
             price: Price | None = None) -> tuple[float | None, float]:
    """返回 (该次费用 USD, 其中因高峰多付的部分)；无法计价返回 (None, 0)。"""
    p = price or PRICES.get(r.engine)
    if p is None or not r.trec:
        return None, 0.0
    base = (r.inp * p.inp + r.cache * p.cache + r.out * p.out) / 1e6
    m = peak_multiplier(r.ts, mult, holidays)
    if m == 1.0:
        return base, 0.0
    return base * m, base * (m - 1.0)


def group_rows(rows: Iterable[Row], keyfn: Callable[[Row], str], mult: float = 2.0,
               holidays: frozenset[dt.date] | None = None) -> list[Bucket]:
    buckets: dict[str, Bucket] = {}
    for r in rows:
        k = keyfn(r) or "(空)"
        b = buckets.setdefault(k, Bucket(k))
        usd, extra = row_cost(r, mult, holidays)
        b.add(r, usd, extra)
    return sorted(buckets.values(), key=lambda b: (-b.usd, -b.calls, b.key))


KEYFUNCS: dict[str, Callable[[Row], str]] = {
    "engine": lambda r: r.engine,
    "stage": lambda r: stage_of(r.tag),
    "tag": lambda r: r.tag,
    "file": lambda r: r.source,
    "day": lambda r: r.ts.astimezone(BJ).strftime("%Y-%m-%d"),
    "book": lambda r: book_of(pathlib.Path(r.source)),
}


# ----------------------------------------------------------------- 输出
def _hit(b: Bucket) -> str:
    den = b.inp + b.cache
    return f"{b.cache / den:.0%}" if den else "—"


def _per_call(b: Bucket) -> str:
    return f"{b.seconds / b.calls:.1f}" if b.calls else "—"


def render_table(buckets: Sequence[Bucket], key_header: str = "组", cny: float = USD_CNY) -> list[str]:
    head = ["| " + key_header + " | 调用 | 输入 | 缓存读 | 输出 | 缓存命中 | USD | CNY | 秒/次 |",
            "|---|---|---|---|---|---|---|---|---|"]
    lines = list(head)
    t = Bucket("合计")
    for b in buckets:
        t.calls += b.calls
        t.inp += b.inp
        t.out += b.out
        t.cache += b.cache
        t.seconds += b.seconds
        t.usd += b.usd
        t.peak_extra += b.peak_extra
        t.unpriced += b.unpriced
        lines.append(f"| {b.key} | {b.calls:,} | {b.inp:,} | {b.cache:,} | {b.out:,} | {_hit(b)} | "
                     f"{b.usd:.4f} | {b.usd * cny:.3f} | {_per_call(b)} |")
    lines.append(f"| **合计** | {t.calls:,} | {t.inp:,} | {t.cache:,} | {t.out:,} | {_hit(t)} | "
                 f"{t.usd:.4f} | {t.usd * cny:.3f} | {_per_call(t)} |")
    return lines


def alerts(rows: Sequence[Row], bad: int, cny: float, mult: float,
           since_hours: float | None = None, now: dt.datetime | None = None) -> list[str]:
    """返回告警行（中文，可直接贴进报告）。"""
    out: list[str] = []
    holidays = holiday_set()
    now = now or dt.datetime.now(BJ)
    peak = [r for r in rows if r.engine.startswith(DEEPSEEK_PREFIX) and in_official_peak(r.ts, holidays)]
    if peak:
        extra = sum(row_cost(r, mult, holidays)[1] for r in peak)
        out.append(f"高峰时段 DeepSeek 调用 {len(peak)} 次（官方工作日 09–12、14–18 翻倍计价），多付约 "
                   f"${extra:.4f}（¥{extra * cny:.3f}）；这些调用宜挪到折扣窗口")
    if since_hours:
        cut = now - dt.timedelta(hours=since_hours)
        recent = [r for r in rows if r.ts >= cut and r.engine.startswith(DEEPSEEK_PREFIX)]
        try:
            from deepseek_offpeak import is_peak as policy_peak  # 现行策略窗口
        except Exception:  # noqa: BLE001 - 拿不到策略就只做价格告警
            policy_peak = None
        if policy_peak is not None:
            off = [r for r in recent if policy_peak(r.ts)]
            if off:
                out.append(f"折扣窗口外 DeepSeek 调用 {len(off)} 次（近 {since_hours:g} 小时；"
                           f"现行策略避开工作日 09–12、14–18 点高峰），最近一次 {off[-1].ts.astimezone(BJ):%m-%d %H:%M}")
    ds = [r for r in rows if r.engine.startswith(DEEPSEEK_PREFIX) and r.trec]
    if ds:
        inp = sum(r.inp for r in ds)
        cache = sum(r.cache for r in ds)
        if inp + cache:
            rate = cache / (inp + cache)
            if rate < 0.5:
                out.append(f"DeepSeek 缓存命中率仅 {rate:.0%}（{cache:,}/{inp + cache:,}）；"
                           f"system 前缀若稳定应远高于此，命中部分按 {PRICES.get('deepseek-flash', Price(0, 0, 0)).cache}"
                           f"/M 计价，等于白花")
    unpriced = sorted({r.engine for r in rows if r.engine not in PRICES and r.trec})
    if unpriced:
        out.append(f"未计价引擎（订阅额度）：{', '.join(unpriced)}——只统计调用与耗时，不折钱")
    if bad:
        out.append(f"账本坏行 {bad} 行（列数不足或时间无法解析），已跳过，不参与合计")
    retry = defaultdict(int)
    for r in rows:
        retry[stage_of(r.tag) + "|" + r.tag] += 1
    dup = sum(1 for v in retry.values() if v > 1)
    if dup:
        out.append(f"同标签重复调用 {dup} 组（返回重试或分片重跑），不影响正确性，但会抬高消耗")
    return out


def summary(rows: Sequence[Row], bad: int, group: str = "engine", cny: float = USD_CNY,
            mult: float = 2.0, title: str = "") -> list[str]:
    fn = KEYFUNCS[group]
    buckets = group_rows(rows, fn, mult)
    lines: list[str] = []
    if title:
        lines.append(f"## {title}\n")
    if not rows:
        lines.append("（没有账本记录：先确认 --root，或任务还没调用过模型）")
        return lines
    lines += render_table(buckets, key_header={"engine": "引擎", "stage": "流程", "tag": "标签",
                                               "file": "账本", "day": "日期", "book": "工程"}[group], cny=cny)
    al = alerts(rows, bad, cny, mult)
    if al:
        lines.append("")
        lines += ["- ⚠ " + a for a in al]
    if rows:
        t0, t1 = min(r.ts for r in rows), max(r.ts for r in rows)
        lines.append("")
        lines.append(f"时间范围：{t0.astimezone(BJ):%Y-%m-%d %H:%M} – {t1.astimezone(BJ):%Y-%m-%d %H:%M}"
                     f"（北京时间），账本 {len({r.source for r in rows})} 份")
    return lines


# ----------------------------------------------------------------- 实时盯盘
class Tailer:
    """跟踪各 usage.tsv 的新增行；首次见到文件时默认从末尾开始，避免把历史一次性倒出来。"""

    def __init__(self, roots: Sequence[str | os.PathLike[str]], from_start: bool = False) -> None:
        self.roots = [str(r) for r in roots]
        self.from_start = from_start
        self.state: dict[pathlib.Path, tuple[int, str]] = {}

    def poll(self) -> list[Row]:
        rows: list[Row] = []
        for path in find_ledgers(self.roots):
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if path not in self.state:
                self.state[path] = (0 if self.from_start else size, "")
                continue
            off, buf = self.state[path]
            if size < off:  # 被截断或重写：从头再读
                off, buf = 0, ""
            if size == off:
                continue
            try:
                with open(path, encoding="utf-8-sig", errors="replace") as fh:
                    fh.seek(off)
                    chunk = buf + fh.read()
            except OSError:
                continue
            lines = chunk.split("\n")
            self.state[path] = (size, lines.pop())
            for ln in lines:
                if not ln.strip() or ln.startswith("时间\t"):
                    continue
                r = parse_row(ln, str(path))
                if r is not None:
                    rows.append(r)
        return rows


def watch(roots: Sequence[str], interval: float = 5.0, group: str = "stage",
          cny: float = USD_CNY, mult: float = 2.0, max_rounds: int | None = None,
          out: TextIO | None = None, sleep: Callable[[float], None] = time.sleep) -> int:
    out = out or sys.stdout
    holidays = holiday_set()
    hist_rows: list[Row] = []
    bad = 0
    for p in find_ledgers(roots):
        rs, b = read_ledger(p)
        hist_rows += rs
        bad += b
    total_usd = sum(row_cost(r, mult, holidays)[0] or 0.0 for r in hist_rows)
    print(f"[盯盘] 已有 {len(hist_rows):,} 次调用，累计约 ${total_usd:.4f}（¥{total_usd * cny:.3f}）；"
          f"跟踪 {len({r.source for r in hist_rows})} 份账本，每 {interval:g} 秒扫一次，Ctrl-C 结束", file=out)
    tailer = Tailer(roots)
    rounds = 0
    new_rows: list[Row] = []
    while max_rounds is None or rounds < max_rounds:
        rounds += 1
        fresh = tailer.poll()
        for r in fresh:
            usd, extra = row_cost(r, mult, holidays)
            money = "订阅额度" if usd is None else f"${usd:.5f}"
            flag = " ⚠高峰" if extra else ""
            print(f"{r.ts.astimezone(BJ):%m-%d %H:%M:%S}  {r.engine:<14} {r.tag:<28} "
                  f"in={r.inp:>6,} out={r.out:>6,} cache={r.cache:>7,}  {r.seconds:5.1f}s  {money}{flag}", file=out)
            hist_rows.append(r)
            new_rows.append(r)
            total_usd += usd or 0.0
        if fresh:
            fresh_usd = sum(row_cost(r, mult, holidays)[0] or 0.0 for r in new_rows)
            span = (new_rows[-1].ts - new_rows[0].ts).total_seconds() / 60 or 1.0
            print(f"  ── 本轮 +{len(fresh)} 次 | 本轮起累计 ${fresh_usd:.4f} | "
                  f"{len(new_rows) / span:.1f} 次/分 | 总 ${total_usd:.4f}（¥{total_usd * cny:.3f}）", file=out)
        if max_rounds is None or rounds < max_rounds:
            sleep(interval)
    if hist_rows:
        print("\n[盯盘结束] 汇总：", file=out)
        for ln in summary(hist_rows[-2000:] if len(hist_rows) > 2000 else hist_rows, bad, group, cny, mult):
            print(ln, file=out)
    return 0


# ----------------------------------------------------------------- CLI
def _roots(args: argparse.Namespace) -> list[str]:
    return list(args.root) if args.root else [os.getcwd()]


def _filter_since(rows: Sequence[Row], since: str | None) -> list[Row]:
    if not since:
        return list(rows)
    cut = dt.datetime.fromisoformat(since).replace(tzinfo=BJ)
    return [r for r in rows if r.ts >= cut]


def cmd_summary(args: argparse.Namespace) -> int:
    rows: list[Row] = []
    bad = 0
    for p in find_ledgers(_roots(args)):
        rs, b = read_ledger(p)
        rows += rs
        bad += b
    rows = _filter_since(rows, args.since)
    title = args.title or ("用量汇总" + (f"（{args.since} 起）" if args.since else ""))
    lines = summary(rows, bad, args.group, args.usd_cny, args.peak_mult, title)
    print("\n".join(lines))
    if args.md:
        pathlib.Path(args.md).write_text("\n".join(lines) + "\n", encoding="utf8")
        print(f"\n已写 {args.md}", file=sys.stderr)
    if args.csv:
        buckets = group_rows(rows, KEYFUNCS[args.group], args.peak_mult)
        with open(args.csv, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["组", "调用", "输入token", "缓存读token", "输出token", "USD", "CNY", "秒", "高峰调用", "高峰多付USD"])
            for b in buckets:
                w.writerow([b.key, b.calls, b.inp, b.cache, b.out, f"{b.usd:.6f}",
                            f"{b.usd * args.usd_cny:.4f}", f"{b.seconds:.1f}", b.peak, f"{b.peak_extra:.6f}"])
        print(f"已写 {args.csv}", file=sys.stderr)
    if args.json:
        buckets = group_rows(rows, KEYFUNCS[args.group], args.peak_mult)
        payload = {
            "generated": dt.datetime.now(BJ).isoformat(timespec="seconds"),
            "roots": _roots(args),
            "group": args.group,
            "ledgers": len({r.source for r in rows}),
            "calls": len(rows),
            "bad_lines": bad,
            "usd": round(sum(b.usd for b in buckets), 6),
            "cny": round(sum(b.usd for b in buckets) * args.usd_cny, 4),
            "buckets": [dataclasses.asdict(b) | {"first": b.first.isoformat() if b.first else None,
                                                 "last": b.last.isoformat() if b.last else None}
                        for b in buckets],
            "alerts": alerts(rows, bad, args.usd_cny, args.peak_mult),
        }
        pathlib.Path(args.json).write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf8")
        print(f"已写 {args.json}", file=sys.stderr)
    if args.top:
        priced = [(row_cost(r, args.peak_mult)[0] or 0.0, r) for r in rows if r.source]
        priced.sort(key=lambda x: -x[0])
        print(f"\n最贵 {args.top} 次：")
        for usd, r in priced[: args.top]:
            print(f"  ${usd:.5f}  {r.ts.astimezone(BJ):%m-%d %H:%M}  {r.engine:<14} {r.tag:<30} "
                  f"in={r.inp:,} out={r.out:,} cache={r.cache:,}  {pathlib.Path(r.source).parent}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    rows: list[Row] = []
    bad = 0
    for p in find_ledgers(_roots(args)):
        rs, b = read_ledger(p)
        rows += rs
        bad += b
    rows = _filter_since(rows, args.since)
    total = sum(row_cost(r, args.peak_mult)[0] or 0.0 for r in rows)
    problems: list[str] = []
    if args.budget_usd is not None and total > args.budget_usd:
        problems.append(f"超出预算：${total:.4f} > ${args.budget_usd:.4f}（¥{total * args.usd_cny:.2f}）")
    al = alerts(rows, bad, args.usd_cny, args.peak_mult, args.since_hours)
    for a in al:
        if a.startswith("高峰") or a.startswith("折扣窗口外"):
            problems.append(a)
    if bad and args.strict:
        problems.append(f"账本坏行 {bad} 行")
    print(f"调用 {len(rows):,} 次，估算 ${total:.4f}（¥{total * args.usd_cny:.3f}）")
    if problems:
        for p in problems:
            print(f"✗ {p}")
        return 1
    print("✓ 未发现超预算、高峰调用或窗口外调用")
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    try:
        return watch(_roots(args), args.interval, args.group, args.usd_cny, args.peak_mult, args.max_rounds)
    except KeyboardInterrupt:
        print("\n（已停止）")
        return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="DeepSeek / 多模型调用消耗监测：汇总 usage.tsv 账本、计价、告警、实时盯盘")
    sub = ap.add_subparsers(dest="cmd")

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--root", action="append", help="要扫描的目录或账本文件（可重复；默认当前目录）")
        p.add_argument("--since", help="只统计该日期之后（YYYY-MM-DD）")
        p.add_argument("--usd-cny", type=float, default=USD_CNY, help=f"美元兑人民币，默认 {USD_CNY}")
        p.add_argument("--peak-mult", type=float, default=2.0, help="官方高峰价格倍数，默认 2")

    s = sub.add_parser("summary", help="一次性汇总（默认按引擎）")
    common(s)
    s.add_argument("--group", choices=list(KEYFUNCS), default="engine", help="分组：engine/stage/tag/file/day/book")
    s.add_argument("--md", help="另存 Markdown 报告")
    s.add_argument("--csv", help="另存 CSV")
    s.add_argument("--json", help="另存 JSON")
    s.add_argument("--top", type=int, default=0, help="附列最贵 N 次调用")
    s.add_argument("--title", help="报告标题")
    s.set_defaults(func=cmd_summary)

    w = sub.add_parser("watch", help="实时盯盘")
    common(w)
    w.add_argument("--interval", type=float, default=5.0, help="轮询间隔秒，默认 5")
    w.add_argument("--group", choices=list(KEYFUNCS), default="stage", help="结束后汇总分组，默认 stage")
    w.add_argument("--max-rounds", type=int, help="最多轮询次数（测试用）")
    w.set_defaults(func=cmd_watch)

    c = sub.add_parser("check", help="给 cron/CI 用：异常退出码非 0")
    common(c)
    c.add_argument("--budget-usd", type=float, help="预算上限（美元），超出报错")
    c.add_argument("--since-hours", type=float, default=24.0, help="窗口外调用只查最近 N 小时，默认 24")
    c.add_argument("--strict", action="store_true", help="账本坏行也判失败")
    c.set_defaults(func=cmd_check)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] not in ("summary", "watch", "check"):
        args = ["summary", *args]  # 不带子命令时默认汇总
    a = build_parser().parse_args(args)
    return int(a.func(a))


if __name__ == "__main__":
    sys.exit(main())
