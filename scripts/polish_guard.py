"""中文通读（run_batches --mode polish）的闸口：润色改写前后，事实性记号必须逐一相同。

模型只看中文译文、按 STYLE.md 第 6 节改顺句子，以 JSONL 问题单（type=润色）交回。本模块在问题单写盘之前逐条模拟应用，
对每条改动所在的段落（含改动跨到的相邻段）比较改前改后，下列任一项不同就拒绝该条（记入 rejected_polish.jsonl，不进问题单）：
  引证（作者, 年份：species_format.citation_signature + cite_diff.cites_strict）、所有 4 位年份、图号引用（图 N…）、
  斜体 *…* 里的拉丁名、数字及其单位、〔译注…〕与 [OCR?]、页码标记 <!-- p.N -->（顺序也要一致）、
  该块术语表 HARD 节的中文译名（改前出现几次，改后至少还要有几次）。
另外不许改变换行数（标题、页码标记行、段落结构不动）、不许把 old 改成空串。
区域按段落而不是按 old 本身比较：old 只截到引证或斜体的一半，也会因整段指纹变化被发现。
通过的改动仍要过 apply_issues.py 闸口（type=润色 不属于可丢英文/数字的类型）。

指纹挡不住「意思反了」（否定、谁主张什么、量词、限定语、因果）。所以过了指纹的改动还要过语义核验 semantic_filter：
按块把英文原文和编号的 (old, new) 对一次发给核验模型（默认 deepseek-flash，可与润色模型不同），要求逐条回 JSONL
{"i":n,"verdict":"ok"|"meaning_changed","why":"…"}；只有明确回 "ok" 的才保留，其余（含缺条、乱码、调用失败）一律拒绝（fail closed），
理由写进 rejected_polish.jsonl。
"""
from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Callable
from typing import Any

import cite_diff
import species_format as sf
from direct_mode import PAGE_MARK, _para_spans

TYPE = "润色"
CHECK_ENGINE = "deepseek-flash"
CHECK_SYSTEM = """你是中英译文的语义核验员。给你一段英文原文，和一组润色改动（编号，old=改前中文，new=改后中文）。
润色只许改语序和措辞，不许改意思。逐条判断：new 与 old 是否等义，且与英文原文不矛盾。下列任一项变了，判 meaning_changed：
1. 极性与否定（not / no / never / without；「不是……而是」的方向；肯定变否定或反之）；
2. 谁主张什么（who claims what：谁说、谁认为、谁反对；A 主张 X 变成 A 主张非 X）；
3. 量词与范围（some / most / all / only / many / few；一些、大多数、所有、仅）；
4. 限定语（may / might / seem / appear / probably / usually / often；可能、似乎、通常）；
5. 因果、条件、时间先后、比较的方向。
拿不准一律判 meaning_changed。只输出 JSON 行，每个编号一行，不要其他文字：
{"i": 编号, "verdict": "ok" 或 "meaning_changed", "why": "一句话"}"""
_ITALIC = re.compile(r"(?<!\*)\*(?!\*)([^*\n]+?)(?<!\*)\*(?!\*)")
_NOTE = re.compile(r"〔[^〕]*〕|\[OCR\?\]")
_UNITS = ("mm|cm|µm|μm|um|km|mg|kg|ml|m(?![A-Za-z])|g(?![A-Za-z])|l(?![A-Za-z])|%|‰|°|℃|"
          "毫米|厘米|微米|公里|千米|毫克|千克|毫升|倍|米|克|升|对|条|枚|个|节|根|片|只")
_NUM = re.compile(rf"(\d+(?:\.\d+)?)\s*({_UNITS})?")

Key = tuple[Any, ...]


def signature(text: str) -> Counter[Key]:
    """文本的事实指纹（多重集）；不含页码标记（页码标记要比顺序，见 violations）。"""
    text = PAGE_MARK.sub("", text)
    sig: Counter[Key] = Counter(sf.citation_signature(text))
    for ckey, _pos in cite_diff.cites_strict(text):
        sig[("cite2", *ckey)] += 1
    for fkey, _pos in cite_diff.figs_strict(text):
        sig[("fig2", *fkey)] += 1
    for m in _ITALIC.finditer(text):
        sig[("italic", m.group(1))] += 1
    for m in _NOTE.finditer(text):
        sig[("note", m.group(0))] += 1
    for m in _NUM.finditer(text):
        sig[("num", m.group(1), m.group(2) or "")] += 1
    return sig


def _fmt(c: Counter[Key]) -> str:
    return "、".join(" ".join(str(x) for x in k) + (f"×{n}" if n > 1 else "") for k, n in sorted(c.items(), key=str))


_LABEL = {"cite": "引证", "cite2": "引证", "year": "年份", "fig": "图号", "fig2": "图号",
          "italic": "斜体/拉丁名", "note": "译注/OCR 标记", "num": "数字/单位"}


def hard_terms(table: str) -> list[str]:
    """从 yiku 术语表取 HARD 节的中文译名（第 2 列）。"""
    out: list[str] = []
    on = False
    for ln in table.splitlines():
        if ln.startswith("## "):
            on = ln.startswith("## HARD")
        elif on and ln.startswith("|"):
            cells = [c.strip() for c in ln.strip().strip("|").split("|")]
            if len(cells) >= 2 and cells[1] and cells[0] != "英文" and not set(cells[0]) <= set("-: "):
                out.append(cells[1])
    return out


