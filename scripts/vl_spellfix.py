#!/usr/bin/env python3
"""VL OCR 拼写纠错（零模型）：用本卷/本系列词频 + Tesseract 第二读数，纠正 VL 识别出的编辑距离 1 的错字。

用法：python3 scripts/vl_spellfix.py <aligned.json ...> [--pdf PDF] [--tess-root DIR] [--out DIR] [--apply]
  - 词库 = 全部输入 aligned.json 里的词频（各卷互相印证）。
  - 可选 Tesseract 第二读数：--tess-root，其词集作为「另一引擎也读到」的证据。
  - 一个词被改，须同时满足：①该词在词库里 <= RARE 次（罕见）；②存在编辑距离 1 的候选词，词库频次 >= COMMON，
    且 >= RATIO 倍于原词；或候选词出现在 Tesseract 同页词集里而原词不在。
  - 候选唯一性：并列候选时不改，只记「待查」。
  - 只有「本批词频」或「Tesseract」支持的才算改（applied）；仅词典支持的、并列候选的只记建议。
  - 默认只出报告 <out>/spellfix_issues.jsonl；加 --apply 才写 <out>/aligned.spellfixed.json（不覆盖原文件）。
依据（2026-11-23 Fauna Ibérica Vol.21 第 36、47 页，对照原图）：VL-1.6 错 7 词：Síldos、brizoos、Paraeblersia、
Diplosyllis、ligeiramente、diminuitos（均为编辑距离 1）和 pueda（合法词，只能靠第二引擎提示，本脚本不改，仅在有 Tesseract 分歧时标「待查」）。
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

WORD = re.compile(r"[^\W\d_]+(?:-[^\W\d_]+)*", re.UNICODE)
ALPHA = "abcdefghijklmnopqrstuvwxyzñç"
RARE = 1
COMMON = 3
RATIO = 3.0
MIN_LEN = 5


def fold(w: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", w.lower()) if not unicodedata.combining(c))


def edits1(w: str):
    sp = [(w[:i], w[i:]) for i in range(len(w) + 1)]
    out = {a + b[1:] for a, b in sp if b}
    out |= {a + b[1] + b[0] + b[2:] for a, b in sp if len(b) > 1}
    out |= {a + c + b[1:] for a, b in sp if b for c in ALPHA}
    out |= {a + c + b for a, b in sp for c in ALPHA}
    out.discard(w)
    return out


def recase(orig: str, new: str) -> str:
    if orig.isupper() and len(orig) > 1:
        return new.upper()
    if orig[0].isupper():
        return new[0].upper() + new[1:]
    return new


def aspell_forms(lang: str) -> dict[str, str]:
    """aspell 词典全部词形：folded -> 带重音的写法。词典缺失（未装 aspell-<lang>）时返回空表。"""
    try:
        dump = subprocess.run(["aspell", "-d", lang, "dump", "master"], capture_output=True, text=True, check=True).stdout
        exp = subprocess.run(["aspell", "-l", lang, "expand"], input=dump, capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return {}
    out: dict[str, str] = {}
    for w in exp.split():
        if w.isalpha() and w == w.lower():
            out.setdefault(fold(w), w)
    return out


class Lexicon:
    def __init__(self, dicts: dict[str, str] | None = None):
        self.cnt = collections.Counter()   # folded -> count（本批书的词频）
        self.forms = collections.defaultdict(collections.Counter)  # folded -> {surface: n}
        self.dicts = dicts or {}           # folded -> surface，外部拼写词典（西语 + 英语）

    def valid(self, f: str) -> bool:
        return f in self.dicts or self.cnt.get(f, 0) >= 2

    def add_text(self, text: str):
        for m in WORD.finditer(text):
            w = m.group(0)
            self.cnt[fold(w)] += 1
            self.forms[fold(w)][w.lower()] += 1

    def best_form(self, f: str) -> str:
        if f in self.forms:
            return self.forms[f].most_common(1)[0][0]
        return self.dicts[f]


def propose(tok: str, lex: Lexicon, tess: set[str] | None, name_ctx: bool = False):
    """返回 (候选 or None, 原因, 并列候选列表)。

    只处理「词典和本批词频都不认」的词。候选 = 编辑距离 1 且（本批词频 >= COMMON 且 >= RATIO 倍原词，
    或 在外部词典里；人名/属名（首字母大写）只认本批词频，不认外部词典）。Tesseract 也读到的候选优先。
    """
    f = fold(tok)
    if len(f) < MIN_LEN or "-" in tok or lex.valid(f):
        return None, "", []
    own = lex.cnt.get(f, 0)
    is_name = tok[0].isupper() or name_ctx
    scored = []
    for c in edits1(f):
        if len(c) < MIN_LEN:
            continue  # 删字后变成短常用词（Síldo→Sido）风险大，不收
        n = lex.cnt.get(c, 0)
        in_vol = n >= COMMON and n >= RATIO * max(own, 1)
        in_dict = (not is_name) and c in lex.dicts
        if not (in_vol or in_dict):
            continue
        in_tess = bool(tess and c in tess)
        if tess is not None and f in tess:
            continue  # 第二引擎也读成原词：不改
        scored.append((in_tess, in_vol, n, c))
    if not scored:
        return None, "", []
    scored.sort(reverse=True)
    top = scored[0]
    ties = [s for s in scored if s[:3] == top[:3]]
    if len(ties) > 1:
        return None, "ambiguous", [s[3] for s in ties]
    why = "+".join(x for x, ok in (("tess", top[0]), ("vol", top[1]), ("dict", not top[1])) if ok)
    return recase(tok, lex.best_form(top[3])), why, []


PREV_CAP = re.compile(r"[A-Z][a-z]+\.?\s+$")


def fix_text(text: str, lex: Lexicon, tess: set[str] | None):
    """纠错一段文字。证据含本批词频或 Tesseract 才改（applied=True）；仅词典支持的只给建议（applied=False）。
    紧跟首字母大写词的小写词（学名种加词）按人名处理：不认外部词典。"""
    changes = []

    def sub(m):
        tok = m.group(0)
        name_ctx = bool(PREV_CAP.search(text[max(0, m.start() - 25):m.start()]))
        new, why, ties = propose(tok, lex, tess, name_ctx=name_ctx)
        if new and new != tok:
            applied = "tess" in why  # 须第二引擎（Tesseract）也读到候选词才改；其余只作建议
            changes.append({"before": tok, "after": new, "why": why, "applied": applied})
            return new if applied else tok
        if why == "ambiguous":
            changes.append({"before": tok, "after": None, "why": "ambiguous", "applied": False, "cands": ties})
        return tok

    return WORD.sub(sub, text), changes


def load_tess(tess_dir: Path | None, page: int) -> set[str] | None:
    if not tess_dir:
        return None
    toks: set[str] = set()
    found = False
    for p in tess_dir.glob("t%04d*.txt" % page):
        found = True
        toks |= {fold(m.group(0)) for m in WORD.finditer(p.read_text(encoding="utf-8", errors="ignore"))}
    return toks if found else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("aligned", nargs="+", type=Path)
    ap.add_argument("--tess-root", type=Path, default=None,
                    help="其下按 aligned.json 的上级目录名分子目录（如 交付_v21_样本50页/），放 tNNNN_{L,R}.txt（Tesseract 读数）")
    ap.add_argument("--out", type=Path, default=Path("."))
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--lang", default="es,en", help="aspell 词典，逗号分隔；缺词典时只靠本批词频")
    ap.add_argument("--skip-roles", default="ref", help="不处理的块角色（参考文献含多语种人名）")
    a = ap.parse_args(argv)
    docs = [json.loads(p.read_text(encoding="utf-8")) for p in a.aligned]
    dicts: dict[str, str] = {}
    for lg in filter(None, a.lang.split(",")):
        dicts.update(aspell_forms(lg.strip()))
    skip = set(filter(None, a.skip_roles.split(",")))
    lex = Lexicon(dicts)
    for d in docs:
        for pg in d["pages"]:
            for b in pg["blocks"]:
                lex.add_text(b.get("text", ""))
    issues = []
    for p, d in zip(a.aligned, docs):
        for pg in d["pages"]:
            tess = load_tess(a.tess_root / p.parent.name if a.tess_root else None, pg["page"])
            for bi, b in enumerate(pg["blocks"]):
                if b.get("role") in skip:
                    continue
                new, ch = fix_text(b.get("text", ""), lex, tess)
                for c in ch:
                    issues.append({"file": str(p), "page": pg["page"], "block": bi, **c})
                if a.apply and new != b.get("text"):
                    b["text_raw"] = b["text"]  # 原 VL 读数留痕
                    b["text"] = new
                    b["spellfixed"] = True
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "spellfix_issues.jsonl").write_text(
        "\n".join(json.dumps(i, ensure_ascii=False) for i in issues) + ("\n" if issues else ""), encoding="utf-8")
    if a.apply:
        for p, d in zip(a.aligned, docs):
            (a.out / (p.parent.name + ".aligned.spellfixed.json")).write_text(
                json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    n_fix = sum(1 for i in issues if i.get("applied"))
    print("applied %d, suggestions/ambiguous %d -> %s" % (n_fix, len(issues) - n_fix, a.out / "spellfix_issues.jsonl"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
