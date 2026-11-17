#!/usr/bin/env python3
"""把本地多毛类权威来源里一致的形态/分类术语升为「已核」，并导出 glossary。

升核规则（可脚本化、可复查）：
1. 来源属 kb_动物志* / kb_近海1988 / kb_杨德渐*（authority）
2. 同一 en_norm 在权威源中只对应一个 zh（或该 zh 出现次数占优 ≥2 且 ≥70%）
3. 英文命中形态/分类提示词，或中文含志书常用结构词
4. 已否决的不碰；已核保持

导出：
  /mnt/p/翻译-译作/yiku/learning_2026-11-17/glossary_多毛类_形态.tsv
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "yiku"))
from yiku import db as D  # noqa: E402

YIKU = Path("/mnt/p/翻译-译作/yiku/yiku.db")
OUT = Path("/mnt/p/翻译-译作/yiku/learning_2026-11-17")
REPORT = Path(
    "/root/github/Taxonomy-Aware-Scientific-Book-Translation/"
    "docs/research/2026-11-17/local_polychaete_term_learning.md"
)

AUTH_PREFIX = ("kb_动物志", "kb_近海1988", "kb_杨德渐")
MORPH_EN = re.compile(
    r"(?i)\b(prostom|peristom|parapod|chaet|seta|antenna|palp|cirri|cirrus|"
    r"acicul|neuropod|notopod|pygid|pharynx|probosc|mandib|maxilla|"
    r"segment|setiger|branchi|elytr|uncin|opercul|collar|nuchal|"
    r"dorsal|ventral|lateral|anterior|posterior|family|genus|species|"
    r"holotype|paratype|diagnosis|synonym|distribution|ecology|habitat|"
    r"tentacle|jaw|tooth|hook|hood|lobe|papilla|groove|ridge)\b"
)
MORPH_ZH = re.compile(
    r"(口前叶|围口|疣足|刚毛|触手|触须|触角|须|鳃|肛|尾节|咽|吻|"
    r"大颚|小颚|足刺|背须|腹须|鳞片|钩|冠|领|科|属|种|"
    r"模式|分布|生态|生境|体节|刚节)"
)


def is_auth(source: str) -> bool:
    return source.startswith(AUTH_PREFIX)


def morphish(en: str, zh: str) -> bool:
    return bool(MORPH_EN.search(en) or MORPH_ZH.search(zh))


def main() -> None:
    con = D.connect(YIKU)
    rows = list(
        con.execute(
            "SELECT id, en, en_norm, zh, source, status, page, domain, scope "
            "FROM terms WHERE domain='分类学'"
        )
    )
    # en_norm -> Counter(zh) on authority only
    auth_votes: dict[str, Counter[str]] = defaultdict(Counter)
    auth_rows: dict[str, list] = defaultdict(list)
    for r in rows:
        if r["status"] == "否决":
            continue
        if not is_auth(r["source"]):
            continue
        if not morphish(r["en"], r["zh"]):
            continue
        auth_votes[r["en_norm"]][r["zh"]] += 1
        auth_rows[r["en_norm"]].append(r)

    promoted = 0
    skipped_conflict = 0
    chosen: list[tuple[str, str, int, str]] = []
    for en_norm, votes in auth_votes.items():
        total = sum(votes.values())
        zh, n = votes.most_common(1)[0]
        sources = {r["source"] for r in auth_rows[en_norm] if r["zh"] == zh}
        # 至少两个权威来源一致，或同一 zh 出现 ≥3 次
        if len(sources) < 2 and n < 3:
            skipped_conflict += 1
            continue
        if len(votes) > 1 and not (n >= 2 and n / total >= 0.7):
            skipped_conflict += 1
            continue
        if len(zh) > 10 or " " not in en_norm and len(en_norm) > 18:
            skipped_conflict += 1
            continue
        # promote all authority rows with this zh; leave other zh as 候选
        for r in auth_rows[en_norm]:
            if r["zh"] != zh:
                continue
            if r["status"] == "已核":
                continue
            con.execute(
                "UPDATE terms SET status='已核', note=COALESCE(note,'') || ? "
                "WHERE id=?",
                ("|promote_auth_consensus_2026-11-17", r["id"]),
            )
            promoted += 1
        chosen.append((en_norm, zh, n, ",".join(sorted(sources))))

    con.commit()

    # export glossary: 已核 morph + 权威一致
    OUT.mkdir(parents=True, exist_ok=True)
    gloss_path = OUT / "glossary_多毛类_形态.tsv"
    # pick best zh per en from 已核 first, else auth consensus
    best: dict[str, tuple[str, str, str]] = {}
    for r in con.execute(
        "SELECT en, en_norm, zh, source, status, page FROM terms "
        "WHERE domain='分类学' AND status='已核' ORDER BY id"
    ):
        if not morphish(r["en"], r["zh"]):
            continue
        if r["en_norm"] not in best:
            best[r["en_norm"]] = (r["en"], r["zh"], f"{r['source']} p.{r['page'] or ''}")

    lines = ["source\ttarget\tvariants\tnote"]
    for en_norm, (en, zh, note) in sorted(best.items(), key=lambda x: x[1][0].lower()):
        lines.append(f"{en}\t{zh}\t\t{note}")
    gloss_path.write_text("\n".join(lines) + "\n", encoding="utf8")

    stats = {
        "promoted_rows": promoted,
        "consensus_terms": len(chosen),
        "skipped_conflict_en": skipped_conflict,
        "glossary_rows": len(best),
        "glossary": str(gloss_path),
        "yiku_status": dict(con.execute("SELECT status, COUNT(*) FROM terms GROUP BY status")),
        "taxonomy_verified": con.execute(
            "SELECT COUNT(*) FROM terms WHERE domain='分类学' AND status='已核'"
        ).fetchone()[0],
    }
    (OUT / "promote_stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf8"
    )
    # append report section
    if REPORT.exists():
        extra = [
            "",
            "## 升核与导出（全部推进，Cursor）",
            f"- 权威源一致形态词升核行数：**{promoted}**（共识词条 {len(chosen)}；冲突跳过 {skipped_conflict}）",
            f"- 导出 glossary：`{gloss_path}`（{len(best)} 行）",
            f"- 分类学「已核」合计：**{stats['taxonomy_verified']}**",
            "- 用法：`--glossary` 指向该 TSV，配合 `--engine none` 试译",
            "",
        ]
        REPORT.write_text(REPORT.read_text(encoding="utf8").rstrip() + "\n" + "\n".join(extra), encoding="utf8")

    print(json.dumps(stats, ensure_ascii=False, indent=2))
    print("sample consensus:")
    for row in chosen[:15]:
        print(" ", row)


if __name__ == "__main__":
    main()
