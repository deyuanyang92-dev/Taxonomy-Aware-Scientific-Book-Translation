"""术语库存储：SQLite。一个库服务所有领域；领域、类群范围、来源层级都是字段。

库位置：--db 参数 > 环境变量 YIKU_DB > ~/.yiku/yiku.db
"""
from __future__ import annotations

import os
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

# 来源类型的默认层级（数字越小越权威）。每个来源可单独指定 tier 覆盖默认值。
KIND_TIER = {
    "user": 0,          # 用户裁定
    "authority": 1,     # 正式记述该类群/概念的权威专著、志书
    "checklist": 3,     # 物种名录
    "standard": 4,      # 全国科技名词委、国家标准
    "translation": 5,   # 名家译本（中英对照书）
    "zh_original": 5,   # 名家中文论著里的「中文（English）」
    "thesis": 6,        # 学位论文：仅供参考
    "external": 8,      # Wikidata 等网络库：只作线索
    "model": 9,         # 模型建议
}
STATUSES = ("已核", "候选", "否决")
DOMAINS = ("分类学", "进化生物学", "科学史", "分子系统学")  # 常用领域；'*' = 通用
# 默认的跨领域回退：自域查不到（或只有候选）时，再看这些领域的译名，仅作参考，永不压过自域已核。
# 例：环节动物书（分类学）里的 homoplasy、adaptive radiation 等通用进化术语，自域没有时可参考进化生物学。
DEFAULT_FALLBACK = {"分类学": ["进化生物学"]}

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources(
  key TEXT PRIMARY KEY, title TEXT NOT NULL, kind TEXT NOT NULL, tier INTEGER NOT NULL,
  domain TEXT NOT NULL DEFAULT '*', path TEXT, note TEXT, year INTEGER);
CREATE TABLE IF NOT EXISTS terms(
  id INTEGER PRIMARY KEY, en TEXT NOT NULL, en_norm TEXT NOT NULL, zh TEXT NOT NULL,
  domain TEXT NOT NULL DEFAULT '*', scope TEXT NOT NULL DEFAULT '*',
  source TEXT NOT NULL REFERENCES sources(key), page TEXT, context TEXT,
  status TEXT NOT NULL DEFAULT '候选', note TEXT,
  created TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  UNIQUE(en_norm, zh, domain, scope, source));
