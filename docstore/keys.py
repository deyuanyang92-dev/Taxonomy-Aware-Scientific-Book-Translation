"""检索表（dichotomous key）偶句重建：只读 OCR 行框，确定性，零 token。

为什么在 docstore：`engines/ppocr.py` 的 `rows_to_text` 把一页行框拼成连续文字，检索表的条目号
「—」「N.」、点线和右栏终点在拼接时丢失（issue #38，也是 #35/#36 的根因）。本模块直接读缓存里的
行框（`[[polygon, text, score], …]` 与页宽），按下面的文法重建偶句，输出 `keys.json`。

文法（实测自 Imajima 2001/2007/2009 三卷；规则与阈值在 `rules/keys.toml`）：
 G1  条目栏    单独成框的「N.」是条目 N；横线是备择条目 N'；并成一框的「N．正文」要拆开。
 G1b 内联型    2009 卷「N'.正文」写在一个框里；重复出现的号是备择条目。
 G2  标题行    「検索…」「Key to…」开一张新表；标题上方的行是上一张表的续页。
 G3  终点      每个条目以且仅以一个终点结束：跳转号、类群名、「类群……学名」或「名称……号」。
 G4  隐含条目  OCR 丢了横线时，终点之后左缘的新行就是新条目（IMPLICIT）。
 G4b 丢终点    上一条短行结束又无终点，按隐含条目处理并标 IMPLICIT_LOST（终点被 OCR 丢了）。
 G5  页码      空条目、或离正文很远的孤立跳转号是页码，不是条目。
 G6  页内校准  文本左缘 Tm = 条目号右侧文本 x0 的众数（无条目号时取全页众数）；右缘 R = x1 的 93 百分位。
 G7  无条目号的页结束该表。该页的行仍先处理再结束：2007 卷 p341 的条目号被 OCR 并进正文框、整页
     没有独立条目号，却是真条目；提前结束会丢 2 个偶句（实测）。代价：这类页上的正文可能漏成隐含条目。
 G8  条目栏内、y 与条目号相近的行仍是条目正文，不是小标题。
 G9  图题或文献起头结束该表。

自洽检查（`check`）：每条有终点；每个 N 有 N'；跳转号指向存在的编号条目。
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

RULES_PATH = Path(__file__).resolve().parent / "rules" / "keys.toml"

Row = dict[str, Any]  # {x0, x1, y0, y1, t}
Lead = dict[str, Any]


class Grammar:
    """rules/keys.toml 编译后的正则与阈值。"""

    def __init__(self, path: Path | None = None) -> None:
        d = tomllib.loads((path or RULES_PATH).read_text(encoding="utf-8"))
        ch, pat = d["chars"], d["patterns"]
        self.dash = set(ch["dash"])

        def sub(s: str) -> str:
            return s.replace("@LD@", ch["leader"]).replace("@PR@", ch["prime"])

        c = {k: re.compile(sub(v)) for k, v in pat.items()}
        self.lead_num, self.lead_merged, self.inline = c["lead_num"], c["lead_merged"], c["inline"]
        self.jump, self.tail_jump, self.name_jump = c["jump"], c["tail_jump"], c["name_jump"]
        self.group_taxon, self.heading, self.caption, self.taxon = (
            c["group_taxon"], c["heading"], c["caption"], c["taxon"])
        self.latin_row = c["latin_row"]
        self.g: dict[str, float] = d["geometry"]
        self.term_fixes = [(re.compile(a), b) for a, b in d.get("fixes", {}).get("terminal", [])]

    def is_dash(self, t: str) -> bool:
        return bool(t) and all(c in self.dash for c in t)

    def fix_term(self, v: str) -> str:
        for rx, rep in self.term_fixes:
            v = rx.sub(rep, v)
        return v.strip()

    def is_marker(self, t: str) -> bool:
        return bool(self.lead_num.match(t)) or self.is_dash(t)


@lru_cache(maxsize=1)
def default_grammar() -> Grammar:
    return Grammar()


def rows_from_raw(raw_rows: Iterable[Any]) -> list[Row]:
    """PP-OCR 缓存的 `[[polygon, text, score], …]` → 行框字典；空文本丢弃。"""
    rows: list[Row] = []
    for poly, text, _score in raw_rows:
        t = str(text).strip()
        if not t:
            continue
        xs = [p[0] for p in poly]
        ys = [p[1] for p in poly]
        rows.append({"x0": min(xs), "x1": max(xs), "y0": min(ys), "y1": max(ys), "t": t})
    return rows


def _mode_margin(xs: list[float], bin_px: float) -> float:
    bins: dict[int, list[float]] = {}
    for x in xs:
        bins.setdefault(int(x // bin_px), []).append(x)
    best = sorted(sorted(bins.values(), key=len)[-1])  # 最大箱；同大小取后者（与原型一致）
    return best[len(best) // 2]


def calibrate(gr: Grammar, width: float, rows: list[Row], min_markers: int = 2) -> tuple[float, float]:
    """G6：返回 (Tm 文本左缘, R 右缘)。优先用条目号自己定位，退回全页众数。
    min_markers：定位所需的独立条目号数；表在进行中的续页只剩一两个条目时可降到 1（2001 p383）。"""
    g = gr.g
    x1s = sorted(r["x1"] for r in rows)
    right = x1s[int(len(x1s) * g["right_edge_pct"])] if x1s else width
    mk = [r for r in rows if r["x1"] - r["x0"] < g["marker_max_width"] * width
          and r["x0"] < g["marker_zone"] * width and gr.is_marker(r["t"])]
    # 条目号右边必有同一行的正文框；页眉页脚的页码（如「244.」）孤零零一个，不算（2007 p341）
    mk = [m for m in mk if any(o is not m and o["x0"] > m["x0"] and o["y0"] < m["y1"] and o["y1"] > m["y0"]
                               for o in rows)]
    merged = [r for r in rows if r["x0"] < g["marker_zone"] * width and gr.lead_merged.match(r["t"])]
    if len(mk) >= min_markers or (len(mk) == 1 and 1 <= len(merged) < g["inline_min_rows"]):  # 一个独立条目号 + 并进正文的条目号，也够定位（2007 p220）
        mx1 = sorted(r["x1"] for r in mk)[len(mk) // 2]
        xs = [r["x0"] for r in rows if len(r["t"]) >= g["min_marker_text"]
              and mx1 - g["marker_overlap"] * width < r["x0"] < mx1 + g["margin_probe"] * width]
        if xs:
            return _mode_margin(xs, g["margin_bin"]), right
    il = [r["x0"] for r in rows if len(r["t"]) >= g["min_row_chars"] and r["x0"] < g["marker_zone"] * width
          and gr.inline.match(r["t"])]
    if len(il) >= g["inline_min_rows"]:  # 内联型页（条目号并进正文框，如 2009 卷偏左的页）：用这些行自己定位
        return _mode_margin(il, g["margin_bin"]), right
    xs = [r["x0"] for r in rows if len(r["t"]) >= g["min_row_chars"] and r["x0"] > g["fallback_x_min"] * width]
    if not xs:
        return g["fallback_margin"] * width, right
    return _mode_margin(xs, g["margin_bin"]), right


class KeyParser:
    """逐页喂入行框，累积条目（lead）。每页一次 `feed_page`，最后 `finish`。"""

    def __init__(self, grammar: Grammar | None = None) -> None:
        self.gr = grammar or default_grammar()
        self.leads: list[Lead] = []
        self.events: list[tuple[int, str, str]] = []
        self.cur: Lead | None = None
        self.n: str | None = None
        self.primes = 0
        self.in_key = False
        self.key_id = 0
        self.marked = False
        # 版面项（按解析顺序）：("couplet", Lead) / ("heading", 文本, 表号) / ("rest", 文本, 原因)
        self.items: dict[int, list[tuple[Any, ...]]] = {}

    # ---- 条目簿记
    def _close(self) -> Lead | None:
        c, self.cur = self.cur, None
        if c is not None and (c["text"].strip() or c["term"]):
            self.leads.append(c)
        return c

    def _start(self, pg: int, kind: str, n: str | None, y1: float) -> None:
        prev = (self.n, self.primes)
        had = self.cur is not None and bool(self.cur["text"].strip() or self.cur["term"])
        self._close()
        reopen = self.leads[-1] if had else None
        if kind == "num":
            self.n, self.primes, lab = n, 0, str(n)
        else:
            self.primes += 1
            lab = f"{self.n or '?'}" + "'" * self.primes
        self.cur = {"page": pg, "key": self.key_id, "lead": lab, "kind": kind, "text": "", "term": [],
                    "ty1": None, "last_y1": y1, "prev": prev, "reopen": reopen, "lx1": None,
                    "ly0": None}
        self.items.setdefault(pg, []).append(("couplet", self.cur))

    def _rest(self, pg: int, text: str, why: str, r: Row | None = None) -> None:
        pos = (round(r["x0"]), round(r["y0"])) if r else (0, 0)
        self.items.setdefault(pg, []).append(("rest", text, why, *pos))

    def _start_inline(self, pg: int, n: str, primes: int, y1: float) -> None:
        """G1b：「N.正文」/「N'.正文」；重复出现的号是备择条目。"""
        if primes == 0 and n != self.n:
            self._start(pg, "num", n, y1)
        else:
            if n != self.n:
                self.n, self.primes = n, 0
            self._start(pg, "dash", None, y1)

    def _reset_key(self) -> None:
        self._close()
        self.n, self.primes = None, 0
        self.in_key = False

    def _pending_jumps(self) -> set[str]:
        """本表已出现的跳转号里，还没作为条目号出现过的（表被插图版打断时用）。"""
        mine = [ld for ld in self.leads if ld["key"] == self.key_id]
        if self.cur is not None:
            mine.append(self.cur)
        have = {ld["lead"] for ld in mine}
        out: set[str] = set()
        for ld in mine:
            for v in ld["term"]:
                m = re.search(r"(\d+)$", v.split("->")[-1].strip())
                if m and "図" not in v and m.group(1) not in have:
                    out.add(m.group(1))
        return out

    def _is_plate(self, width: float, rows: list[Row]) -> bool:
        """整页插图版（有图题、条目栏里没有条目号）且表里还有没到的跳转号：表在这页之后续。"""
        gr, g = self.gr, self.gr.g
        if not any(gr.caption.match(r["t"]) for r in rows) or not self._pending_jumps():
            return False
        return not any(r["x0"] < g["marker_zone"] * width and (gr.lead_num.match(r["t"]) or gr.is_dash(r["t"]))
                       for r in rows)

    def _drop_page_number(self) -> None:
        """G5：上页末尾的空条目其实是页码，恢复状态并重开上一条。"""
        c = self.cur
        if c is not None and not c["text"].strip() and not c["term"]:
            self.n, self.primes = c["prev"]
            self.cur = None
            if c["reopen"] is not None:
                self.leads.remove(c["reopen"])
                self.cur = c["reopen"]

    def _term(self, val: str, y1: float) -> None:
        assert self.cur is not None
        self.cur["term"].append(val)
        self.cur["ty1"] = y1

    # ---- 一页
    def feed_page(self, width: float, rows: list[Row], pg: int) -> None:
        gr, g = self.gr, self.gr.g
        self._drop_page_number()
        hd = [r for r in rows if gr.heading.search(r["t"]) and len(r["t"]) <= g["heading_max_chars"]
              and r["x1"] - r["x0"] < g["heading_max_width"] * width]
        if hd:
            hy = min(r["y0"] for r in hd)
            above = [r for r in rows if r["y0"] < hy - g["heading_slack"] and r not in hd]
            below = [r for r in rows if r["y0"] >= hy - g["heading_slack"] and r not in hd]
            cal = calibrate(gr, width, below)
            if self.cur is not None:  # G2：上方的行续上一张表
                self._rows(width, above, pg, cal)
            self._reset_key()
            self.key_id += 1
            self.in_key = True
            self.events.append((pg, "HEADING", hd[0]["t"]))
            self.items.setdefault(pg, []).append(
                ("heading", " ".join(r["t"] for r in sorted(hd, key=lambda r: r["y0"])), self.key_id))
            self._rows(width, below, pg, cal)
        elif self.in_key:
            if self._is_plate(width, rows):
                for r in rows:
                    self._rest(pg, r["t"], "plate", r)
                self.events.append((pg, "PLATE", f"跳转号 {sorted(self._pending_jumps())[:3]} 还没到，表在下页续"))
                return
            self._rows(width, rows, pg, calibrate(gr, width, rows, min_markers=1))
            if self.in_key and not self.marked:  # G7：先吃完这页再结束该表
                self._reset_key()

    def _is_target(self, r: Row, width: float, cal: tuple[float, float]) -> tuple[str, str] | None:
        gr, g = self.gr, self.gr.g
        tm, right = cal
        if r["x1"] < right - g["right_tol"] * width:
            return None
        far, t = tm + g["target_far"] * (right - tm), r["t"]
        m = gr.jump.match(t)
        if m and r["x0"] >= far:
            return "jump", m.group(1)
        m = gr.name_jump.match(t)
        if m and gr.taxon.search(m.group(1)):
            return "namejump", f"{m.group(1).strip(' .…')} -> {m.group(2)}"
        m = gr.group_taxon.match(t)
        if m and r["x0"] >= tm + g["indent_tol"] * width:
            grp = m.group(1).strip(" .…")
            return "taxon", (grp + " -> " if grp else "") + m.group(2).strip()
        if r["x0"] >= far and gr.taxon.search(t) and len(t) < 70:
            return "taxon", t.strip(". …")
        if r["x0"] >= tm + g["indent_tol"] * width and len(t) < 90 and gr.latin_row.match(t):
            return "taxon", t.strip(". …")
        return None

    def _page_has_target(self, width: float, rows: list[Row], cal: tuple[float, float]) -> bool:
        """本页有没有终点行；页底孤立在右下角的纯数字是页码，不算。"""
        ordered = sorted(rows, key=lambda r: r["y0"])
        gap = self.gr.g["pageno_gap"]
        for i, r in enumerate(ordered):
            tg = self._is_target(r, width, cal)
            if not tg:
                continue
            is_foot = (tg[0] == "jump" and i == len(ordered) - 1
                       and (i == 0 or r["y0"] > ordered[i - 1]["y1"] + gap))
            if not is_foot:
                return True
        return False

    def _scan(self, width: float, rows: list[Row], cal: tuple[float, float]) -> tuple[Any, list[float], bool, bool]:
        """一页的条目号概况：(条目栏判定函数, 条目号 y 列表, 是否内联型, 页上有无条目号)。"""
        gr, g = self.gr, self.gr.g
        tm = cal[0]
        lx0, lx1 = tm - g["lead_left"] * width, tm - g["lead_right"] * width

        def marker(r: Row) -> bool:
            return bool(r["x0"] < lx0 and (r["x1"] < lx1 or gr.lead_merged.match(r["t"])))

        marked = any(marker(r) and (gr.lead_num.match(r["t"]) or gr.lead_merged.match(r["t"])
                                    or gr.is_dash(r["t"])) for r in rows)
        mys = [(r["y0"] + r["y1"]) / 2 for r in rows
               if marker(r) and (gr.lead_num.match(r["t"]) or gr.is_dash(r["t"]))]
        inline = (not mys) and sum(1 for r in rows if r["x0"] < tm + g["inline_tol"] * width
                                   and gr.inline.match(r["t"])) >= 2
        return marker, mys, inline, marked or inline

    @staticmethod
    def _same_line_left_to_right(rows: list[Row], marker: Any) -> list[Row]:
        """同一视觉行上的框按 x0 从左到右排。

        只按行中心 y 排序时，右栏的跳转号（框矮，中心偏下）有时排在左边描述行之前，
        于是号码被并给上一条、描述行再被误判为隐含条目（2007 p218 的 15'/19'/22'/23'/25'）。
        条目号框保持原来的 lead_y_pull 次序，不参与重排。
        """
        out: list[Row] = []
        i = 0
        while i < len(rows):
            first = rows[i]
            if marker(first):
                out.append(first)
                i += 1
                continue
            line = [first]
            mid = (first["y0"] + first["y1"]) / 2
            j = i + 1
            while (j < len(rows) and not marker(rows[j])
                   and first["y0"] < (rows[j]["y0"] + rows[j]["y1"]) / 2 < first["y1"]
                   and rows[j]["y0"] < mid < rows[j]["y1"]):
                line.append(rows[j])
                j += 1
            out.extend(sorted(line, key=lambda r: r["x0"]))
            i = j
        return out

    def _rows(self, width: float, rows: list[Row], pg: int, cal: tuple[float, float]) -> None:  # noqa: C901
        gr, g = self.gr, self.gr.g
        tm, right = cal
        lx0, lx1 = tm - g["lead_left"] * width, tm - g["lead_right"] * width
        marker, mys, inline, self.marked = self._scan(width, rows, cal)
        # 无条目号、也没有一个终点行的页放不下完整偶句：上一条若已有终点，这页是表后的正文（种记述等），
        # 不得再按 G4 开隐含条目（否则整页正文变成一串隐含条目）。
        tail_page = (not self.marked and self.cur is not None and bool(self.cur["term"])
                     and not self._page_has_target(width, rows, cal))
        rows = sorted(rows, key=lambda r: (r["y0"] + r["y1"]) / 2 - (g["lead_y_pull"] if marker(r) else 0))
        rows = self._same_line_left_to_right(rows, marker)
        bottom_y = max((r["y1"] for r in rows), default=0.0)
        for r in rows:
            t = r["t"]
            if inline and r["x0"] < tm + g["inline_tol"] * width:
                m = gr.inline.match(t)
                if m:
                    self._start_inline(pg, m.group(1), len(m.group(2)), r["y1"])
                    r = dict(r, t=m.group(3))
                    t = r["t"]
            if r["x0"] < lx0:
                if r["x1"] < lx1:
                    m = gr.lead_num.match(t)
                    if m:
                        self._start(pg, "num", m.group(1), r["y1"])
                        continue
                    if gr.is_dash(t):
                        self._start(pg, "dash", None, r["y1"])
                        continue
                m = gr.lead_merged.match(t)
                if m:
                    self._start(pg, "num", m.group(1), r["y1"])
                    r = dict(r, t=m.group(2), x0=tm)
                    t = r["t"]
                elif any(abs((r["y0"] + r["y1"]) / 2 - y) < g["lead_y_match"] for y in mys):
                    r = dict(r, x0=tm)  # G8
                    t = r["t"]
                else:  # 条目栏里的非条目行：小标题，结束该表
                    self._reset_key()
                    self.events.append((pg, "SUBHEAD", t))
                    self._rest(pg, t, "subhead", r)
                    continue
            if self.cur is None:
                self._rest(pg, t, "outside", r)
                continue
            if gr.caption.match(t):  # G9
                self._reset_key()
                self.events.append((pg, "ENDKEY", t[:20]))
                self._rest(pg, t, "caption", r)
                continue
            c = self.cur
            if tail_page and c["term"]:
                self._reset_key()
                self.events.append((pg, "NOTKEY", t[:20]))
                self._rest(pg, t, "outside", r)
                continue
            tg = self._is_target(r, width, cal)
            if tg:
                kind, val = tg
                if kind == "jump" and c["page"] == pg and r["y0"] > c["last_y1"] + g["pageno_gap"]:
                    self.events.append((pg, "PAGENO", val))
                    self._rest(pg, val, "pageno", r)
                    continue
                if kind == "jump" and c["term"] and r["y1"] >= bottom_y - 1:
                    # 条目已有终点，页面最底的孤立数字是页码（2009 卷 p168 的「165」曾被当成第二个终点）。
                    self.events.append((pg, "PAGENO", val))
                    self._rest(pg, val, "pageno", r)
                    continue
                self._term(val, r["y1"])
                continue
            if _BARE_NUM.match(t) and r["x0"] < tm + g["indent_tol"] * width:
                # 左缘孤立的纯数字不是描述：多为页码（OCR 偶把「46」认成「46e」）。
                # 不让它开出隐含条目（2009 卷有 10 处「62」「104」「166」…被当成条目正文）。
                self.events.append((pg, "PAGENO", t))
                self._rest(pg, t, "pageno", r)
                continue
            m = gr.tail_jump.match(t) if r["x1"] >= right - g["right_tol"] * width else None
            body, tail = (m.group(1), m.group(2)) if m else (t, None)
            if not m and r["x1"] >= right - g["right_tol"] * width:
                mt = _TAIL_TAXON.match(t)
                if mt:  # 「…鰓はない.Glycera brevicirris Grube（図65)」：终点名并在正文行内
                    body, tail = mt.group(1), mt.group(2).strip()
            if not m and r["x1"] >= right - g["right_tol"] * width:
                m2 = gr.group_taxon.match(t)
                if m2:
                    body, tail = m2.group(1), m2.group(2).strip()
            if (c["term"] and c["ty1"] is not None and (c["page"] != pg or r["y0"] >= c["ty1"] - g["new_lead_gap"])
                    and r["x0"] < tm + g["indent_tol"] * width):  # G4
                self._start(pg, "implicit", None, r["y1"])
                c = self.cur  # type: ignore[assignment]
                self.events.append((pg, "IMPLICIT", c["lead"]))
            if (not c["term"] and c["text"].strip() and c["page"] == pg and c["lx1"] is not None
                    and c["lx1"] < right - g["lost_tol"] * width and r["x0"] < tm + g["indent_tol"] * width
                    and r["y0"] >= c["last_y1"] - g["new_lead_gap"]):  # G4b
                self._start(pg, "implicit", None, r["y1"])
                c = self.cur  # type: ignore[assignment]
                self.events.append((pg, "IMPLICIT_LOST", c["lead"]))
            c["text"] += body
            c["lx1"] = r["x1"]
            c["ly0"] = r["y0"]
            c["last_y1"] = max(c["last_y1"], r["y1"])
            if tail:
                self._term(tail, r["y1"])

    def finish(self) -> list[Lead]:
        self._close()
        return self.leads


