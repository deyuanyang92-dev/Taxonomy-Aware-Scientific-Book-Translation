#!/usr/bin/env python3
"""模型比测：同一提示词，多个 engine 翻译若干样段，自动评分，再生成盲评目录。

工作目录 D 的约定：
  D/src/<段>.txt        样段原文（每段一个文件）
  D/terms/<段>.md       该段术语表（yiku table 的输出；`terms` 子命令可生成）
  D/system.md           系统提示词（缺省由 RULES + 领域包 + STYLE + 输出要求拼成，并存盘备查）
  D/out/<engine>/<段>.md  各 engine 的译文
  D/usage.tsv           llm_engines 记录的 token 与耗时
  D/scores.tsv  D/term_miss.tsv   `eval` 的结果
  D/blind/<段>/A.md …   盲评用译文（随机字母）；D/blind_key_<段>.json 字母 -> engine 的映射（评完再看）
  D/盲评_<段>.md        盲评记录表（评者填 重大/轻微）

子命令（先 run，再 eval，再 blind，评完用 tally 汇总）：
  bench.py terms D [--domain 分类学] [--scope 科名]
  bench.py run   D --engines deepseek-flash,claude-sonnet,codex [--domain 分类学] [-j 1]
  bench.py eval  D
  bench.py blind D [--seed 1]
  bench.py tally D

评分只是粗筛：术语落实率只算「已核」且原文出现的术语，按字面匹配译名；数字、学名看是否原样保留；
汉字/原文字符比低于 0.05 标「疑似拒译」。质量以盲评为准，评者最好不是参赛模型之一，否则会偏向自己所属的一家。
"""
from __future__ import annotations

import argparse
import collections
import json
import random
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import direct_mode  # noqa: E402
import llm_engines  # noqa: E402

PENDING_HEAD = direct_mode.PENDING_HEAD
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
# 拉丁学名粗筛里要排除的普通大写词（句首词等）
LATIN_STOP = {"Morphology", "Systematics", "Chaetae", "Each", "Like", "Detailed", "This", "Living", "Antennae", "Hanson"}


# ---------------------------------------------------------------- 评分

def verified_terms(terms_md: str) -> list[tuple[str, str]]:
    """从 yiku 术语表（Markdown 表格）取 状态=已核 的 (英文, 译名)。"""
    rows = []
    for line in terms_md.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 4 and cells[3] == "已核" and cells[0] != "英文":
            rows.append((cells[0], cells[1]))
    return rows


def present_en(en: str, src: str) -> bool:
    pat = r"(?<![A-Za-z])" + re.escape(en).replace(r"\ ", r"[\s-]+") + r"(?:s|es)?(?![A-Za-z])"
    return re.search(pat, src, re.I) is not None


def zh_variants(zh: str) -> set[str]:
    v = {zh, re.sub(r"[（(].*?[)）]", "", zh), re.split(r"[；;]", zh)[0]}
    return {x.strip() for x in v if x.strip()}


def _norm_range(s: str) -> str:
    return re.sub(r"[–—～~]", "-", s)


def score(src: str, terms_md: str, translation: str) -> dict[str, object]:
    """对一份译文打自动分。返回术语 (命中, 应有)、数字、学名、汉字数、汉字/原文字符、待定术语行数、疑似拒译、漏掉的术语。"""
    body = translation.split(PENDING_HEAD)[0]
    terms = [(e, z) for e, z in verified_terms(terms_md) if present_en(e, src)]
    miss = [(e, z) for e, z in terms if not any(v in body for v in zh_variants(z))]
    nums = re.findall(r"\d+(?:[.,–-]\d+)*", src)
    body_n = _norm_range(body)
    nums_ok = sum(1 for x in nums if _norm_range(x) in body_n)
    latin = {w for w in re.findall(r"\b[A-Z][a-z]{3,}(?:idae|inae|ida|ella|ia|us|is|a)\b", src) if w not in LATIN_STOP}
    latin_ok = sum(1 for w in latin if w in body)
    zh_chars = len(re.findall(r"[一-鿿]", body))
    ratio = zh_chars / max(len(src), 1)
    pend = 0
    if PENDING_HEAD in translation:
        pend = len([ln for ln in translation.split(PENDING_HEAD, 1)[1].splitlines() if ln.strip()])
    return {
        "terms": (len(terms) - len(miss), len(terms)), "nums": (nums_ok, len(nums)),
        "latin": (latin_ok, len(latin)), "zh_chars": zh_chars, "ratio": round(ratio, 3),
        "pending": pend, "refused": len(src) > 500 and ratio < direct_mode.MIN_ZH_RATIO, "miss": miss,
    }


