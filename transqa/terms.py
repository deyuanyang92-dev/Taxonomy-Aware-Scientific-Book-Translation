"""术语按本地库规范化（0 token）：以原文为锚，只在原文出现该术语的段里，把译文中的「异写」换成库里的定名。

用户 2026-11-15：「分类术语完全可以靠本地库修正；一些术语确实是原始文献中使用，不一定是错误」。所以：
- 依据是本地库（项目术语表 / yiku），不是从 Google 稿里挖出来的替换表；
- **以原文为锚**：只有原文这一段出现了库里的源术语，才规范它的译法。原文作者自己用的旧术语、旧体系
  （例如英文原文本身写 setae、历史上的阶元名）有自己的条目或没有条目，不会被「现代化」；
- 只替换库里明确登记的异写（variants），不做模糊猜测；替换数写进报告。

库的格式（TSV / Markdown 表均可，前三列）：源术语 | 定名 | 异写（用 ; 分隔，可含词形：setae;seta=chaeta）
异写写成 `x=y` 表示 x 换成 y（处理单复数等词形）；只写 x 表示 x 换成定名。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Term:
    source: str
    target: str
    variants: dict[str, str] = field(default_factory=dict)   # 异写 → 应换成


def load(path: str | Path) -> list[Term]:
    out = []
    for ln in Path(path).read_text(encoding='utf-8').splitlines():
        cells = [c.strip() for c in (ln.strip().strip('|').split('|') if ln.lstrip().startswith('|') else ln.split('\t'))]
        if len(cells) < 2 or not cells[0] or set(cells[0]) <= set('-: '):
            continue
        var: dict[str, str] = {}
        if len(cells) >= 3 and cells[2]:
            for v in re.split(r'\s*;\s*', cells[2]):
                if not v:
                    continue
                a, _, b = v.partition('=')
                var[a.strip()] = (b.strip() or cells[1])
        out.append(Term(cells[0], cells[1], var))
    return out


def _stem(w: str) -> str:
    w = w.lower()
    return w[:max(4, len(w) - 2)] if len(w) > 5 else w


def source_has(src: str, term: str) -> bool:
    """原文段是否出现该源术语（容忍屈折：每个实词去掉词尾 2 字母后出现即可）。

    源术语为空或 ``*``：视为「机翻异写」全局规则（Google 系统性错，不依赖原文锚），
    用于 mine_corrections 挖出的 en→en 替换（如 bristles→chaetae）。
    """
    if not (term or "").strip() or term.strip() == "*":
        return True
    low = src.lower()
    words = [w for w in re.split(r'[\s/(),;.]+', term) if len(w) > 2]
    return bool(words) and all(_stem(w) in low for w in words)


def normalize(src: str, tgt: str, terms: list[Term]) -> tuple[str, list[tuple[str, str, int]]]:
    """返回（规范化后的译文，[(异写, 定名, 次数)]）。斜体（学名）与 [TN:] 内不动。"""
    log: list[tuple[str, str, int]] = []
    protected: list[str] = []

    def keep(m: re.Match[str]) -> str:
        protected.append(m.group(0))
        return f'\x00{len(protected) - 1}\x00'

    body = re.sub(r'\*[^*\n]+\*|\[TN:[^\]]*\]', keep, tgt)
    # 所有生效条目的异写统一按长度从长到短替换：否则短的先换（bristle→seta）会让长的
    # （bristle segment→setiger）匹配不上，得到「seta segment」（Hartmann-Schröder 1971 试点，2026-11-15）
    active = sorted({(var, rep) for t in terms if t.variants and source_has(src, t.source)
                     for var, rep in t.variants.items()}, key=lambda x: (-len(x[0]), x[0]))
    for var, rep in active:
        pat = re.compile(rf'(?<![\w-]){re.escape(var)}(?![\w-])', re.I)
        n = len(pat.findall(body))
        if n:
            def case(m: re.Match[str], r: str = rep) -> str:   # 保留原大小写（句首大写）
                return r[0].upper() + r[1:] if m.group(0)[0].isupper() else r
            body = pat.sub(case, body)
            log.append((var, rep, n))
    out = re.sub(r'\x00(\d+)\x00', lambda m: protected[int(m.group(1))], body)
    return out, log
