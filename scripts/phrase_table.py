#!/usr/bin/env python3
"""分类文献短语表：高频固定搭配只译一次，全书（及同语种后续书）共用；顺带学会 Google 在这些短语上的固定错法。

依据（2026-11-15，Hartmann-Schröder 德文 17 份 479 万字符，docs/research/2026-11-15/taxo_token_economy.md）：
整句、整「骨架」很少重复（骨架重复 ≥2 次只覆盖描述 23%），但短语层高度重复：最常见 1000 个 2–5 词短语覆盖
描述/标签段词次 38%，2000 个 45%。

    python3 phrase_table.py extract CORPUS.md... -o cand.tsv --sl de [--top 2000 --min-freq 15 --max-n 8]
    python3 phrase_table.py patterns CORPUS.md... -o patterns.tsv --sl de   # 句式骨架
    python3 phrase_table.py translate cand.tsv --sl de --tl en --glossary G.tsv [--engine deepseek-flash]   # 写 en 列
    python3 phrase_table.py google cand.tsv --sl de --tl en                                                  # 写 google 列（免费）
    python3 phrase_table.py export cand.tsv -o phrases_de_en.tsv    # 术语表格式：de | en | variants(google=en) | evidence

导出的表与术语表同格式，transqa.terms.normalize 以原文为锚使用（原文有该短语，译文里的 Google 写法换成规范写法）。
数字以 # 表示的短语只导出到 en 列供提示词与风险检查用，不作替换（variants 留空）。
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FIELDS = ["de", "freq", "en", "google", "status"]
# 短语首尾不应是这些（残片）：德文冠词、连词、介词；英文同理
EDGE_STOP = {
    "de": set("der die das den dem des ein eine einer einem eines und oder zu zum zur im am vom bei mit von aus auf "
              "in an als wie bis sowie jedoch aber nur noch auch sehr etwas".split()),
    "en": set("the a an and or of to in on at by with from as for".split()),
}


def ngrams(text: str) -> list[list[str]]:
    paras = []
    for p in re.split(r"\n\s*\n", text):
        if p.lstrip().startswith("<!--"):
            continue
        for clause in re.split(r"[.;:()\[\]]", p):
            w = ["#" if x.isdigit() else x for x in re.findall(r"[^\W\d_]+|\d+", clause)]
            if w:
                paras.append(w)
    return paras


def extract(
    files: list[str],
    sl: str,
    top: int,
    min_freq: int,
    kinds: set[str] | None = None,
    *,
    max_n: int = 5,
) -> list[dict]:
    from transqa.taxoblocks import kind
    cnt: Counter = Counter()
    stop = EDGE_STOP.get(sl, set())
    ns = tuple(range(2, max(2, max_n) + 1))
    for f in files:
        for p in re.split(r"\n\s*\n", Path(f).read_text(encoding="utf-8")):
            if p.lstrip().startswith("<!--") or (kinds and kind(p, sl) not in kinds):
                continue
            for w in ngrams(p):
                for n in ns:
                    for i in range(len(w) - n + 1):
                        g = tuple(w[i:i + n])
                        if g[0].lower() in stop or g[-1].lower() in stop or g.count("#") == n:
                            continue
                        if not any(len(x) >= 4 and x != "#" for x in g):
                            continue
                        cnt[g] += 1
    cand = [(g, c) for g, c in cnt.items() if c >= min_freq]
    cand.sort(key=lambda x: (-x[1], -len(x[0])))
    keep: list[tuple[tuple[str, ...], int]] = []
    for g, c in cand:
        # 被更长、频次相近（≥80%）的短语包含的，丢掉
        s = " ".join(g)
        if any(len(h) > len(g) and c2 >= 0.8 * c and f" {s} " in f" {' '.join(h)} " for h, c2 in keep):
            continue
        keep.append((g, c))
        if len(keep) >= top:
            break
    return [{"de": " ".join(g), "freq": c, "en": "", "google": "", "status": ""} for g, c in keep]


# 句式骨架：实词保留，数字→#，学名样→SP，常见功能词→_
_FUNC = {
    "de": set(
        "der die das den dem des ein eine einer einem eines und oder zu zum zur im am vom "
        "bei mit von aus auf in an als wie bis sowie jedoch aber nur noch auch sehr etwas "
        "ist sind war waren wird werden hat haben hatte hatten sich".split()
    ),
    "en": set(
        "the a an and or of to in on at by with from as for is are was were be been being "
        "has have had do does did this that these those".split()
    ),
}


def _skeleton_token(w: str, sl: str) -> str:
    if w == "#" or w.isdigit():
        return "#"
    low = w.lower()
    if low in _FUNC.get(sl, set()):
        return "_"
    # 学名样：大写开头且后续小写较长，或全小写拉丁尾
    if re.match(r"^[A-Z][a-z]{3,}$", w) and low.endswith(
        ("us", "a", "um", "is", "ae", "ii", "orum", "ibus")
    ):
        return "SP"
    return w


def extract_patterns(
    files: list[str],
    sl: str,
    top: int,
    min_freq: int,
    kinds: set[str] | None = None,
) -> list[dict]:
    """抽取描述句式骨架（如 Prostomium _ # Augen），供提示词例句 / 风险对照。"""
    from transqa.taxoblocks import kind
    cnt: Counter = Counter()
    for f in files:
        text = Path(f).read_text(encoding="utf-8", errors="replace")
        for p in re.split(r"\n\s*\n", text):
            if p.lstrip().startswith("<!--") or (kinds and kind(p, sl) not in kinds):
                continue
            for w in ngrams(p):
                if len(w) < 4 or len(w) > 16:
                    continue
                sk = tuple(_skeleton_token(x, sl) for x in w)
                # 至少 2 个实词
                if sum(1 for t in sk if t not in {"_", "#", "SP"}) < 2:
                    continue
                cnt[sk] += 1
    rows = [{"pattern": " ".join(g), "freq": c} for g, c in cnt.items() if c >= min_freq]
    rows.sort(key=lambda r: (-r["freq"], -len(r["pattern"])))
    return rows[:top]


