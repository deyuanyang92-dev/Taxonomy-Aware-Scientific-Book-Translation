"""VL OCR 拼写纠错（B+C）：词典 + 本批词频 + WoRMS 学名 + Tesseract 第二读数，疑点再交 DeepSeek 在上下文里裁。

自动改写：tess、worms、LLM 裁定且证据类为 tess-disagree/tess-weak；其余（含 LLM 同意的 dict/vol 候选）只进待审建议。
依据（2026-11-23 Fauna Ibérica Vol.21 第 36、47 页对照原图）：VL-1.6 输出里有 Síldos、brizoos、Paraeblersia、
Diplosyllis、ligeiramente、diminuitos（均为编辑距离 1）和 pueda（合法词）。VL 输出以前直通 aligned.json，不经任何词表检查。

证据层级（越前越强，自动改写只认前三层，其余只记建议）：
  tess  ：候选词也在同页 Tesseract 词集里，而原词不在（两个引擎独立读到）。
  worms ：首字母大写词 / 紧跟属名的小写词，不是已知学名，但与 WoRMS 本地缓存里的属名/同属种加词唯一相差 1 个字符。
  llm   ：疑点（并列候选、词典候选、Tesseract 分歧）连同前后文交 DeepSeek，只许在给定候选里选或 KEEP；返回不在候选内一律作废。
  vol   ：本批词频；dict：外部拼写词典（aspell）。两者只作建议。
每处改动留痕：块里保留 text_raw，issues 里记 before/after/why。参考文献块默认不处理。
"""
from __future__ import annotations

import collections
import json
import re
import sqlite3
import subprocess
import unicodedata
from pathlib import Path
from typing import Any, Callable

WORD = re.compile(r"[^\W\d_]+(?:-[^\W\d_]+)*", re.UNICODE)
ALPHA = "abcdefghijklmnopqrstuvwxyzñç"
COMMON = 3
RATIO = 3.0
STRONG = 10
MIN_LEN = 5
PREV_CAP = re.compile(r"([A-Z][a-z]+)\.?\s+$")
CTX = 45
AUTO = ("tess", "worms", "vol-strong")
AUTO_LLM = ("tess-disagree", "tess-weak")  # 2026-11-23 实测 Vol.21/25/36/41 抽样：LLM 在这两类 14 对 0 错；dict/vol/worms-weak/ambiguous 类 26 对 23 错，只作待审建议


