"""booklayout run: config errors, page parsing, status budget warnings, copy-as-translation,
and the builder speed fixes (genus regex cache, image sha1 cache, page-map read counter)."""
from __future__ import annotations

import json

import pytest

from booklayout import builder, run


def test_parse_pages():
    assert run.parse_pages(None, 10) == (1, 10)
    assert run.parse_pages("all", 10) == (1, 10)
    assert run.parse_pages("3-5", 10) == (3, 5)
    assert run.parse_pages("4", 10) == (4, 4)
    for bad in ("0-3", "5-3", "2-11"):
        with pytest.raises(ValueError):
            run.parse_pages(bad, 10)


def test_missing_pdf_is_config_error(tmp_path):
    rc = run.run_book(tmp_path / "nope.pdf", tmp_path / "o", None, "en", "zh-CN", "t", None,
                      False, False, False, 60.0, None)
    assert rc == run.EXIT_CONFIG == 40


def test_bad_page_range_is_config_error(tmp_path):
    import fitz
    doc = fitz.open()
    doc.new_page()
    f = tmp_path / "a.pdf"
    doc.save(str(f))
    rc = run.run_book(f, tmp_path / "o", "5-9", "en", "zh-CN", "t", None, False, False, False, 60.0, None)
    assert rc == run.EXIT_CONFIG


def test_status_budget_warning_and_file(tmp_path):
    st = run.Status(tmp_path / "s.json", 10.0)
    st.stage("fast", 1.0, True)
    st.stage("slow", 99.0, True)
    d = json.loads((tmp_path / "s.json").read_text(encoding="utf-8"))
    assert d["stages"]["slow"]["s"] == 99.0
    assert any("slow" in w for w in d["warnings"]) and not any("fast" in w for w in d["warnings"])


def test_copy_source_as_translation(tmp_path):
    src = tmp_path / "s.json"
    src.write_text(json.dumps({"pages": [{"blocks": [{"text": "a"}, {"text": "b", "translation": "B"}, {"text": ""}]}]}),
                   encoding="utf-8")
    dst = tmp_path / "d.json"
    assert run.copy_source_as_translation(src, dst) == 1
    blocks = json.loads(dst.read_text(encoding="utf-8"))["pages"][0]["blocks"]
    assert blocks[0]["translation"] == "a" and blocks[1]["translation"] == "B" and "translation" not in blocks[2]


def test_genus_regex_cached_per_set():
    g = {"Nereis", "Arenicola"}
    assert builder._genus_rx(g) is builder._genus_rx(g)
    assert builder._genus_rx(g).search("see Nereis diversicolor")
    assert builder._genus_rx({"Spio"}) is not builder._genus_rx(g)


def test_counting_map_counts_reads():
    m = builder._CountingMap({"1": 5})
    assert m.reads == 0
    assert m.get("1") == 5 and m.get("x", "d") == "d" and m["1"] == 5
    assert m.reads == 3


def test_image_sha1_is_cached():
    from docx.parts.image import ImagePart
    assert getattr(ImagePart, "_bl_sha1_cached", False)
