"""外部页面库的识别（detect）与收编（import）。

别的模型或脚本在库外自建了页面文本时，先 `docstore detect <目录>` 看清格式和对应哪本书，
再 `docstore import <目录> --adapter <名>` 收编。导入只读来源、只往资料库里加版本，不改来源。

已有 adapter：
  codex_kb      Codex 本地知识库：原始证据/<来源>/{来源.json,pages/pNNNN.json}、OCR初识/<来源>/pNNNN.json、校正规则.json
  sqlite_pages  含 sources(key,title,path,pages,sha256) 与 pages(source,page,text,method) 表的 sqlite
  json_pages    pNNNN.json 目录（字段 text、method，可选 avg_score）；书目由 来源.json/来源.md 或 --key 指定
  txt_pages     pNNNN.txt 目录（每页一个文本文件）；子目录对应书，--map 指定 目录→key/偏移/dpi
"""

from __future__ import annotations

import csv
import difflib
import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Callable

from . import classify
from .store import Store, _flock, _int, agent, check_key, make_version, now, sha256_file

PAGE_JSON = re.compile(r"^p(\d{4})\.json$")
PAGE_TXT = re.compile(r"^p(\d{4})\.txt$")
SKIP_DIRS = {"_资料库", "__pycache__", ".git", "images"}

Log = Callable[[str], None]


# ---------------------------------------------------------------- 公共
def _classify_method(method: str, text: str) -> tuple[str, str]:
    """把来源的 method 文字映射到 (method, verify_level)。"""
    m = method or ""
    if not (text or "").strip():
        return ("text_layer" if "文本层" in m else "ocr"), "blank"
    if "文本层" in m and "OCR" not in m.upper():
        return "text_layer", "text_layer"
    return "ocr", "ocr_raw"


def resolve_doc(store: Store, *, key_hint: str, path: str = "", sha: str = "", by: str, log: Log,
                pages: int | None = None, **meta) -> str:
    """按 sha256 找到或登记资料；原件不在本机时登记为「原件缺失」，key 用 key_hint。"""
    if not sha and path and os.path.exists(path):
        sha = sha256_file(path)
    if sha:
        hit = store.find_sha(sha)
        if hit:
            return hit["key"]
    check_key(key_hint)
    if not (path and os.path.exists(path)):
        reg = {r["key"]: r for r in store.docs()}
        if key_hint in reg and (not sha or reg[key_hint]["status"] == "原件缺失" or not reg[key_hint]["sha256"]):
            return key_hint   # 来源只给了名字（如 --map 指定的 key）：用已登记的同名资料
        key, _ = store.register(None, by=by, key=key_hint, sha=sha, pages=pages, status="原件缺失", **meta)
        log(f"  登记（原件缺失）{key}")
        return key
    key, new = store.register(path, by=by, key=key_hint, sha=sha, **meta)
    if new:
        log(f"  登记 {key} ← {path}")
    return key


def _log_import(store: Store, src: str, adapter: str, by: str, producer: str, stats: dict) -> None:
    p = store.root / "imports.tsv"
    with _flock(store.root / ".imports.lock"):
        new = not p.exists()
        with open(p, "a", encoding="utf-8", newline="") as f:
            w = csv.writer(f, delimiter="\t")
            if new:
                w.writerow(["time", "adapter", "src", "by", "producer", "docs", "versions"])
            w.writerow([now(), adapter, str(Path(src).resolve()), by, producer,
                        ",".join(sorted(stats.get("docs", []))), stats.get("versions", 0)])


