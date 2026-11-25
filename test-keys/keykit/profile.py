"""体例参数 profile。规则依据：RULES.md 第四节（second_lead/overflow/figref/dest_zh_name 随语言与原书取默认，用户可覆盖）。"""
from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path


@dataclass
class Profile:
    second_lead: str = "dash"  # dash | prime | backref | serial | number
    overflow: str = "wrap"  # wrap | fill
    figref: str = "source"  # before | after | source
    dest_zh_name: bool = True
    font_size: float = 10
    latin_font: str = "Times New Roman"
    cjk_font: str = "SimSun"
    text_w_mm: float = 150


def for_lang(lang: str, source_style: str | None = None) -> Profile:
    """RULES.md 第四节默认：zh -> wrap + 中文名；其他 -> fill。second_lead 无法推定时报错，不静默套默认。"""
    if not source_style:
        raise ValueError("原书体例未确证，请指定 second_lead")
    if lang.lower().startswith("zh"):
        return Profile(second_lead=source_style, overflow="wrap", dest_zh_name=True)
    return Profile(second_lead=source_style, overflow="fill", dest_zh_name=False)


def load(path: Path | str, base: Profile) -> Profile:
    """用 toml 覆盖 base 的同名字段。"""
    data = tomllib.loads(Path(path).read_text("utf-8"))
    names = {f.name for f in fields(Profile)}
    for k, v in data.items():
        if k in names:
            setattr(base, k, v)
    return base


def detect_style(raw_lead_tokens: list[str]) -> str | None:
    """多数票检测第二分支体例。普通数字号（首条）为中性，不计票；不足 70% 一致返回 None。"""
    counts = {"dash": 0, "prime": 0, "backref": 0}
    plain: list[int] = []
    for t in raw_lead_tokens:
        s = t.strip()
        if re.fullmatch(r"[—–\-]+\.?", s):
            counts["dash"] += 1
        elif re.fullmatch(r"\d+\s*['′’]\.?", s):
            counts["prime"] += 1
        elif re.fullmatch(r"\d+\s*\(\d+\)\.?", s):
            counts["backref"] += 1
        elif re.fullmatch(r"\d+\.?", s):
            plain.append(int(s.rstrip(".")))
    voted = sum(counts.values())
    if voted == 0:
        if len(plain) >= 2 and plain == list(range(plain[0], plain[0] + len(plain))):
            return "number"
        return None
    # backref 体例中第一条为 "N (B)."，第二条为 "—"：二者合计计入 backref
    if counts["backref"] and (counts["backref"] + counts["dash"]) / voted >= 0.7:
        return "backref"
    best = max(counts, key=lambda k: counts[k])
    return best if counts[best] / voted >= 0.7 else None
