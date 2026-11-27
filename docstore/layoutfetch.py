"""docstore layout: fetch PaddleOCR-VL page layout (block labels + boxes) for a registered PDF.

Only the layout store is written (<root>/layout/<key>/pNNNN.json via paddle_vl.save_layout); page
text in the store is not touched.  Used for native PDFs, whose text layer is better than OCR but
which carry no region semantics (title / toc / table / figure caption / header).  Issue #71.
Pages already cached are skipped unless force=True.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable


def cached_pages(root: Path, key: str) -> set[int]:
    d = Path(root) / "layout" / key
    return {int(p.stem[1:]) for p in d.glob("p[0-9][0-9][0-9][0-9].json")} if d.is_dir() else set()


def fetch_layout(root: Path, key: str, pdf: str, pages: list[int], *, force: bool = False,
                 chunk: int = 20, run: Callable[..., Any] | None = None,
                 save: Callable[..., Any] | None = None, log: Callable[[str], None] = print) -> dict:
    """Return {"fetched": [...], "skipped": [...], "failed": {page: reason}}."""
    if run is None or save is None:
        from .engines import paddle_vl
        run = run or paddle_vl.run_chunk
        save = save or paddle_vl.save_layout
    have = set() if force else cached_pages(root, key)
    todo = [p for p in pages if p not in have]
    res: dict[str, Any] = {"fetched": [], "skipped": sorted(set(pages) & have), "failed": {}}
    for i in range(0, len(todo), chunk):
        part = todo[i:i + chunk]
        ok, failed = run(pdf, part, log=log, chunk_no=i // chunk + 1)
        for p, (_txt, meta) in sorted(ok.items()):
            if meta.get("_layout") is None:
                res["failed"][p] = "no layout in result"
                continue
            save(root, key, p, meta)
            res["fetched"].append(p)
        res["failed"].update(failed)
    return res
