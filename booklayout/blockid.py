"""Stable block identity across re-splits, and block coverage checks.

Block ids are positional (``p004_01``) and drift when a page is re-split.  A
*fingerprint table* records, per block, the source hash plus context; after a
re-split :func:`remap` maps old ids to new ids by content.  Ambiguous or
missing matches are returned for a human queue, never guessed.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from booklayout.normalize import block_src_hash, neighbour_hash, safe_key


def _blocks(data: dict[str, Any]) -> list[tuple[int, int, dict[str, Any]]]:
    out = []
    for p in data.get("pages", []):
        for i, b in enumerate(p.get("blocks", [])):
            out.append((p.get("page", 0), i, b))
    return out


def _sp(b: dict[str, Any], page: Any) -> Any:
    """Single normaliser for ``source_page``: null/absent means the logical page."""
    sp = b.get("source_page")
    if sp is None:
        return page
    if isinstance(sp, (bool, float)):  # True == 1 and 1.0 == 1 must not pass as page 1
        return ("bad", repr(sp))
    if isinstance(sp, str) and sp.strip().isdigit():  # "1" written by older repair == 1
        return int(sp)
    return sp


def _valid_id(x: Any) -> bool:
    return isinstance(x, str) and bool(x)


def fingerprint_table(data: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per block: id, hash, page, index, source_page, neighbour hashes."""
    rows = _blocks(data)
    hashes = [block_src_hash(b) for _, _, b in rows]
    table = []
    for k, (page, i, b) in enumerate(rows):
        table.append({
            "block_id": b.get("block_id"), "hash": hashes[k], "page": page, "index": i,
            "source_page": _sp(b, page),
            "prev": neighbour_hash(hashes, k - 1), "next": neighbour_hash(hashes, k + 1),
        })
    return table


def remap(old: list[dict[str, Any]], new_data: dict[str, Any]) -> dict[str, Any]:
    """Map old block ids to new ones, independent of table order.

    Maps only when evidence is unambiguous:
    * unique hash on both sides: same source_page required;
    * repeated hash (either side): group sizes (counted over ALL new blocks,
      including unaddressable ones) must match, no candidate in the group may be
      unaddressable (invalid/duplicate id), and exactly one candidate has
      identical (prev, next) neighbours and the same source_page, claimed by
      exactly one old block.
    Position alone is never evidence.  Everything else is ``ambiguous`` or an
    orphan.  Old ids must be non-empty strings and unique, else ambiguous
    (``1`` and ``"1"`` never merge).
    """
    new = fingerprint_table(new_data)
    new_ids = Counter(r["block_id"] for r in new if _valid_id(r["block_id"]))
    bad_new = {safe_key(r["block_id"]) for r in new
               if not _valid_id(r["block_id"]) or new_ids[r["block_id"]] > 1}

    def addressable(r: dict[str, Any]) -> bool:
        return _valid_id(r["block_id"]) and new_ids[r["block_id"]] == 1

    by_hash: dict[str, list[dict[str, Any]]] = {}
    for row in new:
        if row["hash"]:
            by_hash.setdefault(row["hash"], []).append(row)
    old_count: Counter[str] = Counter(o["hash"] for o in old if o["hash"])
    id_count: Counter[str] = Counter(o["block_id"] for o in old if _valid_id(o["block_id"]))
    mapping: dict[str, str] = {}
    ambiguous: dict[str, list[str]] = {}
    orphans: list[str] = []
    orphan_rows: set[int] = set()
    claims: dict[str, list[str]] = {}
    pick: dict[str, str] = {}
    row_cands: dict[int, list[str]] = {}  # per-ROW candidates: duplicate old ids must not share them
    for n, o in enumerate(old):
        # invalid old ids are keyed by row index so 1 / "1" / [1] never merge
        oid = f"#{n}:{o['block_id']!r}" if not _valid_id(o["block_id"]) else o["block_id"]
        cands = by_hash.get(o["hash"], []) if o["hash"] else []
        if not cands:
            orphans.append(oid)
            orphan_rows.add(n)
            continue
        cand_ids = [repr(c["block_id"]) if not _valid_id(c["block_id"]) else c["block_id"] for c in cands]
        if not _valid_id(o["block_id"]) or id_count[o["block_id"]] > 1:
            ambiguous[oid] = cand_ids
            row_cands[n] = cand_ids
            continue
        same_sp = [c for c in cands if c["source_page"] == o["source_page"]]
        if len(cands) == 1 and old_count[o["hash"]] == 1:
            ok = same_sp
        elif len(cands) == old_count[o["hash"]] and all(addressable(c) for c in cands):
            ok = [c for c in same_sp if c["prev"] == o["prev"] and c["next"] == o["next"]]
        else:
            ok = []
        if len(ok) == 1 and addressable(ok[0]):
            pick[oid] = ok[0]["block_id"]
            claims.setdefault(pick[oid], []).append(oid)
        else:
            ambiguous[oid] = row_cands[n] = [
                repr(c["block_id"]) if not _valid_id(c["block_id"]) else c["block_id"] for c in (ok or cands)]
    pick_row = {oid: n for n, o in enumerate(old) for oid in [o["block_id"]] if _valid_id(oid) and oid in pick}
    for oid, nid in pick.items():
        if len(claims[nid]) == 1:
            mapping[oid] = nid
        else:
            ambiguous[oid] = [nid]
            row_cands[pick_row[oid]] = [nid]
    queue: list[dict[str, Any]] = []
    for n, o in enumerate(old):
        oid = f"#{n}:{o['block_id']!r}" if not _valid_id(o["block_id"]) else o["block_id"]
        if n in orphan_rows:
            queue.append({"row": n, "id": oid, "raw_id": repr(o["block_id"]), "status": "orphan",
                          "candidates": []})
        elif n in row_cands or oid in ambiguous:
            queue.append({"row": n, "id": oid, "raw_id": repr(o["block_id"]), "status": "ambiguous",
                          "candidates": list(row_cands.get(n, ambiguous[oid]))})
    return {"map": mapping, "ambiguous": ambiguous, "orphans": sorted(orphans), "queue": queue,
            "invalid_new_ids": sorted((x if isinstance(x, str) else x[2] for x in bad_new), key=str)}


