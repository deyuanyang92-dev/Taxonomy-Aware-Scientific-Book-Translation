"""docstore 命令行。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import adapters, qc, textify
from .store import LEVELS, Store, agent

SKIP_ADD = {"_资料库", "_本地知识库", "知识库", "参考库", "_work", "__pycache__", ".git"}
DOC_EXT = {".pdf"}
WRITE_CMDS = {"add", "text", "verify", "import", "pair", "rebuild", "set", "rename", "attach", "consensus", "qc", "postfix"}
WRITE_CMDS.add("proofread")


def _by(args) -> str:
    return agent(getattr(args, "by", None))


def _iter_files(paths: list[str]):
    for s in paths:
        p = Path(s)
        if p.is_file():
            yield p
            continue
        for dirpath, dirnames, filenames in os.walk(p):
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP_ADD and not d.startswith("."))
            for f in sorted(filenames):
                if Path(f).suffix.lower() in DOC_EXT:
                    yield Path(dirpath) / f


def cmd_add(st: Store, a) -> None:
    for f in _iter_files(a.paths):
        key, new = st.register(f, by=_by(a))
        d = st.doc(key)
        print(("新登记 " if new else "已登记 ") + f"{key}\t{d['kind']}\t{d['lang']}\t{d['domain']}\t{d['pages']}页\t{f.name}")


def cmd_text(st: Store, a) -> None:
    keys = a.keys
    if a.pending or not keys:
        keys = [d["key"] for d in st.docs() if d["path"] and Path(d["path"]).exists()
                and len(st.page_numbers(d["key"])) < (int(d["pages"] or 0))]
        keys.sort(key=lambda k: int(st.doc(k)["pages"] or 0) * (os.path.getsize(st.doc(k)["path"]) or 1))
    for k in keys:
        engines = [x.strip() for x in a.engines.split(",") if x.strip()]
        r = textify.textify(
            st,
            k,
            by=_by(a),
            workers=a.workers,
            dpi=a.dpi,
            limit=a.limit,
            engines=engines,
            vlm=a.vlm,
            pages=_parse_pages(a.pages),
            fix=not a.no_fix,
            layer_only=a.layer_only,
            ocr_threads=a.ocr_threads,
            log=lambda m: print(m, flush=True),
        )
        print(json.dumps(r, ensure_ascii=False), flush=True)


def _parse_pages(spec: str | None) -> list[int] | None:
    if not spec:
        return None
    out: set[int] = set()
    for chunk in spec.split(","):
        s = chunk.strip()
        if not s:
            continue
        if "-" in s:
            a, b = s.split("-", 1)
            x, y = int(a), int(b)
            for n in range(min(x, y), max(x, y) + 1):
                out.add(n)
        else:
            out.add(int(s))
    return sorted(out)


def cmd_consensus(st: Store, a) -> None:
    pages = _parse_pages(a.pages)
    r = textify.consensus(st, a.key, pages=pages, by=_by(a), dpi=a.dpi)
    print(json.dumps(r, ensure_ascii=False), flush=True)


def cmd_quality(st: Store, a) -> None:
    rows = []
    for p in st.pages(a.key):
        q = p.get("quality") or {}
        why = []
        if p["verify_level"] == "blank":
            continue
        if q.get("ocr_conf") is not None and q["ocr_conf"] < a.min_conf:
            why.append(f"低置信 {q['ocr_conf']}")
        if q.get("chars", 0) < 30:
            why.append(f"少字 {q.get('chars')}")
        if q.get("pua") or q.get("replacement"):
            why.append(f"乱码 私用区{q.get('pua')} 替换符{q.get('replacement')}")
        if q.get("missing_glyph"):
            why.append(f"缺字□ {q['missing_glyph']}")
        if why and p["verify_level"] not in ("ocr_verified",):
            rows.append((p["page"], p["verify_level"], p.get("producer") or "", "；".join(why)))
    out = st.root / "quality" / f"{a.key}.tsv"
    out.parent.mkdir(exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write("page\tverify_level\tproducer\t问题\t核对结果\n")
        for r in rows:
            f.write("\t".join(map(str, r)) + "\t\n")
    for r in rows[: a.show]:
        print("\t".join(map(str, r)))
    print(f"{len(rows)} 页待抽查，抽查单 {out}")


def cmd_qc(st: Store, a) -> None:
    if a.calibrate:
        r = qc.calibrate(st)
        out = Path(__file__).resolve().parents[1] / "docs" / "ocr_qc_calibration.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(r, ensure_ascii=False, indent=2))
        print(f"标定写入 {out}", flush=True)
        return
    if not a.key:
        print("qc 需要 <key>，或使用 --calibrate", file=sys.stderr)
        sys.exit(2)
    pages = _parse_pages(a.pages)
    r = qc.run_qc(
        st,
        a.key,
        by=_by(a),
        pages=pages,
        apply=a.apply,
        redo=a.redo,
        limit=a.limit,
        log=lambda m: print(m, flush=True),
    )
    print(json.dumps(r, ensure_ascii=False), flush=True)


def cmd_verify(st: Store, a) -> None:
    raw = Path(a.fix).read_text(encoding="utf-8")
    fixes = None
    if a.fix.endswith(".json"):
        x = json.loads(raw)
        if "text" in x:
            new = x["text"]
            fixes = x.get("fixes")
        else:  # {"replace": {"误": "正"}}
            fixes = x.get("replace", x)
            new = (st.read_page(a.key, a.page) or {}).get("text") or ""
            for k, v in fixes.items():
                new = new.replace(k, v)
    else:
        new = raw
    p = st.verify(a.key, a.page, new, by=_by(a), note=a.note, fixes=fixes, level=a.level)
    h = p["history"][-1]
    print(f"{a.key} p{a.page} → {p['verify_level']}（by {h['by']}，改动 {len(h['diff'])} 行）")


def cmd_search(st: Store, a) -> None:
    rs = st.search(a.query, key=a.key, kind=a.kind, domain=a.domain, level=a.level, limit=a.limit)
    for r in rs:
        pr = f"印{r['printed_page']}" if r["printed_page"] is not None else "印?"
        print(f"{r['key']}\tp{r['page']}\t{pr}\t{r['verify_level']}\t{r['producer']}\t{r['snippet']}")
    print(f"共 {len(rs)} 条", file=sys.stderr)


def cmd_page(st: Store, a) -> None:
    if a.image:
        print(st.render(a.key, a.page, dpi=a.dpi))
        return
    p = st.page(a.key, a.page)
    if p is None:
        print(f"{a.key} p{a.page} 无记录", file=sys.stderr)
        sys.exit(1)
    if a.json:
        print(json.dumps(p, ensure_ascii=False, indent=1))
        return
    q = p.get("quality") or {}
    print(f"# {a.key} PDF p{a.page}  印刷页 {p['printed_page'] if p['printed_page'] is not None else '?'}  "
          f"[{p['verify_level']}]  producer={p.get('producer')}  engine={p.get('engine')}  time={p.get('time')}")
    print(f"# 字符 {q.get('chars')}  置信 {q.get('ocr_conf')}  其他版本 {len(p.get('alternates', []))}"
          + "".join(f"\n#   alt: [{v.get('verify_level')}] {v.get('producer')} · {v.get('engine')}"
                    for v in p.get("alternates", [])))
    for h in p.get("history", []):
        print(f"# 校正: {h['time']} by {h['by']} {h['from_level']}→{h['level']} {h.get('note', '')[:80]}")
    print(p.get("text") or "")


def cmd_cite(st: Store, a) -> None:
    print(st.cite(a.key, a.page))


def cmd_export(st: Store, a) -> None:
    fmt = "translate" if a.translate else "marked" if a.marked else "md" if a.md else "txt"
    txt = st.export(a.key, fmt, _parse_pages(a.pages))
    if a.out:
        Path(a.out).write_text(txt, encoding="utf-8")
        print(a.out)
    else:
        sys.stdout.write(txt)


def cmd_status(st: Store, a) -> None:
    rows = st.status()
    tot = {lv: 0 for lv in LEVELS}
    print("key\tkind\tdomain\tpages\tdone\t" + "\t".join(LEVELS) + "\tproducers")
    for r in rows:
        for lv in LEVELS:
            tot[lv] += r["levels"].get(lv, 0)
        prod = ",".join(f"{k}:{v}" for k, v in sorted(r["producers"].items(), key=lambda x: -x[1]))
        print(f"{r['key']}\t{r['kind']}\t{r['domain']}\t{r['pages']}\t{r['done']}\t"
              + "\t".join(str(r["levels"].get(lv, 0)) for lv in LEVELS) + f"\t{prod}")
    print(f"合计 {len(rows)} 份资料，{sum(tot.values())} 页：" + "，".join(f"{k} {v}" for k, v in tot.items()))


def cmd_rebuild(st: Store, a) -> None:
    print(st.rebuild())


def cmd_import(st: Store, a) -> None:
    r = adapters.run_import(st, a.src, a.adapter, by=_by(a), producer=a.producer, key=a.key, offset=a.offset,
                            dpi=a.dpi, map_file=a.map, engine=a.engine or "", log=lambda m: print(m, flush=True))
    print(json.dumps(r, ensure_ascii=False))


def cmd_detect(st: Store, a) -> None:
    for f in adapters.detect(st, a.src, max_depth=a.depth):
        books = "; ".join(f"{b['name']}→{b['match'] or '?'}({b['by']}{' ' + b['note'] if b['note'] else ''})"
                          for b in f["books"])
        print(f"{f['format']}\t{f['pages']}页\t{'已导入 ' + f['imported'] if f['imported'] else '未导入'}\t"
              f"{f['path']}\t{books}")


def cmd_pair(st: Store, a) -> None:
    for x, y in ((a.a, a.b), (a.b, a.a)):
        d = st.doc(x)
        note = d["note"] if "pair" in d["note"] else (d["note"] + "；pair 初判，待确认").lstrip("；")
        st.update_doc(x, pair=y, note=note)
    print(f"pair {a.a} ⇄ {a.b}")


def cmd_set(st: Store, a) -> None:
    fields = dict(kv.split("=", 1) for kv in a.fields)
    st.update_doc(a.key, **fields)
    print(st.doc(a.key))


def cmd_lang(st: Store, a) -> None:
    """语言识别（纯脚本）：参数可为 PDF、目录或已登记 key；--set 把结果写回登记表（lang，及 kind 英文原著/外文原著）。"""
    from . import langid

    by_path = {str(Path(d["path"]).resolve()): d["key"] for d in st.docs() if d.get("path")}
    targets: list[tuple[str | None, Path]] = []
    for x in a.items:
        if Path(x).exists():
            for f in _iter_files([x]):
                targets.append((by_path.get(str(f.resolve())), f))
        else:
            targets.append((x, Path(st.doc(x)["path"])))
    for key, pdf in targets:
        r = langid.detect_pdf(pdf, k=a.k, ocr=not a.no_ocr)
        low = [s for s in r["sampled"] if s["chars"] >= 300 and (s["lang"] == "und" or s["conf"] < 0.7)]
        share = " ".join(f"{k}:{v}" for k, v in r["share"].items())
        flag = f"  需复核 {len(low)} 页" if low else ""
        print(f"{r['lang']}\t{share}\t{key or '-'}\t{pdf.name}{flag}")
        if a.json:
            print(json.dumps(r, ensure_ascii=False))
        if a.set and key and r["lang"] != "und":
            d = st.doc(key)
            fields = {"lang": r["lang"]}
            if d.get("kind") in ("英文原著", "外文原著"):
                fields["kind"] = "英文原著" if r["lang"] == "en" else "外文原著"
            st.update_doc(key, **fields)


def cmd_postfix(st: Store, a) -> None:
    """拉丁字母语种 OCR 后处理（latinfix，零 token）：词表取同语种全部资料的主版本页文本。
    改过的页写新版本（producer=latinfix，成为主版本），旧版本留在 alternates；改动逐条记 _audit/latinfix_<key>.jsonl。"""
    from . import latinfix
    from .store import make_version

    vocabs: dict[str, object] = {}
    audit = st.root / "_audit"
    audit.mkdir(exist_ok=True)
    for key in a.keys:
        d = st.doc(key)
        lang = d.get("lang") or ""
        if lang not in vocabs:
            same = [x["key"] for x in st.docs() if (x.get("lang") or "") == lang]
            vocabs[lang] = latinfix.build_vocab(p.get("text") or "" for k in same for p in st.pages(k))
        vocab = vocabs[lang]
        n_pages = n_changes = 0
        stats: dict[str, int] = {}
        with open(audit / f"latinfix_{key}.jsonl", "a", encoding="utf-8") as log:
            for n in st.page_numbers(key):
                pg = st.read_page(key, n) or {}
                if not (pg.get("text") or "").strip():  # 规则幂等：已改过的页再跑只会应用新加的规则
                    continue
                new, ch = latinfix.fix_page(pg["text"], vocab)  # type: ignore[arg-type]
                if not ch:
                    continue
                n_pages += 1
                n_changes += len(ch)
                for rule, old, rep in ch:
                    stats[rule] = stats.get(rule, 0) + 1
                    log.write(json.dumps({"page": n, "rule": rule, "old": old, "new": rep, "dry": a.dry},
                                         ensure_ascii=False) + "\n")
                if a.dry:
                    continue
                base = pg.get("producer") if not str(pg.get("producer") or "").startswith("latinfix") else \
                    (pg.get("extra") or {}).get("latinfix", {}).get("base_producer")
                v = make_version(new, pg.get("method") or "ocr", producer="latinfix", engine=f"{pg.get('engine') or ''} + latinfix",
                                 dpi=pg.get("dpi"), level=pg.get("verify_level"), source=f"{d['path']}#latinfix",
                                 conf=(pg.get("quality") or {}).get("ocr_conf"),
                                 extra={"latinfix": {"changes": len(ch), "base_producer": base}})
                st.put_version(key, n, v, promote=True)
        print(f"{key}\t改 {n_pages} 页 {n_changes} 处\t{stats}{'（dry）' if a.dry else ''}")


def cmd_proofread(st: Store, a) -> None:
    from .proofread import proofread_doc, rejudge_doc

    if a.rejudge:
        result = rejudge_doc(st, a.key, pages=_parse_pages(a.pages), dry=a.dry, by=_by(a))
    else:
        result = proofread_doc(st, a.key, below=a.below, pages=_parse_pages(a.pages), limit=a.limit,
                              engine=a.engine, workers=a.workers, include_unknown=a.include_unknown,
                              dry=a.dry, by=_by(a))
    print(json.dumps(result, ensure_ascii=False), flush=True)


def cmd_attest(st: Store, a) -> None:
    """短语在本地库某语种资料里的佐证（页数、资料数）；多个短语时按资料数排序，判断哪个译法是实际用法。"""
    from .attest import attest

    rows = [attest(st, p, a.lang, a.kind) for p in a.phrases]
    for r in sorted(rows, key=lambda r: (-r["docs"], -r["pages"])) if len(rows) > 1 else rows:
        cap = "+" if r.get("capped") else ""
        print(f"{r['docs']}\t{r['pages']}{cap}\t{r['phrase']}\t{','.join(r['sample_keys'])}")


def cmd_keys(st: Store, a) -> None:
    """检索表偶句重建：读 PP-OCR 行框缓存，零 token，不触发 OCR（issue #38）。"""
    from . import keys

    if a.keys_cmd == "check":
        data = json.loads(Path(a.file).read_text(encoding="utf-8"))
        rep = keys.check_couplets(data["couplets"])
    else:
        if not a.key and not (a.cache and a.last):
            print("需要 key，或同时给 --cache 与 --last", file=sys.stderr)
            sys.exit(1)
        if a.cache:
            cache = Path(a.cache)
        else:
            from .engines import ppocr

            d = st.doc(a.key)
            if not d["path"] or not Path(d["path"]).exists():
                print(f"{a.key}：登记表里没有可用的原件 PDF，无法定位行框缓存；可用 --cache 指定目录", file=sys.stderr)
                sys.exit(1)
            cache = ppocr._cache_file(d["path"], 1, a.dpi).parent
        last = a.last or int(st.doc(a.key)["pages"] or 0)
        if not cache.is_dir() or last < a.first:
            print(f"行框缓存不存在或页范围为空：{cache}（先 docstore text --engines ppocr）", file=sys.stderr)
            sys.exit(1)
        pages, missing = keys.read_cache_pages(cache, a.first, last)
        data = keys.extract(pages)
        data["missing_pages"] = missing
        if a.out:
            Path(a.out).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        rep = keys.check_by_key([{**c, "term": c["terminals"]} for c in data["couplets"]])
        if missing:
            print(f"缺行框缓存 {len(missing)} 页（不 OCR）：{missing[:10]}", file=sys.stderr)
    n_ok = 0
    for kid, v in rep.items():
        ok = not v["problems"]
        n_ok += ok
        print(f"表{kid}\tp{v['first_page']}-{v['last_page']}\t偶句 {v['couplets']}\t{'自洽' if ok else str(len(v['problems'])) + ' 处缺陷'}")
        if a.problems:
            for pr in v["problems"]:
                print(f"    {pr}")
    print(f"共 {len(rep)} 张表，{n_ok} 张自洽", file=sys.stderr)


