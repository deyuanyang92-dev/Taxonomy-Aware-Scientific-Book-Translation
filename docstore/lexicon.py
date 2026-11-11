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

    def _best(self, token: str, vocab: list[str], max_dist: int) -> str | None:
        best: list[tuple[int, str]] = []
        for cand in vocab:
            d = _lev(token, cand)
            if d <= max_dist:
                best.append((d, cand))
        if not best:
            return None
        best.sort(key=lambda x: (x[0], x[1]))
        if len(best) > 1 and best[0][0] == best[1][0]:
            return None
        return best[0][1]

    def apply(self, text: str) -> tuple[str, list[dict]]:
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
        for m in sorted(set(LATIN_RE.findall(fixed)), key=len, reverse=True):
            best = self._best(m, self.latin, max_latin)
            if best and best != m:
                fixed = fixed.replace(m, best)
                changes.append({"rule": "latin_edit_distance", "before": m, "after": best})
        max_cn = int(self.cfg.get("chinese", {}).get("max_distance", 1))
        for token in sorted(set(re.findall(r"[\u4e00-\u9fff]{2,8}", fixed)), key=len, reverse=True):
            best = self._best(token, self.chinese, max_cn)
            if best and best != token:
                fixed = fixed.replace(token, best)
                changes.append({"rule": "chinese_edit_distance", "before": token, "after": best})
        return fixed, changes

