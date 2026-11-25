"""译忆库：按语对（sl, tl）分别存「原文段 → 译文段」，带来源，同书二次运行零外部调用。

    ~/.cache/yzz-translate/tm.sqlite（环境变量 TM_DB 可覆盖）

语对严格隔离：ru→en 与 en→zh 各存各的，不会串用。键是原文规范化（空白折叠）后的 sha256。
用法：tm.lookup(src, sl, tl) -> str | None；tm.store(src, tgt, sl, tl, source)。
"""
from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import time
from pathlib import Path


def db_path() -> Path:
    env = os.environ.get("TM_DB")
    return Path(env).expanduser() if env else Path.home() / ".cache/yzz-translate/tm.sqlite"


def _key(src: str) -> str:
    return hashlib.sha256(re.sub(r"\s+", " ", src).strip().encode("utf-8")).hexdigest()


def _conn(path: Path | None = None) -> sqlite3.Connection:
    p = path or db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p)
    con.execute(
        "CREATE TABLE IF NOT EXISTS tm (sl TEXT, tl TEXT, k TEXT, src TEXT, tgt TEXT, source TEXT, ts REAL,"
        " PRIMARY KEY (sl, tl, k))")
    return con


def lookup(src: str, sl: str, tl: str, path: Path | None = None) -> str | None:
    if not src.strip():
        return None
    with _conn(path) as con:
        row = con.execute("SELECT tgt FROM tm WHERE sl=? AND tl=? AND k=?", (sl, tl, _key(src))).fetchone()
    return row[0] if row else None


def store(src: str, tgt: str, sl: str, tl: str, source: str, path: Path | None = None) -> None:
    """同键覆盖（后写为准，source 记下是谁写的）；空原文或空译文不存。"""
    if not src.strip() or not tgt.strip():
        return
    with _conn(path) as con:
        con.execute("INSERT OR REPLACE INTO tm VALUES (?,?,?,?,?,?,?)",
                    (sl, tl, _key(src), src, tgt, source, time.time()))
