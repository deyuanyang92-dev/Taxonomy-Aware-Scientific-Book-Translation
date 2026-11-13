"""Config-driven OCR post-correction."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]


LATIN_RE = re.compile(r"\b[A-Z][a-z-]+(?:\s+[a-z][a-z-]+){1,2}\b")
CN_TOKEN_MAX = 8
CN_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]{2,%d}" % CN_TOKEN_MAX)
CJK_CHAR_RE = re.compile(r"[\u4e00-\u9fff]")
LATIN_LETTER_RE = re.compile(r"[A-Za-z]")
# 行尾断词：小写字母 + 连字号 + 换行/空白 + 小写字母
HYPHEN_BREAK_RE = re.compile(r"(?<=[a-z])-\s+(?=[a-z])")
# CJK 字符占（CJK + 拉丁字母）的比例低于它，就当英文页
ENGLISH_MAX_CJK_RATIO = 0.05


def is_english_text(text: str) -> bool:
    """页面基本是英文：中文字符占 (中文字符 + 拉丁字母) 不足 5%。"""
    cjk = len(CJK_CHAR_RE.findall(text))
    latin = len(LATIN_LETTER_RE.findall(text))
    return cjk <= ENGLISH_MAX_CJK_RATIO * (cjk + latin)


def _lev(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    dp = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        prev, dp[0] = dp[0], i
        for j, cb in enumerate(b, 1):
            old = dp[j]
            dp[j] = min(dp[j] + 1, dp[j - 1] + 1, prev + (ca != cb))
            prev = old
    return dp[-1]


def _lev_bounded(a: str, b: str, k: int) -> int:
    """编辑距离；超过 k 时提前结束并返回 k + 1（整行最小值已超过 k 就不可能再回到 k 以内）。"""
    la, lb = len(a), len(b)
    if abs(la - lb) > k:
        return k + 1
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        ca = a[i - 1]
        cur = [i] * (lb + 1)
        row_min = i
        for j in range(1, lb + 1):
            v = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != b[j - 1]))
            cur[j] = v
            if v < row_min:
                row_min = v
        if row_min > k:
            return k + 1
        prev = cur
    return prev[lb] if prev[lb] <= k else k + 1


def _deletes(w: str) -> set[str]:
    return {w[:i] + w[i + 1:] for i in range(len(w))}


class VocabIndex:
    """词表的近似查找：best(token) 返回编辑距离 <= max_dist 的唯一最近词，并列或无则 None；
    token 本身在词表内时返回 token（语义同原先对整张词表逐词算编辑距离，只是不再全表扫描）。

    max_dist <= 1 用「删除一位」倒排索引；更大的距离用按长度分桶 + 带提前终止的编辑距离。
    max_token_len：待查词的最大长度，比它长 max_dist 以上的词条不可能命中，建索引时直接丢掉
    （中文词表里有大量整行长条目，不丢会白占内存）。
    """

    def __init__(self, words, max_dist: int, max_token_len: int | None = None):
        self.k = max_dist
        cap = None if max_token_len is None else max_token_len + max_dist
        self.words = frozenset(w for w in words if w and (cap is None or len(w) <= cap))
        self._del: dict[str, list[str]] = {}
        self._len: dict[int, list[str]] = {}
        if max_dist == 1:
            for w in self.words:
                for key in _deletes(w) | {w}:
                    self._del.setdefault(key, []).append(w)
        elif max_dist >= 2:
            for w in self.words:
                self._len.setdefault(len(w), []).append(w)

    def _candidates(self, token: str) -> set[str]:
        if self.k == 1:
            out: set[str] = set()
            for key in _deletes(token) | {token}:
                out.update(self._del.get(key, ()))
            return out
        out = set()
        for n in range(len(token) - self.k, len(token) + self.k + 1):
            out.update(self._len.get(n, ()))
        return out

    def best(self, token: str) -> str | None:
        if token in self.words:
            return token
        if self.k <= 0:
            return None
        scored = []
        for cand in self._candidates(token):
            d = _lev_bounded(token, cand, self.k)
            if d <= self.k:
                scored.append((d, cand))
        if not scored:
            return None
        scored.sort()
        if len(scored) > 1 and scored[0][0] == scored[1][0]:
            return None
        return scored[0][1]


def _read_lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return []


class Fixer:
    def __init__(self, rules_path: str | Path):
        self.path = Path(rules_path)
        self.cfg = tomllib.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        self.latin = self._load_latin()
        self.chinese = self._load_chinese()
        self._indexes: dict[str, VocabIndex] = {}

    def _load_latin(self) -> list[str]:
        out = set(self.cfg.get("latin", {}).get("builtin", []))
        for src in self.cfg.get("latin", {}).get("sources", []):
            p = Path(src)
            if p.is_file():
                for ln in _read_lines(p):
                    for m in LATIN_RE.finditer(ln):
                        out.add(m.group(0))
            elif p.is_dir():
                for f in p.rglob("*"):
                    if f.suffix.lower() in {".tsv", ".csv", ".txt", ".md"}:
                        for ln in _read_lines(f):
                            for m in LATIN_RE.finditer(ln):
                                out.add(m.group(0))
        db = self.cfg.get("latin", {}).get("taxadb_sqlite", "")
        if db and Path(db).exists():
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            try:
                tabs = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if "treatment" in tabs:
                    cols = {r[1] for r in con.execute("PRAGMA table_info(treatment)")}
                    if "taxon" in cols:
                        for (x,) in con.execute("SELECT DISTINCT taxon FROM treatment WHERE taxon IS NOT NULL"):
                            if isinstance(x, str) and LATIN_RE.fullmatch(x.strip()):
                                out.add(x.strip())
                if "name_usage" in tabs:
                    cols = {r[1] for r in con.execute("PRAGMA table_info(name_usage)")}
                    col = "name_latin" if "name_latin" in cols else ("taxon" if "taxon" in cols else "")
                    if col:
                        for (x,) in con.execute(f"SELECT DISTINCT {col} FROM name_usage WHERE {col} IS NOT NULL"):
                            if isinstance(x, str) and LATIN_RE.fullmatch(x.strip()):
                                out.add(x.strip())
            except sqlite3.Error:
                pass
            finally:
                con.close()
        return sorted(out)

    def _load_chinese(self) -> list[str]:
        out = set(self.cfg.get("chinese", {}).get("builtin", []))
        for src in self.cfg.get("chinese", {}).get("sources", []):
            p = Path(src)
            if p.is_file():
                out.update([x.strip() for x in _read_lines(p) if x.strip()])
            elif p.is_dir():
                for f in p.rglob("*"):
                    if f.suffix.lower() in {".tsv", ".csv", ".txt", ".md"}:
                        out.update([x.strip() for x in _read_lines(f) if x.strip()])
        return sorted(out)

    def _index(self, name: str, vocab: list[str], max_dist: int, max_token_len: int | None) -> VocabIndex:
        idx = self._indexes.get(name)
        if idx is None or idx.k != max_dist:
            idx = self._indexes[name] = VocabIndex(vocab, max_dist, max_token_len)
        return idx

    @staticmethod
    def _latin_english(text: str, idx: VocabIndex, changes: list[dict]) -> str:
        """英文页的拉丁名步骤：只做「行尾断词合并」，且合并结果必须与词表条目完全相同；绝不做编辑距离纠错。

        LATIN_RE（大写词 + 1~2 个小写词）在英文正文里会匹配作者名（Boilly and Wissocq）、属名、
        普通句子开头（The body is），而词表里混有 OCR 文本、散文行抓来的短语。编辑距离 1~2 的「纠错」
        因此把人名、种名和普通词改成别的词（Boilly->Bailey, Friedman->Freeman, papillicornis->papilliorni,
        is->has；2026-11-13 Harrison1992_MAI_Annelida 实测 330 处大写词、56 处拉丁种加词被改错）。
        英文页没有可靠的词表可据以猜词，所以只保留确定无误的断词合并。
        """

        def repl(m: re.Match[str]) -> str:
            raw = m.group(0)
            if raw in idx.words:
                return raw
            joined = HYPHEN_BREAK_RE.sub("", raw)
            if joined != raw and joined in idx.words:
                if not any(c["rule"] == "latin_dehyphen" and c["before"] == raw for c in changes):
                    changes.append({"rule": "latin_dehyphen", "before": raw, "after": joined})
                return joined
            return raw

        return LATIN_RE.sub(repl, text)

    def apply(self, text: str, *, english: bool | None = None) -> tuple[str, list[dict]]:
        """english：True/False 强制英文页（保守）/中文页（原行为）；None 按中文字符占比自动判断。"""
        fixed = text
        changes: list[dict] = []
        for rule in self.cfg.get("regex_rules", []):
            new = re.sub(rule["pattern"], rule["replace"], fixed)
            if new != fixed:
                changes.append({"rule": rule.get("name", "regex"), "before": fixed, "after": new})
                fixed = new
        for rule in self.cfg.get("replace_rules", []):
            if rule["before"] in fixed:
                new = fixed.replace(rule["before"], rule["after"])
                changes.append({"rule": rule.get("name", "replace"), "before": rule["before"], "after": rule["after"]})
                fixed = new
        max_latin = int(self.cfg.get("latin", {}).get("max_distance", 2))
        latin_idx = self._index("latin", self.latin, max_latin, None)
        if english is None:
            english = is_english_text(fixed)
        if english:
            fixed = self._latin_english(fixed, latin_idx, changes)
        else:
            for m in sorted(set(LATIN_RE.findall(fixed)), key=len, reverse=True):
                best = latin_idx.best(m)
                if best and best != m:
                    fixed = fixed.replace(m, best)
                    changes.append({"rule": "latin_edit_distance", "before": m, "after": best})
        max_cn = int(self.cfg.get("chinese", {}).get("max_distance", 0))
        if max_cn <= 0:
            return fixed, changes
        cn_idx = self._index("chinese", self.chinese, max_cn, CN_TOKEN_MAX)
        for token in sorted(set(CN_TOKEN_RE.findall(fixed)), key=len, reverse=True):
            best = cn_idx.best(token)
            if best and best != token:
                fixed = fixed.replace(token, best)
                changes.append({"rule": "chinese_edit_distance", "before": token, "after": best})
        return fixed, changes

