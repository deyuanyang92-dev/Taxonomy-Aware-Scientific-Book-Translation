"""T2: booklayout ingest-native -> aligned/2 (design 2026-11-26 B.5)."""
from pathlib import Path

import fitz
import pytest

from booklayout import cli, fontlevels, ingest_native
from booklayout.profile import validate_aligned

VOL3 = Path("/mnt/p/翻译-译作/Handbook_Annelida/Handbook of Zoology-Annelida-Volume3.pdf")


def _pdf(path, npages=4):
    doc = fitz.open()
    for n in range(npages):
        page = doc.new_page(width=420, height=600)
        page.insert_text((200, 30), "RUNNING HEAD TEXT", fontname="helv", fontsize=8)
        page.insert_text((200, 580), f"{100 + n}", fontname="helv", fontsize=8)
        if n == 0:
            page.insert_text((50, 80), "7.4.1 Fabriciidae", fontname="hebo", fontsize=12)
            page.insert_text((50, 105), "Introduction", fontname="hebo", fontsize=9.5)
        y = 130
        for i in range(6):
            page.insert_text((50, y + 12 * i), f"Body text line {i} of paragraph on page {n} goes here ok.",
                             fontname="tiro", fontsize=9.5)
        page.insert_text((50, y + 80), "Fig. 1: A caption sentence.", fontname="tiro", fontsize=9.5)
        page.insert_text((50, y + 110), "seg-", fontname="tiro", fontsize=9.5)
        page.insert_text((50, y + 121), "ment of Nereis", fontname="tiro", fontsize=9.5)
        w = fitz.get_text_length("ment of Nereis ", fontname="tiro", fontsize=9.5)
        page.insert_text((50 + w, y + 121), "virens", fontname="tiit", fontsize=9.5)
    doc.save(str(path))
    doc.close()


@pytest.fixture()
def data(tmp_path):
    _pdf(tmp_path / "a.pdf")
    return ingest_native.ingest(tmp_path / "a.pdf")


def test_schema_and_source(data):
    assert data["schema"] == "aligned/2"
    assert data["source"]["kind"] == "native" and len(data["source"]["sha1"]) == 40
    assert validate_aligned(data) == []
    assert all("chapter" in p and p["kind"] == "chapter" for p in data["pages"])


def test_furniture_dropped(data):
    texts = [b["text"] for p in data["pages"] for b in p["blocks"]]
    assert not any("RUNNING HEAD" in t for t in texts)
    assert not any(t.strip() in {"100", "101", "102", "103"} for t in texts)


def test_headings_match_fontlevels(tmp_path, data):
    heads = [(p["page"], b["text"], b["level"], b["level_source"])
             for p in data["pages"] for b in p["blocks"] if b["role"] == "heading"]
    doc = fitz.open(str(tmp_path / "a.pdf"))
    ref = fontlevels.analyse([doc.load_page(0)])["headings"]
    assert [(h["text"], h["level"]) for h in ref] == [(t, lv) for _p, t, lv, _s in heads]
    assert heads[0][3] == "number" and heads[1][3] == "font"
    blk = data["pages"][0]["blocks"][0]
    assert blk["style"] == "Heading 1" and blk["src"]["origin"] == "native"


def test_roles_runs_and_hyphen_join(data):
    blocks = [b for p in data["pages"] for b in p["blocks"]]
    cap = next(b for b in blocks if b["role"] == "caption")
    assert cap["style"] == "Caption"
    joined = next(b for b in blocks if "segment" in b["text"])
    assert "*virens*" in joined["text"]
    assert any(r.get("i") and r["t"].strip() == "virens" for r in joined["runs"])
    assert joined["src"]["page"] and len(joined["src"]["bbox"]) == 4 and len(joined["src"]["hash"]) == 16
    assert joined["font"]["family"] and joined["font"]["size"] == 9.5


def test_hash_stable_and_sensitive(tmp_path, data):
    again = ingest_native.ingest(tmp_path / "a.pdf")
    h = lambda d: [b["src"]["hash"] for p in d["pages"] for b in p["blocks"]]  # noqa: E731
    assert h(data) == h(again) and len(set(h(data))) > 1


def test_pages_subset(tmp_path):
    _pdf(tmp_path / "a.pdf")
    d = ingest_native.ingest(tmp_path / "a.pdf", [2, 3])
    assert [p["page"] for p in d["pages"]] == [2, 3]


