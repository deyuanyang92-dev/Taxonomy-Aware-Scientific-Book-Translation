"""usage_monitor：账本解析、计价（含官方高峰翻倍）、分组汇总、告警闸门、实时盯盘。不调真实 API。"""
import datetime as dt
import json
import pathlib

import pytest

import usage_monitor as um

BJ = dt.timezone(dt.timedelta(hours=8))
HDR = "时间\tengine\t标签\t输入token\t输出token\t缓存读token\t耗时秒\n"
# 2026-11-16 是周一：03:00 为闲时，10:00 落在官方高峰（09–12）
OFFPEAK = "2026-11-16 03:00:00"
PEAK = "2026-11-16 10:00:00"


def line(ts, engine="deepseek-flash", tag="auto/revise/c000/0", inp=1000, out=500, cache=0, sec=1.0):
    return f"{ts}\t{engine}\t{tag}\t{inp}\t{out}\t{cache}\t{sec}"


def make_ledger(root: pathlib.Path, rel: str, lines) -> pathlib.Path:
    p = root / rel / "usage.tsv"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(HDR + "\n".join(lines) + "\n", encoding="utf8")
    return p


def t(h, m=0, day=16, month=11):
    return dt.datetime(2026, month, day, h, m, tzinfo=BJ)


# ---------------------------------------------------------------- 解析
def test_parse_row_and_bad_line():
    r = um.parse_row(line(OFFPEAK), "x/usage.tsv")
    assert r is not None and r.engine == "deepseek-flash" and r.inp == 1000 and r.trec
    assert r.ts == t(3)
    # 命令行引擎记 "-"，仍算一条调用、但无 token
    r2 = um.parse_row(line(OFFPEAK, engine="codex-sol", inp="-", out="-", cache="-"))
    assert r2 is not None and not r2.trec and r2.tokens == 0
    assert um.parse_row("坏行\t没有列") is None
    assert um.parse_row("2026-13-45 99:00:00\ta\tb\t1\t2\t3\t4") is None


def test_read_ledger_bom_and_header(tmp_path):
    p = tmp_path / "a" / "usage.tsv"
    p.parent.mkdir()
    p.write_bytes(("\ufeff" + HDR + line(OFFPEAK) + "\n" + "garbage\n").encode("utf8"))
    rows, bad = um.read_ledger(p)
    assert len(rows) == 1 and bad == 1


def test_stage_of():
    assert um.stage_of("auto/revise/c000/0") == "auto/revise"
    assert um.stage_of("auto/check/c012/1") == "auto/check"
    assert um.stage_of("body/c01") == "body"
    assert um.stage_of("polish/verify") == "polish/verify"
    assert um.stage_of("S1/judge") == "S1/judge"
    assert um.stage_of("") == "(空)"


def test_find_ledgers_skips_images(tmp_path):
    make_ledger(tmp_path, "书A/核译", [line(OFFPEAK)])
    make_ledger(tmp_path, "images", [line(OFFPEAK)])
    make_ledger(tmp_path, ".git/x", [line(OFFPEAK)])
    found = um.find_ledgers([str(tmp_path)])
    assert [p.parent.name for p in found] == ["核译"]


def test_book_of(tmp_path):
    p = make_ledger(tmp_path, "书A/ch1/核译", [line(OFFPEAK)])
    assert um.book_of(p, tmp_path) == "书A"
    assert um.book_of(p) == "核译"          # 不传 root 时退回上一级目录名


# ---------------------------------------------------------------- 计价
def test_peak_window_rules(monkeypatch):
    monkeypatch.delenv("YZZ_DEEPSEEK_HOLIDAYS", raising=False)
    assert um.in_official_peak(t(10)) and um.in_official_peak(t(14)) and um.in_official_peak(t(17, 59))
    assert not um.in_official_peak(t(8, 59)) and not um.in_official_peak(t(12, 0)) and not um.in_official_peak(t(3))
    assert not um.in_official_peak(t(10, day=15))          # 周日
    monkeypatch.setenv("YZZ_DEEPSEEK_HOLIDAYS", "2026-11-16")
    assert not um.in_official_peak(t(10))                  # 法定节假日不翻倍


def test_cost_offpeak_vs_peak():
    r = um.parse_row(line(OFFPEAK))
    usd, extra = um.row_cost(r)
    base = (1000 * 0.15 + 500 * 0.60) / 1e6
    assert usd == pytest.approx(base) and extra == 0
    rp = um.parse_row(line(PEAK))
    usd_p, extra_p = um.row_cost(rp)
    assert usd_p == pytest.approx(base * 2) and extra_p == pytest.approx(base)


