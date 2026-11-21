#!/usr/bin/env python3
"""低成本翻译流水线：Google 免费初译 → 脚本修正 → DeepSeek flash 不开思考一次核对润色 → 报警段才开思考。

  python3 gtrans.py <英文.txt> -o <输出目录> [--domain 进化生物学] [--llm-mode rewrite|edits] [--rewrite-engine E] [--think-escalate] [--no-llm] [--dry]

输入：英文文本，空行分段；`<!-- p.N -->` 页码标记和标题（# 行、全大写短行、Title Case 单行）各自成单元，原样保留、不送 Google；
  「Fig.」开头的图注单独成单元；前一段没写完句子、页码标记之后接着写的，合并成一段，标记移到合并段之后（同 join_page_breaks）。
1 Google（translate.googleapis.com，gtx 免费端点）：每段一个请求，超过 4500 字符按句子边界切块；请求间隔 1–2 秒，
  429/5xx/网络错误指数退避，最多重试 5 次；结果缓存在 ~/.cache/yzz-translate/gtrans_cache.sqlite（键 sha1(原文)），重跑不再花请求。
2 脚本修正（不调模型）：
  a skill/google_fixes.tsv：错<TAB>对<TAB>说明<TAB>触发词（可省）。有触发词的，仅当该单元英文里出现它才替换；
  b yiku table 的 HARD 术语：把 Google 对该术语单独翻译的结果（缓存）换成 yiku 定名；SOFT 术语不自动替换；
  c 一致性检查：同一英文术语在单元内出现 ≥2 次，译文里同时出现多种译法（yiku 定名、Google 默认译法、修正表里的错译、
    SOFT 的备选译名）→ 警告；
  d fidelity_check --fix（拉丁名、人名、数字、术语首现括注）；标题全文处理完后跑 heading_bilingual；cite_diff 只报告。
3 LLM（除非 --no-llm）。--llm-mode rewrite（默认）：每单元（正文段合并到 ≤1500 英文词）让名家译者整段改写（system 含 skill/STYLE.md §6），
  引擎缺省 deepseek-flash、关思考，--rewrite-engine 可换（如 claude-sonnet）。改写稿须通过护栏（引证、年份、数字单位、拉丁名、页码标记、
  HARD 术语不变，段数不变），否则保留初稿并记录；通过后再做一次意义核对（deepseek-flash 关思考，只报意思不一致的句子并给最小修正），
  修正须 zh_old 恰好出现一次并过同一护栏；核对返回格式错误则保留改写稿，在 report.md 标注该单元。--think-escalate：仍有未修复意义警告的单元，开思考再核对一次。
  --llm-mode edits（旧模式）：deepseek-flash 关思考，一次调用只返回 JSON 改动；改动须 old 在单元译文里恰好出现一次，并通过 polish_guard，否则拒绝并记录；
  --think-escalate：第一轮后仍有一致性警告或保真问题的单元，才开思考重跑一次。
4 输出：out_dir/zh.md（带页码标记）、report.md（逐单元）、edits.jsonl（采纳与拒绝的改动）。每次 LLM 调用由 llm_engines 追加到 usage.tsv。
DeepSeek 只在折扣时段（北京时间 18:00–次日 09:00 随时可用；高峰 09–12、14–18 点工作日不发请求）调用，除非 LLM_SKIP_OFFPEAK=1（须用户授权）。--dry 只列计划（请求数、缓存命中、估算 token），不联网、不调模型。
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import random
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cite_diff
import fidelity_check as fc
import heading_bilingual as hb
import llm_engines as le
import polish_guard as pg
from direct_mode import PAGE_MARK

ROOT = Path(__file__).resolve().parent.parent
GOOGLE_URL = "https://translate.googleapis.com/translate_a/single"
# 2026-11-16：translate.googleapis.com 对并发批量请求整段 IP 返回 429（连单条也 429），
# clients5 的 dict-chrome-ex 端点仍可用；作为 429/5xx 时的即时后备。
GOOGLE_FALLBACK_URL = "https://clients5.google.com/translate_a/t"
CHUNK_MAX = 4500
MAX_RETRIES = 5
ENGINE = "deepseek-flash"
MAX_WORDS = 1500
DEFAULT_CACHE = "~/.cache/yzz-translate/gtrans_cache.sqlite"
# PDF extraction leaves control bytes (notably 0x08) inside running headers
# and OCR failures (U+FFFD) in leader-dot runs; either can push the encoded
# request past Google's limit and get HTTP 400. Strip both before URL encoding.
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f�]")

_sleep = time.sleep           # 测试里替换，免得真等


class GoogleError(RuntimeError):
    pass


class GoogleBadRequest(GoogleError):
    """HTTP 4xx（非 429）：请求本身被拒，原样重试没用；上层按句拆分后再试（issue #6）。"""

    def __init__(self, msg: str, code: int):
        super().__init__(msg)
        self.code = code


MIN_SPLIT = 40          # 短于此长度的段不再拆


def char_classes(q: str) -> dict[str, int]:
    """诊断用的字符类别计数（不含原文本身，避免日志里出现受版权保护的文字）。"""
    c = {"ascii": 0, "latin_ext": 0, "cyrillic": 0, "cjk": 0, "digit": 0, "space": 0, "punct": 0, "control": 0,
         "percent": 0, "other": 0}
    for ch in q:
        o = ord(ch)
        if ch.isspace():
            c["space"] += 1
        elif o < 32 or 0x7F <= o < 0xA0 or o == 0xFFFD:
            c["control"] += 1
        elif ch.isdigit():
            c["digit"] += 1
        elif ch == "%":
            c["percent"] += 1
        elif o < 128 and ch.isalpha():
            c["ascii"] += 1
        elif o < 128:
            c["punct"] += 1
        elif 0x80 <= o < 0x250:
            c["latin_ext"] += 1
        elif 0x400 <= o < 0x530:
            c["cyrillic"] += 1
        elif 0x4E00 <= o < 0xA000:
            c["cjk"] += 1
        else:
            c["other"] += 1
    return {k: v for k, v in c.items() if v}


# ---------------------------------------------------------------- Google：切块、缓存、限速、重试

_ABBR = {"fig", "figs", "al", "e.g", "i.e", "vs", "p", "pp", "no", "cf", "ca", "sp", "spp", "ssp", "var", "dr", "mr",
         "st", "prof", "viz", "etc", "ed", "eds", "vol", "ch", "sect"}