def cmd_eval(d: Path) -> int:
    rows, miss_lines = [], []
    agg: dict[str, list[int]] = collections.defaultdict(lambda: [0] * 6)
    for md in sorted((d / "out").glob("*/*.md")):
        engine, seg = md.parent.name, md.stem
        src_f, terms_f = d / "src" / f"{seg}.txt", d / "terms" / f"{seg}.md"
        if not src_f.exists():
            continue
        s = score(src_f.read_text(encoding="utf8"), terms_f.read_text(encoding="utf8") if terms_f.exists() else "",
                  md.read_text(encoding="utf8"))
        t, n, lt = s["terms"], s["nums"], s["latin"]
        assert isinstance(t, tuple) and isinstance(n, tuple) and isinstance(lt, tuple)
        rows.append([engine, seg, f"{t[0]}/{t[1]}", f"{n[0]}/{n[1]}", f"{lt[0]}/{lt[1]}", s["zh_chars"], s["ratio"],
                     s["pending"], "疑似拒译" if s["refused"] else ""])
        miss = s["miss"]
        assert isinstance(miss, list)
        miss_lines += [f"{engine}\t{seg}\t{e}\t{z}" for e, z in miss]
        a = agg[engine]
        for k, (x, y) in enumerate((t, n, lt)):
            a[2 * k] += x
            a[2 * k + 1] += y
    head = "engine\t段\t术语落实\t数字\t学名\t汉字\t汉字/原文字符\t待定术语行\t备注\n"
    (d / "scores.tsv").write_text(head + "".join("\t".join(map(str, r)) + "\n" for r in rows), encoding="utf8")
    (d / "term_miss.tsv").write_text("\n".join(miss_lines) + ("\n" if miss_lines else ""), encoding="utf8")
    for e, a in sorted(agg.items()):
        print(f"{e:16s} 术语 {a[0]}/{a[1]} ({a[0] / max(a[1], 1):.0%})  数字 {a[2]}/{a[3]}  学名 {a[4]}/{a[5]}")
    return 0


# ---------------------------------------------------------------- 术语表与翻译

def cmd_terms(d: Path, domain: str, scope: str | None) -> int:
    for src in sorted((d / "src").glob("*.txt")):
        out = d / "terms" / f"{src.stem}.md"
        if out.exists():
            continue
        sc = direct_mode.detect_scope(src.read_text(encoding="utf8")) if scope is None else scope
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(direct_mode.yiku_table(src, domain, sc), encoding="utf8")
        print("术语表", out)
    return 0


def system_prompt(d: Path, domain: str, book_desc: str, notes: str) -> str:
    f = d / "system.md"
    if f.exists():
        return f.read_text(encoding="utf8")
    s = direct_mode.build_system("translate", domain, book_desc, notes)
    f.write_text(s, encoding="utf8")
    return s


def run_one(d: Path, engine: str, seg: str, system: str) -> str:
    p = d / "out" / engine / f"{seg}.md"
    if p.exists() and p.stat().st_size > 200:
        return f"{engine} {seg} 已有，跳过"
    terms_f = d / "terms" / f"{seg}.md"
    terms = terms_f.read_text(encoding="utf8") if terms_f.exists() else ""
    user = direct_mode.user_translate(terms, (d / "src" / f"{seg}.txt").read_text(encoding="utf8"))
    t0 = time.time()
    try:
        text, usage = llm_engines.call(engine, system, user, tag=f"bench/{seg}", usage_file=d / "usage.tsv")
    except llm_engines.EngineError as e:
        with open(d / "失败记录.txt", "a", encoding="utf8") as f:
            f.write(f"{time.strftime('%F %T')} {engine} {seg}：{e}\n")
        return f"{engine} {seg} 失败：{e}"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf8")
    return f"{engine} {seg} {len(text)} 字符 {usage.get('output_tokens')} token {time.time() - t0:.0f}s"


