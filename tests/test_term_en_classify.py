import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import term_en_classify as C  # noqa: E402

COLS_GL = ["term", "definition", "applicable", "abbr", "source"]
META = {"7": {"start": 60, "end": 70, "title_en": "SIGALIONIDAE"}}


def test_rules_label_rank_and_taxon():
    assert C.rules_label("family") == ("rank", [])
    assert C.rules_label("Siboglinidae") == ("taxon_name", [])
    assert C.rules_label("branchia")[0] != "taxon_name"  # -ia is not a taxon suffix


def test_rules_label_domains_and_heads():
    assert C.rules_label("chaeta") == ("structure", ["chaetae"])
    assert "appendage" in C.rules_label("ventral cirrus")[1]
    assert C.rules_label("ventral cirrus")[0] == "structure"
    assert "digestive" in C.rules_label("pharynx")[1]
    assert C.rules_label("serrate")[0] == "character_state"  # descriptor ending, no head noun
    assert C.rules_label("methodfoo") == ("", [])  # no rule hit -> residual


def test_locate_rouse_and_handbook():
    loc = C.locate("ch07 SIGALIONIDAE", META, "Rouse2022")
    assert loc["section"] == "ch07" and loc["pages"] == "60-70" and loc["file"] == "ch07.txt"
    hb = C.locate("3.2 Sigalionidae Kinberg, 1855 [s7_3.txt]", META, "Handbook")
    assert hb["section"] == "3.2" and hb["file"] == "s7_3.txt"


def test_zh_status():
    assert C.zh_status({"zh_yiku": "背须", "zh_rouse": "背须"}) == "一致"
    assert C.zh_status({"zh_yiku": "叫鞘翅", "zh_rouse": "鞘翅"}) == "冲突待裁"
    assert C.zh_status({"zh_yiku": "", "zh_rouse": ""}) == "无"