def test_cli_and_build(tmp_path):
    _pdf(tmp_path / "a.pdf")
    out = tmp_path / "a.json"
    assert cli.main(["ingest-native", str(tmp_path / "a.pdf"), "--pages", "1-3", "-o", str(out)]) == 0
    assert cli.main(["validate-aligned", "--aligned", str(out)]) == 0
    fig = tmp_path / "fig"
    fig.mkdir()
    (fig / "source_figure_audit.json").write_text("{}", encoding="utf-8")
    docx = tmp_path / "a.docx"
    cli.main(["build", "--aligned", str(out), "--figures", str(fig), "--out", str(docx), "--title", "T",
              "--no-cache", "--strict-schema"])
    assert (tmp_path / "a.DRAFT.docx").exists() or docx.exists()


def test_validate_v2_rejects_bad_fields():
    base = {"schema": "aligned/2", "pages": [{"page": 1, "blocks": [
        {"role": "body", "text": "x", "src": {"origin": "fax", "bbox": [1, 2, 3]}, "level_source": "guess"}]}]}
    errs = validate_aligned(base)
    assert any("src.origin" in e for e in errs) and any("bbox" in e for e in errs)
    assert any("level_source" in e for e in errs)
    base["schema"] = "aligned/1"  # legacy files: new fields not policed
    assert validate_aligned(base) == []


@pytest.mark.skipif(not VOL3.exists(), reason="Handbook Vol3 PDF not on this machine")
def test_handbook_vol3_p13_14_smoke():
    d = ingest_native.ingest(VOL3, [13, 14])
    heads = [(b["level"], b["text"]) for p in d["pages"] for b in p["blocks"] if b["role"] == "heading"]
    # T2b: the 8 pt running head "7.4 Sedentaria..." (1 of 2 pages, so the 3-page signature misses it) is furniture
    assert not any("Sedentaria" in t for _, t in heads)
    assert any(t == "7.4.8 Fabriciidae Rioja, 1923" for _, t in heads)
    assert d["pages"][0]["columns"] == 2
    doc = fitz.open(str(VOL3))
    ref = fontlevels.analyse([doc.load_page(12), doc.load_page(13)])["headings"]
    kept = [(h["level"], h["text"]) for h in ref if "Sedentaria" not in h["text"]]
    assert [t for _, t in kept] == [t for _, t in heads]   # same headings; levels re-based once the head is gone
    assert validate_aligned(d) == []


# ---- T2b regressions (2026-11-26) ----

ROUSE = Path("/mnt/p/翻译-译作/Rouse2022_Annelida/原书/Rouse2022_Annelida_专著全本.pdf")


def test_unglue_page_number():
    assert ingest_native.unglue("413Index") == "Index"
    assert ingest_native.unglue("2019 Index") == "2019 Index"      # a space means no fusion
    assert ingest_native.unglue("3D printing") == "3D printing"    # needs >= 2 digits and Capital+lower


def test_caption_label_tolerates_bold_marker_and_figure_opener():
    from booklayout.pdffigures import CAPTION_RE

    for s in ("**Fig. 7.4.8.1**: Micrographs", "FIGURE 2.7: Annelid", "Figure 3. x", "*Fig. 2*"):
        assert CAPTION_RE.match(s), s
    assert CAPTION_RE.match("**Fig. 7.4.8.1**: x").group("label") == "7.4.8.1"
    assert not CAPTION_RE.match("Figurative speech 3")


def test_report_does_not_flag_bold_or_figure_captions(tmp_path):
    base = {"page": 1, "chapter": "c", "kind": "chapter"}
    blocks = [{"block_id": f"b{i}", "role": "caption", "text": t, "translation": t}
              for i, t in enumerate(("**Fig. 7.4.8.1**: x", "FIGURE 2.7: y", "Something else"))]
    data = {"pages": [dict(base, blocks=blocks)]}
    rep = cli._report(data, tmp_path)
    assert rep["bad_captions"] == ["b2"]


def _hb(size, bold=False, italic=False, family="Dante", level_source="font"):
    return {"role": "heading", "text": "x", "level": 9, "level_source": level_source,
            "font": {"family": family, "size": size, "bold": bold, "italic": italic}}


