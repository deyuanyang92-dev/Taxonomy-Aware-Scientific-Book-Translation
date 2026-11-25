"""日文检索表条目拆段：OCR 常把整张检索表并成一段，谷歌机翻会重排条目。

依据：2026-11-22 零模型实测（docs/research/2026-11-21-zero-model-run.md）Imajima 2001 p.137：
「…Ephesiella gallardi(図78)単一鉤状剛毛を…brevicapitis(図77)…」并成一段。
规则（确定性）：条目结论以「(図N)」「（図N）」收尾，其后紧跟日文字符时在其后断段。
只处理含 2 处以上「図N」结论的段落，普通正文里的单个图引用不动。
"""
from __future__ import annotations

import re

_FIG_END = re.compile(r"([(（]図\s*\d+[)）])(?=[぀-ヿ㐀-鿿])")


def split_keys(text: str) -> str:
    out = []
    for para in text.split("\n\n"):
        if len(_FIG_END.findall(para)) >= 2:
            para = _FIG_END.sub(lambda m: m.group(1) + "\n\n", para)
        out.append(para)
    return "\n\n".join(out)
