from pathlib import Path

from docstore.layoutfetch import cached_pages, fetch_layout


def test_fetch_skips_cached_and_saves(tmp_path: Path) -> None:
    d = tmp_path / "layout" / "K"
    d.mkdir(parents=True)
    (d / "p0002.json").write_text("{}")
    calls, saved = [], []

    def run(pdf, pages, log, chunk_no):
        calls.append(list(pages))
        ok = {p: ("t", {"_layout": {"page": p}, "_raw_jsonl": "x"}) for p in pages if p != 3}
        return ok, {3: "boom"}

    def save(root, key, p, meta):
        saved.append(p)

    r = fetch_layout(tmp_path, "K", "x.pdf", [1, 2, 3, 4], run=run, save=save, log=lambda s: None)
    assert calls == [[1, 3, 4]]
    assert saved == [1, 4] and r["fetched"] == [1, 4]
    assert r["skipped"] == [2] and r["failed"] == {3: "boom"}
    assert cached_pages(tmp_path, "K") == {2}


def test_force_refetches(tmp_path: Path) -> None:
    (tmp_path / "layout" / "K").mkdir(parents=True)
    (tmp_path / "layout" / "K" / "p0001.json").write_text("{}")
    calls = []
    fetch_layout(tmp_path, "K", "x.pdf", [1], force=True,
                 run=lambda pdf, pages, log, chunk_no: (calls.append(pages) or ({}, {})),
                 save=lambda *a: None, log=lambda s: None)
    assert calls == [[1]]
