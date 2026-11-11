"""OCR consensus by line and char voting."""

from __future__ import annotations

import difflib
from dataclasses import dataclass


@dataclass
class Reading:
    source: str
    text: str
    conf: float


def _weight(r: Reading) -> float:
    priors = {
        "rapidocr": 1.0,
        "rapid": 1.0,
        "tesseract": 0.1,
        "tess": 0.1,
    }
    return float(r.conf) * priors.get((r.source or "").lower(), 1.0)


def _map_lines(base: list[str], other: list[str]) -> dict[int, list[str]]:
    out: dict[int, list[str]] = {i: [] for i in range(len(base))}
    sm = difflib.SequenceMatcher(a=base, b=other)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for i, j in zip(range(i1, i2), range(j1, j2)):
                out[i].append(other[j])
        elif tag == "replace":
            span_a = max(1, i2 - i1)
            span_b = j2 - j1
            for k in range(span_a):
                i = i1 + k
                j = j1 + min(k, max(0, span_b - 1))
                if i < len(base) and j < j2:
                    out[i].append(other[j])
        elif tag == "insert" and i1 > 0:
            out[i1 - 1].append(" ".join(other[j1:j2]))
    return out


def _vote_char(chars: list[tuple[str, float]]) -> tuple[str, bool, list[dict]]:
    score: dict[str, float] = {}
    for ch, w in chars:
        if not ch:
            continue
        score[ch] = score.get(ch, 0.0) + w
    if not score:
        return "", False, []
    ranked = sorted(score.items(), key=lambda x: (-x[1], x[0]))
    best, best_w = ranked[0]
    total = sum(score.values())
    tie = len(ranked) > 1 and abs(ranked[0][1] - ranked[1][1]) < 1e-6
    unresolved = tie or (best_w / total < 0.52)
    disag = [{"char": k, "score": round(v, 4)} for k, v in ranked[:4]] if len(ranked) > 1 else []
    return best, unresolved, disag


def _vote_line(lines: list[tuple[str, float]], line_no: int) -> tuple[str, list[dict], int]:
    max_len = max((len(x[0]) for x in lines), default=0)
    out: list[str] = []
    disagreements: list[dict] = []
    unresolved = 0
    for idx in range(max_len):
        chars = [(txt[idx] if idx < len(txt) else "", conf) for txt, conf in lines]
        ch, bad, disag = _vote_char(chars)
        if bad:
            unresolved += 1
        if disag:
            disagreements.append({"line": line_no, "col": idx + 1, "candidates": disag})
        out.append(ch)
    return "".join(out).rstrip(), disagreements, unresolved


def vote(readings: list[Reading]) -> tuple[str, float | None, list[dict], int]:
    if not readings:
        return "", None, [], 0
    ordered = sorted(readings, key=lambda r: (_weight(r), len(r.text)), reverse=True)
    if len(ordered) >= 2:
        srcs = {(ordered[0].source or "").lower(), (ordered[1].source or "").lower()}
        if {"rapidocr", "tesseract"} <= srcs or {"rapid", "tess"} <= srcs:
            # 当前校准：RapidOCR 在本项目样本上明显更稳，先保守采用其文本，
            # 再交给 lexicon 规则纠错；避免次优引擎拉低 CER。
            return ordered[0].text.strip(), round(float(ordered[0].conf), 4), [], 0
    if len(ordered) >= 2:
        r0 = difflib.SequenceMatcher(None, ordered[0].text, ordered[1].text).ratio()
        if r0 < 0.35:
            # 两引擎分歧过大时，保留主引擎结果，避免“坏引擎拉低”。
            return ordered[0].text.strip(), round(float(ordered[0].conf), 4), [], 0
    base = ordered[0]
    base_lines = base.text.splitlines()
    mapped: list[list[tuple[str, float]]] = [[(ln, _weight(base))] for ln in base_lines] or [[("", _weight(base))]]
    for r in ordered[1:]:
        mm = _map_lines(base_lines, r.text.splitlines())
        for i in range(len(mapped)):
            for ln in mm.get(i, []):
                # 跳过与主行差异极大的候选，减少错位投票。
                if base_lines and i < len(base_lines):
                    sim = difflib.SequenceMatcher(None, base_lines[i], ln).ratio()
                    if sim < 0.2:
                        continue
                mapped[i].append((ln, _weight(r)))
    out_lines = []
    disagreements: list[dict] = []
    unresolved = 0
    for i, rows in enumerate(mapped, 1):
        line, disag, un = _vote_line(rows, i)
        out_lines.append(line)
        disagreements.extend(disag)
        unresolved += un
    conf = sum(float(r.conf) for r in readings) / len(readings)
    return "\n".join(out_lines).strip(), round(conf, 4), disagreements, unresolved