def fold(w: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", w.lower()) if not unicodedata.combining(c))


def edits1(w: str) -> set[str]:
    sp = [(w[:i], w[i:]) for i in range(len(w) + 1)]
    out = {a + b[1:] for a, b in sp if b}
    out |= {a + b[1] + b[0] + b[2:] for a, b in sp if len(b) > 1}
    out |= {a + c + b[1:] for a, b in sp if b for c in ALPHA}
    out |= {a + c + b for a, b in sp for c in ALPHA}
    out.discard(w)
    return out


CONF = {frozenset(p) for p in ("bh", "ce", "il", "nu", "ft")}


def ocr_like(a: str, b: str) -> bool:
    """a→b 是否典型 OCR 混淆：单字符替换（b/h、c/e、i/l、n/u、f/t）、相邻互换、或叠字（多/少一个重复字母）。"""
    if len(a) == len(b):
        d = [i for i in range(len(a)) if a[i] != b[i]]
        if len(d) == 1:
            return frozenset((a[d[0]], b[d[0]])) in CONF
        return len(d) == 2 and d[1] == d[0] + 1 and a[d[0]] == b[d[1]] and a[d[1]] == b[d[0]]
    sh, lg = (a, b) if len(a) < len(b) else (b, a)
    if len(lg) - len(sh) != 1:
        return False
    for i in range(len(lg)):
        if lg[:i] + lg[i + 1:] == sh:
            return (i > 0 and lg[i] == lg[i - 1]) or (i + 1 < len(lg) and lg[i] == lg[i + 1])
    return False


def inflection(a: str, b: str) -> bool:
    """同一词干、只在末两位不同（falcígeros/-as、Hesionides/-idos、-a/-as）：词形变化，不自动改。"""
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n >= 4 and n >= min(len(a), len(b)) - 2 and abs(len(a) - len(b)) <= 2 and a != b


def gender_swap(a: str, b: str) -> bool:
    """同词干、末尾 o/os 与 a/as 互换（性数变化，两词常都合法）。"""
    for x, y in (("os", "as"), ("o", "a")):
        for p, q in ((x, y), (y, x)):
            if a.endswith(p) and b.endswith(q) and a[:-len(p)] == b[:-len(q)]:
                return True
    return False


def recase(orig: str, new: str) -> str:
    if orig.isupper() and len(orig) > 1:
        return new.upper()
    if orig[0].isupper():
        return new[0].upper() + new[1:]
    return new


def aspell_forms(lang: str) -> dict[str, str]:
    """aspell 词典全部词形：folded -> 带重音写法。未装 aspell-<lang> 时返回空表。"""
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


def worms_names(path: Path | str | None) -> tuple[dict[str, str], dict[str, set[str]]]:
    """从 WoRMS 本地缓存取 (高阶名/属名: folded->原写法, 属名 folded -> 种加词 folded 集)。缓存缺失返回空。"""
    genera: dict[str, str] = {}
    epith: dict[str, set[str]] = collections.defaultdict(set)
    if not path or not Path(path).exists():
        return genera, epith
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    for (vn,) in db.execute("SELECT DISTINCT valid_name FROM worms_taxa"):
        parts = vn.split()
        if not parts or not parts[0][:1].isupper():
            continue
        genera.setdefault(fold(parts[0]), parts[0])
        if len(parts) >= 2 and parts[1].isalpha():
            epith[fold(parts[0])].add(fold(parts[1]))
    return genera, epith


class Lexicon:
    def __init__(self, dicts: dict[str, str] | None = None, genera: dict[str, str] | None = None,
                 epith: dict[str, set[str]] | None = None):
        self.cnt: collections.Counter[str] = collections.Counter()
        self.forms: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
        self.dicts = dicts or {}
        self.genera = genera or {}
        self.epith = epith or {}

    def is_known_name(self, f: str) -> bool:
        if f in self.genera:
            return True
        if not hasattr(self, "_all_ep"):
            self._all_ep = set().union(*self.epith.values()) if self.epith else set()
        return f in self._all_ep

    def valid(self, f: str) -> bool:
        return f in self.dicts or self.cnt.get(f, 0) >= 2

    def add_text(self, text: str) -> None:
        for m in WORD.finditer(text):
            w = m.group(0)
            self.cnt[fold(w)] += 1
            self.forms[fold(w)][w.lower()] += 1

    def best_form(self, f: str) -> str:
        if f in self.forms:
            return self.forms[f].most_common(1)[0][0]
        return self.dicts.get(f) or f


def _unique(cands: list[str]) -> str | None:
    return cands[0] if len(cands) == 1 else None


def propose(tok: str, lex: Lexicon, tess: set[str] | None, genus_ctx: str | None = None) -> dict[str, Any] | None:
    """返回 {after, why, cands} 或 None。only 处理词典、本批词频、WoRMS 都不认的词。"""
    f = fold(tok)
    if len(f) < MIN_LEN or "-" in tok:
        return None
    # 本批词频>=2 通常算「有效」，但 VL 会把同一学名连续读错；学名候选（大写/紧跟属名）在 WoRMS 不认且词典不认时仍检查
    name_like = bool(lex.genera) and tok.isascii() and (tok[0].isupper() or genus_ctx is not None)
    # 词典不认、只靠本批词频过关的小写词（出现<=3 次）：仍找候选，但只会是建议（why=vol/dict），不会自动改
    rare_vol_only = f not in lex.dicts and lex.cnt.get(f, 0) <= 3 and not tok[0].isupper() and genus_ctx is None and bool(lex.dicts)
    if lex.valid(f) and not (name_like and f not in lex.dicts and f not in lex.genera) and not rare_vol_only:
        return None
    tess_same = tess is not None and f in tess
    if tess_same and not (lex.genera and tok[0].isupper() and tok.isascii() and genus_ctx is None):
        return None  # 第二引擎也读成原词（大写学名属名例外：两个引擎可能同样把 h 读成 b，交 WoRMS 唯一匹配判）
    own = lex.cnt.get(f, 0)
    is_name = tok[0].isupper() or genus_ctx is not None
    # 1) WoRMS：属名 / 同属种加词
    if lex.genera and is_name and tok.isascii():  # 学名不带重音；带重音的是西语词
        if genus_ctx is not None:
            pool = lex.epith.get(fold(genus_ctx), set())
            if f in pool:
                return None
            hits = [c for c in edits1(f) if c in pool and len(c) >= MIN_LEN]
            surf = lambda c: c  # noqa: E731
        else:
            if f in lex.genera:
                return None
            hits = [c for c in edits1(f) if c in lex.genera and len(c) >= MIN_LEN]
            surf = lambda c: lex.genera[c].lower()  # noqa: E731
        u = _unique(hits)
        if tess_same and not (u and len(u) == len(f) and ocr_like(f, fold(u))):  # 两引擎同读：只认同长度的易混字母替换（h/b 等），不动增删字母的异写（Lopadorhynchus）
            return None
        if u:
            weak = not ocr_like(f, fold(u)) or inflection(f, fold(u))
            return {"after": recase(tok, surf(u)), "why": "worms-weak" if weak else "worms", "cands": [recase(tok, surf(u))]}
        if len(hits) > 1:
            return {"after": None, "why": "ambiguous", "cands": [surf(c) for c in hits]}
    # 2) 本批词频 / 词典（非学名词）候选；Tesseract 同见者优先
    scored = []
    for c in edits1(f):
        if len(c) < MIN_LEN:
            continue
        n = lex.cnt.get(c, 0)
        in_vol = n >= COMMON and n >= RATIO * max(own, 1)
        in_dict = (not is_name) and c in lex.dicts
        if not (in_vol or in_dict):
            continue
        scored.append((bool(tess and c in tess), in_vol, n, c))
    if scored:
        scored.sort(reverse=True)
        top = scored[0]
        ties = [s for s in scored if s[:3] == top[:3]]
        if len(ties) > 1:
            return {"after": None, "why": "ambiguous", "cands": [recase(tok, lex.best_form(s[3])) for s in ties]}
        why = "tess" if top[0] else ("vol" if top[1] else "dict")
        if why == "vol" and top[2] >= STRONG * max(own, 1) and top[3] in lex.dicts and f not in lex.dicts and not inflection(f, top[3]):
            why = "vol-strong"  # 词典不认的低频词，ED-1 词是词典词且全书频次 >=10 倍：自动改（实测见 LEDGER）
        if why == "tess" and inflection(f, top[3]):
            why = "tess-weak"
        return {"after": recase(tok, lex.best_form(top[3])), "why": why, "cands": [recase(tok, lex.best_form(top[3]))]}
    return None


def disagree(tok: str, lex: Lexicon, tess: set[str] | None) -> list[str]:
    """VL 词不在 Tesseract 页词集、却有 Tesseract 的编辑距离 1 词，且该词本批也出现 → 分歧候选（合法词写错，如 pueda）。"""
    f = fold(tok)
    if not tess or len(f) < MIN_LEN or f in tess or "-" in tok:
        return []
    return sorted(recase(tok, lex.best_form(c)) for c in edits1(f)
                  if c in tess and len(c) >= MIN_LEN and lex.cnt.get(c, 0) >= 1 and not inflection(f, c))


def _ctx(text: str, m: re.Match[str]) -> str:
    return text[max(0, m.start() - CTX):m.end() + CTX].replace("\n", " ")


def fix_text(text: str, lex: Lexicon, tess: set[str] | None, decisions: dict[str, str] | None = None,
             pending: list[dict[str, Any]] | None = None) -> tuple[str, list[dict[str, Any]]]:
    """纠一段文字。decisions: key(token|ctx)->LLM 选择（KEEP 或候选）。pending 收集待 LLM 裁的疑点。"""
    changes: list[dict[str, Any]] = []

    def sub(m: re.Match[str]) -> str:
        tok = m.group(0)
        pm = PREV_CAP.search(text[max(0, m.start() - 25):m.start()])
        genus = pm.group(1) if pm and tok[0].islower() else None
        pr = propose(tok, lex, tess, genus)
        ctx = _ctx(text, m)
        key = tok + "|" + ctx
        if pr and pr["after"] and pr["after"] != tok and pr["why"] in AUTO:
            changes.append({"before": tok, "after": pr["after"], "why": pr["why"], "applied": True})
            return pr["after"]
        cands = pr["cands"] if pr else []
        why = pr["why"] if pr else ""
        if not cands and genus is None:
            cands = disagree(tok, lex, tess)
            why = "tess-disagree" if cands else ""
        if not cands:
            return tok
        if decisions is not None and key in decisions:
            ch = decisions[key]
            if ch in cands and ch != tok:
                n_o, n_c = lex.cnt.get(fold(tok), 0), lex.cnt.get(fold(ch), 0)
                ok = why in AUTO_LLM and not lex.is_known_name(fold(tok))  # 原词本身是 WoRMS 已知属名/种加词，LLM 也不得改（rathkei→ratbkei）
                if ok and why == "tess-weak" and gender_swap(fold(tok), fold(ch)):  # o↔a 阴阳性互换两词都合法（pseudoespinígeros→-eras）：新词须 >=5 倍常见
                    ok = n_c >= 5 * max(n_o, 1)
                changes.append({"before": tok, "after": ch, "why": "llm(%s)" % why, "applied": ok})
                return ch if ok else tok
            changes.append({"before": tok, "after": pr["after"] if pr else None, "why": why, "applied": False,
                            "llm": ch, "cands": cands})
            return tok
        if pending is not None:
            pending.append({"key": key, "token": tok, "ctx": ctx, "cands": cands})
        changes.append({"before": tok, "after": pr["after"] if pr else None, "why": why, "applied": False, "cands": cands})
        return tok

    return WORD.sub(sub, text), changes


def llm_decide(pending: list[dict[str, Any]], call: Callable[..., tuple[str, dict]], engine: str = "deepseek-flash",
               batch: int = 40, cache: Path | None = None) -> dict[str, str]:
    """把疑点分批交 LLM：只许在候选里选，或 KEEP（保持原词）。返回 key -> 选择。"""
    done: dict[str, str] = {}
    if cache and cache.exists():
        done = json.loads(cache.read_text(encoding="utf-8"))
    todo = [p for i, p in enumerate(pending) if p["key"] not in done and p["key"] not in {q["key"] for q in pending[:i]}]
    sysmsg = ("你是西班牙语/葡萄牙语动物志 OCR 校对员。每条给出 OCR 词及上下文。"
              "只在给出的候选里选一个，或答 KEEP（原词无误，如人名、学名、他语种词、合法词）。"
              "仅当候选明显使原词所在句子更通顺或更像正确学名/术语时才选候选。只输出 JSON 对象 {编号: 选择}，不加说明。")
    for i in range(0, len(todo), batch):
        part = todo[i:i + batch]
        user = json.dumps({str(j): {"词": p["token"], "上下文": p["ctx"], "候选": p["cands"]} for j, p in enumerate(part)},
                          ensure_ascii=False)
        out, _ = call(engine, sysmsg, user, max_tokens=4000, tag="spellfix")
        m = re.search(r"\{.*\}", out, re.S)
        res = json.loads(m.group(0)) if m else {}
        for j, p in enumerate(part):
            done[p["key"]] = str(res.get(str(j), "KEEP"))
        if cache:
            cache.write_text(json.dumps(done, ensure_ascii=False), encoding="utf-8")
    return done


def load_tess(tess_dir: Path | None, page: int) -> set[str] | None:
    if not tess_dir:
        return None
    toks: set[str] = set()
    found = False
    for p in tess_dir.glob("t%04d*.txt" % page):
        found = True
        toks |= {fold(m.group(0)) for m in WORD.finditer(p.read_text(encoding="utf-8", errors="ignore"))}
    return toks if found else None


def fix_aligned(docs: list[dict[str, Any]], names: list[str], lex: Lexicon, tess_dirs: list[Path | None],
                skip_roles: set[str], decide: Callable[[list[dict[str, Any]]], dict[str, str]] | None = None,
                apply: bool = True, suggest_roles: set[str] | None = None) -> list[dict[str, Any]]:
    """纠 docs（aligned.json 内容）。先只收集疑点（不改文本），交 decide（LLM）裁，再一遍落实。
    apply 时就地改块 text 并留 text_raw。返回 issues。"""
    def run(decisions, pending, write):
        issues = []
        for name, d, td in zip(names, docs, tess_dirs):
            for pg in d["pages"]:
                tess = load_tess(td, pg["page"])
                for bi, b in enumerate(pg["blocks"]):
                    if b.get("role") in skip_roles or not b.get("text"):
                        continue
                    new, ch = fix_text(b["text"], lex, tess, decisions, pending)
                    sug = b.get("role") in (suggest_roles or ()) and not (b.get("role") == "key" and not b["text"].lstrip().startswith("("))  # 检索表正文条目照常纠；括号异名条目只建议
                    for c in ch:
                        if sug:  # 索引/检索表条目照印刷原样（含原书自身的异写，如 Glyphobesione、(kosteriensis)）：只建议
                            c = {**c, "applied": False, "note": "index/key: suggest only"}
                        issues.append({"file": name, "page": pg["page"], "block": bi, **c})
                    if sug:
                        continue
                    if write and new != b["text"]:
                        b.setdefault("text_raw", b["text"])
                        b["text"] = new
                        b["spellfixed"] = True
        return issues

    decisions = None
    if decide:
        pend: list[dict[str, Any]] = []
        run(None, pend, False)
        decisions = decide(pend) if pend else {}
    return run(decisions, None, apply)
