"""fingerprint / likeness, and the fontlevels / probe fixes they rest on."""
import fitz
import pytest

from booklayout import cli, fontlevels, likeness
from booklayout.fingerprint import fingerprint
from booklayout.furniture import signature
from docstore.probe import page_columns


def _span(font, size, text="Title", flags=0):
    return {"font": font, "size": size, "text": text, "flags": flags}


def test_line_styles_faux_small_caps_and_mixed_scripts():
    caps = [_span("Foo-Bold", 14, "F"), _span("Foo-Bold", 10, "ABRICIIDAE")]
    assert fontlevels._line_styles(caps) == {("Foo", 14, True, fontlevels.is_serif("Foo-Bold"))}
    mixed = [_span("SimHei", 12, "第八章蠕鳞虫科的形态"), _span("Times-Bold", 12, "Chapter", 4)]
    (st,) = fontlevels._line_styles(mixed)
    assert st[0] == "SimHei"  # most characters win
    body_plus_big = [_span("Foo", 9, "text"), _span("Bar-Bold", 14, "BIG")]
    assert len(fontlevels._line_styles(body_plus_big)) == 2  # still rejected


def test_cjk_sans_is_not_serif():
    assert not fontlevels.is_serif("SimHei")
    assert not fontlevels.is_serif("ABCDEF+MicrosoftYaHei-Bold")
    assert fontlevels.is_serif("SimSun")


def _pg(heading_y):
    doc = fitz.open()
    page = doc.new_page(width=420, height=600)
    page.insert_text((50, heading_y), "Chapter Title", fontname="hebo", fontsize=14)
    for i in range(12):
        page.insert_text((50, 150 + 12 * i), f"Body text line number {i} of the paragraph goes here.",
                         fontname="tiro", fontsize=9.5)
    return page


def test_heading_equal_to_running_head_is_kept_only_in_body():
    furn = {signature("Chapter Title")}
    in_body = _pg(100)
    body = fontlevels.body_style([in_body])
    assert [c["text"] for c in fontlevels.heading_candidates(in_body, body, furn)] == ["Chapter Title"]
    at_edge = _pg(30)
    assert fontlevels.heading_candidates(at_edge, body, furn) == []


def _rows(n, x0, x1, y0=100):
    return [{"text": "t", "x0": x0, "x1": x1, "y0": y0 + 14 * i, "y1": y0 + 14 * i + 10} for i in range(n)]


def test_page_columns_ignores_figure_labels_and_edge_band():
    text = _rows(10, 50, 250) + _rows(10, 300, 500)
    assert page_columns(text)[0] == 2
    labels = [{"text": "L", "x0": 200, "x1": 350, "y0": 400 + 6 * i, "y1": 405 + 6 * i} for i in range(12)]
    assert page_columns(text + labels)[0] == 1  # the old misreading
    assert page_columns(text + labels, 800, exclude=[(190, 395, 360, 480)])[0] == 2
    head = [{"text": "H", "x0": 100, "x1": 450, "y0": 20, "y1": 30}] * 6
    assert page_columns(text + head, 800)[0] == 2


def _book(path, cols, figure=True, folio="alternating", n=4):
    doc = fitz.open()
    for p in range(1, n + 1):
        page = doc.new_page(width=420, height=600)
        page.insert_text((150, 28), "Handbook of Zoology", fontname="helv", fontsize=8)
        fx = (50 if p % 2 else 340) if folio == "alternating" else 200
        page.insert_text((fx, 575), str(p), fontname="helv", fontsize=8)
        page.insert_text((50, 80), "1 Chapter", fontname="hebo", fontsize=16)
        page.insert_text((50, 100), "Section", fontname="hebo", fontsize=11)
        if cols == 2:
            for i in range(26):
                page.insert_text((40, 130 + 11 * i), f"left column text line {i} of paragraph", fontname="tiro", fontsize=8)
                page.insert_text((225, 130 + 11 * i), f"right column text line {i} of paragraph", fontname="tiro", fontsize=8)
        else:
            for i in range(26):
                page.insert_text((50, 130 + 11 * i), f"single column text line number {i} of the paragraph", fontname="tiro", fontsize=8)
        if figure and p == 2:
            page.draw_rect(fitz.Rect(60, 430, 200, 520), fill=(0.7, 0.7, 0.7))
            page.insert_text((60, 535), "Figure 1. A caption here", fontname="tiro", fontsize=8)
    doc.save(str(path))
    return path


@pytest.fixture(scope="module")
def books(tmp_path_factory):
    d = tmp_path_factory.mktemp("lk")
    return {"src": _book(d / "src.pdf", 2), "one": _book(d / "one.pdf", 1, figure=False, folio="center"),
            "same": _book(d / "same.pdf", 2)}