_SENT_END = re.compile(r"""([.!?]["'”’)\]]*)\s+(?=["'“‘(\[]?[A-Z0-9])""")
_LAST_WORD = re.compile(r"[A-Za-z]+(?:\.[A-Za-z]+)*$")


def split_sentences(text: str) -> list[str]:
    out: list[str] = []
    start = 0
    for m in _SENT_END.finditer(text):
        if m.group(1)[0] == ".":
            w = _LAST_WORD.search(text[start:m.start(1)])
            if w and (w.group(0).lower() in _ABBR or len(w.group(0)) == 1):     # Fig. / et al. / A. R. Wallace
                continue
        out.append(text[start:m.end(1)])
        start = m.end()
    if text[start:].strip():
        out.append(text[start:])
    return [s.strip() for s in out if s.strip()]


def split_chunks(text: str, limit: int = CHUNK_MAX) -> list[str]:
    """≤limit 字符的块，尽量在句子边界切；单句超长才在空格处硬切。"""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    cur = ""
    for s in split_sentences(text):
        while len(s) > limit:
            if cur:
                chunks.append(cur)
                cur = ""
            cut = s.rfind(" ", 0, limit)
            cut = cut if cut > 0 else limit
            chunks.append(s[:cut].strip())
            s = s[cut:].strip()
        if cur and len(cur) + 1 + len(s) > limit:
            chunks.append(cur)
            cur = s
        else:
            cur = f"{cur} {s}" if cur else s
    if cur:
        chunks.append(cur)
    return chunks


def http_get(url: str, timeout: float = 30) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return str(r.read().decode("utf8"))


def _parse_google(data: object) -> str:
    """两种免费端点的返回：gtx 的 [[[译文,原文,...],...]]；clients5 的 [译文] 或 [译文,...]。"""
    if isinstance(data, list) and data:
        if all(isinstance(x, str) for x in data):
            return "".join(data)
        try:
            return "".join(str(seg[0]) for seg in data[0] if seg and seg[0])  # type: ignore[index]
        except (TypeError, IndexError):
            pass
    if isinstance(data, dict) and isinstance(data.get("sentences"), list):
        return "".join(str(s.get("trans", "")) for s in data["sentences"] if isinstance(s, dict))
    raise TypeError(f"Google 返回格式无法解析：{str(data)[:120]}")


class Cache:
    """sqlite 持久缓存，键 sha1(原文)。"""

    def __init__(self, path: str | Path | None = None):
        p = Path(path or os.environ.get("GTRANS_CACHE") or DEFAULT_CACHE).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(p, timeout=30, check_same_thread=False)
        self.con.execute("PRAGMA journal_mode=WAL")      # 多进程同时读写：读不挡写，写等锁而不是立刻报错
        self.con.execute("PRAGMA busy_timeout=30000")
        self.lock = threading.Lock()
        self.con.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, en TEXT, zh TEXT, ts REAL)")
        self.con.commit()

    @staticmethod
    def key(text: str) -> str:
        return hashlib.sha1(text.encode("utf8")).hexdigest()

    def get(self, text: str) -> str | None:
        with self.lock:
            row = self.con.execute("SELECT zh FROM cache WHERE key=?", (self.key(text),)).fetchone()
        if row is None or not str(row[0]).strip():
            return None          # 旧版曾把空响应写入缓存；空译文按未命中处理，重新请求
        return str(row[0])

    def put(self, text: str, zh: str) -> None:
        for attempt in range(5):
            try:
                with self.lock:
                    self.con.execute("INSERT OR REPLACE INTO cache VALUES (?,?,?,?)",
                                     (self.key(text), text, zh, time.time()))
                    self.con.commit()
                return
            except sqlite3.OperationalError as exc:   # busy_timeout 之外再兜底：并发书目可能同时提交
                if "locked" not in str(exc) or attempt == 4:
                    raise
                time.sleep(0.2 * (attempt + 1))