def cmd_rename(st: Store, a) -> None:
    st.rename(a.old, a.new)
    print(f"{a.old} → {a.new}")


def check_offset(st: Store, key: str, samples: int = 3) -> list[tuple[int, int | None, float]]:
    """抽几页：用 PDF 文本层（无则 OCR）比对已有页文本，返回 (PDF页, 最像的已有页, 相似度)。"""
    import difflib

    import fitz

    d = st.doc(key)
    nums = st.page_numbers(key)
    out: list[tuple[int, int | None, float]] = []
    if not nums:
        return out
    with fitz.open(d["path"]) as pdf:
        n = len(pdf)
        picks = [max(1, n * i // (samples + 1)) for i in range(1, samples + 1)]
        for pg in picks:
            txt = pdf[pg - 1].get_text()
            if len("".join(txt.split())) < 30:
                txt, _ = textify.OCR_FUNC(d["path"], pg, 200)
            a = "".join(txt.split())[:500]
            best, best_r = None, 0.0
            for m in range(pg - 8, pg + 9):
                rec = st.read_page(key, m)
                if not rec:
                    continue
                for v in [rec] + rec.get("alternates", []):
                    r = difflib.SequenceMatcher(None, a, "".join((v.get("text") or "").split())[:500]).ratio()
                    if r > best_r:
                        best, best_r = m, r
            out.append((pg, best, round(best_r, 2)))
    return out


def cmd_attach(st: Store, a) -> None:
    r = st.attach(a.key, a.pdf, by=_by(a))
    print(json.dumps(r, ensure_ascii=False))
    if r["pdf_pages"] != r["page_records"]:
        print(f"提醒：PDF {r['pdf_pages']} 页，已有页面记录 {r['page_records']} 页，不一致（未改页号）")
    if a.check:
        res = check_offset(st, a.key)
        for pg, best, ratio in res:
            flag = "一致" if best == pg and ratio >= 0.5 else "不一致或无法确认"
            print(f"  PDF p{pg} ↔ 已有 p{best}  相似度 {ratio}  {flag}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="docstore", description="本地资料库：登记、文本化、核对、检索、引页")
    ap.add_argument("--root", help="库根（默认 $DOCSTORE_ROOT 或 /mnt/p/翻译-译作/参考资料/_资料库）")
    ap.add_argument("--by", help="写入者（模型或工具名，默认 $DOCSTORE_AGENT，再缺省 unknown）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("add", help="登记文件或目录（按 sha256 去重）")
    s.add_argument("paths", nargs="+")
    s.set_defaults(fn=cmd_add)

    s = sub.add_parser("text", help="文本化（文本层直取，扫描页 OCR，断点续跑）")
    s.add_argument("keys", nargs="*")
    s.add_argument("--pending", action="store_true")
    s.add_argument("--workers", type=int, default=4, help="并行 OCR 进程数（1 = 串行）")
    s.add_argument("--ocr-threads", type=int, help="每个 OCR 进程的 onnxruntime 线程数（默认 核数 // workers）")
    s.add_argument("--dpi", type=int, default=300)
    s.add_argument("--limit", type=int, help="每本最多处理多少页（估时用）")
    s.add_argument("--pages", help="只处理这些页（PDF 页码，1 起），如 655-671,700")
    s.add_argument("--layer-only", action="store_true",
                   help="只取 PDF 自带文本层，不 OCR（大批文献先建检索/语料；之后去掉此参数再跑即补 OCR）")
    s.add_argument("--no-fix", action="store_true", help="不对共识文本再跑 lexicon 编辑距离纠错（保留引擎原文）")
    s.add_argument("--engines", default="rapidocr,tesseract", help="OCR 引擎列表，逗号分隔")
    s.add_argument("--vlm", help="可选 VLM（仅处理低置信分歧）")
    s.set_defaults(fn=cmd_text)

    s = sub.add_parser("consensus", help="对已有 OCR 版本重算共识，不重复 OCR")
    s.add_argument("key")
    s.add_argument("--pages", help="页码范围，如 1-30,35,40-42")
    s.add_argument("--dpi", type=int, default=300)
    s.set_defaults(fn=cmd_consensus)

    s = sub.add_parser("quality", help="列低质量页，生成抽查单")
    s.add_argument("key")
    s.add_argument("--min-conf", type=float, default=0.85)
    s.add_argument("--show", type=int, default=30)
    s.set_defaults(fn=cmd_quality)

    s = sub.add_parser("qc", help="自动质控：风险分分流（通过/重做/人工），断点续跑")
    s.add_argument("key", nargs="?", help="资料 key；与 --calibrate 互斥时用")
    s.add_argument("--pages", help="页码范围，如 1-30,35")
    s.add_argument("--limit", type=int, help="最多处理页数")
    s.add_argument("--apply", action="store_true", help="执行自动通过（ocr_raw→ocr_sampled）")
    s.add_argument("--redo", action="store_true", help="与 --apply 联用：对 redo 页追加高 dpi OCR")
    s.add_argument("--calibrate", action="store_true", help="在金标准上标定查全率/误报率")
    s.set_defaults(fn=cmd_qc)

    s = sub.add_parser("verify", help="写入对原页的校正（全文 txt，或 json: {text} / {replace:{误:正}}）")
    s.add_argument("key")
    s.add_argument("page", type=int)
    s.add_argument("--fix", required=True)
    s.add_argument("--note", default="")
    s.add_argument("--level", default="ocr_verified", choices=["ocr_verified", "ocr_sampled"])
    s.set_defaults(fn=cmd_verify)

    s = sub.add_parser("search", help="全文检索")
    s.add_argument("query")
    s.add_argument("--key")
    s.add_argument("--kind")
    s.add_argument("--domain")
    s.add_argument("--level", choices=LEVELS)
    s.add_argument("--limit", type=int, default=50)
    s.set_defaults(fn=cmd_search)

    s = sub.add_parser("page", help="取一页文本或页图")
    s.add_argument("key")
    s.add_argument("page", type=int)
    s.add_argument("--image", action="store_true")
    s.add_argument("--dpi", type=int, default=150)
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_page)

    s = sub.add_parser("cite", help="规范引注")
    s.add_argument("key")
    s.add_argument("page", type=int)
    s.set_defaults(fn=cmd_cite)

    s = sub.add_parser("export", help="导出全文")
    s.add_argument("key")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--txt", action="store_true")
    g.add_argument("--md", action="store_true")
    g.add_argument("--translate", action="store_true",
                   help="auto_translate.py 输入：<!-- PDF p.N --> 页标记、段内接行、接回连字符断词")
    g.add_argument("--marked", action="store_true",
                   help="翻译用原文：每页前一行 <!-- p.N -->（印刷页码），供种名按页规范（species_format.py）")
    s.add_argument("--pages", help="只导出这些 PDF 页（1 起），如 24-30,32")
    s.add_argument("-o", "--out")
    s.set_defaults(fn=cmd_export)

    s = sub.add_parser("status", help="各资料文本化进度与核对等级")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("rebuild", help="由 pages/*.json 重建 sqlite")
    s.set_defaults(fn=cmd_rebuild)

    s = sub.add_parser("import", help="收编库外页面库")
    s.add_argument("src")
    s.add_argument("--adapter", required=True, choices=sorted(adapters.ADAPTERS))
    s.add_argument("--producer", help="原数据的生产者（默认按 adapter：codex / claude-script）")
    s.add_argument("--key")
    s.add_argument("--offset", type=int, help="PDF页 = 文件页 + offset")
    s.add_argument("--dpi", type=int)
    s.add_argument("--engine")
    s.add_argument("--map", help="TSV: dir key offset dpi [producer engine]；key 写 - 表示跳过")
    s.set_defaults(fn=cmd_import)

    s = sub.add_parser("detect", help="扫描目录，识别疑似页面库")
    s.add_argument("src")
    s.add_argument("--depth", type=int, default=5)
    s.set_defaults(fn=cmd_detect)

    s = sub.add_parser("pair", help="把两份资料设为对照书")
    s.add_argument("a")
    s.add_argument("b")
    s.set_defaults(fn=cmd_pair)

    s = sub.add_parser("set", help="修改登记字段：docstore set <key> kind=志书 year=1999")
    s.add_argument("key")
    s.add_argument("fields", nargs="+")
    s.set_defaults(fn=cmd_set)

    s = sub.add_parser("attach", help="给已登记资料（如「原件缺失」）绑定原件 PDF，不复制不移动")
    s.add_argument("key")
    s.add_argument("pdf")
    s.add_argument("--check", action="store_true", help="抽页比对 PDF 与已有页文本，核页码偏移")
    s.set_defaults(fn=cmd_attach)

    s = sub.add_parser("postfix", help="拉丁字母语种 OCR 后处理（♂♀、小型大写、µm、全库词频纠错；零 token）")
    s.add_argument("keys", nargs="+")
    s.add_argument("--dry", action="store_true", help="只记录将改什么，不写版本")
    s.set_defaults(fn=cmd_postfix)

    s = sub.add_parser("proofread", help="Proofread low-confidence OCR against page images")
    s.add_argument("key")
    s.add_argument("--rejudge", action="store_true", help="Recheck stored proofread alternates without model calls")
    s.add_argument("--below", type=float, default=0.92)
    s.add_argument("--pages", help="PDF page ranges, e.g. 1-30,35")
    s.add_argument("--limit", type=int)
    s.add_argument("--engine", default="codex-sol")
    s.add_argument("--workers", type=int, default=3)
    s.add_argument("--include-unknown", action="store_true")
    s.add_argument("--dry", action="store_true", help="List candidates without rendering, model calls, or writes")
    s.set_defaults(fn=cmd_proofread)

    s = sub.add_parser("attest", help="短语在本地库某语种资料中的佐证（资料数、页数；0 token）")
    s.add_argument("phrases", nargs="+")
    s.add_argument("--lang", default="en")
    s.add_argument("--kind")
    s.set_defaults(fn=cmd_attest)

    s = sub.add_parser("lang", help="识别资料语言（纯脚本：文本层或快速 OCR + 功能词，零 token）")
    s.add_argument("items", nargs="+", help="PDF、目录或已登记 key")
    s.add_argument("--k", type=int, default=8, help="抽样页数（默认 8）")
    s.add_argument("--no-ocr", action="store_true", help="无文本层也不 OCR")
    s.add_argument("--set", action="store_true", help="结果写回登记表 lang/kind")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_lang)

    s = sub.add_parser("keys", help="检索表偶句重建（读 PP-OCR 行框缓存；零 token，不 OCR）")
    ks = s.add_subparsers(dest="keys_cmd", required=True)
    e = ks.add_parser("extract", help="从行框缓存重建偶句，图检查，可写 keys.json")
    e.add_argument("key", nargs="?", help="已登记资料 key（与 --cache 二选一）")
    e.add_argument("--cache", help="行框缓存目录（含 pNNNN.json）；缺省由 key 的 PDF 指纹推出")
    e.add_argument("--dpi", type=int, default=200)
    e.add_argument("--first", type=int, default=1)
    e.add_argument("--last", type=int, default=0, help="末页（默认到资料末页；用 --cache 时必须给）")
    e.add_argument("--out", help="写 keys.json（couplets、keys、events、missing_pages）")
    e.add_argument("--problems", action="store_true", help="列出每张表的具体缺陷")
    c = ks.add_parser("check", help="对 keys.json 重做按表图检查（人工补完条目后用）")
    c.add_argument("file")
    c.add_argument("--problems", action="store_true")
    s.set_defaults(fn=cmd_keys)

    s = sub.add_parser("rename", help="改 key（登记表、pair、页面目录一起改）")
    s.add_argument("old")
    s.add_argument("new")
    s.set_defaults(fn=cmd_rename)

    a = ap.parse_args(argv)
    if a.cmd in WRITE_CMDS and not a.by and not os.environ.get("DOCSTORE_AGENT"):
        print("提醒：未指定 --by，也未设 DOCSTORE_AGENT，写入者将记为 unknown。", file=sys.stderr)
    st = Store(a.root)
    a.fn(st, a)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