def check(leads: list[Lead]) -> list[str]:
    """图规则：N 有 N'；每条有终点；跳转号指向存在的编号条目。"""
    probs: list[str] = []
    nums = {ld["lead"] for ld in leads if "'" not in ld["lead"]}
    have = {ld["lead"] for ld in leads}
    for n in sorted(nums, key=lambda x: (len(x), x)):
        if n + "'" not in have:
            probs.append(f"missing alternate for {n}")
    for ld in leads:
        if not ld["term"]:
            probs.append(f"no terminal: {ld['lead']} p{ld['page']}")
        for v in ld["term"]:
            m = re.search(r"(\d+)$", v.split("->")[-1].strip())
            if m and "図" not in v and m.group(1) not in nums:
                probs.append(f"jump to unknown {m.group(1)} from {ld['lead']} p{ld['page']}")
    return probs


def check_by_key(leads: list[Lead]) -> dict[int, dict[str, Any]]:
    """按表分别检查：{表号: {pages, couplets, problems}}。"""
    out: dict[int, dict[str, Any]] = {}
    for kid in sorted({ld["key"] for ld in leads}):
        ls = [ld for ld in leads if ld["key"] == kid]
        out[kid] = {"first_page": ls[0]["page"], "last_page": ls[-1]["page"], "couplets": len(ls),
                    "problems": check(ls)}
    return out