class Google:
    """Google 免费端点（translate_a/single, client=gtx）。

    提速（2026-11-15 实测，保→英 150 段）：逐段请求 4 线程带 0.5 s 间隔 237 段/分钟，8 线程无间隔 320 段/分钟；
    把多段拼进一个请求反而频繁 429（21 段/分钟），故不拼段。用 urllib：同机 `requests` 库请求被 429、urllib 正常。
    prefetch() 先并发填缓存，主流程再顺序取用；遇 429/5xx 所有线程一起冷却，避免越打越封。"""

    def __init__(self, cache: Cache, sl: str = "en", tl: str = "zh-CN", pause: tuple[float, float] = (1.0, 2.0),
                 diag_path: str | Path | None = None):
        self.cache = cache
        self.diag_path = Path(diag_path) if diag_path else None
        self.diagnostics: list[dict[str, Any]] = []
        self.sl, self.tl, self.pause = sl, tl, pause
        self.requests = 0
        self.hits = 0
        self.chars = 0
        self._cool_until = 0.0
        self._primary_down_until = 0.0      # 主端点整段 IP 429 后，先直连后备端点，避免每条都撞一次
        self._lock = threading.Lock()

    def _ck(self, c: str) -> str:
        """缓存键原文：英→中沿用旧键（已有缓存不失效）；其他语言对加前缀隔离。"""
        return c if (self.sl, self.tl) == ("en", "zh-CN") else f"[{self.sl}>{self.tl}]{c}"

    def has(self, text: str) -> bool:
        return all(self.cache.get(self._ck(c)) is not None for c in split_chunks(text.strip()))

    def _fetch(self, q: str) -> str:
        q = CONTROL_RE.sub("", q)
        if not q.strip():
            return ""
        primary = GOOGLE_URL + "?" + urllib.parse.urlencode(
            {"client": "gtx", "sl": self.sl, "tl": self.tl, "dt": "t", "q": q}, quote_via=urllib.parse.quote)
        fallback = GOOGLE_FALLBACK_URL + "?" + urllib.parse.urlencode(
            {"client": "dict-chrome-ex", "sl": self.sl, "tl": self.tl, "q": q}, quote_via=urllib.parse.quote)
        if self.pause[1] > 0:
            _sleep(random.uniform(*self.pause))
        last: Exception | None = None
        slept_until = 0.0
        for k in range(MAX_RETRIES + 1):
            if self._cool_until > max(slept_until, time.time()):  # 别的线程触发了冷却：一起等
                _sleep(self._cool_until - time.time())
                slept_until = self._cool_until
            fatal: urllib.error.HTTPError | None = None
            urls = (fallback,) if self._primary_down_until > time.time() else (primary, fallback)
            for url in urls:
                try:
                    with self._lock:
                        self.requests += 1
                        self.chars += len(q)
                    out = _parse_google(json.loads(http_get(url)))
                    if not out.strip():        # Google 偶发返回空串；不能缓存，按失败重试/换端点
                        last = GoogleError(f"Google 返回空译文：{q[:60]!r}")
                        continue
                    return out
                except urllib.error.HTTPError as exc:
                    last = exc
                    if url is primary and exc.code == 429:     # 主端点限流：10 分钟内直接走后备
                        with self._lock:
                            self._primary_down_until = time.time() + 600
                    if exc.code != 429 and exc.code < 500:
                        fatal = exc      # 主端点 4xx：先试后备端点，两者都 4xx 才算致命
                    continue
                except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError,
                        IndexError, TypeError, KeyError) as exc:
                    last = exc
            if fatal is not None:
                raise GoogleBadRequest(f"Google HTTP {fatal.code}：{fatal.reason}", fatal.code) from fatal
            if k < MAX_RETRIES:
                wait = 5 * 2 ** k + random.uniform(0, 2)
                if isinstance(last, urllib.error.HTTPError):  # 429/5xx：全体冷却
                    with self._lock:
                        self._cool_until = max(self._cool_until, time.time() + wait)
                        slept_until = self._cool_until
                print(f"[gtrans] Google 请求失败（{type(last).__name__}），{wait:.0f} 秒后第 {k + 2} 次尝试", file=sys.stderr)
                _sleep(wait)
        raise GoogleError(f"Google 重试 {MAX_RETRIES} 次仍失败：{last}")

    def _diag(self, q: str, code: int, depth: int) -> None:
        rec = {"code": code, "length": len(q), "depth": depth, "sha1": hashlib.sha1(q.encode("utf8")).hexdigest()[:12],
               "classes": char_classes(q), "sl": self.sl, "tl": self.tl}
        with self._lock:
            self.diagnostics.append(rec)
            if self.diag_path:
                self.diag_path.parent.mkdir(parents=True, exist_ok=True)
                with self.diag_path.open("a", encoding="utf8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"[gtrans] HTTP {code}：长 {len(q)} 字符，按句拆分重试（诊断 {rec['sha1']} {rec['classes']}）", file=sys.stderr)

    def _split_for_retry(self, q: str) -> list[str]:
        parts = split_sentences(q)
        if len(parts) < 2:        # 单句：在空格处对半切
            half = max(MIN_SPLIT // 2, len(q) // 2)
            parts = split_chunks(q, half) if len(q) > MIN_SPLIT else [q]
        return parts

    def _fetch_split(self, q: str, depth: int = 0) -> str:
        """_fetch；遇 HTTP 400 不再原样重试，而是按句拆小块逐块请求，按原顺序拼回（保持段落对齐）。"""
        try:
            return self._fetch(q)
        except GoogleBadRequest as exc:
            if exc.code != 400 or len(q) <= MIN_SPLIT or depth >= 6:
                raise
            self._diag(q, exc.code, depth)
            parts = self._split_for_retry(q)
            if len(parts) < 2:
                raise
            return " ".join(self._fetch_split(x, depth + 1) for x in parts)

    def translate(self, text: str) -> str:
        text = text.strip()
        if not text:
            return ""
        parts: list[str] = []
        for c in split_chunks(text):
            zh = self.cache.get(self._ck(c))
            if zh is None:
                zh = self._fetch_split(c)
                self.cache.put(self._ck(c), zh)
            else:
                self.hits += 1
            parts.append(zh)
        out = "".join(parts).strip()
        if not out:
            raise GoogleError(f"Google 返回空译文：{text[:60]!r}")
        return out

    def prefetch(self, texts: list[str], workers: int = 8) -> int:
        """并发预取未缓存的块（无间隔，遇 429 全体冷却）；返回新请求数。失败的块留给顺序流程重试并报错。"""
        todo = list(dict.fromkeys(c for t in texts if t.strip() for c in split_chunks(t.strip())
                                  if self.cache.get(self._ck(c)) is None))
        if not todo:
            return 0
        saved, self.pause = self.pause, (0.0, 0.0)

        def one(c: str) -> None:
            try:
                self.cache.put(self._ck(c), self._fetch_split(c))
            except GoogleError as exc:
                print(f"[gtrans] 预取失败（稍后顺序重试）：{exc}", file=sys.stderr)

        try:
            with ThreadPoolExecutor(workers) as ex:
                list(ex.map(one, todo))
        finally:
            self.pause = saved
        return len(todo)

    def term(self, en: str) -> str:
        """术语单独的 Google 译法（缓存），去掉句末标点。"""
        return self.translate(en).strip().strip("。.！!？? ")


# ---------------------------------------------------------------- 解析：块与单元

@dataclass
class Block:
    kind: str            # marker | heading | para | caption
    en: str
    level: int = 0       # 标题的 # 个数


CAPTION = re.compile(r"^(?:Figs?\.|Figure)\s*\d")
_TERMINAL = re.compile(r"""[.!?:;…]["'”’)\]*]*$""")


def _clean_para(lines: list[str]) -> str:
    text = "\n".join(x.strip() for x in lines)
    text = re.sub(r"(?<=[a-z])-\n(?=[a-z])", "", text)         # OCR 行末断词
    return re.sub(r"\s*\n\s*", " ", text).strip()


def _join_page_breaks(blocks: list[Block]) -> list[Block]:
    out: list[Block] = []
    i = 0
    while i < len(blocks):
        cur = blocks[i]
        i += 1
        moved: list[Block] = []
        while cur.kind == "para" and not _TERMINAL.search(cur.en):
            j, ms = i, []
            while j < len(blocks) and blocks[j].kind == "marker":
                ms.append(blocks[j])
                j += 1
            if not ms or j >= len(blocks) or blocks[j].kind != "para":
                break
            cur = Block("para", f"{cur.en} {blocks[j].en}")
            moved += ms
            i = j + 1
        out.append(cur)
        out.extend(moved)
    return out


def parse_blocks(text: str) -> list[Block]:
    text = text.replace("\r\n", "\n")
    lines = text.split("\n")
    heads = {h.line: h for h in hb.english_headings(text)}
    blocks: list[Block] = []
    buf: list[str] = []

    def flush() -> None:
        if buf:
            en = _clean_para(buf)
            blocks.append(Block("caption" if CAPTION.match(en) else "para", en))
            buf.clear()

    for i, raw in enumerate(lines):
        s = raw.strip()
        if not s:
            flush()
        elif PAGE_MARK.match(raw):
            flush()
            blocks.append(Block("marker", s))
        elif i in heads:
            flush()
            m = re.match(r"(#+)\s", s)
            blocks.append(Block("heading", s, len(m.group(1)) if m else 2))
        else:
            buf.append(raw)
    flush()
    return _join_page_breaks(blocks)


def heading_text(b: Block) -> str:
    t = re.sub(r"^#+\s*", "", b.en).strip()
    return hb.title_case(t)


@dataclass
class Unit:
    kind: str                     # body | caption | heading | marker
    blocks: list[Block]
    page: str = ""
    zh: str = ""

    @property
    def en(self) -> str:
        return "\n\n".join(b.en for b in self.blocks)

    @property
    def words(self) -> int:
        return sum(len(b.en.split()) for b in self.blocks if b.kind != "marker")


def build_units(blocks: list[Block], max_words: int = MAX_WORDS) -> list[Unit]:
    units: list[Unit] = []
    cur: Unit | None = None
    pending: list[Block] = []
    page = ""

    def flush() -> None:
        nonlocal cur
        if cur:
            units.append(cur)
            cur = None

    def flush_markers() -> None:
        nonlocal pending
        for m in pending:
            units.append(Unit("marker", [m]))
        pending = []

    for b in blocks:
        if b.kind == "marker":
            pending.append(b)
            lab = PAGE_MARK.match(b.en)
            page = lab.group(1) if lab else page
            continue
        kind = {"para": "body", "caption": "caption", "heading": "heading"}[b.kind]
        w = len(b.en.split())
        if cur and cur.kind == kind and kind != "heading" and cur.words + w <= max_words:
            cur.blocks += [*pending, b]
            pending = []
            continue
        flush()
        flush_markers()
        cur = Unit(kind, [b], page)
    flush()
    flush_markers()
    return units


# ---------------------------------------------------------------- 脚本修正

_CJK = "一-鿿"


def tidy(zh: str) -> str:
    """去掉 Google 译文里中文标点后、数字与汉字之间多出的空格（不动换行）。"""
    zh = re.sub(r"(?<=[。！？；：，、）」』》”’…])[ \t]+", "", zh)
    zh = re.sub(r"[ \t]+(?=[（「『《“‘])", "", zh)
    zh = re.sub(rf"(?<=\d)[ \t]+(?=[{_CJK}])", "", zh)
    return re.sub(rf"(?<=[{_CJK}])[ \t]+(?=\d)", "", zh)


@dataclass
class Fix:
    wrong: str
    right: str
    note: str = ""
    term: str = ""


def default_fixes() -> Path | None:
    for p in (ROOT / "skill" / "google_fixes.tsv", ROOT / "google_fixes.tsv"):   # 仓库里在 skill/，技能目录副本里在根
        if p.exists():
            return p
    return None


def load_fixes(path: str | Path | None = None) -> list[Fix]:
    p = Path(path) if path else default_fixes()
    out: list[Fix] = []
    if p is None or not p.exists():
        return out
    for ln in p.read_text(encoding="utf8").splitlines():
        if ln.lstrip().startswith("#") or not ln.strip():
            continue
        c = ln.split("\t") + ["", "", "", ""]
        if c[0].strip() and c[1].strip():
            out.append(Fix(c[0].strip(), c[1].strip(), c[2].strip(), c[3].strip()))
    return out


def apply_fixes(zh: str, en: str, fixes: list[Fix]) -> tuple[str, list[str]]:
    applied: list[str] = []
    for f in fixes:
        if f.term and not re.search(f.term, en, re.I):
            continue
        n = zh.count(f.wrong)
        if n:
            zh = zh.replace(f.wrong, f.right)
            applied.append(f"{f.wrong}→{f.right}×{n}")
    return zh, applied


def parse_table(table: str) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """yiku table 输出 -> (HARD 行, SOFT 行)，每行 (英文, 中文译名)。"""
    hard: list[tuple[str, str]] = []
    soft: list[tuple[str, str]] = []
    sec = ""
    for ln in table.splitlines():
        if ln.startswith("## "):
            sec = "hard" if ln.startswith("## HARD") else "soft" if ln.startswith("## SOFT") else ""
        elif sec and ln.startswith("|"):
            c = [x.strip() for x in ln.strip().strip("|").split("|")]
            if len(c) >= 2 and re.match(r"[A-Za-z]", c[0]) and re.search(r"[一-鿿]", c[1]) and c[0] != "英文":
                (hard if sec == "hard" else soft).append((c[0], c[1]))
    return hard, soft


def term_count(en: str, term: str) -> int:
    return len(re.findall(rf"(?<![A-Za-z]){re.escape(term)}(?:e?s)?(?![A-Za-z])", en, re.I))


def replace_google_terms(zh: str, hard: list[tuple[str, str]], probe: Any) -> tuple[str, list[str]]:
    """把 Google 对 HARD 术语的默认译法换成 yiku 定名。长术语优先；g 落在定名内部（会叠字）或太短的不动。"""
    applied: list[str] = []
    for en, zh_name in sorted(hard, key=lambda r: -len(r[0])):
        z = (fc.zh_forms(zh_name) or [""])[0]
        g = str(probe(en.lower()))
        if not z or not g or g == z or len(g) < 2 or g in z or g not in zh:
            continue
        n = zh.count(g)
        zh = zh.replace(g, z)
        applied.append(f"{en}: {g}→{z}×{n}")
    return zh, applied


def consistency(zh: str, en: str, hard: list[tuple[str, str]], soft: list[tuple[str, str]],
                variants: dict[str, set[str]]) -> list[str]:
    """同一英文术语在单元内出现 ≥2 次、译文里却同时出现多种译法 → 警告。"""
    warns: list[str] = []
    for term, zh_name in [*hard, *soft]:
        if term_count(en, term) < 2:
            continue
        forms = list(dict.fromkeys([*fc.zh_forms(zh_name), *sorted(variants.get(term.lower(), set()))]))
        present = [f for f in forms if f in zh]
        present = [f for f in present if not any(f != o and f in o for o in present)]
        if len(present) >= 2:
            warns.append(f"术语 {term} 出现 {term_count(en, term)} 次，译文里有多种译法：{'、'.join(present)}")
    return warns


# ---------------------------------------------------------------- yiku / LLM

def yiku_table(en: str, domain: str) -> str:
    exe = shutil.which("yiku")
    if not exe:
        return ""
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf8") as f:
        f.write(en)
    try:
        r = subprocess.run([exe, "table", f.name, "--domain", domain], capture_output=True, text=True, timeout=120)
        return r.stdout if r.returncode == 0 else ""
    finally:
        os.unlink(f.name)


def open_yiku(domain: str) -> Any:
    return fc.open_yiku(domain)


def engine_call(*args: Any, **kwargs: Any) -> tuple[str, dict[str, Any]]:
    return le.call(*args, **kwargs)


SYSTEM = """你是{domain}专著的中文审校。给你英文原文、机器初译和术语表。
逐句对照英文，只找并改正：误译、漏译、专名错误（人名、船名、书名、年份）、术语未按术语表、概念被替换（如 particle 与 factor 不可互换）、明显翻译腔。
不改动意思正确且通顺的句子；不增删信息；引文、年份、数字、拉丁学名、页码标记 <!-- p.N --> 不得改动。
只输出 JSON 数组，每项 {{"old": 初译中原样存在的片段, "new": 改后片段, "type": "误译|漏译|专名|术语|润色"}}。\
old 必须在初译中恰好出现一次，取短而唯一的片段。没有问题输出 []。"""


@contextlib.contextmanager
def thinking(on: bool) -> Iterator[None]:
    old = os.environ.get("YZZ_DEEPSEEK_THINKING")
    if on:
        os.environ["YZZ_DEEPSEEK_THINKING"] = "1"
    else:
        os.environ.pop("YZZ_DEEPSEEK_THINKING", None)
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("YZZ_DEEPSEEK_THINKING", None)
        else:
            os.environ["YZZ_DEEPSEEK_THINKING"] = old


def table_for_prompt(table: str) -> str:
    i = table.find("## HARD")
    return (table[i:] if i >= 0 else table)[:3500]


def build_user(table: str, en: str, zh: str, warns: list[str]) -> str:
    s = f"## 术语表\n{table_for_prompt(table)}\n\n## 英文原文\n{en}\n\n## 机器初译\n{zh}"
    if warns:
        s += "\n\n## 脚本报警（请重点核对这些问题）\n" + "\n".join(f"- {w}" for w in warns)
    return s


def parse_edits(text: str) -> list[dict[str, Any]]:
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    return [e for e in data if isinstance(e, dict)] if isinstance(data, list) else []


def apply_edits(zh: str, edits: list[dict[str, Any]], hard: list[str]) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    """old 恰好出现一次 + polish_guard 通过才采纳。返回 (新译文, 采纳, 拒绝)。"""
    items: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for e in edits:
        if isinstance(e.get("old"), str) and isinstance(e.get("new"), str) and e["old"]:
            items.append({"old": e["old"], "new": e["new"], "orig_type": str(e.get("type", ""))})
        else:
            rejected.append({**e, "reject": "缺 old/new 或 old 为空"})
    ok, bad = pg.filter_issues(zh, items, hard_for=lambda _it: hard)
    for it in ok:
        zh = zh.replace(it["old"], it["new"], 1)
    return zh, ok, rejected + bad


# ---------------------------------------------------------------- 整段改写 + 意义核对

REWRITE_HEAD = ("你是名家译者，把译文改写成地道、凝练的学术中文。忠实第一：不增删信息，引文、年份、数字、学名、术语不变；"
                "概念不得替换；保持原段落划分，不拆段不并段。")
REWRITE_TAIL = "只输出改写后的完整中文，不要解释。"

MEANING_SYS = """你是英中译文的意义核对员。逐句对照英文原文与中文译文，只找中文与英文意思不一致的句子：
极性或否定、谁主张了什么（主语与归属）、数量词、模糊限定语（may、usually、some）、因果关系、漏译或增译。不报文风问题。
对每个不一致的句子给出最小修正，引文、年份、数字、学名、术语不得改动。
只输出 JSON 数组，每项 {"zh_old": 中文里原样存在的短而唯一的片段, "zh_new": 改后片段, "why": 简短理由}。意思全部一致输出 []。"""

_LATIN = re.compile(r"(?<![A-Za-z])[A-Z][a-z]{2,} [a-z]{3,}(?![A-Za-z])")
_PARA_SPLIT = re.compile(r"\n\s*\n")
_RW_LABEL = {"used": "采用", "rejected": "拒绝，保留初稿", "failed": "调用失败，保留初稿"}


def style_section() -> str:
    """skill/STYLE.md 的「## 6.」整节（运行时读取；找不到则空）。"""
    for p in (ROOT / "skill" / "STYLE.md", ROOT / "STYLE.md"):
        if p.exists():
            m = re.search(r"^## 6\..*?(?=^## \d|\Z)", p.read_text(encoding="utf8"), re.S | re.M)
            if m:
                return m.group(0).strip()
    return ""


def rewrite_system() -> str:
    return "\n\n".join(x for x in (REWRITE_HEAD, style_section(), REWRITE_TAIL) if x)


def term_lines(table: str, extra: list[str] | None = None, limit: int = 60) -> str:
    """术语表压成 `en=中文` 行（HARD 在前，SOFT 在后），再附脚本修正里带触发词的项。"""
    hard, soft = parse_table(table)
    rows = [f"{en}={zh}" for en, zh in [*hard, *soft]][:limit]
    return "\n".join(dict.fromkeys(rows + list(extra or [])))


def strip_fences(txt: str) -> str:
    t = txt.strip()
    m = re.match(r"^```[A-Za-z]*\n(.*?)\n?```$", t, re.S)
    return (m.group(1) if m else t).strip()


def para_count(text: str) -> int:
    return len([p for p in _PARA_SPLIT.split(text.strip()) if p.strip()])


def rewrite_violations(before: str, after: str, hard: list[str]) -> list[str]:
    """polish_guard（引证、年份、数字单位、斜体拉丁名、页码标记、HARD 术语）+ 非斜体拉丁双名 + 段数。空列表＝通过。"""
    if not after.strip():
        return ["改写稿为空"]
    why = pg.violations(before, after, hard)
    a, b = Counter(_LATIN.findall(before.replace("*", ""))), Counter(_LATIN.findall(after.replace("*", "")))
    if a != b:
        why.append("拉丁双名被改动：" + "、".join(sorted(((a - b) + (b - a)).keys())))
    if para_count(before) != para_count(after):
        why.append(f"段数改变（{para_count(before)} -> {para_count(after)}）")
    return why


def parse_meaning(text: str) -> list[dict[str, Any]] | None:
    """意义核对返回 -> 问题列表；格式错误（无 JSON 数组、解析失败、元素不是对象）返回 None。"""
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, list) or not all(isinstance(e, dict) for e in data):
        return None
    return data


# ---------------------------------------------------------------- 主流程

@dataclass
class Opts:
    domain: str = "进化生物学"
    think_escalate: bool = False
    no_llm: bool = False
    dry: bool = False
    max_words: int = MAX_WORDS
    fixes: str | None = None
    cache: str | None = None
    stem: str = "gtrans"
    llm_mode: str = "rewrite"            # rewrite：整段改写 + 意义核对；edits：旧的 JSON 改动单
    rewrite_engine: str | None = None    # 缺省 ENGINE（deepseek-flash）


@dataclass
class Rep:
    idx: int
    kind: str
    page: str
    words: int
    chars: int = 0
    fixes: list[str] = field(default_factory=list)
    terms: list[str] = field(default_factory=list)
    warns: list[str] = field(default_factory=list)
    fidelity: list[str] = field(default_factory=list)
    cites: list[str] = field(default_factory=list)
    applied: list[dict[str, Any]] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)
    tok_in: int = 0
    tok_out: int = 0
    think_in: int = 0
    think_out: int = 0
    thinking_used: bool = False
    note: list[str] = field(default_factory=list)
    rewrite: str = ""                    # "" | used | rejected | failed
    rewrite_why: list[str] = field(default_factory=list)
    mc_status: str = ""                  # "" | ok | malformed | failed
    mc_found: int = 0
    mc_fixed: int = 0
    mc_left: list[dict[str, Any]] = field(default_factory=list)


