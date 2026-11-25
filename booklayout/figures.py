"""Figures and captions as linked layout objects (issue #18).

A figure and its caption share an id and keep their source bounding boxes.
Linking uses the caption label when the figure carries one, otherwise
geometry (horizontal overlap first, then vertical gap), one-to-one.  Counting
figures and unmatched labels is not enough to call a page placed correctly, so
``audit_placement`` also checks adjacency, text between the pair, oversize
figures and captions, and overlap.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

BBox = tuple[float, float, float, float]
MAX_FIGURE_PAGE_FRACTION = 0.85
MAX_CAPTION_CHARS = 1500
MAX_CAPTION_PAGE_FRACTION = 0.35
MAX_GAP_PT = 60.0


@dataclass
class FigureObject:
    id: str
    page: int
    bbox: BBox
    caption_id: str | None = None
    caption_bbox: BBox | None = None
    caption_text: str = ""
    caption_chars: int = 0
    label: str | None = None


def _overlap_x(a: BBox, b: BBox) -> float:
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0]))


def _gap_y(a: BBox, b: BBox) -> float:
    """Vertical distance between two boxes (0 when they overlap vertically)."""
    return max(0.0, max(a[1], b[1]) - min(a[3], b[3]))


def link_figures(figures: Sequence[Mapping[str, Any]], captions: Sequence[Mapping[str, Any]]):
    """Return (objects, unmatched={"figures": [ids], "captions": [ids]})."""
    objs = [
        FigureObject(id=f["id"], page=f["page"], bbox=tuple(f["bbox"]),  # type: ignore[arg-type]
                     label=str(f["label"]) if f.get("label") is not None else None)
        for f in figures
    ]
    free = list(captions)

    def attach(obj: FigureObject, cap: Mapping[str, Any]) -> None:
        obj.caption_id = cap["id"]
        obj.caption_bbox = tuple(cap["bbox"])  # type: ignore[arg-type]
        obj.caption_text = cap.get("text", "")
        obj.caption_chars = int(cap.get("chars", len(obj.caption_text)))
        free.remove(cap)

    for obj in objs:  # 1. explicit label on the same page
        if obj.label is None:
            continue
        for cap in free:
            if cap["page"] == obj.page and str(cap.get("label")) == obj.label:
                attach(obj, cap)
                break
    pairs = []  # 2. geometry for the rest, cheapest pair first
    for obj in objs:
        if obj.caption_id:
            continue
        for cap in free:
            if cap["page"] != obj.page:
                continue
            cb = tuple(cap["bbox"])
            ov = _overlap_x(obj.bbox, cb)  # type: ignore[arg-type]
            if ov <= 0:
                continue
            pairs.append((_gap_y(obj.bbox, cb), -ov, obj.id, cap["id"]))  # type: ignore[arg-type]
    for _gap, _ov, oid, cid in sorted(pairs):
        obj = next(o for o in objs if o.id == oid)
        cap = next((c for c in free if c["id"] == cid), None)  # type: ignore[arg-type]
        if obj.caption_id or cap is None:
            continue
        attach(obj, cap)
    unmatched = {"figures": [o.id for o in objs if not o.caption_id],
                 "captions": [c["id"] for c in free]}
    return objs, unmatched


def audit_placement(objs: Sequence[FigureObject], unmatched: Mapping[str, Sequence[str]],
                    page: Mapping[str, float],
                    body_bboxes: Mapping[int, Sequence[BBox]] | None = None,
                    max_caption_chars: int = MAX_CAPTION_CHARS,
                    max_gap: float = MAX_GAP_PT) -> list[dict[str, Any]]:
    area = page["width"] * page["height"]
    problems: list[dict[str, Any]] = []
    for fid in unmatched.get("figures", []):
        problems.append({"reason": "unmatched_figure", "id": fid})
    for cid in unmatched.get("captions", []):
        problems.append({"reason": "unmatched_caption", "id": cid})
    for o in objs:
        w, h = o.bbox[2] - o.bbox[0], o.bbox[3] - o.bbox[1]
        if w * h > MAX_FIGURE_PAGE_FRACTION * area:
            problems.append({"reason": "oversize_figure", "id": o.id, "page": o.page})
        if not o.caption_bbox:
            continue
        cb = o.caption_bbox
        if o.caption_chars > max_caption_chars or \
                (cb[2] - cb[0]) * (cb[3] - cb[1]) > MAX_CAPTION_PAGE_FRACTION * area:
            problems.append({"reason": "oversize_caption", "id": o.id, "caption": o.caption_id})
        if _overlap_x(o.bbox, cb) > 0 and cb[1] < o.bbox[3] and cb[3] > o.bbox[1]:
            problems.append({"reason": "figure_caption_overlap", "id": o.id, "page": o.page})
        gap = _gap_y(o.bbox, cb)
        if gap > max_gap:
            problems.append({"reason": "caption_not_adjacent", "id": o.id, "gap_pt": round(gap, 1)})
        top, bottom = min(o.bbox[3], cb[3]), max(o.bbox[1], cb[1])
        for bb in (body_bboxes or {}).get(o.page, []):
            if bb[1] >= top - 0.5 and bb[3] <= bottom + 0.5 and _overlap_x(bb, o.bbox) > 0:
                problems.append({"reason": "body_between_figure_and_caption", "id": o.id})
                break
    return problems