def test_cost_unpriced_engine():
    assert um.row_cost(um.parse_row(line(OFFPEAK, engine="codex-sol")))[0] is None
    assert um.row_cost(um.parse_row(line(OFFPEAK, engine="claude-sonnet")))[0] is None


# ---------------------------------------------------------------- 汇总与告警
def rows_fixture():
    return [r for r in (um.parse_row(line(OFFPEAK, tag="auto/revise/c000/0")),
                        um.parse_row(line(OFFPEAK, tag="auto/revise/c001/1", inp=0, out=900)),
                        um.parse_row(line(OFFPEAK, tag="auto/check/c000/0", inp=2000, out=10)),
                        um.parse_row(line(PEAK, tag="body/c01", engine="deepseek-flash")),
                        um.parse_row(line(OFFPEAK, tag="body/c01", engine="codex-sol")))
            if r]


def test_group_rows_by_stage():
    buckets = um.group_rows(rows_fixture(), um.KEYFUNCS["stage"])
    keys = [b.key for b in buckets]
    assert keys[0] == "auto/revise"                 # 按花费降序
    assert {b.key for b in buckets} == {"auto/revise", "auto/check", "body"}
    body = [b for b in buckets if b.key == "body"][0]
    assert body.calls == 2 and body.unpriced == 1


def test_summary_report_mentions_peak_and_total():
    lines = um.summary(rows_fixture(), 0, "stage", title="用量汇总")
    text = "\n".join(lines)
    assert "用量汇总" in text and "| **合计** | 5 |" in text
    assert "高峰时段 DeepSeek 调用 1 次" in text
    assert "未计价引擎" in text and "codex-sol" in text


def test_summary_empty():
    assert "没有账本记录" in "\n".join(um.summary([], 0))


def test_check_budget_gate(tmp_path, capsys):
    make_ledger(tmp_path, "书A/核译", [line(OFFPEAK, inp=1_000_000, out=0)])
    assert um.main(["check", "--root", str(tmp_path), "--budget-usd", "0.01"]) == 1
    assert "超出预算" in capsys.readouterr().out
    assert um.main(["check", "--root", str(tmp_path), "--budget-usd", "10"]) == 0
    assert "✓" in capsys.readouterr().out


def test_summary_exports(tmp_path, capsys):
    make_ledger(tmp_path, "书A/核译", [line(OFFPEAK)])
    md, csvp, js = tmp_path / "u.md", tmp_path / "u.csv", tmp_path / "u.json"
    code = um.main(["summary", "--root", str(tmp_path), "--md", str(md), "--csv", str(csvp),
                    "--json", str(js), "--group", "book", "--top", "1"])
    assert code == 0
    out = capsys.readouterr().out
    assert "最贵 1 次" in out and "书A" in out
    assert md.read_text(encoding="utf8").startswith("## 用量汇总")
    assert "deepseek-flash" in csvp.read_text(encoding="utf-8-sig")
    payload = json.loads(js.read_text(encoding="utf8"))
    assert payload["calls"] == 1 and payload["buckets"][0]["key"] == "书A"


# ---------------------------------------------------------------- 实时盯盘
def test_tailer_reads_only_new_rows(tmp_path):
    p = make_ledger(tmp_path, "书A/核译", [line(OFFPEAK, tag="old/c00")])
    tailer = um.Tailer([str(tmp_path)])
    assert tailer.poll() == []                      # 首次见到文件：从末尾开始
    with open(p, "a", encoding="utf8") as fh:
        fh.write(line(OFFPEAK, tag="new/c00") + "\n")
    rows = tailer.poll()
    assert [r.tag for r in rows] == ["new/c00"]
    assert tailer.poll() == []                      # 没有新增就不重复报


def test_tailer_handles_truncation(tmp_path):
    p = make_ledger(tmp_path, "书A/核译", [line(OFFPEAK, tag="old/c00")])
    tailer = um.Tailer([str(tmp_path)], from_start=True)
    assert len(tailer.poll()) == 1
    p.write_text(HDR + line(OFFPEAK, tag="rewritten/c00") + "\n", encoding="utf8")
    assert [r.tag for r in tailer.poll()] == ["rewritten/c00"]


def test_watch_prints_new_calls(tmp_path):
    make_ledger(tmp_path, "书A/核译", [line(OFFPEAK, tag="old/c00")])
    um.watch([str(tmp_path)], interval=0.01, max_rounds=2, sleep=lambda s: None)
