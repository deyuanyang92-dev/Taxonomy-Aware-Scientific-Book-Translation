"""从本地资料库 docstore 取中文用例：某个中文译名在中文著作里的实际用法（KWIC，左右各 width 字）。

docstore 是可选依赖：没装、没有库、检索出错都静默返回空，不影响术语表生成。
优先取该译名所属来源书（来源键与 docstore 键同名时）里的用例，不够再从其他中文著作补，每本最多 1 条以求多样。
不取「本项目译稿」（我们自己的译文不是用例）、英文书和学位论文。
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

EXCLUDE_KINDS = {"本项目译稿", "英文原著", "学位论文"}
MIN_ZH_LEN = 2  # 单字译名（如「须」）检索噪声太大，不取用例
MIN_CJK_RATIO = 0.6  # 窗口里汉字占非空白字符的比例低于此值视为 OCR 乱码/英文串，不取
MAX_NUMBERS = 3      # 窗口里数字串（连续数字）超过此数视为目录、索引、页码串，不取
_NUM = re.compile(r"\d+")
_CJK = re.compile("[\u4e00-\u9fff]")
_PUA = re.compile("[\ue000-\uf8ff]")  # 私用区字符（字体映射残留）


def _env_excluded() -> set[str]:
    """环境变量 YIKU_USAGE_EXCLUDE_KEYS（逗号分隔的 docstore 键）：这些书不当用例来源（比测防泄漏用）。"""
    return {k.strip() for k in os.environ.get("YIKU_USAGE_EXCLUDE_KEYS", "").split(",") if k.strip()}


class UsageFinder:
    def __init__(self, store: Any = None, *, width: int = 30):
        self.store = store
        self.width = width
        self._cache: dict[tuple[str, tuple[str, ...], int, tuple[str, ...]], list[str]] = {}

    # ---- 对外 ----
    def examples(self, zh: str, prefer_keys: list[str] | tuple[str, ...] = (), n: int = 2,
                 longer: list[str] | tuple[str, ...] = ()) -> list[str]:
        """返回至多 n 条「…左【译名】右…（书 p.页）」。出错或无库返回空列表。
        longer：包含 zh 的更长译名（如 zh=同塑、longer=[同塑性]）；zh 恰好是它们的一部分的出现处不算用例。"""
        zh = zh.strip()
        if self.store is None or len(zh) < MIN_ZH_LEN or n <= 0:
            return []
        longer = tuple(x for x in longer if zh in x and x != zh)
        ck = (zh, tuple(prefer_keys), n, longer)
        if ck not in self._cache:
            try:
                self._cache[ck] = self._find(zh, list(prefer_keys), n, longer)
            except Exception:  # noqa: BLE001 - 用例只是点缀，任何检索故障都不能拖垮术语表
                self._cache[ck] = []
        return self._cache[ck]

    # ---- 内部 ----
    def _doc_ok(self, key: str) -> bool:
        if key in _env_excluded():
            return False
        try:
            d = self.store.doc(key)
        except KeyError:
            return False
        return (d.get("lang") or "zh") == "zh" and d.get("kind") not in EXCLUDE_KINDS

    def _tier(self, key: str) -> int:
        """排序用层级：标「备用」的资料（用户 2026-11-13：质量一般，只作参考）排最后；未设层级的居中。"""
        try:
            d = self.store.doc(key)
        except KeyError:
            return 99
        if "备用" in (d.get("note") or ""):
            return 98
        try:
            return int(d.get("tier") or 50)
        except ValueError:
            return 50

    def _find(self, zh: str, prefer: list[str], n: int, longer: tuple[str, ...]) -> list[str]:
        out: list[str] = []
        seen_keys: set[str] = set()
        seen_pages: set[tuple[str, int]] = set()

        def take(rows: list[dict], one_per_book: bool) -> None:
            for r in rows:
                if len(out) >= n:
                    return
                k, pg = r["key"], r["page"]
                if (k, pg) in seen_pages or (one_per_book and k in seen_keys) or not self._doc_ok(k):
                    continue
                snip = self._kwic(k, pg, r.get("printed_page"), zh, longer)
                if snip:
                    seen_pages.add((k, pg))
                    seen_keys.add(k)
                    out.append(snip)

        for k in prefer:  # 来源书：同一本最多取 n 条
            if len(out) >= n:
                break
            if self._doc_ok(k):
                take(self.store.search(zh, key=k, limit=8), one_per_book=False)
        if len(out) < n:  # 其他中文著作：按层级（越小越权威）、核对等级排，每本 1 条
            rows = self.store.search(zh, limit=60)
            rows.sort(key=lambda r: (self._tier(r["key"]), r["key"], r["page"]))
            take(rows, one_per_book=True)
        return out

    def _kwic(self, key: str, page: int, printed: int | None, zh: str, longer: tuple[str, ...] = ()) -> str | None:
        from docstore.store import search_text
        p = self.store.read_page(key, page)
        if not p:
            return None
        text = _PUA.sub("", search_text(p.get("text") or ""))
        i = _find_free(text, zh, longer)
        if i < 0:
            return None
        left = text[max(0, i - self.width):i].lstrip()
        right = text[i + len(zh):i + len(zh) + self.width].rstrip()
        win = re.sub(r"\s+", "", left + zh + right)
        if len(_CJK.findall(win)) < MIN_CJK_RATIO * len(win) or len(_NUM.findall(win)) > MAX_NUMBERS:
            return None
        s = ("…" if i - self.width > 0 else "") + left + f"【{zh}】" + right + ("…" if i + len(zh) + self.width < len(text) else "")
        s = s.replace("|", "｜").replace("\n", " ")
        return f"{s}（{key} p.{printed if printed is not None else page}）"


def _find_free(text: str, zh: str, longer: tuple[str, ...]) -> int:
    """zh 在 text 里第一个不属于更长译名（longer）的出现位置；没有返回 -1。"""
    i = text.find(zh)
    while i >= 0:
        if not any(text.startswith(x, i - x.find(zh)) for x in longer if i - x.find(zh) >= 0):
            return i
        i = text.find(zh, i + 1)
    return -1


def default_finder(width: int = 30) -> UsageFinder:
    """按环境变量 DOCSTORE_ROOT（缺省用 docstore 的默认库根）打开资料库；没装 docstore 或库不存在则返回无库的 finder。"""
    try:
        from docstore.store import DEFAULT_ROOT, Store
    except ImportError:
        return UsageFinder(None, width=width)
    root = Path(os.environ.get("DOCSTORE_ROOT") or DEFAULT_ROOT)
    if not (root / "docstore.sqlite").exists():  # 不替用户凭空建库
        return UsageFinder(None, width=width)
    try:
        return UsageFinder(Store(root), width=width)
    except Exception:  # noqa: BLE001
        return UsageFinder(None, width=width)