def check_coverage(data: dict[str, Any], expected_pages: list[int],
                   skipped: dict[int, str] | None = None,
                   source_page_ok: dict[tuple[str, int, int], str] | None = None,
                   expected_blocks: list[tuple[int, str]] | None = None,
                   pages_only: bool = False) -> dict[str, Any]:
    """Coverage gate.

    ``expected_pages`` alone only proves pages exist.  Pass ``expected_blocks``
    (ordered ``(source_page, block_src_hash)`` from the docstore source) to also
    prove no block is lost, extra, reordered or empty.  Skip reasons must be
    non-blank; ``source_page_ok`` maps ``(block_id, source_page, logical_page)`` ->
    justification and permits only that exact block to sit off its source page.
    Without ``expected_blocks`` the result is never ``ok`` unless the caller
    opts in with ``pages_only=True`` (page-level check only).  Skipped source
    pages are subtracted from the expected side only: a block of a skipped source
    page present in the output is an error (``excluded_present``), on any page.  Block ids must be
    non-empty strings.
    """
    skipped = skipped or {}
    source_page_ok = source_page_ok or {}
    bad_reasons = sorted({n for d in (skipped, source_page_ok) for n, r in d.items()
                          if not (r or "").strip()}, key=repr)
    plist = [p.get("page") for p in data.get("pages", [])]
    dup_pages = sorted({n for n in plist if plist.count(n) > 1})
    pages = {p.get("page"): p for p in data.get("pages", [])}
    missing = [n for n in expected_pages if n not in pages and n not in skipped]
    empty = [n for n in expected_pages if n in pages and n not in skipped and not pages[n].get("blocks")]
    skipped_but_present = [n for n in skipped if n in pages and pages[n].get("blocks")]
    unexpected = sorted(n for n in pages if n not in expected_pages)
    seen: set[Any] = set()
    dup: list[Any] = []
    textless: list[Any] = []
    bad_ids: list[Any] = []
    for _, _, b in _blocks(data):
        bid = b.get("block_id")
        if not isinstance(bid, str) or not bid:
            bad_ids.append(bid)
        if safe_key(bid) in seen:
            dup.append(bid)
        seen.add(safe_key(bid))
        if not block_src_hash(b):
            textless.append(bid)
    def _allowed(b: dict[str, Any], n: Any) -> bool:
        try:
            return (b.get("block_id"), _sp(b, n), n) in source_page_ok
        except TypeError:  # unhashable id / source_page: never justified
            return False

    def _skipped(sp: Any) -> bool:
        try:
            return sp in skipped
        except TypeError:
            return False

    mismatch = sorted({n for n, p in pages.items() for b in p.get("blocks", [])
                       if _sp(b, n) != n and not _allowed(b, n)}, key=repr)
    excluded_present = sorted({_sp(b, n) for n, p in pages.items() for b in p.get("blocks", [])
                               if _skipped(_sp(b, n))}, key=repr)
    block_gaps: dict[str, Any] = {}
    if expected_blocks is not None:
        got: list[tuple[int, str]] = []
        bad_sp: list[Any] = []
        for pg, _, b in _blocks(data):
            sp = _sp(b, pg)
            try:
                hash(sp)
            except TypeError:
                bad_sp.append(b.get("block_id"))
                sp = repr(sp)
            else:
                if isinstance(sp, tuple) and sp and sp[0] == "bad":
                    bad_sp.append(b.get("block_id"))
            got.append((sp, block_src_hash(b)))
        exp: list[tuple[int, str]] = [(e[0], e[1]) for e in expected_blocks if e[0] not in skipped]
        ce: Counter[tuple[int, str]] = Counter(exp)
        cg: Counter[tuple[int, str]] = Counter(got)
        lost = list((ce - cg).elements())
        extra = list((cg - ce).elements())
        block_gaps = {"lost": lost, "extra": extra, "bad_source_page": bad_sp,
                      "out_of_order": (not lost and not extra and got != exp)}
    ok = not (bad_ids or (expected_blocks is None and not pages_only) or missing or empty or skipped_but_present or excluded_present or unexpected or dup or mismatch
              or dup_pages or bad_reasons or textless
              or (expected_blocks is not None and (block_gaps["lost"] or block_gaps["extra"] or block_gaps["bad_source_page"]
                                                   or block_gaps["out_of_order"])))
    return {"missing": missing, "empty": empty, "skipped_but_present": skipped_but_present,
            "unexpected": unexpected, "duplicate_ids": dup, "duplicate_pages": dup_pages,
            "source_page_mismatch": mismatch, "excluded_present": excluded_present, "blank_reasons": bad_reasons,
            "textless_blocks": textless, "invalid_ids": bad_ids,
            "block_level_checked": expected_blocks is not None,
            "block_gaps": block_gaps, "ok": ok}