class Runner:
    def __init__(self, opts: Opts, google: Google):
        self.o, self.g = opts, google
        self.fixes = load_fixes(opts.fixes)
        self.persons = fc.load_persons()
        self.yiku = open_yiku(opts.domain) if not opts.dry else None
        self.seen: set[str] = set()

    # -- Google 层
    def google_unit(self, u: Unit) -> None:
        parts: list[str] = []
        for b in u.blocks:
            if b.kind == "marker":
                parts.append(b.en)
            elif b.kind == "heading":
                zh = tidy(self.g.translate(heading_text(b)))
                parts.append(f"{'#' * b.level} {zh.strip('。 ')}")
            else:
                parts.append(tidy(self.g.translate(b.en)))
        u.zh = "\n\n".join(parts)

    # -- 脚本修正 + 保真检查（不调模型）
    def script_pass(self, u: Unit, rep: Rep, table: str) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
        en = u.en
        u.zh, rep.fixes = apply_fixes(u.zh, en, self.fixes)
        hard, soft = parse_table(table)
        u.zh, rep.terms = replace_google_terms(u.zh, hard, self.g.term)
        return hard, soft

    def fidelity(self, u: Unit, seen: set[str]) -> fc.Result:
        return fc.check_texts(u.en, u.zh, yiku=self.yiku, persons=self.persons, fix=True, seen=seen)

    def actionable(self, i: fc.Issue, en: str) -> bool:
        """单个大写词的「拉丁名」报警多是地名（Patagonia）：既不是斜体、yiku 也不认识的，只记录，不触发思考重跑。"""
        if i.kind != "拉丁名" or " " in i.item:
            return True
        return f"*{i.item}*" in en or bool(self.yiku and self.yiku.knows(i.item))

    def warnings(self, u: Unit, hard: list[tuple[str, str]], soft: list[tuple[str, str]], res: fc.Result) -> list[str]:
        variants: dict[str, set[str]] = {}
        for en, z in hard:
            v = {self.g.term(en.lower())} | {f.wrong for f in self.fixes if f.right in fc.zh_forms(z)}
            variants[en.lower()] = {x for x in v if x and x != z}
        return consistency(u.zh, u.en, hard, soft, variants) + [i.line().split("\n")[0] for i in res.unfixed if self.actionable(i, u.en)]

    # -- LLM 层
    def llm_pass(self, u: Unit, rep: Rep, table: str, hard_zh: list[str], warns: list[str], think: bool) -> None:
        tag = f"gtrans/{self.o.stem}/u{rep.idx}/{'think' if think else 'nothink'}"
        try:
            with thinking(think):
                txt, use = engine_call(ENGINE, SYSTEM.format(domain=self.o.domain), build_user(table, u.en, u.zh, warns),
                                       max_tokens=32000 if think else 16000, tag=tag)
        except le.EngineError as exc:
            rep.note.append(f"LLM{'（思考）' if think else ''}调用失败：{exc}")
            return
        tin, tout = int(use.get("input_tokens") or 0), int(use.get("output_tokens") or 0)
        if think:
            rep.think_in, rep.think_out, rep.thinking_used = rep.think_in + tin, rep.think_out + tout, True
        else:
            rep.tok_in, rep.tok_out = rep.tok_in + tin, rep.tok_out + tout
        edits = parse_edits(txt)
        if not edits and "[" not in txt:
            rep.note.append("LLM 返回里没有 JSON 数组，未采纳任何改动")
        u.zh, ok, bad = apply_edits(u.zh, edits, hard_zh)
        rep.applied += [{**x, "pass": "think" if think else "nothink"} for x in ok]
        rep.rejected += [{**x, "pass": "think" if think else "nothink"} for x in bad]


    # -- LLM 层（rewrite 模式）：整段改写 → 护栏 → 意义核对
    def _tokens(self, rep: Rep, use: dict[str, Any], think: bool) -> None:
        tin, tout = int(use.get("input_tokens") or 0), int(use.get("output_tokens") or 0)
        if think:
            rep.think_in, rep.think_out, rep.thinking_used = rep.think_in + tin, rep.think_out + tout, True
        else:
            rep.tok_in, rep.tok_out = rep.tok_in + tin, rep.tok_out + tout

    def rewrite_pass(self, u: Unit, rep: Rep, table: str, hard_zh: list[str]) -> None:
        extra = [f"{f.term}={f.right}" for f in self.fixes if f.term and any(a.startswith(f"{f.wrong}→{f.right}") for a in rep.fixes)]
        user = f"## 术语表\n{term_lines(table, extra)}\n\n## 英文原文\n{u.en}\n\n## 当前中文译文\n{u.zh}"
        tag = f"gtrans/{self.o.stem}/u{rep.idx}/rewrite"
        try:
            with thinking(False):
                txt, use = engine_call(self.o.rewrite_engine or ENGINE, rewrite_system(), user, max_tokens=16000, tag=tag)
        except le.EngineError as exc:
            rep.rewrite = "failed"
            rep.note.append(f"LLM 改写调用失败：{exc}")
            return
        self._tokens(rep, use, False)
        new = strip_fences(txt)
        why = rewrite_violations(u.zh, new, hard_zh)
        if why:
            rep.rewrite, rep.rewrite_why = "rejected", why
            return
        rep.rewrite, u.zh = "used", new
        remaining = self.meaning_check(u, rep, hard_zh, think=False)
        if remaining and self.o.think_escalate:
            self.meaning_check(u, rep, hard_zh, think=True)

    def meaning_check(self, u: Unit, rep: Rep, hard_zh: list[str], think: bool) -> list[dict[str, Any]]:
        """一次意义核对：采纳 zh_old 恰好出现一次且过护栏的修正，返回未能修复的问题。"""
        tag = f"gtrans/{self.o.stem}/u{rep.idx}/meaning-{'think' if think else 'nothink'}"
        try:
            with thinking(think):
                txt, use = engine_call(ENGINE, MEANING_SYS, f"## 英文原文\n{u.en}\n\n## 中文译文\n{u.zh}",
                                       max_tokens=32000 if think else 16000, tag=tag)
        except le.EngineError as exc:
            rep.mc_status = "failed"
            rep.note.append(f"意义核对{'（思考）' if think else ''}调用失败：{exc}")
            return []
        self._tokens(rep, use, think)
        flags = parse_meaning(txt)
        if flags is None:
            rep.mc_status = "malformed"
            return []
        rep.mc_status = "ok"
        edits = [{"old": f.get("zh_old"), "new": f.get("zh_new"), "type": str(f.get("why", ""))} for f in flags]
        u.zh, ok, bad = apply_edits(u.zh, edits, hard_zh)
        tag2 = "meaning-think" if think else "meaning"
        rep.applied += [{**x, "pass": tag2} for x in ok]
        rep.rejected += [{**x, "pass": tag2} for x in bad]
        rep.mc_found += len(flags)
        rep.mc_fixed += len(ok)
        rep.mc_left = bad
        return bad

    def process(self, u: Unit, idx: int) -> Rep:
        rep = Rep(idx, u.kind, u.page, u.words, chars=sum(len(b.en) for b in u.blocks if b.kind != "marker"))
        self.google_unit(u)
        if u.kind == "heading":
            u.zh, rep.fixes = apply_fixes(u.zh, u.en, self.fixes)
            return rep
        table = yiku_table(u.en, self.o.domain)
        hard, soft = self.script_pass(u, rep, table)
        hard_zh = pg.hard_terms(table)
        seen0 = set(self.seen)
        res = self.fidelity(u, set(seen0))
        u.zh = res.zh
        edits_mode = self.o.llm_mode == "edits"
        if not self.o.no_llm:
            if edits_mode:
                self.llm_pass(u, rep, table, hard_zh, [], think=False)
            else:
                self.rewrite_pass(u, rep, table, hard_zh)
        seen = set(seen0)
        res = self.fidelity(u, seen)
        u.zh = res.zh
        warns = self.warnings(u, hard, soft, res)
        if warns and self.o.think_escalate and not self.o.no_llm and edits_mode:
            self.llm_pass(u, rep, table, hard_zh, warns, think=True)
            seen = set(seen0)
            res = self.fidelity(u, seen)
            u.zh = res.zh
            warns = self.warnings(u, hard, soft, res)
        self.seen = seen
        rep.warns = warns
        rep.fidelity = [i.line().split("\n")[0] for i in res.issues]
        try:
            cd = cite_diff.compare([u.en], [u.zh])
            rep.cites = [f"{r.kind} {r.obj}：{r.verdict}" for r in cd.rows if r.status == "real"]
        except Exception as exc:  # noqa: BLE001 - cite_diff 只是附带报告，出错不影响译文
            rep.note.append(f"cite_diff 出错：{type(exc).__name__}: {exc}")
        return rep


