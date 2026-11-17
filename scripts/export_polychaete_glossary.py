#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "yiku"))
from yiku import db as D  # noqa: E402

YIKU = Path("/mnt/p/翻译-译作/yiku/yiku.db")
OUT = Path("/mnt/p/翻译-译作/yiku/learning_2026-11-17/glossary_多毛类_形态.tsv")
MORPH_EN = re.compile(
    r"(?i)\b(prostom|peristom|parapod|chaet|seta|antenna|palp|cirri|cirrus|"
    r"acicul|neuropod|notopod|pygid|pharynx|probosc|mandib|maxilla|"
    r"segment|setiger|branchi|elytr|uncin|opercul|collar|nuchal|"
    r"dorsal|ventral|lateral|anterior|posterior|family|genus|species|"
    r"holotype|paratype|diagnosis|synonym|distribution|ecology|habitat|"
    r"tentacle|jaw|tooth|hook|hood|lobe|papilla)\b"
)
MORPH_ZH = re.compile(
    r"(口前叶|围口|疣足|刚毛|触手|触须|触角|鳃|肛|尾节|咽|吻|"
    r"大颚|小颚|足刺|背须|腹须|鳞片|科|属|种|模式|分布|生态|体节|刚节)"
)


def main() -> None:
    con = D.connect(YIKU)
    best: dict[str, tuple[str, str, str]] = {}
    for r in con.execute(
        "SELECT en, en_norm, zh, source, page FROM terms "
        "WHERE domain='分类学' AND status='已核'"
    ):
        en, zh = r["en"], r["zh"]
        if len(zh) > 10:
            continue
        if not (MORPH_EN.search(en) or MORPH_ZH.search(zh)):
            continue
        if " " not in en and len(en) > 18:
            continue
        if r["en_norm"] not in best:
            best[r["en_norm"]] = (en, zh, f"{r['source']} p.{r['page'] or ''}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    lines = ["source\ttarget\tvariants\tnote"]
    for _, (en, zh, note) in sorted(best.items(), key=lambda x: x[1][0].lower()):
        lines.append(f"{en}\t{zh}\t\t{note}")
    OUT.write_text("\n".join(lines) + "\n", encoding="utf8")
    st = dict(con.execute("SELECT status, COUNT(*) FROM terms GROUP BY status"))
    tax = con.execute(
        "SELECT COUNT(*) FROM terms WHERE domain='分类学' AND status='已核'"
    ).fetchone()[0]
    print(f"glossary_rows={len(best)} path={OUT}")
    print(f"yiku_status={st} taxonomy_verified={tax}")
    for k in ("parapodium", "chaeta", "chaetae", "prostomium", "setae"):
        print(k, best.get(k))


if __name__ == "__main__":
    main()