def check_couplets(couplets: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """对 keys.json 里的 couplets 重做按表检查（人工补完条目后用）。"""
    leads = [{**c, "term": c.get("terminals", [])} for c in couplets]
    return check_by_key(leads)


_NOT_NAME_END = {"sp", "spp", "cf", "aff", "var", "nov", "n"}
_NAME_NUM = re.compile(r"^(.*?[A-Za-z)）])\s*(?:[…‥⋯]+|\s[.．·]+|[.．·]{2,})\s*(\d{1,3})$")
_JA_GROUP = re.compile(r"^([^A-Za-z0-9]*?[\u3040-\u30ff\u4e00-\u9fff][^A-Za-z0-9]*?)\s*([A-Z][a-z].*)$")


def term_struct(gr: Grammar, v: str) -> dict[str, str]:
    """终点字符串 → 版式栏位。kind：jump(号) / name_jump(名称+号) / group_taxon(类群+学名) / taxon(学名)。
    「Eunoe…14」「Syllis . 1」按名称+号拆开（名称末词是 sp./cf. 等时不拆）；
    「シンカイウロコムシ亜科Branchinotogluminae」日文类群名与学名粘连时按类群+学名拆开。"""
    v = gr.fix_term(v)
    if " -> " in v:
        left, right = (x.strip() for x in v.split(" -> ", 1))
        if right.isdigit():
            return {"kind": "name_jump", "name": left, "num": right}
        return {"kind": "group_taxon", "group": left, "taxon": right}
    if v.isdigit():
        return {"kind": "jump", "num": v}
    m = _NAME_NUM.match(v)
    if m and m.group(1).split()[-1].rstrip(".").lower() not in _NOT_NAME_END:
        return {"kind": "name_jump", "name": m.group(1).strip(), "num": m.group(2)}
    m = _JA_GROUP.match(v)
    if m:
        return {"kind": "group_taxon", "group": m.group(1).strip(), "taxon": m.group(2).strip()}
    return {"kind": "taxon", "taxon": v}


# 正文行尾「标点 + 拉丁名 + （図N）」。名称部分不得含中日文，避免吞掉描述。
_TAIL_TAXON = re.compile(
    r"^(.*?[;；.．。，,]\s*)([A-Z][A-Za-z.\-]+(?:\s+[A-Za-z.&\-()]+){0,6}\s*[（(]\s*図\s*\d+\s*[）)])\s*$")
_LEADER_RUN = re.compile(r"\s*[…‥⋯.．·]{2,}\s*")
_DESC_PUNCT = re.compile(r"[，；、。;,]")


def pull_text_from_slots(c: dict[str, Any]) -> bool:
    """条目正文为空（或只有横线）而终点栏位里装着整句描述：把描述移回 text，返回是否改动。

    OCR 偶尔把一整行（描述 + 点线 + 名称/号）并成一个右栏框，于是整句落进终点。
    - name_jump：名称里还有点线 → 最后一段点线之前是描述，之后才是名称；
    - group_taxon：类群部分带标点或过长 → 它其实是描述，终点只剩学名。"""
    if c["text"].strip(" —一-"):
        return False
    for i, s in enumerate(c["slots"]):
        if s["kind"] == "name_jump":
            parts = _LEADER_RUN.split(s["name"])
            if len(parts) >= 2 and parts[-1].strip() and parts[0].strip():
                c["text"] = _LEADER_RUN.sub(" ", " ".join(parts[:-1])).strip()
                s["name"] = parts[-1].strip()
                c["terminals"][i] = f"{s['name']} -> {s['num']}"
                return True
        elif s["kind"] == "group_taxon":
            g = s["group"]
            if _DESC_PUNCT.search(g) or len(g) > 14:
                c["text"] = g
                c["slots"][i] = {"kind": "taxon", "taxon": s["taxon"]}
                c["terminals"][i] = s["taxon"]
                return True
    return False


_BARE_NUM = re.compile(r"^\s*\d{1,4}[a-z]?\s*$")
_LEAD_JUNK = r"[…‥⋯.．·]"
# 描述句末粘着学名 +（図N）：OCR 把点线吞了，学名没有进右栏框。学名须含「図」才拆，避免误伤正文里的拉丁词。
_TAIL_TAXON = re.compile(r"^(.*?[^A-Za-z\s(（])\s*" + _LEAD_JUNK + r"*\s*"
                         r"([A-Z][A-Za-z（）() .\-]*[（(]\s*図[^)）]*[)）])\s*$")
# 「……Perinereis…21」「….Hmipodia …3」：点线 + 名称 + 点线 + 号。
_TAIL_NAME_JUMP = re.compile(r"^(.*?)\s*" + _LEAD_JUNK + r"{2,}\s*([A-Z][a-z]+)\s*" + _LEAD_JUNK +
                             r"+\s*(\d{1,3})$")
# 「…6」「..*11」「ある.17」：末尾点线（可夹 OCR 杂点 *）+ 号。描述须以汉字/假名/中日标点收尾，
# 才认单个句点（「var. 2」「2.5」这类拉丁、小数不拆）。
_TAIL_JUMP = re.compile(r"^(.*?[\u3000-\u9fff\uff00-\uffef])\s*[…‥⋯.．·][*.．·…\s]*(\d{1,3})$")


def recover_tail_target(gr: Grammar, c: dict[str, Any]) -> str | None:
    """条目没有终点栏位、但描述末尾粘着终点：拆回栏位，返回所用规则名（没改返回 None）。"""
    if c["slots"] or not c["text"].strip():
        return None
    t = c["text"].strip()
    for name, rx in (("tail_name_jump", _TAIL_NAME_JUMP), ("tail_taxon", _TAIL_TAXON),
                     ("tail_jump", _TAIL_JUMP)):
        m = rx.match(t)
        if not m or not m.group(1).strip(" —一-…."):
            continue
        head = m.group(1).rstrip(" …‥⋯.．·*")
        term = f"{m.group(2)} -> {m.group(3)}" if name == "tail_name_jump" else m.group(2)
        c["text"] = head
        term = gr.fix_term(term)
        if not term:
            return None
        c["terminals"].append(term)
        c["slots"].append(term_struct(gr, term))
        return name
    return None


def extract(pages: Iterable[tuple[int, float, list[Row]]], grammar: Grammar | None = None) -> dict[str, Any]:
    """pages: (页号, 页宽, 行框) 按页序。返回可直接写 keys.json 的字典。"""
    kp = KeyParser(grammar)
    widths: dict[str, float] = {}
    for pg, width, rows in pages:
        widths[str(pg)] = width
        kp.feed_page(width, rows, pg)
    leads = kp.finish()
    gr = kp.gr
    for ld in leads:  # 固定错字写进终点文本本身（共享同一列表，补读终点仍能被图检查看到）
        ld["term"][:] = [t for t in (gr.fix_term(v) for v in ld["term"]) if t]
    index = {id(ld): i for i, ld in enumerate(leads)}
    couplets = [{"key": ld["key"], "lead": ld["lead"], "kind": ld["kind"], "page": ld["page"],
                 "text": ld["text"], "terminals": ld["term"],
                 **({"geom": {"y0": ld["ly0"], "y1": ld["last_y1"]}} if ld.get("ly0") is not None else {}),
                 "slots": [term_struct(gr, v) for v in ld["term"]]} for ld in leads]
    for c in couplets:
        pull_text_from_slots(c)
        fix = recover_tail_target(gr, c)
        if fix:
            c["fix"] = fix
    # 整页版面：每页按阅读顺序的 {couplet 下标 | heading | rest}；下游据此整页替换检索表页
    layout: dict[str, list[dict[str, Any]]] = {}
    for pg in sorted(kp.items):
        out: list[dict[str, Any]] = []
        for it in kp.items[pg]:
            if it[0] == "couplet":
                if id(it[1]) in index:
                    out.append({"t": "couplet", "i": index[id(it[1])]})
            elif it[0] == "heading":
                out.append({"t": "heading", "text": it[1], "key": it[2]})
            else:
                out.append({"t": "rest", "text": it[1], "why": it[2], "x0": it[3], "y0": it[4]})
        layout[str(pg)] = out
    by_key = check_by_key(leads)
    return {"couplets": couplets,
            "keys": [{"key": k, **v} for k, v in by_key.items()],
            "layout": layout,
            "widths": {k: widths[k] for k in layout},
            "events": [{"page": p, "event": e, "detail": d} for p, e, d in kp.events]}


class FixError(ValueError):
    """keys_fix.json 的某条改动对不上提取结果（页号/条目号不存在、匹配多条、缺依据）。"""


def _match(couplets: list[dict[str, Any]], page: int, lead: str, kind: str | None) -> int:
    hits = [i for i, c in enumerate(couplets)
            if c["page"] == page and c["lead"] == lead and (kind is None or c["kind"] == kind)]
    if len(hits) != 1:
        raise FixError(f"p{page} 条目 {lead}{'/' + kind if kind else ''}：匹配到 {len(hits)} 条，必须恰好 1 条")
    return hits[0]


def _shift_layout(layout: dict[str, list[dict[str, Any]]], start: int, delta: int) -> None:
    for items in layout.values():
        for it in items:
            if it.get("t") == "couplet" and it["i"] >= start:
                it["i"] += delta


def apply_fixes(data: dict[str, Any], fixes: dict[str, Any], grammar: Grammar | None = None) -> dict[str, Any]:
    """按人工核对页面图像后写的 keys_fix.json 改正提取结果；原地修改并返回 data。

    `{"fixes": [{"op": "set", "page": 172, "lead": "11", "terminals": ["Eunice sp.（図5）"], "why": "…"}, …]}`
    - set   改 text / terminals / lead / kind 中给出的字段（给了 terminals 就重算 slots 并清掉 fix）
    - drop  删掉一条（幽灵条目）；
    - add   在 after={page, lead[, kind]} 之后插入 couplet={lead, kind, text, terminals}。
    每条必须写 why（对照了哪页图像、看到什么）。匹配必须恰好一条，否则抛 FixError：提取器改进后旧补丁
    失效时要显式报出，不能静默套错位置。改完重做按表检查并写回 data["keys"]；已应用的记入 data["fixes"]。
    """
    gr = grammar or default_grammar()
    cs: list[dict[str, Any]] = data["couplets"]
    layout: dict[str, list[dict[str, Any]]] = data.setdefault("layout", {})
    applied: list[dict[str, Any]] = []
    for n, fx in enumerate(fixes.get("fixes", []), start=1):
        op = fx.get("op")
        if not str(fx.get("why", "")).strip():
            raise FixError(f"第 {n} 条改动缺 why（依据）")
        if op in ("set", "drop"):
            i = _match(cs, int(fx["page"]), str(fx["lead"]), fx.get("kind"))
        if op == "set":
            c = cs[i]
            for f in ("text", "lead", "kind"):
                if f in fx:
                    c[f] = fx[f]
            if "terminals" in fx:
                c["terminals"] = list(fx["terminals"])
                c["slots"] = [term_struct(gr, v) for v in c["terminals"]]
                c.pop("fix", None)
        elif op == "drop":
            del cs[i]
            for pg, items in layout.items():
                layout[pg] = [it for it in items if not (it.get("t") == "couplet" and it["i"] == i)]
            _shift_layout(layout, i + 1, -1)
        elif op == "add":
            a = fx["after"]
            i = _match(cs, int(a["page"]), str(a["lead"]), a.get("kind"))
            src = fx["couplet"]
            new = {"key": cs[i]["key"], "lead": src["lead"], "kind": src.get("kind", "dash"),
                   "page": int(src.get("page", cs[i]["page"])), "text": src.get("text", ""),
                   "terminals": list(src.get("terminals", []))}
            new["slots"] = [term_struct(gr, v) for v in new["terminals"]]
            cs.insert(i + 1, new)
            _shift_layout(layout, i + 1, 1)
            items = layout.setdefault(str(new["page"]), [])
            pos = next((j + 1 for j, it in enumerate(items) if it.get("t") == "couplet" and it["i"] == i), 0)
            items.insert(pos, {"t": "couplet", "i": i + 1})
        else:
            raise FixError(f"第 {n} 条改动 op={op!r} 不认识（set/drop/add）")
        rec = {k: v for k, v in fx.items() if k != "couplet"}
        if op == "add":
            rec["lead_added"] = fx["couplet"]["lead"]
        applied.append(rec)
    by_key = check_couplets(cs)
    data["keys"] = [{"key": k, **v} for k, v in by_key.items()]
    data["fixes"] = applied
    return data


def read_cache_pages(cache_dir: Path, first: int, last: int) -> tuple[list[tuple[int, float, list[Row]]], list[int]]:
    """读 PP-OCR 行框缓存目录 `pNNNN.json`；返回 (页, 缺页号)。不触发 OCR。"""
    pages: list[tuple[int, float, list[Row]]] = []
    missing: list[int] = []
    for pg in range(first, last + 1):
        f = cache_dir / f"p{pg:04d}.json"
        if not f.exists():
            missing.append(pg)
            continue
        d = json.loads(f.read_text(encoding="utf-8"))
        pages.append((pg, float(d["width"]), rows_from_raw(d["rows"])))
    return pages, missing