def render_report(src: str, o: Opts, reps: list[Rep], g: Google, bilingual_note: str) -> str:
    tin = sum(r.tok_in + r.think_in for r in reps)
    tout = sum(r.tok_out + r.think_out for r in reps)
    nthink = sum(r.thinking_used for r in reps)
    L = [f"# gtrans 报告：{src}",
         f"领域 {o.domain}；单元 {len(reps)}；Google 请求 {g.requests} 次、{g.chars} 字符、缓存命中 {g.hits}；"
         f"DeepSeek 输入 {tin} / 输出 {tout} token；开思考的单元 {nthink}"
         + ("；未调用 LLM（--no-llm）" if o.no_llm else ""),
         f"标题双语：{bilingual_note}", ""]
    for r in reps:
        L.append(f"## 单元 {r.idx}（{r.kind}，{r.words} 词，Google {r.chars} 字符{'，起始页 p.' + r.page if r.page else ''}）")
        if r.fixes:
            L.append("- 修正表：" + "；".join(r.fixes))
        if r.terms:
            L.append("- yiku 术语替换：" + "；".join(r.terms))
        for tag, items in (("一致性/保真警告", r.warns), ("保真检查（含已修）", r.fidelity), ("cite_diff", r.cites), ("备注", r.note)):
            if items:
                L.append(f"- {tag}：")
                L += [f"  - {x}" for x in items]
        if r.kind in ("body", "caption") and not o.no_llm and o.llm_mode == "rewrite":
            L.append(f"- 改写：{_RW_LABEL.get(r.rewrite, '未执行')}"
                     f"；token 入/出 {r.tok_in}/{r.tok_out}；思考：{'是，入/出 ' + str(r.think_in) + '/' + str(r.think_out) if r.thinking_used else '否'}")
            L += [f"  - 拒绝原因：{x}" for x in r.rewrite_why]
            if r.rewrite == "used":
                L.append(f"- 意义核对：发现 {r.mc_found}，已修 {r.mc_fixed}，未修 {len(r.mc_left)}")
                if r.mc_status == "malformed":
                    L.append("  - 须人工复核：意义核对返回格式错误，已保留改写稿，意义未经核对")
                elif r.mc_status == "failed":
                    L.append("  - 须人工复核：意义核对调用失败，已保留改写稿，意义未经核对")
                for x in r.mc_left:
                    L.append(f"  - 未修：「{x.get('old', '')}」→「{x.get('new', '')}」（{x.get('orig_type', x.get('type', ''))}）：{x.get('reject', '')}")
        elif r.kind in ("body", "caption") and not o.no_llm:
            L.append(f"- LLM：采纳 {len(r.applied)}，拒绝 {len(r.rejected)}；token 入/出 {r.tok_in}/{r.tok_out}；"
                     f"思考：{'是，入/出 ' + str(r.think_in) + '/' + str(r.think_out) if r.thinking_used else '否'}")
            for x in r.rejected:
                L.append(f"  - 拒绝：「{x.get('old', '')}」→「{x.get('new', '')}」：{x.get('reject', '')}")
        L.append("")
    return "\n".join(L)


