#!/usr/bin/env python3
"""术语表/短语表英文译法的本地英文库佐证（0 token）：每行 en 与每个异写（Google 写法）各出现在多少份英文资料。

    python3 scripts/attest_glossary.py glossary_de_en.tsv out.tsv      # 术语表：每个异写都查
    python3 scripts/attest_glossary.py phrases_de_en.tsv out.tsv       # 短语表：只查有异写的行

读法：异写的资料数 ≥ 3×定名资料数+1，说明 Google 写法在英文分类文献里更通行，不应强行替换；
定名资料数为 0 的短语多是残片，本身不能作为删除依据。每个查询约 1 秒（FTS5 trigram）。
库根取 $DOCSTORE_ROOT 或 docstore 默认库。
"""

from __future__ import annotations

import csv
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docstore.attest import attest  # noqa: E402
from docstore.store import Store  # noqa: E402

HEADER = ["src", "de", "en", "en_docs", "en_pages", "variant", "var_docs", "var_pages"]


def main(src: str, dst: str) -> int:
    store = Store()
    cache: dict[str, dict] = {}

    def at(phrase: str) -> dict:
        if phrase not in cache:
            cache[phrase] = attest(store, phrase)
        return cache[phrase]

    phrases_only = "phrase" in Path(src).name
    t0 = time.time()
    n = 0
    with open(src, encoding="utf-8") as fin, open(dst, "w", newline="", encoding="utf-8") as fout:
        out = csv.writer(fout, delimiter="\t")
        out.writerow(HEADER)
        for row in csv.DictReader(fin, delimiter="\t"):
            en = row["en"].strip()
            var = (row.get("variants") or "").strip()
            if "#" in en or (phrases_only and not var):
                continue
            e = at(en)
            variants = [v.split("=")[0].strip() for v in var.split(";") if v.strip()] or [""]
            for v in variants:
                r = at(v) if v else {"docs": "", "pages": ""}
                out.writerow([src, row["de"], en, e["docs"], e["pages"], v, r["docs"], r["pages"]])
                n += 1
    print(n, "rows", round(time.time() - t0), "s")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1], sys.argv[2]))