def imported_sources(store: Store) -> list[dict]:
    p = store.root / "imports.tsv"
    if not p.exists():
        return []
    with open(p, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def _meta_from_md(md: Path) -> dict:
    """从参考库 来源.md 读原件路径和页码偏移。"""
    out: dict = {}
    t = md.read_text(encoding="utf-8", errors="ignore")
    m = re.search(r"原件[^`\n]*`([^`]+\.pdf)`", t)
    if m:
        out["path"] = m.group(1)
    m = re.search(r"偏移\s*\+(\d+)", t) or re.search(r"印刷页\s*=\s*PDF页\s*[−-]\s*(\d+)", t)
    if m:
        out["page_offset"] = -int(m.group(1))
    return out


def _book_info(d: Path) -> dict:
    """在目录或其上级找 来源.json / 来源.md，取 key、path、sha256、offset。"""
    for base in (d, d.parent):
        j = base / "来源.json"
        if j.exists():
            x = json.loads(j.read_text(encoding="utf-8"))
            return {"key": x.get("key") or base.name, "path": x.get("path", ""), "sha256": x.get("sha256", ""),
                    "pages": x.get("pages")}
        m = base / "来源.md"
        if m.exists():
            info = _meta_from_md(m)
            info["key"] = base.name
            return info
    return {}


# ---------------------------------------------------------------- codex_kb
def import_codex_kb(store: Store, src: Path, *, by: str, producer: str = "codex", log: Log = print,
                    **_) -> dict:
    stats: dict[str, Any] = {"docs": set(), "versions": 0, "verified": 0}
    rules = {}
    if (src / "校正规则.json").exists():
        rules = json.loads((src / "校正规则.json").read_text(encoding="utf-8"))
    keymap: dict[str, str] = {}
    for sj in sorted((src / "原始证据").glob("*/来源.json")):
        info = json.loads(sj.read_text(encoding="utf-8"))
        name = sj.parent.name
        g = classify.guess(Path(info["path"])) if info.get("path") else {}
        key = resolve_doc(store, key_hint=info.get("key") or name, path=info.get("path", ""),
                          sha=info.get("sha256", ""), by=by, log=log, pages=info.get("pages"),
                          kind=g.get("kind"), lang=g.get("lang"), domain=info.get("domain") or g.get("domain"),
                          title=g.get("title"), note=classify.NOTE)
        keymap[name] = key
        stats["docs"].add(key)
        cache = info.get("cache") or info.get("thesis_cache") or ""
        for f in sorted((sj.parent / "pages").glob("p[0-9][0-9][0-9][0-9].json")):
            x = json.loads(f.read_text(encoding="utf-8"))
            text = x.get("text") or ""
            raw_m = x.get("method", "")
            method, level = _classify_method(raw_m, text)
            dpi = 200 if ("OCR缓存" in raw_m and "Rouse2022" in (x.get("evidence_path") or cache)) else None
            eng = {"text_layer": "PDF 文本层（既有缓存）", "ocr": "RapidOCR（既有 OCR 缓存）"}[method]
            if dpi:
                eng = "RapidOCR 200dpi（Rouse2022 术语库/OCR 缓存）"
            v = make_version(text, method, producer=producer, engine=eng, dpi=dpi, level=level,
                             source=str(f), extra={"orig_method": raw_m, "evidence_path": x.get("evidence_path", ""),
                                                   "imported_by": by, "review_status": x.get("review_status", "")})
            store.put_version(key, int(x.get("page") or f.stem[1:]), v, index=False)
            stats["versions"] += 1
        store.con.commit()
    approved = set(rules.get("approved_pages", []))
    fixes = rules.get("confirmed_fixes", {})
    records = rules.get("核准记录", [])
    for f in sorted((src / "OCR初识").glob("*/p[0-9][0-9][0-9][0-9].json")):
        name = f.parent.name
        if name not in keymap:
            log(f"  跳过 {f}：原始证据 中无 {name}")
            continue
        key = keymap[name]
        x = json.loads(f.read_text(encoding="utf-8"))
        n = int(x.get("page") or f.stem[1:])
        text = x.get("text") or ""
        v = make_version(text, "ocr", producer=producer, engine=f"RapidOCR（{x.get('engine', '')}；{x.get('image_origin', '')}）",
                         conf=_float(x.get("avg_score")), source=str(f),
                         extra={"imported_by": by, "recognized_at": x.get("recognized_at", ""),
                                "orig_round": x.get("round")})
        store.put_version(key, n, v, index=False)
        stats["versions"] += 1
        tag = f"{name}:p{n:04d}"
        if tag in approved:
            applied = {a: b for a, b in fixes.items() if a in text}
            new = text
            for a, b in applied.items():
                new = new.replace(a, b)
            rec: dict = next((r for r in records if r.get("页") == tag), {})
            store.verify(key, n, new, by=producer, fixes=applied, engine=rec.get("方式", "原页目视核对"),
                         note=f"迁移自 {src / '校正规则.json'} approved_pages；{rec.get('结论', '')}")
            stats["verified"] += 1
    store.con.commit()
    for k in stats["docs"]:
        _reindex(store, k)
    return stats


# ---------------------------------------------------------------- sqlite_pages
def import_sqlite_pages(store: Store, src: Path, *, by: str, producer: str = "codex", log: Log = print,
                        **_) -> dict:
    stats: dict[str, Any] = {"docs": set(), "versions": 0}
    files = [src] if src.is_file() else sorted(p for p in src.glob("*.sqlite") if _is_pages_sqlite(p))
    for db in files:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        srcs = {r[0]: r for r in con.execute("SELECT key, title, path, pages, sha256 FROM sources")}
        keymap = {}
        for name, (_, title, path, pages, sha) in srcs.items():
            g = classify.guess(Path(path)) if path else {}
            keymap[name] = resolve_doc(store, key_hint=name, path=path or "", sha=sha or "", by=by, log=log,
                                       pages=pages, kind=g.get("kind"), lang=g.get("lang"),
                                       domain=g.get("domain"), title=title or g.get("title"), note=classify.NOTE)
            stats["docs"].add(keymap[name])
        for name, page, text, method in con.execute("SELECT source, page, text, method FROM pages ORDER BY 1,2"):
            if name not in keymap:
                continue
            m, level = _classify_method(method or "", text or "")
            v = make_version(text or "", m, producer=producer, engine=f"{method}（{db.name}）", level=level,
                             source=f"{db}#{name}:{page}", extra={"orig_method": method, "imported_by": by})
            store.put_version(keymap[name], int(page), v, index=False)
            stats["versions"] += 1
        store.con.commit()
        con.close()
    for k in stats["docs"]:
        _reindex(store, k)
    return stats


def _is_pages_sqlite(p: Path) -> bool:
    try:
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
        cols = {r[1] for r in con.execute("PRAGMA table_info(pages)")}
        tabs = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        con.close()
        return {"source", "page", "text"} <= cols and "sources" in tabs
    except sqlite3.Error:
        return False


# ---------------------------------------------------------------- json_pages / txt_pages
def _page_dirs(src: Path, pat: re.Pattern) -> list[Path]:
    def has(d: Path) -> bool:
        return any(pat.match(f.name) for f in d.iterdir() if f.is_file())
    if has(src):
        return [src]
    out = []
    for d in sorted(x for x in src.iterdir() if x.is_dir() and x.name not in SKIP_DIRS):
        if has(d):
            out.append(d)
        elif (d / "OCR").is_dir() and has(d / "OCR"):
            out.append(d / "OCR")
    return out


def _load_map(path: str | None) -> dict[str, dict]:
    if not path:
        return {}
    out = {}
    with open(path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader((ln for ln in f if not ln.startswith("#")), delimiter="\t"):
            if row.get("key") and row["key"] != "-":
                check_key(row["key"])
            out[row["dir"]] = row
    return out


def _guess_offset(store: Store, key: str, texts: dict[int, str]) -> int | None:
    """拿缓存页和库里已有页比文本，找 PDF页 = 缓存页 + offset。库里无页则返回 None。"""
    have = set(store.page_numbers(key))
    if not have:
        return None
    sample = [n for n in sorted(texts) if len(texts[n]) > 200][:: max(1, len(texts) // 8)][:8]
    best, best_s = None, 0.0
    for off in range(-20, 21):
        s = 0.0
        for n in sample:
            pg = store.read_page(key, n + off) if (n + off) in have else None
            if pg:
                vs = [pg] + pg.get("alternates", [])
                s += max(difflib.SequenceMatcher(None, texts[n][:400], (v.get("text") or "")[:400]).quick_ratio()
                         for v in vs)
        if s > best_s:
            best, best_s = off, s
    return best if sample and best_s / len(sample) > 0.6 else None


def _import_pagedir(store: Store, src: Path, *, kind: str, by: str, producer: str, log: Log,
                    key: str | None = None, offset: int | None = None, dpi: int | None = None,
                    map_file: str | None = None, engine: str = "", **_) -> dict:
    pat = PAGE_JSON if kind == "json" else PAGE_TXT
    stats: dict[str, Any] = {"docs": set(), "versions": 0, "offsets": {}}
    mapping = _load_map(map_file)
    for d in _page_dirs(src, pat):
        name = d.parent.name if d.name == "OCR" else d.name
        row = mapping.get(name, {})
        info = _book_info(d)
        if row.get("key") == "-":
            log(f"  {name}: map 指定跳过")
            continue
        k_hint = key if (key and len(_page_dirs(src, pat)) == 1) else (row.get("key") or info.get("key") or name)
        path = info.get("path", "")
        g = classify.guess(Path(path)) if path else {"kind": "学位论文" if name.startswith("论文") else ""}
        k = resolve_doc(store, key_hint=k_hint, path=path, sha=info.get("sha256", ""), by=by, log=log,
                        pages=info.get("pages"), kind=g.get("kind"), lang=g.get("lang"), domain=g.get("domain"),
                        title=g.get("title") or name, page_offset=info.get("page_offset"), note=classify.NOTE)
        stats["docs"].add(k)
        texts: dict[int, str] = {}
        extras: dict[int, dict] = {}
        for f in sorted(d.iterdir()):
            m = pat.match(f.name)
            if not m:
                continue
            n = int(m.group(1))
            if kind == "json":
                x = json.loads(f.read_text(encoding="utf-8"))
                texts[n] = x.get("text") or ""
                conf = _float(x.get("avg_score"))
                if conf is None and isinstance(x.get("lines"), list) and x["lines"]:
                    raw = [_float(ln[2]) for ln in x["lines"] if isinstance(ln, list) and len(ln) > 2]
                    cs = [c for c in raw if c is not None]
                    conf = sum(cs) / len(cs) if cs else None
                extras[n] = {"orig_method": x.get("method", ""), "conf": conf}
            else:
                texts[n] = f.read_text(encoding="utf-8", errors="replace")
                extras[n] = {}
        off = _int(row.get("offset")) if row.get("offset") not in (None, "") else offset
        if off is None:
            off = _guess_offset(store, k, texts)
            if off is None:
                off = 0
                log(f"  {name}: 无偏移信息且库中无可比页，按 PDF页=文件页")
            else:
                log(f"  {name}: 按文本比对推得 PDF页 = 文件页 {off:+d}")
        stats["offsets"][name] = off
        ddpi = _int(row.get("dpi")) if row.get("dpi") else dpi
        eng = row.get("engine") or engine or (f"RapidOCR {ddpi}dpi" if ddpi else "OCR（来源未注明引擎）")
        for n, text in texts.items():
            ex = extras[n]
            method, level = ("ocr", "ocr_raw") if text.strip() else ("ocr", "blank")
            if ex.get("orig_method"):
                method, level = _classify_method(ex["orig_method"], text)
            v = make_version(text, method, producer=row.get("producer") or producer, engine=eng, dpi=ddpi,
                             level=level, conf=ex.get("conf"), source=str(d / (f"p{n:04d}." + kind)),
                             extra={"imported_by": by, "file_page": n, "orig_method": ex.get("orig_method", "")})
            store.put_version(k, n + off, v, index=False)
            stats["versions"] += 1
        store.con.commit()
        _reindex(store, k)
    return stats


def import_json_pages(store: Store, src: Path, *, by: str, producer: str = "codex", log: Log = print, **kw) -> dict:
    return _import_pagedir(store, src, kind="json", by=by, producer=producer, log=log, **kw)


def import_txt_pages(store: Store, src: Path, *, by: str, producer: str = "claude-script", log: Log = print,
                     **kw) -> dict:
    return _import_pagedir(store, src, kind="txt", by=by, producer=producer, log=log, **kw)


ADAPTERS = {
    "codex_kb": import_codex_kb,
    "sqlite_pages": import_sqlite_pages,
    "json_pages": import_json_pages,
    "txt_pages": import_txt_pages,
}


def run_import(store: Store, src: str | Path, adapter: str, *, by: str | None = None, producer: str | None = None,
               log: Log = print, **kw) -> dict:
    if adapter not in ADAPTERS:
        raise ValueError(f"未知 adapter {adapter}；可选 {', '.join(ADAPTERS)}")
    by = agent(by)
    src = Path(src)
    if kw.get("key"):
        check_key(kw["key"])
    fn = ADAPTERS[adapter]
    args = {"by": by, "log": log, **kw}
    if producer:
        args["producer"] = producer
    stats = fn(store, src, **args)
    _log_import(store, str(src), adapter, by, producer or (fn.__kwdefaults__ or {}).get("producer", ""), stats)
    stats["docs"] = sorted(stats["docs"])
    return stats


def _reindex(store: Store, key: str) -> None:
    for p in store.pages(key):
        store._index_page(p)
    store.con.commit()


def _float(x) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- detect
def detect(store: Store, src: str | Path, max_depth: int = 5) -> list[dict]:
    src = Path(src).resolve()
    imports = imported_sources(store)
    root = store.root.resolve()
    found: list[dict] = []
    covered: list[Path] = []

    def is_imported(p: Path) -> str:
        for r in imports:
            s = Path(r["src"])
            if p == s or s in p.parents:
                return f"{r['time']} {r['adapter']} by {r['by']}"
        return ""

    for dirpath, dirnames, filenames in os.walk(src):
        d = Path(dirpath)
        if d == root or root in d.parents or any(c == d or c in d.parents for c in covered):
            dirnames[:] = []
            continue
        dirnames[:] = [x for x in dirnames if x not in SKIP_DIRS]
        if len(d.relative_to(src).parts) >= max_depth:
            dirnames[:] = []
        if (d / "原始证据").is_dir() and (d / "OCR初识").is_dir():
            names = sorted(p.parent.name for p in (d / "原始证据").glob("*/来源.json"))
            found.append({"path": str(d), "format": "codex_kb", "pages": sum(
                len(list((d / "原始证据" / b / "pages").glob("p*.json"))) for b in names),
                "books": [_match(store, _book_info(d / "原始证据" / b), None, b) for b in names],
                "imported": is_imported(d)})
            covered.append(d)
            dirnames[:] = []
            continue
        for fn in filenames:
            if fn.endswith((".sqlite", ".db")) and _is_pages_sqlite(d / fn):
                con = sqlite3.connect(f"file:{d / fn}?mode=ro", uri=True)
                books = [_match(store, {"key": k, "path": p, "sha256": s}, None, k)
                         for k, p, s in con.execute("SELECT key, path, sha256 FROM sources")]
                n = con.execute("SELECT count(*) FROM pages").fetchone()[0]
                con.close()
                found.append({"path": str(d / fn), "format": "sqlite_pages", "pages": n, "books": books,
                              "imported": is_imported(d / fn)})
        nums_j = [int(m.group(1)) for f in filenames if (m := PAGE_JSON.match(f))]
        nums_t = [int(m.group(1)) for f in filenames if (m := PAGE_TXT.match(f))]
        for fmt, nums in (("json_pages", nums_j), ("txt_pages", nums_t)):
            if len(nums) >= 3:
                name = d.parent.name if d.name in ("OCR", "pages") else d.name
                found.append({"path": str(d), "format": fmt, "pages": len(nums),
                              "books": [_match(store, _book_info(d), max(nums), name)],
                              "imported": is_imported(d)})
    return found


def _match(store: Store, info: dict, maxpage: int | None, name: str) -> dict:
    """按 sha256（或原件路径算出的 sha256）匹配；否则按目录名前缀、页数给候选。"""
    sha = info.get("sha256") or ""
    path = info.get("path") or ""
    if not sha and path and os.path.exists(path):
        sha = sha256_file(path)
    if sha:
        hit = store.find_sha(sha)
        return {"name": name, "match": hit["key"] if hit else "", "by": "sha256",
                "note": "" if hit else f"原件 {path or sha[:12]} 未登记"}
    docs = store.docs()
    pref = [r["key"] for r in docs if r["key"] and (name.startswith(r["key"]) or r["key"].startswith(name))]
    if pref:
        return {"name": name, "match": pref[0], "by": "目录名", "note": "待确认"}
    if maxpage:
        cands = [r["key"] for r in docs if _int(r["pages"]) and abs(_int(r["pages"]) - maxpage) <= 10]  # type: ignore[operator]
        if cands:
            return {"name": name, "match": "", "by": "页数", "note": "候选 " + ",".join(cands[:5])}
    return {"name": name, "match": "", "by": "", "note": "未匹配（原件可能不在本机）"}