def dry_run(units: list[Unit], o: Opts, g: Google) -> str:
    reqs = chars = hits = 0
    for u in units:
        for b in u.blocks:
            if b.kind == "marker":
                continue
            txt = heading_text(b) if b.kind == "heading" else b.en
            if g.has(txt):
                hits += 1
            else:
                reqs += len(split_chunks(txt))
                chars += len(txt)
    terms: set[str] = set()
    for u in units:
        if u.kind not in ("body", "caption"):
            continue
        for en, _zh in parse_table(yiku_table(u.en, o.domain))[0]:
            if not g.has(en.lower()):
                terms.add(en.lower())
    llm = [u for u in units if u.kind in ("body", "caption")]
    words = sum(u.words for u in llm)
    est_in = int(words * 3.1 + 900 * len(llm))
    est_out = 150 * len(llm)
    return (f"[dry] 单元 {sum(u.kind != 'marker' for u in units)}（页码标记 {sum(u.kind == 'marker' for u in units)}）；"
            f"Google 新请求约 {reqs} 次 / {chars} 字符（缓存已有 {hits} 段）；术语探测另需约 {len(terms)} 次；"
            f"LLM {0 if o.no_llm else len(llm)} 次{'（rewrite 模式另有同数的意义核对）' if o.llm_mode == 'rewrite' and not o.no_llm else ''}，"
            f"粗估输入 {est_in} / 输出 {est_out} token（不开思考）")