def _write(p, rows, cols):
    with open(p, "w", encoding="utf8", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(cols)
        w.writerows(rows)


def test_build_and_write(tmp_path):
    ann = tmp_path / "ann.tsv"
    _write(ann, [["ventral cirrus", "cirrus on lower edge", "Polychaeta", "vc", "x"]], COLS_GL)
    rg = tmp_path / "rg.tsv"
    _write(rg, [["chaeta", "bristle", "Annelida", "", ""], ["pharynx", "gut part", "Annelida", "", ""]], COLS_GL)
    bf = tmp_path / "bf.tsv"
    _write(bf, [
        ["Sigalionidae", "Rouse2022", "ch07 SIGALIONIDAE", "ventral cirri", "3", "1", "1", "腹须", "腹须"],
        ["General: x", "Handbook", "h", "noise phrase", "1", "0", "0", "", ""],
        ["Nereididae", "Rouse2022", "ch08 NEREIDIDAE", "bodywall rare", "1", "0", "0", "", ""],
        ["Nereididae", "Rouse2022", "ch08 NEREIDIDAE", "fact represent palp now", "2", "0", "0", "", ""],
    ], ["family", "book", "unit", "term", "freq", "in_glossary", "in_yiku", "zh_yiku", "zh_rouse_std"])
    cs, fams = C.build(bf, ann, rg, META, min_body_freq=2)
    keys = {c["key"]: c for c in cs}
    assert "ventral cirrus" in keys and "chaeta" in keys
    assert "bodywall rare" not in keys          # body-only, freq 1: dropped
    assert "fact represent palp now" not in keys  # body-only, 5 words: noise
    assert keys["ventral cirrus"]["fam"]["Sigalionidae"] == 3
    assert keys["ventral cirrus"]["tier"] == "glossary"
    sig = next(f for f in fams if f["family"] == "Sigalionidae")
    assert sig["rouse_chapter"] == "ch07 SIGALIONIDAE" and sig["rouse_pages"] == "60-70"
    out = tmp_path / "out"
    C.write_outputs(cs, fams, out)
    for n in ("01_英文术语.xlsx", "01_英文术语.tsv", "02_中文译名证据.xlsx", "03_来源与出现位置.xlsx",
              "04_科章节定位.xlsx", "05_出现位置明细.tsv"):
        assert (out / n).exists(), n
    from openpyxl import load_workbook

    def xrows(n):
        ws = load_workbook(out / n).active
        return [[c.value for c in r] for r in ws.iter_rows()]

    h1 = xrows("01_英文术语.xlsx")[0]
    assert not [h for h in h1 if h.startswith("zh_")] and "type" in h1
    for n in ("01_英文术语.xlsx", "02_中文译名证据.xlsx", "03_来源与出现位置.xlsx", "04_科章节定位.xlsx"):
        w = load_workbook(out / n).active
        assert w.freeze_panes == "A2" and w.auto_filter.ref and w["A1"].font.bold, n
    h2, *b2 = xrows("02_中文译名证据.xlsx")
    assert "zh_status" in h2
    assert next(dict(zip(h2, r)) for r in b2 if r[1] == "ventral cirrus")["zh_status"] == "一致"
    h3, *b3 = xrows("03_来源与出现位置.xlsx")
    assert "attested_families" in h3
    assert next(dict(zip(h3, r)) for r in b3 if r[1] == "ventral cirrus")["attested_families"].startswith("Sigalionidae(3)")
    assert xrows("04_科章节定位.xlsx")[0][0] == "family"
    locs = list(csv.DictReader(open(out / "05_出现位置明细.tsv", encoding="utf8"), delimiter="\t"))
    assert any(x["term"] == "ventral cirrus" and x["pages"] == "60-70" for x in locs)


def test_leading_non_letter_terms_excluded_and_xlsx_text(tmp_path):
    # '-day-old larva' is a fragment of '6-day-old larva': excluded from deliverables, logged. xlsx cells stay text.
    from openpyxl import load_workbook

    ann = tmp_path / "ann.tsv"
    _write(ann, [["-day-old larva", "larva of 1 day", "Annelida", "", ""]], COLS_GL)
    bf = tmp_path / "bf.tsv"
    _write(bf, [["Opheliidae", "Rouse2022", "ch09 OPHELIIDAE", "-day-old larva", "2", "0", "0", "", ""]],
           ["family", "book", "unit", "term", "freq", "in_glossary", "in_yiku", "zh_yiku", "zh_rouse_std"])
    exc: list = []
    cs, fams = C.build(bf, ann, _rg(tmp_path), META, min_body_freq=2, excluded=exc)
    assert [e["term"] for e in exc] == ["-day-old larva"] and exc[0]["reason"] == "leading_non_letter"
    out = tmp_path / "out"
    C.write_outputs(cs, fams, out)
    assert not [r for r in csv.DictReader(open(out / "01_英文术语.tsv", encoding="utf8"), delimiter="\t")
                if not r["term"][:1].isalpha()]
    vals = []
    for x in out.glob("0[123]_*.xlsx"):
        ws = load_workbook(x, read_only=True).active
        vals += [(c.value, c.data_type) for row in ws.iter_rows(min_row=2) for c in row if c.value == "-day-old larva"]
    assert not vals  # excluded from all xlsx
    assert all(isinstance(row[1].value, str) for x in out.glob("0[123]_*.xlsx")
               for row in load_workbook(x).active.iter_rows(min_row=2))


def _rg(tmp_path):
    p = tmp_path / "rg.tsv"
    _write(p, [["chaeta", "bristle", "Annelida", "", ""]], COLS_GL)
    return p


def test_load_labels_merge_key_and_term(tmp_path):
    a, b = tmp_path / "a.tsv", tmp_path / "b.tsv"
    _write(a, [["chaeta", "structure", "", "1"], ["pharynx", "structure", "digestive", "1"]], ["key", "type", "domain", "is_term"])
    _write(b, [["chaeta", "", "chaetae", "", "r"]], ["term", "type", "domain", "is_term", "reason"])
    m = C.load_labels([str(a), str(b)])
    assert m["chaeta"]["type"] == "structure" and m["chaeta"]["domain"] == "chaetae"  # empty cell does not erase
    assert m["pharynx"]["domain"] == "digestive"


def test_raw_occurrences_columns_and_locations(tmp_path):
    ann = tmp_path / "ann.tsv"
    _write(ann, [["ventral cirrus", "cirrus on lower edge", "Polychaeta", "vc", "x"],
                 ["unseen term", "never in text", "Polychaeta", "", "x"]], COLS_GL)
    rg = tmp_path / "rg.tsv"
    _write(rg, [["ventral cirri", "rouse def", "Annelida", "", ""], ["rouse only", "d2", "Annelida", "", ""]], COLS_GL)
    bf = tmp_path / "bf.tsv"
    _write(bf, [
        ["Sigalionidae", "Rouse2022", "ch07 SIGALIONIDAE", "Ventral Cirri", "3", "1", "1", "腹须", "腹须"],
        ["General: x", "Handbook", "3.2 Intro Kinberg, 1855 [s7_3.txt]", "ventral cirrus", "1", "1", "0", "", ""],
    ], ["family", "book", "unit", "term", "freq", "in_glossary", "in_yiku", "zh_yiku", "zh_rouse_std"])
    out = tmp_path / "raw.tsv"
    n = C.write_raw_occurrences(bf, ann, rg, META | {"7": {**META["7"], "id": "oso-x-chapter-7"}}, out)
    rows = list(csv.DictReader(open(out, encoding="utf8"), delimiter="\t"))
    assert n == len(rows) == 4
    assert list(rows[0]) == C.RAW_COLS and len(C.RAW_COLS) == 26
    assert [r["occ_id"] for r in rows] == ["OCC000001", "OCC000002", "OCC000003", "OCC000004"]
    ro = rows[0]
    assert (ro["unit_kind"], ro["unit_id"], ro["rouse_chapter_no"], ro["rouse_oso_id"]) == ("family", "ch07", "7", "oso-x-chapter-7")
    assert (ro["rouse_page_start"], ro["rouse_page_end"], ro["source_file"]) == ("60", "70", "ch07.txt")
    assert ro["term_raw"] == "Ventral Cirri" and ro["term_key"] == "ventral cirrus" and ro["family"] == "Sigalionidae"
    assert ro["in_annikey"] == "1" and ro["annikey_term"] == "ventral cirrus" and ro["in_rouse_glossary"] == "1"
    hb = rows[1]
    assert (hb["unit_kind"], hb["unit_id"], hb["hb_section_no"], hb["source_file"]) == ("general", "3.2", "3.2", "s7_3.txt")
    assert hb["family"] == "" and hb["hb_section_title"].startswith("Intro") and hb["rouse_chapter_no"] == ""
    go = {r["term_key"]: r for r in rows if r["unit_kind"] == "glossary_only"}
    assert set(go) == {"unseen term", "rouse only"}
    assert go["unseen term"]["unit_id"] == "" and go["unseen term"]["in_annikey"] == "1" and go["unseen term"]["freq"] == "0"
    assert go["rouse only"]["in_rouse_glossary"] == "1" and go["rouse only"]["in_annikey"] == "0"
