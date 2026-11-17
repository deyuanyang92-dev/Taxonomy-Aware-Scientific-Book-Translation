#!/usr/bin/env python3
"""从本地知识库学习多毛类术语 → 写入 yiku（候选），并输出学习小结。

依据：知识库.sqlite（8376 条带页码）+ ANNiKEY 英文定义；主库 yiku.db。
规则：只写「候选」；过滤明显 OCR/噪声对；不覆盖已核。
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "yiku"))
from yiku import db as D  # noqa: E402

YIKU = Path("/mnt/p/翻译-译作/yiku/yiku.db")
KB = Path("/mnt/p/翻译-译作/一些经典译作/知识库/知识库.sqlite")
ANNI = Path("/mnt/p/翻译-译作/参考资料/ANNiKEY术语表/ANNiKEY_术语定义.tsv")
OUT = Path("/mnt/p/翻译-译作/yiku/learning_2026-11-17")
REPORT = Path("/root/github/Taxonomy-Aware-Scientific-Book-Translation/docs/research/2026-11-17/local_polychaete_term_learning.md")

# 形态/分类高频英文词干（助过滤噪声）；过短人名等另剔
MORPH_HINT = re.compile(
    r"(?i)\b(prostom|peristom|parapod|chaet|seta|antenna|palp|cirri|cirrus|"
    r"acicul|neuropod|notopod|pygid|pharynx|probosc|mandib|maxilla|"
    r"segment|setiger|branchi|elytr|uncin|opercul|tube|collar|"
    r"nuchal|anal|dorsal|ventral|lateral|anterior|posterior|"
    r"family|genus|species|type|holotype|paratype|diagnosis|"
    r"synonym|distribution|ecology|habitat)\b"
)
CJK = re.compile(r"[\u4e00-\u9fff]")
BAD_ZH = re.compile(r"(应用|一文|标志着|有说服力|深入研究|开始探讨)")


def ok_pair(en: str, zh: str) -> bool:
    en, zh = en.strip(), zh.strip()
    if not en or not zh or len(en) < 3 or len(en) > 48:
        return False
    if len(zh) < 2 or len(zh) > 16:
        return False
    if not CJK.search(zh):
        return False
    if re.search(r"[A-Za-z]{3,}", zh):  # 中文侧夹长英文
        return False
    if BAD_ZH.search(zh):
        return False
    if re.fullmatch(r"[A-Z][a-z]+", en) and en[0].isupper() and " " not in en:
        # 单独大写开头词：只要形态提示才收（否则多是人名）
        if not MORPH_HINT.search(en):
            return False
    # 明显句子碎片
    if "。" in zh or "，" in zh:
        return False
    return True


def learn_kb(con) -> dict:
    kb = sqlite3.connect(f"file:{KB}?mode=ro", uri=True)
    kb.row_factory = sqlite3.Row
    sources = list(kb.execute("SELECT source, COUNT(*) n FROM terms GROUP BY source ORDER BY n DESC"))
    print("KB sources:", [(r["source"], r["n"]) for r in sources])

    # 登记来源（志书/专著 = authority；论文 = thesis）
    kind_map = {
        "动物志09": ("authority", 1, 1997, "中国动物志 多毛纲 叶须虫目"),
        "动物志33": ("authority", 1, 2004, "中国动物志 多毛纲 沙蚕目"),
        "动物志46": ("authority", 1, 2012, "中国动物志 星虫螠虫"),
        "动物志54": ("authority", 1, 2014, "中国动物志 多毛纲 缨鳃虫目"),
        "近海1988": ("authority", 2, 1988, "杨德渐孙瑞平 中国近海多毛环节动物"),
        "杨德渐2006": ("authority", 2, 2006, "杨德渐相关专著/论文（知识库）"),
        "杨德渐2013": ("authority", 2, 2013, "杨德渐相关（知识库）"),
        "论文_近海沙蚕科": ("thesis", 6, 1981, "吴宝铃等 中国近海沙蚕科研究"),
        "论文_蔡文倩_索沙蚕": ("thesis", 6, None, "蔡文倩 索沙蚕科"),
        "论文_隋吉星_双栉虫蛰龙介": ("thesis", 6, None, "隋吉星 双栉虫蛰龙介"),
        "吴旭文2013": ("thesis", 6, 2013, "吴旭文 矶沙蚕科欧努菲虫科"),
        "王跃云2017": ("thesis", 6, 2017, "王跃云 磷虫科竹节虫科"),
        "周进2008": ("thesis", 6, 2008, "周进（知识库）"),
        "孙悦2018": ("thesis", 6, 2018, "孙悦（知识库）"),
    }
    added = rejected = 0
    by_src: Counter[str] = Counter()
    samples = []
    for src_key, kind, tier, year, title in [
        (k, *v) for k, v in kind_map.items()
    ]:
        D.add_source(con, f"kb_{src_key}", title, kind, tier=tier, domain="分类学",
                     path=str(KB), note="从知识库.sqlite terms 导入（候选）", year=year)
        rows = kb.execute(
            "SELECT en, zh, page, context FROM terms WHERE source=? AND status IS NOT '否决'",
            (src_key,),
        )
        for r in rows:
            en, zh = (r["en"] or "").strip(), (r["zh"] or "").strip()
            if not ok_pair(en, zh):
                rejected += 1
                continue
            n = D.add_term(
                con, en, zh, f"kb_{src_key}",
                domain="分类学", scope="多毛类",
                page=str(r["page"] or ""),
                context=(r["context"] or "")[:200],
                status="候选",
                note="local_kb_learn_2026-11-17",
            )
            if n:
                added += n
                by_src[src_key] += 1
                if len(samples) < 20:
                    samples.append((en, zh, src_key, r["page"]))
    con.commit()
    kb.close()
    return {"added": added, "rejected": rejected, "by_src": dict(by_src), "samples": samples}


def learn_annikey(con) -> dict:
    """ANNiKEY 无中文：登记为英文义项库（source），术语以 en=en、zh=〔英〕暂存不入库中文定名。
    只把词条写入 sidecar TSV 供定名时查义项。"""
    if not ANNI.exists():
        return {"ok": False}
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    text = ANNI.read_text(encoding="utf-8", errors="replace").splitlines()
    header = text[0].split("\t")
    for ln in text[1:]:
        cols = ln.split("\t")
        if len(cols) < 2:
            continue
        term, definition = cols[0].strip(), cols[1].strip()
        if term and definition:
            rows.append((term, definition[:300]))
    out = OUT / "ANNiKEY_en_definitions.tsv"
    out.write_text(
        "en\tdefinition\n" + "\n".join(f"{a}\t{b}" for a, b in rows) + "\n",
        encoding="utf8",
    )
    D.add_source(con, "ANNiKEY_2025", "ANNiKEY glossary v1.01 Glasby et al.",
                 "external", tier=8, domain="分类学", path=str(ANNI),
                 note="英文定义；中文定名须另据志书", year=2025)
    con.commit()
    return {"ok": True, "n": len(rows), "path": str(out)}


def yiku_stats(con) -> dict:
    n = con.execute("SELECT COUNT(*) FROM terms").fetchone()[0]
    by_st = dict(con.execute("SELECT status, COUNT(*) FROM terms GROUP BY status"))
    by_dom = dict(con.execute("SELECT domain, COUNT(*) FROM terms GROUP BY domain"))
    poly = con.execute(
        "SELECT COUNT(*) FROM terms WHERE domain='分类学' AND (scope LIKE '%多毛%' OR note LIKE '%local_kb%')"
    ).fetchone()[0]
    return {"total": n, "by_status": by_st, "by_domain": by_dom, "polychaete_related": poly}


def style_notes() -> list[str]:
    """从知识库 passages 抽样看志书表述（只读统计）。"""
    kb = sqlite3.connect(f"file:{KB}?mode=ro", uri=True)
    notes = []
    try:
        n = kb.execute("SELECT COUNT(*) FROM passages").fetchone()[0]
        notes.append(f"形态/描述段落 passages≈{n}")
        # 常见「具N」模式
        for pat, label in [
            ("%具%个%", "具…个"),
            ("%长于%", "长于"),
            ("%短于%", "短于"),
            ("%疣足%", "疣足"),
            ("%刚毛%", "刚毛"),
            ("%口前叶%", "口前叶"),
        ]:
            c = kb.execute("SELECT COUNT(*) FROM passages WHERE text LIKE ?", (pat,)).fetchone()[0]
            notes.append(f"  passages 含「{label}」: {c}")
    finally:
        kb.close()
    return notes


def write_report(stats: dict, kb_res: dict, ann: dict, style: list[str]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# 本地多毛类文献术语学习（2026-11-17）",
        "",
        "## 家底",
        "- docstore registry≈2948 条，多毛/环节相关约 2920",
        "- 知识库：12 源、3478 页、8376 条 en–zh、10227 段 passages",
        "- OCR：动物志 09/33/46/54、近海1988、若干学位论文",
        "- ANNiKEY：518 条英文形态定义",
        f"- yiku 主库：`{YIKU}`",
        "",
        "## 本轮动作",
        f"- 从知识库过滤导入 **候选** {kb_res['added']} 条（拒收噪声 {kb_res['rejected']}）",
        f"- 分源：{kb_res['by_src']}",
        f"- ANNiKEY 英文定义导出：{ann}",
        "",
        "## 导入样例（候选，待核）",
    ]
    for en, zh, src, page in kb_res.get("samples", []):
        lines.append(f"- `{en}` → {zh}（{src} p.{page}）")
    lines += ["", "## yiku 现状", f"```json\n{json.dumps(stats, ensure_ascii=False, indent=2)}\n```",
              "", "## 志书表述信号（passages）", *[f"- {s}" for s in style],
              "", "## 结论",
              "1. **有用**：本地文献已足够支撑术语库；主杠杆是「有出处的 en–zh + 异写」而非整句 TM。",
              "2. 知识库原 8376 条噪声不少（OCR/人名/句碎片）；本轮用规则过滤后再进 yiku，一律 **候选**。",
              "3. 下一步：按志书页抽核高频形态词（口前叶/疣足/刚毛…）升「已核」；ANNiKEY 只助义项不直接给中文。",
              "4. 译书时 `--engine none` + 本库 glossary，可继续压 LLM token。",
              ""]
    REPORT.write_text("\n".join(lines), encoding="utf8")
    print("wrote", REPORT)


def main() -> None:
    assert YIKU.exists(), YIKU
    assert KB.exists(), KB
    con = D.connect(YIKU)
    before = yiku_stats(con)
    print("BEFORE", before)
    kb_res = learn_kb(con)
    print("KB import", kb_res["added"], "rejected", kb_res["rejected"])
    ann = learn_annikey(con)
    print("ANNiKEY", ann)
    after = yiku_stats(con)
    print("AFTER", after)
    style = style_notes()
    for s in style:
        print(s)
    write_report(after, kb_res, ann, style)
    # sidecar stats
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "import_stats.json").write_text(
        json.dumps({"before": before, "after": after, "kb": kb_res, "annikey": ann},
                   ensure_ascii=False, indent=2),
        encoding="utf8",
    )


if __name__ == "__main__":
    main()