CREATE INDEX IF NOT EXISTS terms_en ON terms(en_norm);
"""


def default_path() -> Path:
    return Path(os.environ.get("YIKU_DB") or Path.home() / ".yiku" / "yiku.db")


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    p = Path(path) if path else default_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    cols = {r[1] for r in con.execute("PRAGMA table_info(sources)")}
    if "year" not in cols:  # 旧库迁移：来源出版年，同层级时新版优先
        con.execute("ALTER TABLE sources ADD COLUMN year INTEGER")
        con.commit()
    return con


def norm(en: str) -> str:
    """英文规范化：小写、合并空白、去首尾标点。学名大小写不敏感地匹配。"""
    return re.sub(r"\s+", " ", en.strip().strip(".,;:()[]\"'")).lower()


def add_source(con, key, title, kind, tier=None, domain="*", path=None, note=None, year=None):
    """登记来源。year 为出版年：同层级来源译名不一致时，新版优先（未给 year 时保留库中已有值）。"""
    if kind not in KIND_TIER:
        raise ValueError(f"kind 必须是 {sorted(KIND_TIER)} 之一")
    con.execute(
        "INSERT INTO sources(key,title,kind,tier,domain,path,note,year) VALUES(?,?,?,?,?,?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET title=excluded.title, kind=excluded.kind, tier=excluded.tier, "
        "domain=excluded.domain, path=excluded.path, note=excluded.note, "
        "year=coalesce(excluded.year, sources.year)",
        (key, title, kind, KIND_TIER[kind] if tier is None else tier, domain, path, note, year))
    con.commit()


def set_source(con, key, *, tier=None, year=None, note=None):
    """只改给出的字段（层级、出版年、备注），其余不动。"""
    if con.execute("SELECT 1 FROM sources WHERE key=?", (key,)).fetchone() is None:
        raise KeyError(f"来源 {key} 未登记")
    for col, val in (("tier", tier), ("year", year), ("note", note)):
        if val is not None:
            con.execute(f"UPDATE sources SET {col}=? WHERE key=?", (val, key))
    con.commit()


def add_term(con, en, zh, source, domain="*", scope="*", page=None, context=None,
             status="候选", note=None) -> bool:
    """写入一条术语；同一 (en, zh, 领域, 范围, 来源) 已存在时只在新状态更确定时升级状态。返回是否新增。"""
    if status not in STATUSES:
        raise ValueError(f"status 必须是 {STATUSES} 之一")
    en, zh = en.strip(), zh.strip()
    if not en or not zh:
        return False
    if not con.execute("SELECT 1 FROM sources WHERE key=?", (source,)).fetchone():
        raise KeyError(f"来源 {source!r} 未登记，先 yiku source add")
    cur = con.execute(
        "INSERT OR IGNORE INTO terms(en,en_norm,zh,domain,scope,source,page,context,status,note) "
        "VALUES(?,?,?,?,?,?,?,?,?,?)",
        (en, norm(en), zh, domain or "*", scope or "*", source, page, context, status, note))
    if cur.rowcount == 0 and status == "已核":
        con.execute("UPDATE terms SET status='已核' WHERE en_norm=? AND zh=? AND domain=? AND scope=? AND source=?",
                    (norm(en), zh, domain or "*", scope or "*", source))
    return cur.rowcount == 1


@dataclass
class Hit:
    en: str
    zh: str
    domain: str
    scope: str
    source: str
    tier: int
    status: str
    page: str | None
    note: str | None
    context: str | None = None
    year: int | None = None
    fallback: bool = False  # True = 来自回退领域（不是本书领域），只作参考

    def cite(self) -> str:
        return f"{self.source}" + (f" p.{self.page}" if self.page else "")


def resolve_fallback(domain: str, spec: str | list[str] | None) -> list[str]:
    """回退领域列表。spec=None 取默认（DEFAULT_FALLBACK）；'none'/空串/[] 表示不回退；
    字符串用逗号或分号分隔。本书领域自身和通用域 '*' 不算回退。"""
    if spec is None:
        out = list(DEFAULT_FALLBACK.get(domain, []))
    elif isinstance(spec, str):
        out = [x.strip() for x in re.split(r"[,;，；]", spec) if x.strip() and x.strip().lower() != "none"]
    else:
        out = [x for x in spec if x]
    return [d for d in dict.fromkeys(out) if d not in (domain, "*")]


def candidates(con, en: str, domain: str = "*", scope: set[str] | None = None,
               fallback_domains: list[str] | None = None) -> list[Hit]:
    """某英文术语的全部译名，按可信度排序：已核 > 候选；领域吻合 > 通用；类群吻合 > 通用；来源层级；
    同层级出版年新者优先（用户 2026-11-12：同一作者新旧版不一致，以新的为准）。
    否决的不返回；其他领域的专用译名默认不返回（避免把植物学用字带进动物学）。

    fallback_domains：自域（含通用 '*'）的全部命中排完之后，追加这些领域的命中，Hit.fallback=True。
    回退命中永远排在自域命中之后，即使它的来源层级更高。"""
    scope = scope or set()
    fb = [d for d in dict.fromkeys(fallback_domains or []) if d not in (domain, "*")]

    def fetch(domains: list[str]) -> list[tuple]:
        marks = ",".join("?" * len(domains))
        rows = con.execute(
            "SELECT t.*, s.tier, s.year FROM terms t JOIN sources s ON s.key=t.source "
            f"WHERE t.en_norm=? AND t.status!='否决' AND t.domain IN ({marks})",
            (norm(en), *domains)).fetchall()
        out = []
        for r in rows:
            sc = {x.strip() for x in r["scope"].split(";")}
            if "*" not in sc and not (sc & scope):
                continue  # 只适用于别的类群
            out.append((r, sc))

        def key(item):
            r, sc = item
            return (r["status"] != "已核", r["domain"] == "*", "*" in sc, r["tier"], -(r["year"] or 0))

        out.sort(key=key)
        return out

    def hit(r, fallback: bool) -> Hit:
        return Hit(r["en"], r["zh"], r["domain"], r["scope"], r["source"], r["tier"], r["status"],
                   r["page"], r["note"], r["context"], r["year"], fallback)

    own = [hit(r, False) for r, _ in fetch(["*", domain])]
    return own + ([hit(r, True) for r, _ in fetch(fb)] if fb else [])


def best(con, en, domain="*", scope=None, fallback_domains=None) -> Hit | None:
    c = candidates(con, en, domain, scope, fallback_domains)
    return c[0] if c else None
