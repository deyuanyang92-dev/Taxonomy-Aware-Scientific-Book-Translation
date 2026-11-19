"""yiku 命令行。所有模型（Codex、Claude、DeepSeek……）都通过这些命令用同一个术语库。"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from . import db as D
from . import decide as DC
from . import extract as X
from . import ingest as I
from . import match as M


def _scope(s: str | None) -> set[str]:
    return {x.strip() for x in (s or "").split(";") if x.strip()}


def _read_tsv(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def _write_tsv(path, header, rows):
    with open(path, "w", encoding="utf8", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def _text(path, ocr="auto"):
    return I.full_text(I.read(path, ocr))


# ---------- 命令 ----------

def cmd_source(a, con):
    if a.action == "add":
        D.add_source(con, a.key, a.title or a.key, a.kind, a.tier, a.domain, a.path, a.note, a.year)
        print(f"已登记来源 {a.key}")
    elif a.action == "set":
        D.set_source(con, a.key, tier=a.tier, year=a.year, note=a.note)
        print(f"已更新来源 {a.key}")
    else:
        for r in con.execute("SELECT s.*, (SELECT count(*) FROM terms t WHERE t.source=s.key) n "
                             "FROM sources s ORDER BY tier, year DESC, key"):
            print(f"{r['tier']}\t{r['key']}\t{r['year'] or '-'}\t{r['kind']}\t{r['domain']}\t{r['n']}条\t{r['title']}")


def cmd_import(a, con):
    n = 0
    for r in _read_tsv(a.tsv):
        en, zh = (r.get(a.en) or "").strip(), (r.get(a.zh) or "").strip()
        if not en or not zh or zh in ("—", "-", "－"):
            continue
        status = a.status
        if a.status_col:
            v = (r.get(a.status_col) or "").strip()
            status = "已核" if v in a.verified_values.split(",") else "候选"
        n += D.add_term(con, en, zh, a.source,
                        domain=(r.get(a.domain_col) if a.domain_col else None) or a.domain,
                        scope=(r.get(a.scope_col) if a.scope_col else None) or "*",
                        page=r.get(a.page_col) if a.page_col else None,
                        context=r.get(a.context_col) if a.context_col else None,
                        status=status, note=r.get(a.note_col) if a.note_col else None)
    con.commit()
    print(f"新增 {n} 条（来源 {a.source}）")


def cmd_paren(a, con):
    text, marks = _text(a.file, a.ocr)
    cands = X.paren_pairs(text, marks)
    if a.out:
        _write_tsv(a.out, ["en", "zh", "page", "context"], [[c.en, c.zh, c.page, c.context] for c in cands])
        print(f"{len(cands)} 条候选写入 {a.out}（人工清理后用 yiku import 导入）")
        return
    n = sum(D.add_term(con, c.en, c.zh, a.source, a.domain, page=c.page, context=c.context) for c in cands)
    con.commit()
    print(f"抽出 {len(cands)} 条，新增候选 {n} 条")


def cmd_pair(a, con):
    en, _ = _text(a.en_file, a.ocr)
    zh, zmarks = _text(a.zh_file, a.ocr)
    if a.terms:
        terms = [x.strip() for x in Path(a.terms).read_text(encoding="utf8").splitlines() if x.strip()]
    elif a.auto:
        terms = X.auto_terms(en, a.min_freq)
    else:  # 默认：库里已有的英文术语 —— 看这位译者怎么译
        terms = [r[0] for r in con.execute("SELECT DISTINCT en FROM terms")]
    _, by_chapter = X.align_chapters(en, zh)
    print(f"术语 {len(terms)} 个；{'按章对齐' if by_chapter else '章数不符，整书按相对位置对齐（误差较大）'}",
          file=sys.stderr)
    res = X.pair_terms(en, zh, terms, a.window, zh_marks=zmarks)
    rows = []
    for t, cs in res.items():
        if not cs:
            continue
        known = D.best(con, t, a.domain)
        alts = ([f"{c.zh}({c.score})" for c in cs[1:]] + ["", "", ""])[:3]
        rows.append([t, cs[0].zh, *alts, cs[0].page, cs[0].context.replace("\t", " ").replace("\n", " "),
                     known.zh if known else ""])
    _write_tsv(a.out, ["en", "zh", "备选1", "备选2", "备选3", "页码", "上下文", "库中现译"], rows)
    print(f"{len(rows)} 条写入 {a.out}。核对 zh 列（可改、可删行）后：yiku import {a.out} --source {a.source} "
          f"--domain {a.domain} --page-col 页码 --context-col 上下文")


def _fallback(a):
    return D.resolve_fallback(a.domain, getattr(a, "fallback", None))


def cmd_lookup(a, con):
    cs = D.candidates(con, a.term, a.domain, _scope(a.scope), _fallback(a))
    if not cs:
        other = con.execute("SELECT DISTINCT domain FROM terms WHERE en_norm=? AND status!='否决' ORDER BY domain",
                            (D.norm(a.term),)).fetchall()
        if other:
            names = "、".join(r[0] for r in other)
            print(f"领域={a.domain} 下无此术语；其他领域有（{names}），加 --domain 查看")
        else:
            print("库中无此术语")
    for h in cs:
        print(f"{h.zh}\t{h.status}\t领域={h.domain}{'(回退)' if h.fallback else ''}\t范围={h.scope}\t{h.cite()}"
              f"\t层级{h.tier}\t{h.year or '-'}\t{h.note or ''}")


def cmd_table(a, con):
    usage = False if getattr(a, "no_usage", False) else None
    print(M.term_table(con, Path(a.src).read_text(encoding="utf8"), a.domain, _scope(a.scope),
                       _fallback(a), usage, getattr(a, "max_chars", M.DEFAULT_MAX_CHARS)))


def cmd_check(a, con):
    decisions: list[dict] = []
    if getattr(a, "decisions", None):
        decisions, errs = DC.read_files(a.decisions)
        for e in errs:
            print(f"决策日志忽略：{e}", file=sys.stderr)
    issues = M.check(con, Path(a.src).read_text(encoding="utf8"), Path(a.zh).read_text(encoding="utf8"),
                     a.domain, _scope(a.scope), _fallback(a), decisions)
    for i in issues:
        print(i.line())
    errors = sum(1 for i in issues if i.level == "error")
    print(f"共 {len(issues)} 处（错误 {errors}，提示 {len(issues) - errors}）", file=sys.stderr)
    return 1 if errors else 0


def cmd_decide(a, con):
    if a.action == "validate":
        bad = 0
        for f in a.files:
            ok, errs = DC.read_files([f])
            for e in errs:
                print(e)
            print(f"{f}：{len(ok)} 条合法，{len(errs)} 处错误")
            bad += len(errs)
        return 1 if bad else 0
    ok, errs = DC.read_files(a.files)
    for e in errs:
        print(f"忽略：{e}", file=sys.stderr)
    if a.action == "review":
        todo = DC.review(con, ok, a.domain, _scope(a.scope), _fallback(a))
        for r in todo:
            print(f"{r['en']} → {r['zh']}｜义项：{r['sense']}｜{';'.join(r['chunks'][:3])}｜{'；'.join(r['flags'])}"
                  f"｜理由：{r['reason']}｜库中候选：{'、'.join(r['candidates']) or '无'}")
        if a.out:
            Path(a.out).write_text("".join(json.dumps({k: v for k, v in r.items() if k not in ("count", "chunks", "candidates")},
                                                      ensure_ascii=False) + "\n" for r in todo), encoding="utf8")
            print(f"{len(todo)} 条写入 {a.out}（可在其中加 \"accept\": false 驳回，再 apply；flags 字段会被忽略）")
        print(f"共 {len(ok)} 条决策，须主会话裁定 {len(todo)} 条", file=sys.stderr)
        return 0
    if not a.book:
        print("apply 须指定 --book", file=sys.stderr)
        return 2
    if errs and not a.skip_invalid:
        print(f"有 {len(errs)} 处格式错误，未写入；修正后重试，或加 --skip-invalid 只写合法的", file=sys.stderr)
        return 1
    r = DC.apply(con, ok, a.book, a.domain, a.scope or "*", a.verified)
    print(f"新增 {r.added} 条、升级为已核 {r.upgraded} 条、并入义项 {r.merged} 条、驳回跳过 {r.skipped} 条、无效 {r.invalid} 条"
          f"（来源 决策_{a.book}，状态 {'已核' if a.verified else '候选'}）")
    return 0


def cmd_review(a, con):
    if a.action == "export":
        q = "SELECT t.*, s.tier FROM terms t JOIN sources s ON s.key=t.source WHERE t.status=?"
        args: list = [a.status]
        if a.domain:
            q += " AND t.domain=?"
            args.append(a.domain)
        rows = con.execute(q + " ORDER BY t.en_norm, s.tier, s.year DESC", args).fetchall()
        _write_tsv(a.tsv, ["id", "en", "zh", "domain", "scope", "source", "page", "context", "决定", "改为", "备注"],
                   [[r["id"], r["en"], r["zh"], r["domain"], r["scope"], r["source"], r["page"] or "",
                     (r["context"] or "").replace("\t", " ").replace("\n", " "), "", "", r["note"] or ""]
                    for r in rows])
        print(f"{len(rows)} 条写入 {a.tsv}。「决定」填 已核/否决，「改为」可改中文；然后 yiku review apply {a.tsv}")
    else:
        n = 0
        for r in _read_tsv(a.tsv):
            dec = (r.get("决定") or "").strip()
            if dec not in ("已核", "否决"):
                continue
            new = (r.get("改为") or "").strip()
            con.execute("UPDATE terms SET status=?, zh=COALESCE(NULLIF(?,''), zh), note=? WHERE id=?",
                        (dec, new, r.get("备注") or None, int(r["id"])))
            n += 1
        con.commit()
        print(f"已更新 {n} 条")


def cmd_wikidata(a, con):
    """Wikidata 中文标签：只作线索，入库为 external 层级候选。学名用 P225，其他用英文标签。"""
    D.add_source(con, "wikidata", "Wikidata 中文标签", "external")
    for term in a.terms:
        prop = "wdt:P225" if a.taxon else "rdfs:label"
        val = f'"{term}"' if a.taxon else f'"{term}"@en'
        q = (f"SELECT DISTINCT ?i ?zh WHERE {{ ?i {prop} {val} . ?i rdfs:label ?zh . "
             f"FILTER(lang(?zh) IN ('zh','zh-cn','zh-hans')) }} LIMIT 5")
        url = "https://query.wikidata.org/sparql?" + urllib.parse.urlencode({"query": q, "format": "json"})
        req = urllib.request.Request(url, headers={"User-Agent": "yiku/0.1 (terminology research tool)"})
        try:
            data = json.load(urllib.request.urlopen(req, timeout=30))
        except Exception as e:  # 网络失败不影响其他术语
            print(f"{term}\t查询失败：{e}")
            continue
        for b in data["results"]["bindings"]:
            zh, qid = b["zh"]["value"], b["i"]["value"].rsplit("/", 1)[-1]
            D.add_term(con, term, zh, "wikidata", a.domain, page=qid, note="网络标签，未确证")
            print(f"{term}\t{zh}\t{qid}")
    con.commit()


def cmd_stats(a, con):
    for r in con.execute("SELECT domain, status, count(*) n FROM terms GROUP BY domain, status ORDER BY domain"):
        print(f"{r['domain']}\t{r['status']}\t{r['n']}")
    # 未解决冲突：排第一、第二的译名都已核、领域范围相同、来源层级也相同、出版年也相同（或缺年份）
    # —— 排序无法裁决，须人工定。同层级但年份不同的，按新版优先自动定，单列「新版取代旧版」备查。
    unresolved, superseded = [], []
    for r in con.execute("SELECT DISTINCT en_norm, domain, scope FROM terms WHERE status='已核'"):
        sc = {x for x in r["scope"].split(";")} - {"*"}
        c = [h for h in D.candidates(con, r["en_norm"], r["domain"], sc)
             if h.status == "已核" and h.domain == r["domain"] and h.scope == r["scope"]]
        if len(c) > 1 and c[0].zh != c[1].zh and c[0].tier == c[1].tier:
            line = f"  {c[0].en}\t{r['domain']}\t" + "、".join(f"{h.zh}({h.cite()})" for h in c[:3])
            if c[0].year and c[1].year and c[0].year != c[1].year:
                superseded.append(line)
            else:
                unresolved.append(line)
    print(f"\n未解决冲突 {len(unresolved)} 条（同层级同年份来源给出不同已核译名，须裁定）：")
    print("\n".join(unresolved[:50]))
    print(f"\n新版取代旧版 {len(superseded)} 条（同层级、年份不同，取新版；首列为采用的译名）：")
    print("\n".join(superseded[:50]))


def build_parser():
    p = argparse.ArgumentParser(prog="yiku", description="领域化中英术语库")
    p.add_argument("--db", help="库文件（默认 $YIKU_DB 或 ~/.yiku/yiku.db）")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("source", help="登记/列出来源")
    s.add_argument("action", choices=["add", "set", "list"])
    s.add_argument("key", nargs="?")
    s.add_argument("--title")
    s.add_argument("--kind", default="authority", choices=sorted(D.KIND_TIER))
    s.add_argument("--tier", type=int)
    s.add_argument("--year", type=int, help="出版年；同层级来源不一致时新版优先")
    s.add_argument("--domain", default="*")
    s.add_argument("--path")
    s.add_argument("--note")

    s = sub.add_parser("import", help="从 TSV 导入术语")
    s.add_argument("tsv")
    s.add_argument("--source", required=True)
    s.add_argument("--en", default="en")
    s.add_argument("--zh", default="zh")
    s.add_argument("--domain", default="*")
    s.add_argument("--domain-col")
    s.add_argument("--scope-col")
    s.add_argument("--page-col")
    s.add_argument("--context-col")
    s.add_argument("--note-col")
    s.add_argument("--status", default="候选", choices=D.STATUSES)
    s.add_argument("--status-col", help="按此列判断是否已核")
    s.add_argument("--verified-values", default="已核,Y,图像核对,索引核对,OCR直接")

    for name, hlp in (("paren", "从中文论著抽「中文（English）」候选"),):
        s = sub.add_parser(name, help=hlp)
        s.add_argument("file")
        s.add_argument("--source", required=True)
        s.add_argument("--domain", default="*")
        s.add_argument("--out", help="只写 TSV 不入库")
        s.add_argument("--ocr", default="auto", choices=["auto", "always", "never"])

    s = sub.add_parser("pair", help="从中英对照书抽译者用字，写审核表")
    s.add_argument("en_file")
    s.add_argument("zh_file")
    s.add_argument("--source", required=True)
    s.add_argument("--domain", default="*")
    s.add_argument("--terms", help="英文术语清单，一行一个")
    s.add_argument("--auto", action="store_true", help="自动从原著挑候选术语")
    s.add_argument("--min-freq", type=int, default=5)
    s.add_argument("--window", type=int, default=400)
    s.add_argument("--out", required=True)
    s.add_argument("--ocr", default="auto", choices=["auto", "always", "never"])

    fb_help = ("回退领域：本领域没有时参考的其他领域（逗号/分号分隔；none=不回退）。"
               "默认 分类学->进化生物学，其他领域不回退")

    s = sub.add_parser("lookup", help="查一个术语的全部译名")
    s.add_argument("term")
    s.add_argument("--domain", default="*")
    s.add_argument("--scope")
    s.add_argument("--fallback", help=fb_help)

    for name, hlp in (("table", "为原文生成术语表（贴进任何模型的提示词）"), ("check", "检查译文术语一致性")):
        s = sub.add_parser(name, help=hlp)
        s.add_argument("src")
        if name == "check":
            s.add_argument("zh")
        s.add_argument("--domain", default="*")
        s.add_argument("--scope", help="类群，如 Sabellidae;Serpulidae")
        s.add_argument("--fallback", help=fb_help)
        if name == "table":
            s.add_argument("--no-usage", action="store_true", help="不从资料库取中文用例")
            s.add_argument("--max-chars", type=int, default=M.DEFAULT_MAX_CHARS, help="SOFT 节的长度预算（HARD 不截断）")
        else:
            s.add_argument("--decisions", nargs="+", help="术语决策日志 JSONL（文件或目录）；给了才按义项核对 SOFT 术语")

    s = sub.add_parser("decide", help="术语决策日志：校验 / 列出须裁定的 / 写回术语库")
    s.add_argument("action", choices=["validate", "review", "apply"])
    s.add_argument("files", nargs="+", help="term_decisions.jsonl（或目录）")
    s.add_argument("--domain", default="*")
    s.add_argument("--scope")
    s.add_argument("--fallback", help=fb_help)
    s.add_argument("--book", help="apply：书名，来源记为 决策_<book>")
    s.add_argument("--verified", action="store_true", help="apply：记为已核（默认候选；须主会话确认后才用）")
    s.add_argument("--skip-invalid", action="store_true", help="apply：跳过格式错误的行而不是整体拒绝")
    s.add_argument("--out", help="review：把须裁定的条目写成 JSONL，供编辑后 apply")

    s = sub.add_parser("review", help="导出候选供裁定 / 应用裁定")
    s.add_argument("action", choices=["export", "apply"])
    s.add_argument("tsv")
    s.add_argument("--status", default="候选")
    s.add_argument("--domain")

    s = sub.add_parser("wikidata", help="查 Wikidata 中文标签（只作线索）")
    s.add_argument("terms", nargs="+")
    s.add_argument("--taxon", action="store_true", help="按学名(P225)查")
    s.add_argument("--domain", default="*")

    sub.add_parser("stats", help="统计与冲突")
    return p


def main(argv=None):
    a = build_parser().parse_args(argv)
    con = D.connect(a.db)
    rc = globals()["cmd_" + a.cmd](a, con)
    sys.exit(rc or 0)


if __name__ == "__main__":
    main()
