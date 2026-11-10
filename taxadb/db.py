"""taxa.sqlite：work / treatment / name_usage / field_check。

字段对齐旧 `_本地知识库/分类数据层/taxa.sqlite` 与 yzz-compilation 的 work.csv / treatment.csv / name_usage.csv。
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

DEFAULT_DB = Path("/mnt/p/翻译-译作/参考资料/_资料库/taxa.sqlite")

SCHEMA = """
CREATE TABLE IF NOT EXISTS work(
  work_id TEXT PRIMARY KEY,          -- = docstore key
  title TEXT, authors TEXT, year TEXT, citation TEXT, local_path TEXT,
  page_offset INTEGER,               -- 印刷页 - PDF 页
  rules TEXT,                        -- 切分所用规则文件
  expected_species INTEGER,          -- 书中给出的种数（金标准）
  inventory_source TEXT,
  split_by TEXT, split_time TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS treatment(
  treatment_id TEXT PRIMARY KEY,     -- <work>:<编号三位>
  work_id TEXT, num INTEGER, rank TEXT,
  taxon TEXT,                        -- 书中学名（属 种 [亚种]），原样拼写
  name_as_printed TEXT,              -- 学名 + 命名人年份，原样
  author_year TEXT, zh_name TEXT, family TEXT, subfamily TEXT, genus TEXT,
  pdf_page_start INTEGER, pdf_page_end INTEGER,
  pages TEXT,                        -- 印刷页 (PDF 页)
  figures TEXT, title_line TEXT,
  synonymy TEXT, 标本采集地 TEXT, 形态特征 TEXT, 地理分布 TEXT, 讨论 TEXT,
  figure_legend TEXT,                -- 从记述范围内剥离的图注（原样）
  original_text TEXT,                -- 记述全文（已去页眉、图注）
  language TEXT, text_origin TEXT,
  text_note TEXT,                    -- 自动规范化记录（如范围号）
  level TEXT,                        -- yzz-compilation 等级：L3 原始描述 / L4 重描述…
  verify_status TEXT,                -- 机器初识 / 已抽查 / 关键字段已核 / 全文已核
  flags TEXT,                        -- 自动发现的疑点（版本不一致、缺小标题…）
  note TEXT);
CREATE TABLE IF NOT EXISTS name_usage(
  usage_id TEXT PRIMARY KEY,         -- <treatment_id>:<序号>
  work_id TEXT, treatment_id TEXT, taxon TEXT,
  name_as_printed TEXT, author_year TEXT, zh_name TEXT,
  usage_type TEXT,                   -- 有效名（本书采用）/ 引用 / 异名或他名（原样）
  pages TEXT, pdf_page INTEGER, aphia_id TEXT, verify_status TEXT, raw TEXT);
CREATE TABLE IF NOT EXISTS field_check(
  treatment_id TEXT, field TEXT, db_value TEXT, page_value TEXT, ok INTEGER,
  pdf_page INTEGER, by TEXT, time TEXT, note TEXT,
  PRIMARY KEY(treatment_id, field));
CREATE INDEX IF NOT EXISTS ix_t_work ON treatment(work_id);
CREATE INDEX IF NOT EXISTS ix_t_family ON treatment(family);
CREATE INDEX IF NOT EXISTS ix_u_t ON name_usage(treatment_id);
"""

TREATMENT_COLS = ["treatment_id", "work_id", "num", "rank", "taxon", "name_as_printed", "author_year", "zh_name",
                  "family", "subfamily", "genus", "pdf_page_start", "pdf_page_end", "pages", "figures", "title_line",
                  "synonymy", "标本采集地", "形态特征", "地理分布", "讨论", "figure_legend", "original_text", "language",
                  "text_origin", "text_note", "level", "verify_status", "flags", "note"]
USAGE_COLS = ["usage_id", "work_id", "treatment_id", "taxon", "name_as_printed", "author_year", "zh_name",
              "usage_type", "pages", "pdf_page", "aphia_id", "verify_status", "raw"]


def db_path(path: str | Path | None = None) -> Path:
    return Path(path or os.environ.get("TAXADB_PATH") or DEFAULT_DB)


def open_db(path: str | Path | None = None) -> sqlite3.Connection:
    p = db_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p, timeout=600)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con