def run(src: Path, out_dir: Path, o: Opts, google: Google | None = None) -> str:
    text = src.read_text(encoding="utf8")
    units = build_units(parse_blocks(text), o.max_words)
    g = google or Google(Cache(o.cache))
    if o.dry:
        msg = dry_run(units, o, g)
        print(msg)
        return msg
    n = g.prefetch([heading_text(b) if b.kind == "heading" else b.en for u in units if u.kind != "marker"
                    for b in u.blocks if b.kind != "marker"])
    if n:
        print(f"[gtrans] Google 并发预取 {n} 块", file=sys.stderr)
    runner = Runner(o, g)
    reps: list[Rep] = []
    for u in units:
        if u.kind == "marker":
            u.zh = u.blocks[0].en
            continue
        reps.append(runner.process(u, len(reps) + 1))
        print(f"[gtrans] 单元 {len(reps)} {u.kind} 完成", file=sys.stderr)
    en_full = "\n\n".join(u.en for u in units)
    zh_full = "\n\n".join(u.zh for u in units)
    al = hb.align(en_full, zh_full)
    note = "无标题" if not al.unaligned_en and not al.proposals else al.mismatch or f"补英文标题 {len(al.proposals)} 个"
    zh_full = al.fixed_text
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "zh.md").write_text(zh_full.rstrip() + "\n", encoding="utf8")
    (out_dir / "report.md").write_text(render_report(src.name, o, reps, g, note), encoding="utf8")
    with open(out_dir / "edits.jsonl", "w", encoding="utf8") as f:
        for r in reps:
            if r.rewrite:
                f.write(json.dumps({"unit": r.idx, "status": f"rewrite_{r.rewrite}", "reject": "；".join(r.rewrite_why)}, ensure_ascii=False) + "\n")
            for x in r.applied:
                f.write(json.dumps({"unit": r.idx, "status": "applied", **x}, ensure_ascii=False) + "\n")
            for x in r.rejected:
                f.write(json.dumps({"unit": r.idx, "status": "rejected", **x}, ensure_ascii=False) + "\n")
    return zh_full


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Google 免费初译 → 脚本修正 → DeepSeek flash 核对润色")
    ap.add_argument("src", help="英文文本文件")
    ap.add_argument("-o", "--out", required=True, help="输出目录（zh.md、report.md、edits.jsonl）")
    ap.add_argument("--domain", default="进化生物学", help="yiku 领域")
    ap.add_argument("--llm-mode", choices=("rewrite", "edits"), default="rewrite",
                    help="rewrite（默认）：整段改写 + 意义核对；edits：旧的 JSON 改动单")
    ap.add_argument("--rewrite-engine", help=f"改写引擎（缺省 {ENGINE}，如 claude-sonnet）；意义核对始终用 {ENGINE}")
    ap.add_argument("--think-escalate", action="store_true", help="仍有警告（rewrite 模式：未修复的意义警告）的单元才开思考再跑一次")
    ap.add_argument("--no-llm", action="store_true", help="只做 Google + 脚本修正")
    ap.add_argument("--dry", action="store_true", help="只列计划，不联网、不调模型")
    ap.add_argument("--max-words", type=int, default=MAX_WORDS, help="每个 LLM 单元的英文词数上限")
    ap.add_argument("--fixes", help="修正表 TSV（缺省 skill/google_fixes.tsv）")
    ap.add_argument("--cache", help=f"Google 缓存 sqlite（缺省 {DEFAULT_CACHE}）")
    a = ap.parse_args(argv)
    src = Path(a.src)
    o = Opts(a.domain, a.think_escalate, a.no_llm, a.dry, a.max_words, a.fixes, a.cache, src.stem,
             llm_mode=a.llm_mode, rewrite_engine=a.rewrite_engine)
    try:
        run(src, Path(a.out), o)
    except GoogleError as exc:
        print(f"[gtrans] {exc}；已缓存的结果保留，稍后重跑即可续做", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
