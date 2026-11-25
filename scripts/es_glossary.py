"""西语形态术语 -> yiku 已核中文，生成 glossary.tsv（es<TAB>en<TAB>zh<TAB>出处）供 vl_translate --glossary 注入。
西->英对照表是人工列的常用形态词（EN_OF）；中文只取 yiku「已核」层级最高的一条，查不到的不入表（不凭空拟译名）。
用法：python3 scripts/es_glossary.py out.tsv
"""
from __future__ import annotations

import subprocess
import sys

EN_OF = {
    "prostomio": "prostomium", "peristomio": "peristomium", "parápodo": "parapodium", "seda": "chaeta",
    "notopodio": "notopodium", "neuropodio": "neuropodium", "cirro dorsal": "dorsal cirrus",
    "cirro ventral": "ventral cirrus", "palpo": "palp", "antena": "antenna", "pigidio": "pygidium",
    "probóscide": "proboscis", "acícula": "acicula", "élitro": "elytra", "branquia": "branchia",
    "órgano nucal": "nuchal organ", "segmento": "segment", "seda compuesta": "compound chaeta",
    "setígero": "setiger", "faringe": "pharynx", "cirro tentacular": "tentacular cirrus",
    "seda simple": "simple chaeta", "ojo": "eye", "mandíbula": "jaw", "lóbulo": "lobe",
    "poliqueto": "polychaete", "anélido": "annelid", "gancho": "hook", "uncino": "uncinus",
}


def lookup(en: str) -> tuple[str, str] | None:
    r = subprocess.run(["yiku", "lookup", en, "--domain", "分类学"], capture_output=True, text=True, check=False)
    for line in r.stdout.splitlines():
        f = line.split("\t")
        if len(f) >= 4 and f[1] == "已核":
            return f[0], f[-1] if len(f) > 5 else ""
    return None


def main(argv: list[str] | None = None) -> int:
    out = (argv or sys.argv[1:])[0]
    rows = []
    for es, en in EN_OF.items():
        hit = lookup(en)
        if hit:
            rows.append(f"{es}\t{en}\t{hit[0]}\t{hit[1]}")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(rows) + "\n")
    print(f"{len(rows)}/{len(EN_OF)} terms with 已核 translation")
    return 0


if __name__ == "__main__":
    sys.exit(main())