def test_refine_levels_compacts_ladder():
    eyebrow = dict(_hb(14), text="CHAPTER 12")
    pages = [{"page": 1, "blocks": [eyebrow, dict(_hb(24), text="ANATOMY"), dict(_hb(14, bold=True), text="A")]},
             {"page": 2, "blocks": [dict(_hb(18), text="GLOSSARY"), dict(_hb(12, family="Dante-Medium"), text="B"),
                                    dict(_hb(12, italic=True), text="C")]}]
    ingest_native.refine_levels(pages, 10.0)
    lv = [b["level"] for p in pages for b in p["blocks"]]
    assert lv == [1, 1, 2, 1, 3, 4]      # eyebrow shares chapter level; 18 and 24 pt share the display tier
    assert pages[0]["blocks"][2]["style"] == "Heading 2"


def test_refine_levels_keeps_numbered_books():
    pages = [{"page": 1, "blocks": [dict(_hb(14), level=1, level_source="number"), dict(_hb(12), level=3)]}]
    ingest_native.refine_levels(pages, 10.0)
    assert [b["level"] for b in pages[0]["blocks"]] == [1, 3]


def test_small_running_head_dropped_in_two_page_sample(tmp_path):
    doc = fitz.open()
    for n, head in enumerate(("7.4 Sedentaria: Spionida", "Fabriciidae Rioja")):  # differs per page
        page = doc.new_page(width=420, height=600)
        page.insert_text((60, 25), head, fontname="helv", fontsize=7)
        for i in range(8):
            page.insert_text((50, 100 + 12 * i), f"Body text line {i} on page {n} goes here okay.",
                             fontname="tiro", fontsize=10)
        page.insert_text((50, 585), "https://doi.org/10.1515/x", fontname="helv", fontsize=6)
    doc.save(str(tmp_path / "s.pdf"))
    d = ingest_native.ingest(tmp_path / "s.pdf")
    texts = [b["text"] for p in d["pages"] for b in p["blocks"]]
    assert not any("Sedentaria" in t or "Fabriciidae" in t or "doi.org" in t for t in texts)
    assert sum("Body text line 0" in t for t in texts) == 2


def test_narrow_gutter_found_when_full_width_line_present():
    mk = lambda x0, x1, y: {"x0": x0, "x1": x1, "y0": y, "y1": y + 9}  # noqa: E731
    lines = [mk(60, 300, 100 + 12 * i) for i in range(6)] + [mk(318, 560, 100 + 12 * i) for i in range(6)]
    g = ingest_native._narrow_gutter(lines)
    assert g and 300 <= g[0] and g[1] <= 318
    assert ingest_native._narrow_gutter(lines[:6]) is None   # single column


@pytest.mark.skipif(not ROUSE.exists(), reason="Rouse native PDF not on this machine")
def test_rouse_native_sample_vs_gt():
    """Quantified on the T1 GT scorer: levels, order and text must not regress (T2b baseline:
    heading_level_strict 0.115, order_tau 0.986, cer 0.031 before; 1.0 / 1.0 / 0.001 after)."""
    import sys

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "scripts" / "bench"))
    import layout_gt
    import layout_score

    pages = [6, 13, 16, 17, 19, 25, 30, 50, 60, 100, 120, 200, 339, 340]
    d = ingest_native.ingest(ROUSE, pages)
    doc = fitz.open(str(ROUSE))
    res = []
    for pg in d["pages"]:
        w, h = doc[pg["page"] - 1].rect.width, doc[pg["page"] - 1].rect.height
        blocks = [{"bbox_rel": [b["src"]["bbox"][0] / w, b["src"]["bbox"][1] / h, b["src"]["bbox"][2] / w,
                                b["src"]["bbox"][3] / h], "role": b["role"], "level": b.get("level"),
                   "text": b["text"], "order": i, "italic_words": []} for i, b in enumerate(pg["blocks"])]
        res.append(layout_score.score_layout(layout_gt.native_gt(str(ROUSE), pg["page"]),
                                             {"engine": "ingest-native", "blocks": blocks}))
    mean = lambda k: sum(r[k] for r in res if r[k] is not None) / max(1, sum(r[k] is not None for r in res))  # noqa: E731
    assert mean("heading_level_strict") >= 0.9
    assert mean("order_tau") >= 0.98
    assert mean("cer") <= 0.02
    assert max(b["level"] for p in d["pages"] for b in p["blocks"] if b["role"] == "heading") <= 4
    texts = [b["text"] for p in d["pages"] for b in p["blocks"] if b["role"] == "heading"]
    assert "introduction and systematics" not in {t.lower() for t in texts}  # running head gone (GLOSSARY p339 is a real title)