def cmd_run(d: Path, engines: list[str], domain: str, book_desc: str, notes: str, jobs: int) -> int:
    bad = [e for e in engines if e not in llm_engines.ENGINES]
    if bad:
        print(f"未知 engine：{bad}；可选 {llm_engines.ENGINES}", file=sys.stderr)
        return 2
    segs = sorted(p.stem for p in (d / "src").glob("*.txt"))
    if not segs:
        print(f"{d}/src 里没有样段 .txt", file=sys.stderr)
        return 2
    system = system_prompt(d, domain, book_desc, notes)
    with ThreadPoolExecutor(max(jobs, 1)) as ex:
        for msg in ex.map(lambda es: run_one(d, es[0], es[1], system), [(e, s) for e in engines for s in segs]):
            print(msg, flush=True)
    return 0


# ---------------------------------------------------------------- 盲评

def cmd_blind(d: Path, seed: int) -> int:
    rng = random.Random(seed)
    segs = sorted(p.stem for p in (d / "src").glob("*.txt"))
    for seg in segs:
        outs = sorted(p for p in (d / "out").glob(f"*/{seg}.md") if p.stat().st_size > 0)
        if not outs:
            continue
        rng.shuffle(outs)
        key = {}
        for letter, p in zip(LETTERS, outs):
            key[letter] = p.parent.name
            dst = d / "blind" / seg / f"{letter}.md"
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(p.read_text(encoding="utf8"), encoding="utf8")
        (d / f"blind_key_{seg}.json").write_text(json.dumps({seg: key}, ensure_ascii=False), encoding="utf8")
        sheet = d / f"盲评_{seg}.md"
        if not sheet.exists():
            rows = "".join(f"| {k} |  |  |  |\n" for k in key)
            sheet.write_text(
                f"# 盲评 {seg}\n评者：（填）；评时不看映射 blind_key_{seg}.json。\n"
                "重大=改变意思或违反硬规则；轻微=表达/格式\n\n| 编号 | 重大 | 轻微 | 记录 |\n|---|---|---|---|\n" + rows,
                encoding="utf8")
        print(f"{seg}：{len(key)} 份 -> {d / 'blind' / seg}")
    return 0


def tally(d: Path) -> dict[str, list[int]]:
    """汇总盲评记录表：engine -> [重大, 轻微, 评过的段数]。没填数字的行不计。"""
    totals: dict[str, list[int]] = collections.defaultdict(lambda: [0, 0, 0])
    for sheet in sorted(d.glob("盲评_*.md")):
        seg = sheet.stem[len("盲评_"):]
        kf = d / f"blind_key_{seg}.json"
        if not kf.exists():
            continue
        key = next(iter(json.loads(kf.read_text(encoding="utf8")).values()))
        for line in sheet.read_text(encoding="utf8").splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) >= 3 and cells[0] in key and cells[1].isdigit() and cells[2].isdigit():
                t = totals[key[cells[0]]]
                t[0] += int(cells[1])
                t[1] += int(cells[2])
                t[2] += 1
    return totals


def cmd_tally(d: Path) -> int:
    for e, (maj, minor, n) in sorted(tally(d).items(), key=lambda kv: (kv[1][0], kv[1][1])):
        print(f"{e:16s} 重大 {maj}  轻微 {minor}  （{n} 段）")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="模型比测：run -> eval -> blind -> tally")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("terms", "run", "eval", "blind", "tally"):
        p = sub.add_parser(name)
        p.add_argument("dir")
        if name in ("terms", "run"):
            p.add_argument("--domain", default="分类学")
        if name == "terms":
            p.add_argument("--scope", default=None)
        if name == "run":
            p.add_argument("--engines", required=True, help="逗号分隔：" + ",".join(llm_engines.ENGINES))
            p.add_argument("--book-desc", default="")
            p.add_argument("--notes", default="", help="附加说明文件")
            p.add_argument("-j", type=int, default=1)
        if name == "blind":
            p.add_argument("--seed", type=int, default=1)
    a = ap.parse_args(argv)
    d = Path(a.dir)
    if a.cmd == "terms":
        return cmd_terms(d, a.domain, a.scope)
    if a.cmd == "run":
        notes = Path(a.notes).read_text(encoding="utf8") if a.notes else ""
        return cmd_run(d, [e for e in a.engines.split(",") if e], a.domain, a.book_desc, notes, a.j)
    if a.cmd == "eval":
        return cmd_eval(d)
    if a.cmd == "blind":
        return cmd_blind(d, a.seed)
    return cmd_tally(d)


if __name__ == "__main__":
    sys.exit(main())
