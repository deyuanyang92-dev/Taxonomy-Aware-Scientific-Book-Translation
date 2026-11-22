"""keytail 真实页回归（11 页人工目视的补读结果）。缓存/PDF/tesseract 缺则跳过。n=11 页，选页偏向告警页，不代表召回率。"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from docstore import keys, keytail

CASES = {  # 缓存哈希 → (页数, 登记键, {(页, 条目号): 终点号})
    "966b8423a9d4": (406, "Imajima2001", {(172, "11"): "12", (266, "1"): "2"}),
    "858f37873e50": (363, "Imajima2007", {(56, "1'"): "26", (177, "17"): "18", (217, "7"): "8", (218, "25'"): "26"}),
    "c1ac037a042b": (361, "Imajima2009", {(67, "27"): "28", (197, "5'"): "18", (297, "49'"): "50"}),
}


def test_recover_real_pages():
    if not shutil.which("tesseract"):
        pytest.skip("no tesseract")
    from docstore import open_store
    root = Path(os.environ.get("DOCSTORE_PPOCR_CACHE", str(Path.home() / ".cache" / "docstore_ppocr")))
    ran = 0
    for h, (n, key, want) in CASES.items():
        cache = root / h / "PP-OCRv5_server_200_v2"
        if not cache.is_dir():
            continue
        try:
            pdf = open_store().doc(key)["path"]
        except Exception:
            continue
        if not Path(pdf).exists():
            continue
        pages, _ = keys.read_cache_pages(cache, 1, n)
        data = keys.extract(pages)
        keytail.recover_tail_jumps(data, keytail.pdf_renderer(pdf, 200), keytail.tesseract_digits)
        got = {(c["page"], c["lead"]): c["terminals"] for c in data["couplets"] if (c["page"], c["lead"]) in want}
        assert {k: v[0] for k, v in got.items()} == want, h
        ran += 1
    if not ran:
        pytest.skip("no cache/pdf")