def violations(before: str, after: str, hard: list[str] | None = None) -> list[str]:
    """改前改后不一致的项（空列表＝通过）。"""
    why: list[str] = []
    a, b = signature(before), signature(after)
    if a != b:
        for kind in sorted({k[0] for k in (a - b) | (b - a)}):
            lost = Counter({k: n for k, n in (a - b).items() if k[0] == kind})
            extra = Counter({k: n for k, n in (b - a).items() if k[0] == kind})
            why.append(f"{_LABEL.get(kind, kind)}被改动：" + (f"丢失 {_fmt(lost)}；" if lost else "")
                       + (f"多出 {_fmt(extra)}；" if extra else ""))
    if PAGE_MARK.findall(before) != PAGE_MARK.findall(after):
        why.append(f"页码标记被改动：{PAGE_MARK.findall(before)} -> {PAGE_MARK.findall(after)}")
    for term in hard or []:
        if after.count(term) < before.count(term):
            why.append(f"HARD 术语「{term}」减少（{before.count(term)} -> {after.count(term)}）")
    return why


def filter_issues(target: str, items: list[dict[str, Any]],
                  hard_for: Callable[[dict[str, Any]], list[str]] | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """按问题单顺序在 target 的副本上逐条模拟应用（apply_issues 也是这个顺序和替换方式），返回 (通过的, 拒绝的)。
    拒绝的条目带 reject 说明。通过的条目 type 一律置为「润色」。hard_for(item)：该条所在块的 HARD 中文译名。"""
    work = target
    ok: list[dict[str, Any]] = []
    bad: list[dict[str, Any]] = []
    for it in items:
        old, new = str(it["old"]), str(it["new"])
        n = work.count(old)
        if n != 1:
            bad.append({**it, "reject": f"old 在（已应用前序改动的）译文中出现 {n} 次"})
            continue
        if not new.strip():
            bad.append({**it, "reject": "new 为空：润色不得删内容"})
            continue
        if old.count("\n") != new.count("\n"):
            bad.append({**it, "reject": "换行数改变：润色不得改段落、标题或页码标记行的结构"})
            continue
        pos = work.index(old)
        hit = [(s, e) for s, e in _para_spans(work) if s < pos + len(old) and e > pos]
        if not hit:
            bad.append({**it, "reject": "old 不在任何段落内"})
            continue
        lo, hi = hit[0][0], hit[-1][1]
        before = work[lo:hi]
        after = work[lo:pos] + new + work[pos + len(old):hi]
        why = violations(before, after, hard_for(it) if hard_for else None)
        if why:
            bad.append({**it, "reject": "；".join(why)})
            continue
        work = work[:pos] + new + work[pos + len(old):]
        ok.append({**it, "type": TYPE})
    return ok, bad


# ---------------------------------------------------------------- 语义核验

def check_user(english: str, pairs: list[tuple[str, str]]) -> str:
    rows = "\n\n".join(f"[{n}]\nold: {o}\nnew: {w}" for n, (o, w) in enumerate(pairs, 1))
    return f"=== 英文原文 ===\n{english.strip()}\n\n=== 待核改动 ===\n{rows}"


def parse_verdicts(text: str, n: int) -> dict[int, tuple[str, str]]:
    """解析核验输出 -> {编号: (verdict, why)}。只认 JSON 行；非 JSON 行、编号越界、缺 verdict 的行忽略。
    同一编号出现多次时，只要有一次不是 ok 就取不是 ok 的那次（宁拒勿放）。"""
    out: dict[int, tuple[str, str]] = {}
    for ln in text.splitlines():
        ln = ln.strip().rstrip(",")
        if not ln.startswith("{"):
            continue
        try:
            d = json.loads(ln)
            i = int(d["i"])
            verdict = str(d["verdict"]).strip().lower()
        except (ValueError, KeyError, TypeError):
            continue
        if not 1 <= i <= n:
            continue
        why = str(d.get("why", "")).strip()
        if i not in out or out[i][0] == "ok":
            out[i] = (verdict, why)
    return out


def semantic_filter(items: list[dict[str, Any]], english_of: Callable[[str], str], engine: str, caller: Callable[..., Any],
                    usage_file: Any = None, tag: str = "") -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """对已过指纹闸口的改动做语义核验，每块一次请求。返回 (通过的, 拒绝的)，拒绝的带 reject 说明。
    只有明确回 "ok" 的通过；缺条、乱码、调用失败、找不到英文原文都拒绝（fail closed）。"""
    ok: list[dict[str, Any]] = []
    bad: list[dict[str, Any]] = []
    by_chunk: dict[str, list[dict[str, Any]]] = {}
    for it in items:
        by_chunk.setdefault(str(it.get("chunk")), []).append(it)
    for cid, group in by_chunk.items():
        try:
            english = english_of(cid)
        except OSError as exc:
            bad += [{**it, "reject": f"语义核验未做：读不到英文原文（{exc}）"} for it in group]
            continue
        pairs = [(str(it["old"]), str(it["new"])) for it in group]
        try:
            text, _usage = caller(engine, CHECK_SYSTEM, check_user(english, pairs), tag=f"{tag}/{cid}/polish-check",
                                  usage_file=usage_file)
        except Exception as exc:  # noqa: BLE001
            bad += [{**it, "reject": f"语义核验调用失败（{engine}）：{exc}"} for it in group]
            continue
        verdicts = parse_verdicts(text, len(group))
        for n, it in enumerate(group, 1):
            verdict, why = verdicts.get(n, ("", ""))
            if verdict == "ok":
                ok.append(it)
            elif not verdict:
                bad.append({**it, "reject": f"语义核验未通过：核验输出缺第 {n} 条或无法解析（{engine}）"})
            else:
                bad.append({**it, "reject": f"语义核验未通过（{engine}）：{verdict}" + (f"：{why}" if why else "")})
    return ok, bad
