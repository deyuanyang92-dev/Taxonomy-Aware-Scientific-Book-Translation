"""在原文里找出术语库收录的术语，生成注入提示词的术语表；对照译文检查术语一致性。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from . import db as D
from .classify import HARD, classify, is_taxon_name
from .db import candidates
from .table import DEFAULT_MAX_CHARS, render_table
from .usage import default_finder

_LATIN_PLURAL = (("us", "i"), ("um", "a"), ("on", "a"), ("a", "ae"), ("is", "es"), ("y", "ies"))


def forms(en: str) -> set[str]:
    """英文词形：单复数、拉丁复数。只变化最后一个词。
    拉丁复数规则要求词干至少 2 个字母：否则 um->a、us->i、on->a 会把「um」「us」变出单字母「复数」，
    冠词 a、代词 I 被当成术语（2026-11-13 试译里「um」被报出现 50 次，实为冠词 a）。"""
    t = en.lower()
    f = {t, t + "s", t + "es"}
    last = re.split(r"[\s-]+", t)[-1]
    for a, b in _LATIN_PLURAL:
        if t.endswith(a) and len(last) - len(a) >= 2:
            f.add(t[: -len(a)] + b)
    return f


def _pattern(en: str, tail: str = "") -> re.Pattern:
    alts = sorted((re.escape(x).replace(r"\ ", r"[\s-]+") for x in forms(en)), key=len, reverse=True)
    # 前后不能紧挨字母或数字：图号 38.2f 里的 f 不是缩写 f.（变型）
    return re.compile(r"(?<![A-Za-z0-9])(?:" + "|".join(alts) + r")(?![A-Za-z0-9])" + tail, re.I)


# 属名后面跟的小写词若是这些英语词，就不是种加词（Glycera has ...、Gyptis and ...）。只含英语虚词/常见动词，不含学科词。
_NOT_EPITHET = (
    "and or the an of in on at to by for from with without as is are was were be been has have had can may might will "
    "would also but that which who whose when where while not only both each other than then thus these those this such "
    "see like also occurs lacks bears shows possesses lives live include includes appears found known called named "
    "spp aff nov gen sensu indet species genus group complex"
).split()
# 双名法里的属名：后面紧跟（可带亚属）种加词；亚属名 (Glycera) 后面也跟种加词。(?-i:...) 让大小写敏感：Glycera Fig. 不是双名。
_EPITHET = r"(?!(?:" + "|".join(_NOT_EPITHET) + r")\b)[a-z]{3,}\b"
_BINOMIAL_TAIL = r"(?!(?-i:(?:\s+(?:\([A-Z][a-z]+\)\s+)?|\)\s+)" + _EPITHET + "))"


def is_genus_word(en: str) -> bool:
    """单个大写开头的拉丁词（属名，也含科名等），可能出现在双名里。"""
    return " " not in en.strip() and is_taxon_name(en)


def standalone_count(en: str, text: str) -> int:
    """属名在原文里「独立出现」的次数：后面跟种加词的（双名法 *Gyptis vittata* 里的属名）不算。
    用户裁定：学名照原书保持拉丁；双名里的属名不要求译成中文属名。*Genus* sp.、cf. 以及后面不是种加词的算独立出现。"""
    return len(_pattern(en, _BINOMIAL_TAIL).findall(text.replace("-\n", "")))


def find_terms(con, text: str, domain: str = "*", fallback_domains: list[str] | None = None) -> dict[str, int]:
    """原文中出现的、库里有译名的术语 -> 出现次数。长术语优先，避免 'palp' 抢 'palpal organ'。
    fallback_domains：回退领域里的术语也算（译名只作参考，见 db.candidates）。"""
    text = text.replace("-\n", "")
    doms = list(dict.fromkeys(["*", domain, *(fallback_domains or [])]))
    ens = [r[0] for r in con.execute(
        f"SELECT DISTINCT en_norm FROM terms WHERE status!='否决' AND domain IN ({','.join('?' * len(doms))})", doms)]
    found: dict[str, int] = {}
    masked = text
    low = text.lower()
    for en in sorted(ens, key=len, reverse=True):
        # 先用子串快速排除：每个词的词干（去掉可能被单复数改变的末 3 字母）必须在原文里，避免对整章逐个跑正则
        if not all(w[: max(len(w) - 3, 1)] in low for w in re.split(r"[\s-]+", en) if w):
            continue
        pat = _pattern(en)
        n = len(pat.findall(masked))
        if n:
            found[en] = n
            masked = pat.sub(" ", masked)
    return found


def term_table(con, text: str, domain: str = "*", scope: set[str] | None = None,
               fallback_domains: list[str] | str | None = None, usage: Any = None,
               max_chars: int = DEFAULT_MAX_CHARS) -> str:
    """Markdown 术语表，供任何模型的提示词使用。分 HARD（必用）与 SOFT（先判义项再取舍）两节，格式见 table.py。

    fallback_domains：None 取默认（分类学 -> 进化生物学），[] 或 'none' 不回退，也可给领域名列表/分号分隔串。
    usage：None 自动打开本机资料库取中文用例（没有则略过），False 关闭，或传入 usage.UsageFinder。
    max_chars：整表目标长度，只约束 SOFT 节；HARD 永不截断。"""
    fb = D.resolve_fallback(domain, fallback_domains)
    finder = default_finder() if usage is None else (None if usage is False else usage)
    return render_table(con, find_terms(con, text, domain, fb), domain, scope, fb, finder, max_chars)


@dataclass
class Issue:
    en: str
    expected: str
    found_alternatives: list[str]
    count_en: int
    level: str = "error"   # error | 提示
    note: str = ""         # 非 HARD 问题的说明（提示、决策日志问题）

    def line(self) -> str:
        if self.note:
            return ("提示：" if self.level == "提示" else "") + f"{self.en}（原文 {self.count_en} 次）{self.note}"
        alt = f"；译文用了落选译名：{'、'.join(self.found_alternatives)}" if self.found_alternatives else ""
        return f"{self.en}（原文 {self.count_en} 次）应译「{self.expected}」，译文中未出现{alt}"


_BRACKET = re.compile(r"[（(][^）)]*[）)]")
_ALT_SEPARATORS = "；;/／、，,"


def _alternatives(zh: str) -> list[str]:
    """复合译名在括号之外按 ；;/／、，, 拆成各备选名（括号里的分隔符不拆）。"""
    depth, cur, out = 0, "", []
    for ch in zh:
        if ch in "（(":
            depth += 1
        elif ch in "）)" and depth > 0:
            depth -= 1
        if depth == 0 and ch in _ALT_SEPARATORS:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return [a.strip() for a in out if a.strip()]


def variants(zh: str) -> set[str]:
    """译名在正文中可接受的形式。
    复合译名（「罩／盖（头罩、口盖）」「进化、演化」「单系(adj.) / 单系性(n.)」）：每个备选名都算。
    括注：括号前的主名即使只有一个字也算（「枕（带齿片者称齿片枕）」→「枕」）；括号在词中间时（「刚（毛）叶」）
    括号内容是可省的字，去掉和展开两种都算。
    另有：去词尾「的」、去词头「具/呈」、门纲级可省阶元字（这些派生形式至少 2 字，免得单字到处命中）。"""
    out = {zh}
    for alt in _alternatives(zh) or [zh]:
        base = {alt, _BRACKET.sub("", alt).strip() or alt}
        if re.search(r"[）)]\s*\S", alt):
            base.add(_BRACKET.sub(lambda m: m.group(0)[1:-1], alt))
        v = set(base)
        for x in list(v):
            v.add(x[:-1] if x.endswith("的") and len(x) > 2 else x)
        for x in list(v):
            v.add(x[1:] if x[:1] in "具呈" and len(x) > 2 else x)
            v.add(re.sub(r"(动物门|门|亚纲|纲)$", lambda m: "动物" if m.group(1) == "动物门" else "", x) or x)
        out |= base | {x for x in v if len(x) >= 2}
    return out


def _uses(zh_text: str, zh: str) -> bool:
    return any(x in zh_text for x in variants(zh))


def check(con, src: str, zh: str, domain: str = "*", scope: set[str] | None = None,
          fallback_domains: list[str] | str | None = None, decisions: list[dict] | None = None) -> list[Issue]:
    """核对译文用词。
    HARD 术语（学名、自域已核译名一致者）：原文出现、译文没有采用译名即报错（error），并指出译文里出现的落选译名。
    SOFT 术语：有决策日志（decisions，条目字段见 decide.py）时，同一英文+同一义项登记了不同译名报错，
    登记过的译名一个都没出现在译文里报错；不同义项允许不同译名。没有决策日志时，只对「有已核译名」的 SOFT
    术语在译文一个已核译名都没出现时给「提示」，不算错误；只有候选的 SOFT 术语不报。"""
    fb = D.resolve_fallback(domain, fallback_domains)
    log: dict[str, list[dict]] = {}
    for d in decisions or []:
        log.setdefault(D.norm(str(d.get("en", ""))), []).append(d)
    found = find_terms(con, src, domain, fb)
    for en in log:  # 决策日志里的术语，库里没有也要核（首次跑时决策还没写回库）
        if en not in found:
            n = len(_pattern(en).findall(src))
            if n:
                found[en] = n
    issues: list[Issue] = []
    for en, n in sorted(found.items()):
        hits = candidates(con, en, domain, scope, fb)
        shown_en = hits[0].en if hits else str(log[en][0].get("en", en)) if en in log else en  # found 的键是小写的
        if is_genus_word(shown_en):
            n = min(n, standalone_count(en, src))
            if n == 0:   # 只在拉丁双名里出现：学名照原书，不要求译属名
                continue
        cls = classify(hits) if hits else None
        if cls is not None and cls.kind == HARD:
            if hits[0].status != "已核" or _uses(zh, cls.zh or ""):
                continue
            alts = sorted({h.zh for h in hits if h.zh != cls.zh and not h.fallback and h.zh in zh})
            issues.append(Issue(hits[0].en, cls.zh or "", alts, n))
            continue
        decs = log.get(en)
        if decs:
            shown = decs[0].get("en", en)
            by_sense: dict[str, set[str]] = {}
            for d in decs:
                by_sense.setdefault(str(d.get("sense", "")), set()).add(str(d.get("zh", "")))
            bad = False
            for sense, zs in sorted(by_sense.items()):
                if len(zs) > 1:
                    bad = True
                    issues.append(Issue(shown, "", [], n, "error",
                                        f"同一义项「{sense}」在决策日志里登记了不同译名：{'、'.join(sorted(zs))}"))
            logged = sorted({z for zs in by_sense.values() for z in zs})
            if not bad and not any(_uses(zh, z) for z in logged):
                issues.append(Issue(shown, logged[0], [], n, "error",
                                    f"按决策日志应译「{'」或「'.join(logged)}」（各义项），译文中一个都没出现"))
            continue
        verified = [h for h in hits if h.status == "已核"]
        if verified and not any(_uses(zh, h.zh) for h in verified):
            want = (cls.preferred if cls and cls.preferred else verified[0].zh)
            names = "、".join(dict.fromkeys(h.zh for h in verified))
            tag = "（回退领域）" if all(h.fallback for h in verified) else ""
            issues.append(Issue(verified[0].en, want, [], n, "提示",
                                f"有已核译名{tag}：{names}，译文中一个都没出现；若本书此处义项不同，请在术语决策里登记",))
    return issues
