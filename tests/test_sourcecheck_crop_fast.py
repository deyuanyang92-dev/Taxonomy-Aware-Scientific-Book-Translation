from pathlib import Path

from PIL import Image

from booklayout import sourcecheck


def test_crop_uses_cached_page_png_without_pdftoppm(tmp_path, monkeypatch):
    cache = tmp_path / "tesseract"
    cache.mkdir()
    Image.new("RGB", (400, 600), "white").save(cache / "p0003.png")

    def boom(*a, **k):
        raise AssertionError("pdftoppm must not run when the page PNG is cached")

    monkeypatch.setattr(sourcecheck.subprocess, "run", boom)
    items = [{"type": "missing", "id": "abc", "src_page": 3, "box": [50, 60, 150, 90]}]
    sourcecheck.crop_items(Path("x.pdf"), items, tmp_path / "crops", 100, cache)
    assert Image.open(items[0]["crop"]).width > 100