def _read(path: str) -> list[dict]:
    return list(csv.DictReader(open(path, encoding="utf-8"), delimiter="\t"))


def _write(path: str, rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=FIELDS, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


SYS = ("You translate short {sl} phrases from taxonomic descriptions of polychaetes into standard {tl} as used in "
       "taxonomic papers. '#' stands for a number; keep it. Use the glossary renderings exactly. Phrases are fragments: "
       "translate them as fragments, literally, without adding words. Return only a JSON object mapping each input "
       "number to its translation.")


def translate(path: str, sl: str, tl: str, glossary: str | None, engine: str, batch: int = 200) -> int:
    import llm_engines
    rows = _read(path)
    gl = ""
    if glossary:
        gl = "\n".join(" = ".join(ln.split("\t")[:2]) for ln in Path(glossary).read_text(encoding="utf-8").splitlines()[1:])
    sysmsg = SYS.format(sl=sl, tl=tl) + (f"\n\nGlossary ({sl} = {tl}):\n{gl}" if gl else "")
    todo = [i for i, r in enumerate(rows) if not r["en"]]
    done = 0
    for k in range(0, len(todo), batch):
        idx = todo[k:k + batch]
        user = "\n".join(f"{n}. {rows[i]['de']}" for n, i in enumerate(idx, 1))
        out, _ = llm_engines.call(engine, sysmsg, user, tag="phrase_table/translate",
                                  usage_file=str(Path(path).with_suffix(".usage.tsv")))
        m = re.search(r"\{.*\}", out, re.S)
        got = json.loads(m.group(0)) if m else {}
        for n, i in enumerate(idx, 1):
            v = got.get(str(n)) or got.get(n)
            if isinstance(v, str) and v.strip():
                rows[i]["en"] = v.strip()
                done += 1
        _write(path, rows)  # 每批写盘，可续跑
    return done


def google(path: str, sl: str, tl: str) -> int:
    import auto_translate
    rows = _read(path)
    g = auto_translate.Google(sl, tl, Path.home() / ".cache/yzz-translate/gtrans_cache.sqlite")
    todo = [r["de"].replace("#", "5") for r in rows if not r["google"]]
    g.g.prefetch(todo, 8)
    n = 0
    for r in rows:
        if not r["google"]:
            r["google"] = g.one(r["de"].replace("#", "5")).replace("5", "#")
            n += 1
    _write(path, rows)
    return n


def _term_fix(google_en: str, canon: str, targets: list[str]) -> bool:
    """规范译法含某个术语表定名、Google 译法没有 → 是术语错误（采纳为异写）。
    只是措辞不同（about the same length / about equally long）不采纳：短语残片单独译时模型的英语未必更好
    （1971 抽查 40 条：two long ones→two long、two on each side→on each side two 反而变差）。"""
    g, c = google_en.lower(), canon.lower()
    return any(t in c and t not in g for t in targets)


def export(path: str, out: str, glossary: str | None = None) -> int:
    rows = [r for r in _read(path) if r["en"] and r.get("status", "") != "reject"]
    targets: list[str] = []
    if glossary:
        targets = sorted({ln.split("\t")[1].strip().lower() for ln in Path(glossary).read_text(encoding="utf-8").splitlines()[1:]
                          if len(ln.split("\t")) > 1 and len(ln.split("\t")[1].strip()) >= 4}, key=len, reverse=True)
    lines = ["de\ten\tvariants\tevidence"]
    for r in rows:
        var = ""
        gg = (r.get("google") or "").strip().rstrip(".")
        if "#" not in r["de"] and gg and gg.lower() != r["en"].lower() and (not glossary or _term_fix(gg, r["en"], targets)):
            var = f"{gg}={r['en']}"
        lines.append(f"{r['de']}\t{r['en']}\t{var}\tphrase_table 频次 {r['freq']}；{r.get('status') or '候选'}")
    Path(out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(rows)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("extract")
    e.add_argument("files", nargs="+")
    e.add_argument("-o", "--out", required=True)
    e.add_argument("--sl", default="de")
    e.add_argument("--top", type=int, default=2000)
    e.add_argument("--min-freq", type=int, default=15)
    e.add_argument("--max-n", type=int, default=5, help="最长 n-gram（长短语可到 8）")
    e.add_argument("--kinds", default="description,locality,ecology,distribution,caption")
    ptn = sub.add_parser("patterns", help="抽取句式骨架（实词+#_/SP），供提示词/对照")
    ptn.add_argument("files", nargs="+")
    ptn.add_argument("-o", "--out", required=True)
    ptn.add_argument("--sl", default="de")
    ptn.add_argument("--top", type=int, default=400)
    ptn.add_argument("--min-freq", type=int, default=5)
    ptn.add_argument("--kinds", default="description,locality,ecology,distribution,caption")
    t = sub.add_parser("translate")
    t.add_argument("table")
    t.add_argument("--sl", default="de")
    t.add_argument("--tl", default="en")
    t.add_argument("--glossary")
    t.add_argument("--engine", default="deepseek-flash")
    g = sub.add_parser("google")
    g.add_argument("table")
    g.add_argument("--sl", default="de")
    g.add_argument("--tl", default="en")
    x = sub.add_parser("export")
    x.add_argument("table")
    x.add_argument("-o", "--out", required=True)
    x.add_argument("--glossary", help="只采纳「规范译法含术语表定名、Google 没有」的差异为异写")
    a = ap.parse_args(argv)
    if a.cmd == "extract":
        rows = extract(
            a.files,
            a.sl,
            a.top,
            a.min_freq,
            set(a.kinds.split(",")) if a.kinds else None,
            max_n=a.max_n,
        )
        _write(a.out, rows)
        print(f"短语 {len(rows)} → {a.out}")
    elif a.cmd == "patterns":
        rows = extract_patterns(
            a.files,
            a.sl,
            a.top,
            a.min_freq,
            set(a.kinds.split(",")) if a.kinds else None,
        )
        with open(a.out, "w", encoding="utf-8", newline="") as fp:
            w = csv.DictWriter(fp, fieldnames=["pattern", "freq"], delimiter="\t")
            w.writeheader()
            w.writerows(rows)
        print(f"句式 {len(rows)} → {a.out}")
    elif a.cmd == "translate":
        print(f"新译 {translate(a.table, a.sl, a.tl, a.glossary, a.engine)}")
    elif a.cmd == "google":
        print(f"Google {google(a.table, a.sl, a.tl)}")
    else:
        print(f"导出 {export(a.table, a.out, a.glossary)}")


if __name__ == "__main__":
    main()
