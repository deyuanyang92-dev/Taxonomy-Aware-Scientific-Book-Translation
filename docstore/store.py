"""资料库核心：登记表 registry.tsv、逐页证据 pages/<key>/pNNNN.json、sqlite 索引（可重建）。

页面 json 只有一份「主版本」（字段在顶层），其他版本放 alternates，校正记录放 history。
多个模型或工具对同一页写入时，各版本并存、不覆盖：核对等级高者（同级 300 dpi > 200 dpi > 其他）
当主版本，其余进入 alternates。
"""

from __future__ import annotations

import contextlib
import csv
import datetime as _dt
import difflib
import fcntl
import hashlib
import io
import json
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any, Iterator

DEFAULT_ROOT = "/mnt/p/翻译-译作/参考资料/_资料库"

# 由高到低
LEVELS = ["text_layer", "ocr_verified", "ocr_sampled", "ocr_raw", "blank"]
LEVEL_RANK = {lv: len(LEVELS) - i for i, lv in enumerate(LEVELS)}

FIELDS = [
    "key", "path", "sha256", "pages", "kind", "lang", "pair", "domain", "tier", "title",
    "authors", "year", "page_offset", "status", "note", "added_by", "added_at",
]

VERSION_KEYS = [
    "text", "method", "engine", "producer", "time", "dpi", "verify_level", "quality", "source",
]

_PUA = re.compile(r"[-]")
_CJK = r"㐀-鿿豈-﫿　-〿＀-￯"
_NL_CJK = re.compile(rf"(?<=[{_CJK}])\s*\n\s*(?=[{_CJK}])")


def now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def agent(by: str | None = None) -> str:
    return by or os.environ.get("DOCSTORE_AGENT") or "unknown"


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def quality(text: str, conf: float | None = None) -> dict:
    q: dict[str, Any] = {
        "chars": len(re.sub(r"\s", "", text or "")),
        "pua": len(_PUA.findall(text or "")),
        "replacement": (text or "").count("�"),
        "missing_glyph": (text or "").count("□"),
    }
    if conf is not None:
        q["ocr_conf"] = round(float(conf), 4)
    return q


def make_version(text: str, method: str, *, producer: str, engine: str = "", dpi: int | None = None,
                 level: str | None = None, source: str = "", conf: float | None = None,
                 time: str | None = None, extra: dict | None = None) -> dict:
    text = text or ""
    if level is None:
        level = "blank" if not text.strip() else ("text_layer" if method.startswith("text_layer") else "ocr_raw")
    elif not text.strip():
        level = "blank"
    v = {
        "text": text, "method": method, "engine": engine, "producer": producer,
        "time": time or now(), "dpi": dpi, "verify_level": level, "quality": quality(text, conf),
        "source": source,
    }
    if extra:
        v.update(extra)
    return v


def version_rank(v: dict) -> tuple:
    dpi = v.get("dpi") or 0
    dpi_rank = 2 if dpi >= 300 else (1 if dpi >= 200 else 0)
    return (LEVEL_RANK.get(v.get("verify_level", "blank"), 0), dpi_rank)


def search_text(text: str) -> str:
    """索引用文本：中文跨行接上，其余换行变空格。"""
    t = _NL_CJK.sub("", text or "")
    return re.sub(r"\s+", " ", t)


@contextlib.contextmanager
def _flock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _atomic_write(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + f".{os.getpid()}.part")
    part.write_text(data, encoding="utf-8")
    os.replace(part, path)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS docs(key TEXT PRIMARY KEY, title TEXT, kind TEXT, lang TEXT, domain TEXT,
    pair TEXT, sha256 TEXT, pages INTEGER, page_offset INTEGER, path TEXT);
CREATE TABLE IF NOT EXISTS pages(id INTEGER PRIMARY KEY, key TEXT, page INTEGER, text TEXT,
    verify_level TEXT, method TEXT, engine TEXT, producer TEXT, chars INTEGER, conf REAL,
    n_versions INTEGER, UNIQUE(key, page));
CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(body, tokenize='trigram');
"""


class Store:
    def __init__(self, root: str | Path | None = None):
        self.root = Path(root or os.environ.get("DOCSTORE_ROOT") or DEFAULT_ROOT)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "pages").mkdir(exist_ok=True)
        self.registry_path = self.root / "registry.tsv"
        self.db_path = self.root / "docstore.sqlite"
        self.con = sqlite3.connect(self.db_path, timeout=600)
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.execute("PRAGMA busy_timeout=600000")
        self.con.executescript(_SCHEMA)
        self._reg: dict[str, dict] | None = None
        self._reg_mtime = 0.0

    # ---------------- 登记表 ----------------
    def _load_registry(self) -> dict[str, dict]:
        mt = self.registry_path.stat().st_mtime if self.registry_path.exists() else 0.0
        if self._reg is not None and mt == self._reg_mtime:
            return self._reg
        reg: dict[str, dict] = {}
        if self.registry_path.exists():
            with open(self.registry_path, encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f, delimiter="\t"):
                    check_key(row["key"])
                    reg[row["key"]] = {k: (row.get(k) or "") for k in FIELDS}
        self._reg, self._reg_mtime = reg, mt
        return reg

    def _save_registry(self, reg: dict[str, dict]) -> None:
        buf = io.StringIO()
        w = csv.writer(buf, delimiter="\t", lineterminator="\n")
        w.writerow(FIELDS)
        for row in reg.values():
            w.writerow([str(row.get(k, "")) for k in FIELDS])
        _atomic_write(self.registry_path, buf.getvalue())
        self._reg = None

    @contextlib.contextmanager
    def edit_registry(self):
        with _flock(self.root / ".registry.lock"):
            self._reg = None
            reg = dict(self._load_registry())
            yield reg
            self._save_registry(reg)
            for row in reg.values():
                self._index_doc(row)
            self.con.commit()

    def docs(self) -> list[dict]:
        return list(self._load_registry().values())

    def doc(self, key: str) -> dict:
        reg = self._load_registry()
        if key not in reg:
            raise KeyError(f"未登记的资料: {key}")
        return reg[key]

    def find_sha(self, sha: str) -> dict | None:
        if not sha:
            return None
        for row in self._load_registry().values():
            if row["sha256"] == sha:
                return row
        return None

    def register(self, path: str | Path | None, *, by: str | None = None, key: str | None = None,
                 sha: str | None = None, **meta: Any) -> tuple[str, bool]:
        """登记一份资料。按 sha256 去重；改名只更新 path；同一路径内容变了另立新 key。
        返回 (key, 是否新登记)。"""
        from . import classify

        p = Path(path) if path else None
        if p is not None and p.exists():
            sha = sha or sha256_file(p)
        sha = sha or ""
        with self.edit_registry() as reg:
            hit = next((r for r in reg.values() if sha and r["sha256"] == sha), None)
            if hit is not None:
                if p is not None and str(p) != hit["path"]:
                    old = hit["path"]
                    if old and Path(old).exists():
                        hit["note"] = _append_note(hit["note"], f"另有副本 {p}")
                    else:
                        hit["path"] = str(p)
                        if old:
                            hit["note"] = _append_note(hit["note"], f"改名，曾用路径 {old}")
                        if hit["status"] == "原件缺失":
                            hit["status"] = "registered"
                return hit["key"], False
            prev = next((r for r in reg.values() if p is not None and r["path"] == str(p)), None)
            guess = classify.guess(p) if p is not None else {}
            guess.update({k: v for k, v in meta.items() if v not in (None, "")})
            k = key or guess.pop("key", None) or (p.stem if p else "doc")
            guess.pop("key", None)
            k = _unique_key(k, reg)
            npages = guess.pop("pages", None)
            if npages is None and p is not None and p.exists():
                npages = _pdf_pages(p)
            row = {f: "" for f in FIELDS}
            row.update({kk: ("" if vv is None else str(vv)) for kk, vv in guess.items() if kk in FIELDS})
            row.update(key=k, path=str(p) if p else "", sha256=sha, pages=str(npages or ""),
                       added_by=agent(by), added_at=now())
            if not row["status"]:
                row["status"] = "registered" if (p and p.exists()) else "原件缺失"
            if prev is not None:
                row["note"] = _append_note(row["note"], f"同一路径内容已变，前版本 {prev['key']}")
                prev["note"] = _append_note(prev["note"], f"原件已被新版本 {k} 替换")
            reg[k] = row
            return k, True

    def update_doc(self, key: str, **fields: Any) -> None:
        with self.edit_registry() as reg:
            for f, v in fields.items():
                if f in FIELDS and f != "key":
                    reg[key][f] = "" if v is None else str(v)

    def rename(self, old: str, new: str) -> None:
        """改 key：登记表、对照书引用、pages/<key>/ 目录与索引一起改（目录整体移动，不删数据）。"""
        check_key(new)
        with self.edit_registry() as reg:
            if old not in reg:
                raise KeyError(old)
            if new in reg:
                raise ValueError(f"key 已存在: {new}")
            row = reg.pop(old)
            row["key"] = new
            row["note"] = _append_note(row["note"], f"曾用 key {old}")
            reg[new] = row
            for r in reg.values():
                if r["pair"] == old:
                    r["pair"] = new
            src, dst = self.root / "pages" / old, self.root / "pages" / new
            if src.exists():
                os.rename(src, dst)
                for f in dst.glob("p[0-9][0-9][0-9][0-9].json"):
                    pg = json.loads(f.read_text(encoding="utf-8"))
                    pg["key"] = new
                    _atomic_write(f, json.dumps(pg, ensure_ascii=False, indent=1))
            self.con.execute("DELETE FROM docs WHERE key=?", (old,))
            self.con.execute("UPDATE pages SET key=? WHERE key=?", (new, old))

    def attach(self, key: str, path: str | Path, *, by: str | None = None) -> dict:
        """给已登记（如「原件缺失」）的资料绑定原件：补 path、sha256、pages，status 改为 registered。
        不复制、不移动原件。返回核对信息（PDF 页数 vs 已有页面记录）。"""
        p = Path(path)
        if not p.is_file():
            raise FileNotFoundError(str(p))
        sha = sha256_file(p)
        npages = _pdf_pages(p)
        with self.edit_registry() as reg:
            if key not in reg:
                raise KeyError(f"未登记的资料: {key}")
            other = next((r["key"] for r in reg.values() if r["sha256"] == sha and r["key"] != key), None)
            if other:
                raise ValueError(f"该原件已登记为 {other}")
            row = reg[key]
            if row["sha256"] and row["sha256"] != sha:
                raise ValueError(f"{key} 已绑定另一原件（sha256 {row['sha256'][:12]}…）")
            row.update(path=str(p), sha256=sha, pages=str(npages or ""),
                       status="registered" if row["status"] == "原件缺失" else row["status"])
            row["note"] = _append_note(row["note"], f"原件绑定 {now()[:10]} by {agent(by)}")
        nums = self.page_numbers(key)
        return {"key": key, "sha256": sha, "pdf_pages": npages, "page_records": len(nums),
                "min_page": min(nums) if nums else None, "max_page": max(nums) if nums else None}

    # ---------------- 页面 ----------------
    def page_path(self, key: str, n: int) -> Path:
        return self.root / "pages" / key / f"p{int(n):04d}.json"

    def read_page(self, key: str, n: int) -> dict | None:
        p = self.page_path(key, n)
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))

    def page_numbers(self, key: str) -> list[int]:
        d = self.root / "pages" / key
        if not d.exists():
            return []
        return sorted(int(f.name[1:5]) for f in d.glob("p[0-9][0-9][0-9][0-9].json"))

    def put_version(self, key: str, n: int, version: dict, *, index: bool = True, promote: bool | None = None) -> dict:
        """加入一个页面版本；同一来源同一文本重复导入时不重复记录。
        promote=None 按 version_rank 决定主版本；True 强制成为主版本；False 只进 alternates。"""
        with _flock(self.root / "pages" / key / ".lock"):
            page = self.read_page(key, n)
            if page is None:
                page = {"key": key, "page": int(n), **{k: version.get(k) for k in VERSION_KEYS},
                        "alternates": [], "history": []}
                for k, v in version.items():
                    if k not in VERSION_KEYS:
                        page.setdefault("extra", {})[k] = v
            else:
                allv = [_primary(page)] + page.get("alternates", [])
                if any(_same(v, version) for v in allv):
                    return page
                if promote is True or (promote is None and version_rank(version) > version_rank(_primary(page))):
                    page["alternates"] = [_primary(page)] + page.get("alternates", [])
                    for k in VERSION_KEYS:
                        page[k] = version.get(k)
                else:
                    page.setdefault("alternates", []).append(version)
            _atomic_write(self.page_path(key, n), json.dumps(page, ensure_ascii=False, indent=1))
        if index:
            self._index_page(page)
            self.con.commit()
        return page

    def verify(self, key: str, n: int, new_text: str, *, by: str | None = None, note: str = "",
               fixes: dict | None = None, level: str = "ocr_verified", engine: str = "人工/模型看原页") -> dict:
        """写入对原页的校正：新文本成为主版本（ocr_verified），旧主版本进 alternates，改动记 history。"""
        if level not in ("ocr_verified", "ocr_sampled"):
            raise ValueError("level 只能是 ocr_verified 或 ocr_sampled")
        with _flock(self.root / "pages" / key / ".lock"):
            page = self.read_page(key, n)
            if page is None:
                raise KeyError(f"{key} p{n} 尚无页面记录")
            old = _primary(page)
            diff = list(difflib.unified_diff(old["text"].splitlines(), new_text.splitlines(), lineterm="", n=0))
            rec = {"action": "verify", "by": agent(by), "time": now(), "level": level,
                   "from_level": old.get("verify_level"), "from_producer": old.get("producer"),
                   "before_sha1": hashlib.sha1(old["text"].encode()).hexdigest(),
                   "after_sha1": hashlib.sha1(new_text.encode()).hexdigest(),
                   "fixes": fixes or {}, "diff": diff[:400], "note": note}
            nv = make_version(new_text, "verified", producer=agent(by), engine=engine, level=level,
                              dpi=old.get("dpi"), source=f"verify by {agent(by)}",
                              conf=None)
            page["alternates"] = [old] + page.get("alternates", [])
            for k in VERSION_KEYS:
                page[k] = nv.get(k)
            page.setdefault("history", []).append(rec)
            _atomic_write(self.page_path(key, n), json.dumps(page, ensure_ascii=False, indent=1))
        self._index_page(page)
        self.con.commit()
        return page

    # ---------------- 索引 ----------------
    def _index_doc(self, row: dict) -> None:
        off = _int(row.get("page_offset"))
        self.con.execute(
            "INSERT OR REPLACE INTO docs VALUES(?,?,?,?,?,?,?,?,?,?)",
            (row["key"], row["title"], row["kind"], row["lang"], row["domain"], row["pair"],
             row["sha256"], _int(row["pages"]), off, row["path"]))

    def _index_page(self, page: dict) -> None:
        q = page.get("quality") or {}
        cur = self.con.execute("SELECT id FROM pages WHERE key=? AND page=?", (page["key"], page["page"]))
        r = cur.fetchone()
        vals = (page.get("text") or "", page.get("verify_level"), page.get("method"), page.get("engine"),
                page.get("producer"), q.get("chars"), q.get("ocr_conf"), 1 + len(page.get("alternates", [])))
        if r:
            pid = r[0]
            self.con.execute("UPDATE pages SET text=?, verify_level=?, method=?, engine=?, producer=?, chars=?,"
                             " conf=?, n_versions=? WHERE id=?", (*vals, pid))
            self.con.execute("DELETE FROM fts WHERE rowid=?", (pid,))
        else:
            cur = self.con.execute("INSERT INTO pages(key,page,text,verify_level,method,engine,producer,chars,"
                                   "conf,n_versions) VALUES(?,?,?,?,?,?,?,?,?,?)",
                                   (page["key"], page["page"], *vals))
            pid = cur.lastrowid
        self.con.execute("INSERT INTO fts(rowid, body) VALUES(?,?)", (pid, search_text(page.get("text") or "")))

    def rebuild(self) -> dict:
        """由 registry.tsv 与 pages/*/pNNNN.json 完全重建 sqlite。"""
        # 先读完所有页面，再在一个写事务里替换，避免其他进程写到一半看到「表不存在」
        self._reg = None
        all_pages = []
        for d in sorted((self.root / "pages").iterdir()):
            if d.is_dir():
                for f in sorted(d.glob("p[0-9][0-9][0-9][0-9].json")):
                    all_pages.append(json.loads(f.read_text(encoding="utf-8")))
        self.con.commit()
        self.con.execute("BEGIN IMMEDIATE")
        try:
            for stmt in ("DELETE FROM docs", "DELETE FROM pages", "DELETE FROM fts"):
                self.con.execute(stmt)
            for row in self.docs():
                self._index_doc(row)
            for pg in all_pages:
                self._index_page(pg)
            self.con.commit()
        except BaseException:
            self.con.rollback()
            raise
        return {"docs": len(self.docs()), "pages": len(all_pages)}

    # ---------------- 读取接口 ----------------
    def printed(self, key: str, n: int) -> int | None:
        off = _int(self.doc(key).get("page_offset")) if key in self._load_registry() else None
        return None if off is None else n + off

    def page(self, key: str, n: int) -> dict | None:
        p = self.read_page(key, n)
        if p is None:
            return None
        p["printed_page"] = self.printed(key, n)
        return p

    def pages(self, key: str) -> Iterator[dict]:
        for n in self.page_numbers(key):
            p = self.page(key, n)
            if p is not None:
                yield p

    def search(self, q: str, *, key: str | None = None, kind: str | None = None, domain: str | None = None,
               level: str | None = None, limit: int = 50) -> list[dict]:
        q = q.strip()
        if not q:
            return []
        where, args = [], []
        for col, val in (("p.key", key), ("d.kind", kind), ("d.domain", domain), ("p.verify_level", level)):
            if val:
                where.append(f"{col}=?")
                args.append(val)
        extra = (" AND " + " AND ".join(where)) if where else ""
        if len(q) >= 3:
            sql = ("SELECT p.key, p.page, p.verify_level, p.producer, d.page_offset, d.title,"
                   " snippet(fts, 0, '【', '】', '…', 24) FROM fts JOIN pages p ON p.id=fts.rowid"
                   " LEFT JOIN docs d ON d.key=p.key WHERE fts MATCH ?" + extra + " ORDER BY p.key, p.page LIMIT ?")
            rows = self.con.execute(sql, ['"' + q.replace('"', '""') + '"', *args, limit]).fetchall()
        else:
            sql = ("SELECT p.key, p.page, p.verify_level, p.producer, d.page_offset, d.title, fts.body"
                   " FROM fts JOIN pages p ON p.id=fts.rowid LEFT JOIN docs d ON d.key=p.key"
                   " WHERE fts.body LIKE ?" + extra + " ORDER BY p.key, p.page LIMIT ?")
            rows = []
            for r in self.con.execute(sql, [f"%{q}%", *args, limit]).fetchall():
                body = r[6]
                i = body.find(q)
                rows.append((*r[:6], "…" + body[max(0, i - 24):i] + "【" + q + "】" + body[i + len(q):i + len(q) + 24] + "…"))
        return [{"key": r[0], "page": r[1], "printed_page": (r[1] + r[4]) if r[4] is not None else None,
                 "verify_level": r[2], "producer": r[3], "title": r[5], "snippet": r[6]} for r in rows]

    def status(self) -> list[dict]:
        out = []
        lv: dict[str, dict] = {}
        for k, lvl, c in self.con.execute("SELECT key, verify_level, count(*) FROM pages GROUP BY 1,2"):
            lv.setdefault(k, {})[lvl] = c
        prod: dict[str, dict] = {}
        for k, p, c in self.con.execute("SELECT key, producer, count(*) FROM pages GROUP BY 1,2"):
            prod.setdefault(k, {})[p or "unknown"] = c
        for row in self.docs():
            k = row["key"]
            done = sum(lv.get(k, {}).values())
            out.append({"key": k, "kind": row["kind"], "domain": row["domain"], "pages": _int(row["pages"]),
                        "done": done, "levels": lv.get(k, {}), "producers": prod.get(k, {}),
                        "status": row["status"]})
        return out

    def cite(self, key: str, n: int) -> str:
        d = self.doc(key)
        pr = self.printed(key, n)
        who = d["authors"] or "作者待核"
        yr = d["year"] or "年份待核"
        pp = f"第 {pr} 页（PDF 第 {n} 页）" if pr is not None else f"PDF 第 {n} 页（印刷页未定）"
        return f"{who}. {yr}. {d['title'] or key}. {pp}. [docstore:{key}]"

    def export(self, key: str, fmt: str = "txt") -> str:
        parts = []
        d = self.doc(key)
        if fmt == "md":
            parts.append(f"# {d['title'] or key}\n")
        for p in self.pages(key):
            tag = f"p{p['page']:04d}" + (f" 印刷页 {p['printed_page']}" if p["printed_page"] is not None else "")
            if fmt == "md":
                parts.append(f"\n## {tag} · {p['verify_level']}\n\n{p.get('text') or ''}\n")
            else:
                parts.append(f"==== {tag} [{p['verify_level']}]\n{p.get('text') or ''}\n")
        return "".join(parts)

    def render(self, key: str, n: int, dpi: int = 150) -> Path:
        import fitz

        d = self.doc(key)
        out = self.root / "images" / key / f"p{int(n):04d}_{dpi}.png"
        if not out.exists():
            out.parent.mkdir(parents=True, exist_ok=True)
            with fitz.open(d["path"]) as pdf:
                pdf[int(n) - 1].get_pixmap(dpi=dpi).save(str(out))
        return out


def _primary(page: dict) -> dict:
    return {k: page.get(k) for k in VERSION_KEYS}


def _same(a: dict, b: dict) -> bool:
    return (a.get("text") == b.get("text") and a.get("source") == b.get("source")
            and a.get("method") == b.get("method"))


def _int(v: Any) -> int | None:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def _append_note(note: str, add: str) -> str:
    return add if not note else (note if add in note else f"{note}；{add}")


def clean_key(k: str) -> str:
    prev = None
    while prev != k:
        prev = k
        k = re.sub(r"[\s/\\:*?\"<>|]+", "_", k.replace("..", "_")).strip("_").lstrip(".")
    return k or "doc"


def check_key(k: str) -> str:
    """key 会拼进 pages/<key>/、images/<key>/ 路径：必须已清洗、不含 ..、不以 . 开头。"""
    if not k or k != clean_key(k) or ".." in k or k.startswith("."):
        raise ValueError(f"key 不合法: {k!r}")
    return k


def _unique_key(k: str, reg: dict) -> str:
    k = clean_key(k)
    if k not in reg:
        return k
    i = 2
    while f"{k}_{i}" in reg:
        i += 1
    return f"{k}_{i}"


def _pdf_pages(p: Path) -> int | None:
    try:
        import fitz

        with fitz.open(str(p)) as d:
            return len(d)
    except Exception:  # noqa: BLE001
        return None


def open_store(root: str | Path | None = None) -> Store:
    return Store(root)


def warn(msg: str) -> None:
    print(msg, file=sys.stderr)