def test_fingerprint_measures_structure(books):
    fp = fingerprint(books["src"])
    assert fp["columns"] == 2 and fp["figures"] == 1 and fp["captions"] == 1
    assert fp["heading"]["n_levels"] == 2
    assert fp["furniture"]["position"] == ["bottom", "top"] and fp["furniture"]["folio_rule"] == "alternating"


def test_likeness_self_and_equivalent_pass(books):
    a, b = fingerprint(books["src"]), fingerprint(books["same"])
    r = likeness.compare(a, b)
    assert r["pass"] and r["n_fail"] == 0


def test_likeness_reports_known_bad_output(books):
    r = likeness.compare(fingerprint(books["src"]), fingerprint(books["one"]))
    failed = {i["field"] for i in r["items"] if not i["ok"] and i["tier"] == "A"}
    assert {"figures", "captions", "columns", "furniture.type"} <= failed
    assert not r["pass"]


def test_columns_out_config_accepts_single_column_translation(books):
    cfg = likeness.LikenessConfig(columns_out=1, skip=["figures", "captions", "furniture.type", "roles"])
    r = likeness.compare(fingerprint(books["src"]), fingerprint(books["one"]), cfg)
    assert r["pass"]
    col = next(i for i in r["items"] if i["field"] == "columns")
    assert col["ok"] and col["src"] == 2 and col["out"] == 1


def test_config_rejects_unknown_key(tmp_path):
    p = tmp_path / "likeness.json"
    p.write_text('{"nonsense": 1}', encoding="utf-8")
    with pytest.raises(ValueError):
        likeness.load_config(p)


def test_cli(books, tmp_path, capsys):
    out = tmp_path / "f.json"
    assert cli.main(["fingerprint", str(books["src"]), "--json", str(out)]) == 0
    assert out.exists() and "columns=2" in capsys.readouterr().out
    assert cli.main(["likeness", str(books["src"]), str(books["same"])]) == 0
    assert cli.main(["likeness", str(books["src"]), str(books["one"])]) == 1


def _plain_book(path, n=3):
    doc = fitz.open()
    for i in range(n):
        page = doc.new_page(width=420, height=600)
        page.insert_text((50, 80), "Chapter Title", fontname="hebo", fontsize=14)
        for j in range(24):
            page.insert_text((50, 130 + 12 * j), f"Body text line {j} of paragraph {i} goes here ok.",
                             fontname="tiro", fontsize=9.5)
    doc.save(str(path))


def test_run_and_failures_with_config(tmp_path):
    src, out = tmp_path / "s.pdf", tmp_path / "o.pdf"
    _plain_book(src)
    _plain_book(out)
    cfg = tmp_path / "likeness.json"
    cfg.write_text('{"columns_out": 1}')
    res = likeness.run(src, out, "1-3", None, cfg)
    assert res["pass"] and likeness.failures(res) == []
    cfg.write_text('{"columns_out": 2}')
    bad = likeness.run(src, out, None, None, cfg)
    assert any("columns" in f for f in likeness.failures(bad))


def test_qa_parser_accepts_likeness_options():
    ns = cli.build_parser().parse_args(
        ["qa", "--aligned", "a", "--figures", "f", "--likeness-src", "s.pdf",
         "--likeness-config", "l.json", "--likeness-src-pages", "1-3"])
    assert str(ns.likeness_src) == "s.pdf" and ns.likeness_src_pages == "1-3"


def _fp(roles, n_levels=3):
    return {"roles": roles, "heading": {"n_levels": n_levels, "numbered": False}, "figures": 0, "captions": 0,
            "columns": 1, "furniture": {"position": ["top"], "kinds": ["text"], "folio_rule": "x", "head_rule_line": False},
            "italic": {"present": False}, "book": {"contents_page": None}, "allowed_info": {}, "n_pages": 1}


def test_role_sequence_does_not_compare_heading_rung_labels():
    # same structure, but the output's ladder numbers its rungs differently (H6 vs H4):
    # rung identity is judged by heading.n_levels, not by the role sequence
    src = _fp(["H2", "BODY", "H6", "BODY", "FIG", "CAP", "BODY", "H6", "BODY"])
    out = _fp(["H1", "BODY", "H4", "BODY", "FIG", "CAP", "BODY", "H4", "BODY"])
    res = likeness.compare(src, out)
    assert next(i for i in res["items"] if i["field"] == "roles")["ok"]


def test_role_sequence_still_fails_when_a_heading_becomes_body_or_figure_moves():
    src = _fp(["H2", "BODY", "H6", "BODY", "FIG", "CAP", "BODY"])
    out = _fp(["BODY", "BODY", "BODY", "CAP", "FIG", "BODY", "BODY"])
    res = likeness.compare(src, out)
    assert not next(i for i in res["items"] if i["field"] == "roles")["ok"]
