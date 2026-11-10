"""把一卷志书的页面文本切成物种记述（treatment）与名称用法（name_usage）。

只用 docstore 的库接口取页：store.pages(key) / store.doc(key)。页文本不改；规范化只作用于写进 taxa.sqlite 的副本。

流程
  1. 每页去页眉（页首若干行内的书名、门纲目、科属名、页码）和图版噪声行；
  2. 标出图注（「图 N」开头的行及其后的字母分项行；只剥离图注本身）；
  3. 找种标题（编号 + 中文名 + 学名 + 命名人年份），与书中清单（金标准）逐号对上；
  4. 记述 = 标题行到下一个种标题或属/亚科/科标题、检索表；内部按小标题分字段；
  5. 学名、命名人年份：同页各 OCR 版本的标题行投票，属名取自属标题，种加词与亚种加词的空格取自异名列表或其他版本。
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Iterable

from .rules import Rules

CJK = r"㐀-鿿\U00020000-\U0002ffff"
_CJK_ONLY = re.compile(rf"^[{CJK}]+$")
_YEAR = re.compile(r"(1[6-9]\d\d|20[0-2]\d)")
_FIG = re.compile(r"[（(]\s*(图[^（()）]*)[）)]?\s*$")
_BINOMIAL = re.compile(r"([A-Z][a-z]+)\s*(\([A-Z][a-z]+\)\s*)?([a-z][a-z\-]+)(?:\s+([a-z][a-z\-]{2,}))?")


# ---------------------------------------------------------------- 页面
@dataclass
class Line:
    page: int
    text: str
    legend: str | None = None   # 所属图号（图注行），None 为正文


def clean_lines(text: str, rules: Rules) -> list[str]:
    """去页眉（只看页首 header_max_lines 行）与噪声行，返回其余行（去首尾空白，空行丢弃）。"""
    lines = [x.strip() for x in (text or "").split("\n")]
    lines = [x for x in lines if x]
    k = 0
    while k < min(rules.header_max_lines, len(lines)) and any(h.match(lines[k]) for h in rules.header):
        k += 1
    return [x for x in lines[k:] if not any(n.match(x) for n in rules.noise)]


def mark_legends(lines: list[Line], rules: Rules) -> None:
    """标出图注行：起始行 +（图号单独成行时）下一行名称 + 分项行。保守：一旦遇到不像图注的行即停止。"""
    i = 0
    while i < len(lines):
        t = lines[i].text
        m = rules.legend_start.match(t)
        if not m:
            i += 1
            continue
        fig = re.match(r"^\s*图\s*(\d{1,3})", t)
        fno = fig.group(1) if fig else "?"
        lines[i].legend = fno
        j = i + 1
        prev = t
        bare = re.fullmatch(r"\s*图\s*\d{1,3}\s*", t) is not None
        while j < len(lines):
            s = lines[j].text
            if lines[j].page != lines[j - 1].page:
                break
            is_leg = False
            if bare and j == i + 1:
                is_leg = True                                  # 「图54」单独一行，下一行是名称
            elif rules.legend_item.match(s) and _looks_item(s):
                is_leg = True
            elif rules.legend_tail.match(s):
                is_leg = True
            elif not prev.rstrip().endswith(("。", ".")):
                if rules.legend_inner.search(s) or (len(s) <= rules.legend_short_tail and s.endswith("。")):
                    is_leg = True
            if not is_leg:
                break
            lines[j].legend = fno
            prev = s
            j += 1
        i = j


def _looks_item(s: str) -> bool:
    """分项行：首字母后紧跟中文（「A.体前部…」「B吻…」），且不是小标题或正文句子。"""
    return not re.match(r"^[A-Z][a-z]", s)


# ---------------------------------------------------------------- 清单（金标准）
def parse_inventory(page_texts: dict[int, str], rules: Rules) -> dict[int, dict]:
    inv: dict[int, dict] = {}
    if not rules.inventory_pages or not rules.inventory_line:
        return inv
    a, b = rules.inventory_pages
    last: int | None = None
    for n in range(a, b + 1):
        for ln in clean_lines(page_texts.get(n, ""), rules):
            m = rules.inventory_line.match(ln)
            if m:
                num = int(m.group("num"))
                zh = re.sub(r"\s", "", m.group("zh"))
                if not _CJK_ONLY.match(zh):
                    last = None
                    continue
                if num not in inv:
                    inv[num] = {"num": num, "zh": zh, "latin": despace(m.group("latin")), "pdf_page": n}
                    last = num
                continue
            if last is not None and inv[last]["latin"].endswith("-") and re.fullmatch(r"[a-z]+", ln):
                inv[last]["latin"] = inv[last]["latin"][:-1] + ln
            last = None
    return inv


# ---------------------------------------------------------------- 工具
def despace(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def join_lines(lines: Iterable[str]) -> str:
    """把版面行接成段：中文与中文直接相接，其余以空格相接；保留行尾连字符。"""
    out = ""
    for s in lines:
        s = s.strip()
        if not s:
            continue
        if not out:
            out = s
        elif re.match(rf"[{CJK}，。；：、（）]", out[-1]) or re.match(rf"[{CJK}，。；：、（）]", s[0]) or out.endswith("-"):
            out += s
        else:
            out += " " + s
    return out


RANGE = re.compile(r"(?<=\d)\s*(?:--|一|－|-|~|～|–)\s*(?=\d)|(?<=\d[a-z])\s*(?:--|一|－|-|–)\s*(?=[a-z]\b)")


def normalize(text: str, rules: Rules) -> tuple[str, Counter]:
    c: Counter = Counter()
    if rules.range_dash and text:
        text, n = RANGE.subn("—", text)
        if n:
            c["范围号→—"] += n
    return text, c


def fmt_author(raw: str) -> str:
    """命名人年份：只恢复 OCR 丢掉的空格与标点形状，不改拼写。"""
    s = (raw or "").strip().replace("（", "(").replace("）", ")").replace("，", ",").replace("．", ".")
    s = re.sub(r"(?<=[a-z])\s*et\s*(?=[A-Z])", " et ", s)
    s = re.sub(r"(?<=[A-Za-z.)])\s*[.,]?\s*(?=(1[6-9]\d\d|20[0-2]\d)\b)", ", ", s)
    s = re.sub(r"[,.]\s*,", ",", s)
    s = re.sub(r"\s*,\s*", ", ", s)
    s = re.sub(r"sp\s*\.?\s*nov\s*\.?", "sp. nov.", s)
    s = re.sub(r"\(\s+", "(", s)
    s = re.sub(r"\s+\)", ")", s)
    s = re.sub(r"\s+", " ", s).strip(" ,;")
    if s.count("(") > s.count(")"):
        s += ")"
    return s


# ---------------------------------------------------------------- 标题行
def match_title(text: str, rules: Rules) -> dict | None:
    m = rules.species.match(text)
    if not m:
        return None
    zh = re.sub(r"\s", "", m.group("zh"))
    tag = ""
    if rules.zh_suffix and (sm := rules.zh_suffix.search(zh)):
        tag, zh = sm.group(1), zh[:sm.start()]
    if not _CJK_ONLY.match(zh):
        return None
    return {"num": int(m.group("num")), "zh": zh, "rest": m.group("rest").strip(), "tag": tag}


# ---------------------------------------------------------------- 版本合并
def merge_text(primary: str, other: str, rules: Rules) -> tuple[str, int]:
    """以主版本为底，补回另一版本有而主版本漏识的短串（≤ merge_max_insert 字），及主版本整行漏掉的种标题行。

    两版本不同字（替换）一律保留主版本。返回 (合并文本, 补入处数)。
    """
    a = clean_lines(primary, rules)
    b = clean_lines(other, rules)
    out: list[str] = []
    n = 0
    sm = SequenceMatcher(None, a, b, autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal" or op == "delete":
            out += a[i1:i2]
        elif op == "insert":
            for ln in b[j1:j2]:
                if match_title(ln, rules):
                    out.append(ln)
                    n += 1
        else:  # replace：逐行配对后做字符级补入
            aa, bb = a[i1:i2], b[j1:j2]
            used = set()
            for ii, x in enumerate(aa):
                best, bj = 0.0, -1
                c = round(ii * len(bb) / max(len(aa), 1))
                for j in range(max(0, c - 3), min(len(bb), c + 4)):
                    y = bb[j]
                    if j in used:
                        continue
                    sm2 = SequenceMatcher(None, x, y, autojunk=False)
                    if sm2.real_quick_ratio() < 0.6 or sm2.quick_ratio() < 0.6:
                        continue
                    r = sm2.ratio()
                    if r > best:
                        best, bj = r, j
                if best >= 0.6:
                    used.add(bj)
                    y = bb[bj]
                    # bb 中位于 bj 之前、未配对的种标题行（主版本漏识）
                    for j in range(bj):
                        if j not in used and match_title(bb[j], rules):
                            used.add(j)
                            out.append(bb[j])
                            n += 1
                    merged, k = _merge_line(x, y, rules.merge_max_insert)
                    out.append(merged)
                    n += k
                else:
                    out.append(x)
            for j, y in enumerate(bb):
                if j not in used and match_title(y, rules):
                    out.append(y)
                    n += 1
    return "\n".join(out), n


def _merge_line(x: str, y: str, max_ins: int) -> tuple[str, int]:
    res, n = [], 0
    for op, i1, i2, j1, j2 in SequenceMatcher(None, x, y, autojunk=False).get_opcodes():
        if op == "insert" and (j2 - j1) <= max_ins and not y[j1:j2].isspace():
            res.append(y[j1:j2])
            n += 1
        elif op != "insert":
            res.append(x[i1:i2])
    return "".join(res), n


def title_text(lines: list[Line], i: int, rules: Rules) -> tuple[str, int]:
    """标题行可能折行：括号未闭合或以逗号/连字符结尾时并入下一行。返回 (全文, 占用行数)。"""
    t = lines[i].text
    used = 1
    while used <= rules.max_wrap_lines and i + used < len(lines):
        opened = t.count("（") + t.count("(") - t.count("）") - t.count(")")
        if opened <= 0 and not re.search(r"[,，\-]\s*$|\bet\s*$", t):
            break
        nxt = lines[i + used]
        if nxt.legend or match_title(nxt.text, rules):
            break
        if opened > 0 and not re.search(r"[,，\-]\s*$|\bet\s*$", t) and not re.match(r"[图\d,，、）)]", nxt.text):
            break
        t = t + ("" if re.search(r"[\-（(]$", t) else " ") + nxt.text
        used += 1
    return t, used


def split_rest(rest: str, genera: list[str], prefer: str = "") -> dict:
    """「CeratonereismirabilisKinberg，1866（图53，图54)」→ 属、亚属、加词串、命名人年份原文、图号。"""
    figs = ""
    fm = re.search(r"[（(]\s*(图[^（()）]*)[）)]?", rest)
    if fm:
        figs = fm.group(1).strip()
        rest = rest[:fm.start()].strip()
    s = rest
    genus = ""
    ds = despace(s)
    for g in ([prefer] if prefer else []) + sorted(genera, key=len, reverse=True):
        if ds.startswith(g) and re.match(r"[a-z(（]", ds[len(g):len(g) + 1] or "a"):
            genus = g
            break
    if not genus:
        m = re.match(r"([A-Z][a-z]+)\s", s)
        genus = m.group(1) if m else ""
    if not genus:
        m = re.match(r"([A-Z][a-z]+)", s)
        genus = m.group(1) if m else ""
    # 去掉属名后的剩余（在原串上按字符推进，跳过空格）
    k, gi = 0, 0
    while k < len(s) and gi < len(genus):
        if s[k].isspace():
            k += 1
            continue
        k += 1
        gi += 1
    tail = s[k:].lstrip()
    subgenus = ""
    sm = re.match(r"[（(]\s*([A-Z][a-z]+)\s*[)）]\s*", tail)
    if sm:
        subgenus, tail = sm.group(1), tail[sm.end():]
    qual = ""
    qm = re.match(r"(cf|aff)\s*\.\s*", tail)
    if qm:
        qual, tail = qm.group(1) + ".", tail[qm.end():]
    em = re.match(r"([a-z][a-z\-\s]*?)(?=\s*[A-Z(（]|\s*$)", tail)
    run = despace(em.group(1)) if em else ""
    author = tail[em.end():].strip() if em else tail
    # 命名人年份到年份（或 sp. nov.）为止，其后不属于标题
    am = re.match(r"(.*?(?:1[6-9]\d\d|20[0-2]\d)[a-z]?\s*[)）]?)", author)
    nm = re.match(r"(.*?sp\s*\.?\s*nov\s*\.?)", author)
    if nm and (not am or len(nm.group(1)) < len(am.group(1))):
        author = nm.group(1)
    elif am:
        author = am.group(1)
    return {"genus": genus, "subgenus": subgenus, "qual": qual, "run": run, "author_raw": author, "figures": figs}


def epithet_split(run: str, genus: str, sources: Iterable[str]) -> tuple[list[str], str]:
    """给无空格的加词串找空格位置：在异名列表、其他版本标题里找同属同串的写法，按出现次数取多数。"""
    if not run:
        return [], "无加词"
    votes: Counter = Counter()
    for src in sources:
        for m in _BINOMIAL.finditer(src or ""):
            if m.group(1) != genus and not genus.startswith(m.group(1)[:4]):
                continue
            ep, sub = m.group(3), m.group(4)
            if sub and despace(ep + sub) == run:
                votes[(ep, sub)] += 1
            elif ep == run:
                votes[(ep,)] += 1
    if not votes:
        return [run], ("加词无旁证" if len(run) > 13 else "")
    best = max(votes.items(), key=lambda kv: (kv[1], -len(kv[0])))[0]
    return list(best), ""


# ---------------------------------------------------------------- 主流程
@dataclass
class Treatment:
    num: int
    start: int                      # 标题行在 lines 中的下标
    end: int = 0                    # 不含
    zh: str = ""
    title: str = ""
    title_used: int = 1
    family: str = ""
    subfamily: str = ""
    genus_ctx: str = ""
    flags: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)


def build_lines(pages: list[dict], rules: Rules) -> list[Line]:
    a, b = rules.body_pages
    out: list[Line] = []
    for p in pages:
        if a <= p["page"] <= b:
            out += [Line(p["page"], t) for t in page_lines(p, rules)[0]]
    mark_legends(out, rules)
    _merge_standalone_numbers(out)
    return out


_BARE_NUM = re.compile(r"^\s*[（(]\s*\d{1,3}\s*[)）]\s*$")


def _merge_standalone_numbers(lines: list[Line]) -> None:
    """编号独立成行的标题（如「(114)」+ 下一行标题）合并为一行，便于 match_title 直接识别。"""
    i = 0
    while i < len(lines) - 1:
        if _BARE_NUM.match(lines[i].text) and not lines[i].legend:
            nxt = lines[i + 1]
            if not nxt.legend and nxt.page == lines[i].page and not _BARE_NUM.match(nxt.text):
                lines[i].text = f"{lines[i].text.strip()} {nxt.text}"
                del lines[i + 1]
        i += 1


def _other_version(p: dict) -> dict | None:
    """主版本之外、文本不同的第一个版本（低 dpi 优先作补充）。"""
    for v in p.get("alternates") or []:
        if (v.get("text") or "").strip() and v.get("text") != p.get("text"):
            return v
    return None


def page_lines(p: dict, rules: Rules) -> tuple[list[str], int]:
    """去页眉后的页面行（只读）：开启 [merge] 时为主版本 + 另一版本补入后的行。返回 (行, 补入处数)。"""
    t = p.get("text") or ""
    o = _other_version(p) if rules.merge else None
    if not o:
        return clean_lines(t, rules), 0
    merged, n = merge_text(t, o.get("text") or "", rules)
    return merged.split("\n") if merged else [], n


def find_titles(lines: list[Line], inv: dict[int, dict], rules: Rules) -> tuple[list[Treatment], list[str]]:
    report: list[str] = []
    cands = []
    for i, ln in enumerate(lines):
        if ln.legend:
            continue
        m = match_title(ln.text, rules)
        if m:
            cands.append((i, m))
    chosen: dict[int, tuple[int, dict, float]] = {}
    last = 0
    for i, m in cands:
        num = m["num"]
        if inv:
            def sim(k: int) -> float:
                assert m is not None
                e = inv.get(k)
                if not e:
                    return 0.0
                lat = despace(m["rest"]).lower()[:len(e["latin"])]
                return max(ratio(m["zh"], e["zh"]), ratio(lat, e["latin"].lower()))
            s = sim(num)
            if num not in inv and last < num <= last + 2:
                s = 0.5                                        # 清单本身漏识这一号：按编号连续接受
                report.append(f"({num}) 清单表未识出此号，按编号连续接受 p{lines[i].page}「{lines[i].text[:30]}」")
            elif s < 0.5:
                alt = last + 1
                if sim(alt) >= 0.6:
                    report.append(f"标题编号 OCR 误识：p{lines[i].page}「{lines[i].text[:30]}」按清单作 ({alt})")
                    num, s = alt, sim(alt)
                else:
                    continue
        else:
            s = 1.0
            if num <= last:
                continue
        if num in chosen and chosen[num][2] >= s:
            continue
        chosen[num] = (i, m, s)
        last = max(last, num)
    # 清单里有、编号行没找到的：在前后两个标题之间按中文名找
    if inv:
        for k in sorted(inv):
            if k in chosen:
                continue
            lo = max((chosen[j][0] for j in chosen if j < k), default=0)
            hi = min((chosen[j][0] for j in chosen if j > k), default=len(lines))
            e = inv[k]
            best = None
            for i in range(lo + 1, hi):
                if lines[i].legend:
                    continue
                tx = re.sub(rf"^[^{CJK}]{{0,6}}", "", lines[i].text)
                head = re.match(rf"([{CJK}]{{1,20}}?)\s*([A-Z].*)$", tx)
                if not head:
                    continue
                r = ratio(head.group(1), e["zh"])
                if r >= 0.75 and (best is None or r > best[2]):
                    best = (i, {"num": k, "zh": head.group(1), "rest": head.group(2)}, r)
            if best:
                chosen[k] = best
                report.append(f"({k}) 编号行未识别，按中文名在 p{lines[best[0]].page} 找到：「{lines[best[0]].text[:30]}」")
                continue
            # 标题行整行漏识（各版本都没有）：以异名列表首行（学名开头）为起点，中文名取自图注或清单
            for i in range(lo + 1, hi):
                ln = lines[i]
                if ln.legend or not re.match(r"[A-Z][a-z]{3,}\s*[a-z]", ln.text):
                    continue
                lat = despace(re.split(r"[,，.:：;；]|\d", ln.text)[0])
                g = lat.lower()[:len(e["latin"])]
                if ratio(g, e["latin"].lower()) >= 0.8:
                    zh = e["zh"]
                    src = "清单"
                    for x in lines[lo + 1:hi]:
                        mm = re.search(rf"([{CJK}]{{2,12}})\s*" + re.escape(lat[:len(e["latin"])][:12]), despace(x.text))
                        if mm and ratio(mm.group(1)[-len(e["zh"]):], e["zh"]) >= 0.6:
                            zh, src = mm.group(1)[-len(e["zh"]):], "图注或正文"
                            break
                    chosen[k] = (i, {"num": k, "zh": zh, "rest": ln.text, "synth": True, "zh_src": src}, 0.5)
                    report.append(f"({k}) 标题行各版本均未识出，以 p{ln.page} 异名首行为起点，中文名取自{src}：{zh}（须看原页）")
                    break
    ts = []
    for num in sorted(chosen):
        i, m, _ = chosen[num]
        t = Treatment(num=num, start=i, zh=m["zh"])
        if m.get("synth"):
            t.flags.append(f"标题行 OCR 缺失：学名、命名人取自异名首行，中文名取自{m.get('zh_src')}")
            t.data["synth"] = True
        if m.get("tag"):
            t.data["tag"] = m["tag"]
        ts.append(t)
    ts.sort(key=lambda t: t.start)
    order = [t.num for t in ts]
    if order != sorted(order):
        report.append(f"标题顺序与编号不一致：{order}")
    return ts, report


def split_volume(pages: list[dict], rules: Rules, *, key: str = "") -> dict:
    """返回 {'treatments': [...], 'inventory': {...}, 'report': [...]}。pages 为 store.pages(key) 的结果列表。"""
    by_n = {p["page"]: p for p in pages}
    page_texts = {n: (p.get("text") or "") for n, p in by_n.items()}
    inv = parse_inventory(page_texts, rules)
    lines = build_lines(pages, rules)
    genera: list[str] = []
    if rules.genus:
        for ln in lines:
            gm = rules.genus.match(ln.text)
            if gm and gm.group("latin") not in genera:
                genera.append(gm.group("latin"))
    ts, report = find_titles(lines, inv, rules)
    starts = {t.start for t in ts}
    # 上下文（科、亚科、属）与终止行
    fam = sub = gen = ""
    ctx_at: dict[int, tuple[str, str, str]] = {}
    stops: list[int] = []
    for i, ln in enumerate(lines):
        if ln.legend:
            continue
        if rules.family and (m := rules.family.match(ln.text)):
            fam, sub, gen = m.group("latin"), "", ""
        if rules.subfamily and (m := rules.subfamily.match(ln.text)):
            sub, gen = m.group("latin"), ""
        if rules.genus and (m := rules.genus.match(ln.text)):
            gen = m.group("latin")
        if any(s.match(ln.text) for s in rules.stop):
            stops.append(i)
        if i in starts:
            ctx_at[i] = (fam, sub, gen)
    out = []
    for k, t in enumerate(ts):
        nxt = ts[k + 1].start if k + 1 < len(ts) else len(lines)
        end = min([s for s in stops if t.start < s < nxt] + [nxt])
        t.end = end
        t.family, t.subfamily, t.genus_ctx = ctx_at.get(t.start, ("", "", ""))
        out.append(_build(t, lines, by_n, inv, genera, rules, key))
    found = len(out)
    if rules.expected_species is not None and found != rules.expected_species:
        report.append(f"种数不符：书中 {rules.expected_species}，切分 {found}")
    if inv:
        miss = sorted(set(inv) - {t["num"] for t in out})
        extra = sorted({t["num"] for t in out} - set(inv))
        if miss:
            report.append("清单有、切分无：" + "；".join(f"({k}){inv[k]['zh']}" for k in miss))
        if extra:
            report.append(f"切分有、清单无：{extra}")
    return {"treatments": out, "inventory": inv, "report": report, "genera": genera}


def _alt_titles(page: dict, num: int, zh: str, rules: Rules) -> list[tuple[str, str]]:
    """同页其他 OCR 版本里同一编号的标题行。返回 [(版本说明, 标题全文)]。"""
    res = []
    for v in page.get("alternates") or []:
        ls = [Line(page["page"], x) for x in clean_lines(v.get("text") or "", rules)]
        best = None
        for i, ln in enumerate(ls):
            m = match_title(ln.text, rules)
            if not m:
                continue
            sc = (m["num"] == num) + ratio(m["zh"], zh)
            if sc >= 1.5 and (best is None or sc > best[0]):
                best = (sc, title_text(ls, i, rules)[0])
        if best:
            res.append((f"{v.get('engine', '')}|{v.get('producer', '')}", best[1]))
    return res


def _sections(body: list[Line], rules: Rules) -> tuple[list[str], dict[str, list[str]], list[str]]:
    """返回 (异名列表行, {字段: 行}, 调整说明)。body 不含标题行与图注行。

    OCR 有时把行首粗体小标题识在其内容行之后（「为热带种。分布于…」「地理分布」）：
    独占一行的小标题后面紧接下一个小标题或记述结束时，把上一字段末尾那一段（从上一个句末标点之后起）移给它。
    """
    syn: list[str] = []
    parts: dict[str, list[str]] = {f: [] for f in rules.fields}
    notes: list[str] = []
    cur: str | None = None
    prev = ""
    events: list[tuple[str, bool]] = []          # (字段, 是否独占一行)
    for ln in body:
        s = ln.text
        hit = None
        for name, fld in list(rules.section_names.items()) + list(rules.section_fuzzy.items()):
            if s == name or (s.startswith(name) and len(s) <= len(fld) + 1):
                hit = (fld, "")
                break
            if s.startswith(name) and (not prev or prev[-1] in rules.sentence_end or cur is None):
                cut = len(fld) if fld.startswith(name) else len(name)
                hit = (fld, s[cut:].lstrip("：: "))
                break
        if hit:
            if cur is not None and events and events[-1][1] and not parts[cur]:
                _pull_back(parts, events, cur, notes)
            cur = hit[0]
            events.append((cur, not hit[1]))
            if hit[1]:
                parts[cur].append(hit[1])
        elif cur is None:
            syn.append(s)
        else:
            parts[cur].append(s)
        prev = s
    if cur is not None and events and events[-1][1] and not parts[cur]:
        _pull_back(parts, events, cur, notes)
    return syn, parts, notes


def _pull_back(parts: dict[str, list[str]], events: list[tuple[str, bool]], cur: str, notes: list[str]) -> None:
    if len(events) < 2:
        return
    before = events[-2][0]
    src = parts.get(before) or []
    if len(src) < 2:
        return
    k = len(src) - 1
    while k > 1 and not src[k - 1].endswith(("。", ".")):
        k -= 1
    if not src[k - 1].endswith(("。", ".")):
        return
    moved = src[k:]
    parts[before] = src[:k]
    parts[cur] = moved
    notes.append(f"OCR 把小标题「{cur}」识在内容之后，已把 {len(moved)} 行从「{before}」移回")


def _build(t: Treatment, lines: list[Line], by_n: dict[int, dict], inv: dict, genera: list[str],
           rules: Rules, key: str) -> dict:
    synth = bool(t.data.get("synth"))
    if synth:
        src = lines[t.start].text
        first = re.split(r"\s*[:：;；]", src)[0]
        title, used = f"({t.num}) {t.zh} {first}", 0
    else:
        title, used = title_text(lines, t.start, rules)
    seg = lines[t.start + used:t.end]
    body = [ln for ln in seg if not ln.legend]
    legends = [ln for ln in seg if ln.legend]
    syn, parts, sec_notes = _sections(body, rules)
    flags: list[str] = list(sec_notes)
    # 学名与命名人：本版本 + 同页其他版本投票
    m = match_title(title if synth else lines[t.start].text, rules)
    rest0 = title[title.find(m["rest"][:6]):] if m and m["rest"][:6] in title else (m["rest"] if m else title)
    page = by_n[lines[t.start].page]
    versions = [("primary", rest0)]
    for tag, tt in ([] if synth else _alt_titles(page, t.num, t.zh, rules)):
        mm = match_title(tt, rules)
        if mm:
            versions.append((tag, tt[tt.find(mm["rest"][:6]):] if mm["rest"][:6] in tt else mm["rest"]))
    seen: set[str] = set()

    def _novel(v: tuple[str, str]) -> bool:
        d = despace(v[1])
        if d in seen:
            return False
        seen.add(d)
        return True

    versions = [v for v in versions if _novel(v)]
    parsed = [(tag, split_rest(r, genera, t.genus_ctx)) for tag, r in versions]
    gen_genus = t.genus_ctx
    flags += t.flags
    name_votes = Counter(p["genus"] + "|" + p["run"] for _, p in parsed if p["genus"] and p["run"])
    auth_votes = Counter(despace(fmt_author(p["author_raw"])) for _, p in parsed if p["author_raw"])
    best_name = _vote(name_votes, parsed[0][1]["genus"] + "|" + parsed[0][1]["run"])
    genus, run = best_name.split("|", 1)
    if gen_genus and genus != gen_genus and genus not in genera and ratio(genus, gen_genus) >= 0.75:
        flags.append(f"属名 OCR「{genus}」按所在属标题作 {gen_genus}")
        genus = gen_genus
    if len(name_votes) > 1:
        flags.append("各版本学名不一：" + "；".join(f"{k}×{v}" for k, v in name_votes.items()))
    if gen_genus and genus != gen_genus and (t.subfamily or t.family):
        flags.append(f"学名属名 {genus} 与所在属标题 {gen_genus} 不同")
    best_auth_ds = _vote(auth_votes, despace(fmt_author(parsed[0][1]["author_raw"])))
    author = next((fmt_author(p["author_raw"]) for _, p in parsed if despace(fmt_author(p["author_raw"])) == best_auth_ds), "")
    if len(auth_votes) > 1:
        flags.append("各版本命名人不一：" + "；".join(f"{k}×{v}" for k, v in auth_votes.items()))
    subgenus = next((p["subgenus"] for _, p in parsed if p["subgenus"]), "")
    figs = next((p["figures"] for _, p in parsed if p["figures"]), "")
    eps, why = epithet_split(run, genus, syn + [v for _, v in versions])
    if why:
        flags.append(why)
    qual = next((p["qual"] for _, p in parsed if p.get("qual")), "")
    taxon = " ".join([genus] + ([f"({subgenus})"] if subgenus else []) + ([qual] if qual else []) + eps)
    rank = "亚种" if len(eps) >= 2 else "种"
    if not _YEAR.search(author or ""):
        flags.append("命名人年份缺年份")
    if inv.get(t.num) and ratio(despace(taxon).lower(), inv[t.num]["latin"].lower()) < 0.8:
        flags.append(f"学名与清单（表）差异大：清单 {inv[t.num]['latin']}")
    zh = t.zh
    if inv.get(t.num) and inv[t.num]["zh"] != zh:
        flags.append(f"中文名与清单不一：清单 {inv[t.num]['zh']}")
    # 字段
    notes: Counter = Counter()

    def norm(s: str) -> str:
        r, c = normalize(s, rules)
        notes.update(c)
        return r

    fields = {f: norm(join_lines(v)) for f, v in parts.items()}
    for f in rules.required:
        if not fields.get(f):
            flags.append(f"缺小标题：{f}")
    synonymy = norm("\n".join(syn))
    full = norm("\n".join([title] + [ln.text for ln in body]))
    p0 = lines[t.start].page
    p1 = body[-1].page if body else p0
    off = rules.page_offset
    pages = f"{p0 + off}" + (f"–{p1 + off}" if p1 > p0 else "") + f" (PDF {p0}" + (f"–{p1}" if p1 > p0 else "") + ")"
    engines = Counter(by_n[n].get("engine", "") for n in range(p0, p1 + 1) if n in by_n)
    origin = "；".join(f"{e} ×{c}页" for e, c in engines.items())
    return {
        "num": t.num, "rank": rank, "taxon": taxon, "name_as_printed": f"{taxon} {author}".strip(),
        "author_year": author, "zh_name": zh, "family": t.family, "subfamily": t.subfamily, "genus": genus,
        "pdf_page_start": p0, "pdf_page_end": p1, "pages": pages, "figures": figs, "title_line": title,
        "synonymy": synonymy, **{f: fields.get(f, "") for f in rules.fields},
        "figure_legend": "\n".join(ln.text for ln in legends), "original_text": full,
        "language": "zh", "text_origin": origin,
        "text_note": "；".join(f"{k} {v} 处" for k, v in notes.items()),
        "flags": flags, "synonymy_lines": syn, "versions": versions,
    }


def _vote(c: Counter, default: str) -> str:
    if not c:
        return default
    top = max(c.values())
    winners = [k for k, v in c.items() if v == top]
    return default if default in winners else winners[0]


def usages(t: dict) -> list[dict]:
    """标题行 → 有效名用法；异名列表中以学名开头的行 → 引用或他名（原样拼写，不订正）。"""
    out = [{"taxon": t["taxon"], "name_as_printed": t["taxon"], "author_year": t["author_year"], "zh_name": t["zh_name"],
            "usage_type": "有效名（本书采用）", "pdf_page": t["pdf_page_start"], "raw": t["title_line"]}]
    for ln in t.get("synonymy_lines", []):
        m = re.match(r"^([A-Z][a-z]+)\s*(\([A-Z][a-z]+\)\s*)?([a-z][a-z\-]+)(\s+[a-z][a-z\-]{2,})?\s*(.*)$", ln)
        if not m or m.group(1) in ("Type", "Fig", "Figs", "Pl"):
            continue
        name = " ".join(x.strip() for x in (m.group(1), m.group(2) or "", m.group(3), m.group(4) or "") if x and x.strip())
        same = despace(name).lower() == despace(t["taxon"]).lower()
        auth = re.match(r"([^:：;；]*?\d{4}[a-z]?)", m.group(5) or "")
        out.append({"taxon": t["taxon"], "name_as_printed": name, "author_year": fmt_author(auth.group(1)) if auth else "",
                    "zh_name": "", "usage_type": "引用（同名）" if same else "异名或他名（原样）",
                    "pdf_page": t["pdf_page_start"], "raw": ln})
    return out
