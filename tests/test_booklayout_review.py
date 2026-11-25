from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from booklayout import review


def _report(tmp: Path) -> Path:
    crop = tmp / "c.png"
    Image.new("RGB", (40, 20), "white").save(crop)
    items = [
        {"id": "a1", "type": "tess_noise", "src_page": 3, "source": "x", "output": "y"},
        {"id": "b2", "type": "review", "src_page": 6, "source": "Nepbtyidae", "output": "Nephtyidae",
         "crop": str(crop), "context": "Familia Nepbtyidae"},
        {"id": "c3", "type": "missing", "src_page": 1, "source": "Museo", "output": "", "crop": str(crop)},
        {"id": "d4", "type": "conflict", "src_page": 24, "source": "D", "output": "I"},
    ]
    p = tmp / "sc.json"
    p.write_text(json.dumps({"items": items}), encoding="utf-8")
    return p


def test_open_items_skip_noise_and_accepted_and_sort_by_severity(tmp_path: Path):
    rep = json.loads(_report(tmp_path).read_text())
    got = [it["id"] for it in review.open_items(rep, {"d4"})]
    assert got == ["c3", "b2"]


def test_review_page_embeds_crops_and_keeps_previous_accepted(tmp_path: Path):
    acc = tmp_path / "accepted.json"
    acc.write_text(json.dumps(["d4", "old"]), encoding="utf-8")
    out = tmp_path / "r.html"
    res = review.run(_report(tmp_path), out, acc)
    assert res["open"] == 2
    page = out.read_text(encoding="utf-8")
    assert page.count('<tr data-id=') == 2
    assert "data:image/png;base64," in page
    assert '"d4", "old"' in page          # export merges earlier decisions
    assert "Nepbtyidae" in page and "&lt;" not in "Nepbtyidae"


def test_review_page_lists_qa_problems(tmp_path: Path):
    qa = tmp_path / "qa.json"
    qa.write_text(json.dumps({"three_reviews": {"review2_layout": {"ok": False, "problems": ["p4 name run-in"]}}}))
    res = review.run(_report(tmp_path), tmp_path / "r.html", None, qa)
    assert res["qa_problems"] == 1
    assert "p4 name run-in" in (tmp_path / "r.html").read_text(encoding="utf-8")
