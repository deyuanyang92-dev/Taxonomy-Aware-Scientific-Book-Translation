"""分类文献的块类型（0 token）：按段首标签词、标题格式、引文格式、动词密度分流。

用途：auto_translate 的 --rewrite-kinds。实测（Hartmann-Schröder 德文 25 万词，2026-11-15）字符占比：
描述 57%、叙述 16%、产地 8%、生态 4%、分布 3%、标题 3%、讨论 3%、图注 2%、OCR 垃圾 2%、引文/文献 1%。
1971 Opisthodonta 试点：描述段 Google 初稿经术语表与学到的替换规则后，与 DeepSeek 改写稿相似度 0.85，
与「DeepSeek 稿 vs Codex 稿」的 0.86 相当 → 描述、标签段可只做意义核对，不整段改写；叙述、讨论段才交模型改写。

kind() 返回：junk heading caption locality ecology distribution remarks label citation reference key narrative description
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

RULES = Path(__file__).with_name("rules") / "taxo_labels.toml"
YEAR = r"1[789]\d\d|20[012]\d"
KINDS = ("junk", "heading", "caption", "locality", "ecology", "distribution", "remarks", "label", "citation",
         "reference", "key", "narrative", "description")


@lru_cache(maxsize=None)
def _lang(sl: str) -> dict[str, list[str]]:
    data = tomllib.loads(RULES.read_text(encoding="utf-8"))
    return data.get(sl) or data["en"]


def _junk(t: str) -> bool:
    """插图区被 OCR 成的乱码行（bt If) 7 bad m CO LIU SA）：短、几乎没有正常词。"""
    words = re.findall(r"[^\W\d_]+", t)
    if not words:
        return not re.search(r"\d{3,}", t)  # 纯标点/零散数字
    normal = sum(1 for w in words if len(w) >= 3 and (w.islower() or w.istitle() or w.isupper()))
    if len(t) < 60 and normal <= 1 and not re.search(YEAR, t):
        return True
    return len(words) >= 4 and normal / len(words) < 0.5


def kind(text: str, sl: str = "de") -> str:
    t = text.strip()
    lab = _lang(sl)
    if _junk(t):
        return "junk"
    if re.match(r"(?:%s)\.?\s*\d" % "|".join(map(re.escape, lab["caption"])), t):
        return "caption"
    if re.match(r"(?:%s)\b" % "|".join(lab["rank"]), t) and len(t) < 300:
        return "heading"
    if len(t) < 200 and re.match(r"[A-Z][a-z]+ (?:\([A-Z][a-z]+\) )?[a-z]+(?: [a-z]+)? (?:n\. ?sp\.|sp\. ?n\.|[A-Z(])", t) \
            and re.search(YEAR, t):
        return "heading"
    for k in ("locality", "ecology", "distribution", "remarks", "other"):
        words = sorted(lab[k], key=len, reverse=True)
        if re.match(r"(?:%s)\s*[:.—–-]" % "|".join(map(re.escape, words)), t):
            return "label" if k == "other" else k
    if re.match(r"^[A-ZÄÖÜ][A-ZÄÖÜ'\- ]{2,}(?:,| &| und| and)", t) and re.search(YEAR, t) and len(t) < 600:
        if re.search(rf"[A-Z]\.\s*(?:\([^)]*\))?,?\s*(?:{YEAR})[a-z]?\.", t[:90]) and len(t) > 60:
            return "reference"
        return "citation"
    if re.match(r"^\d+\s*\(\d+\)", t) or re.match(r"^\d+[a-z]?\s.{5,}?(?:\.{2,}|…|—)\s*\d+\s*$", t):
        return "key"
    verbs = len(re.findall(r"\b(?:%s)\b" % "|".join(lab["narrative_words"]), t, flags=re.I))
    sent = max(1, len(re.findall(r"[.!?](?:\s|$)", t)))
    return "narrative" if verbs / sent >= 0.8 else "description"
