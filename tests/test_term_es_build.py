import csv
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "term_es_build", Path(__file__).resolve().parent.parent / "scripts" / "term_es_build.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

HDR = ["term", "kind", "vol", "page", "printed", "family", "genus", "section", "n"]


def _write(d, rows):
    with open(d / "raw_term_occurrences.tsv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(HDR)
        w.writerows(rows)


def _read(p):
    with open(p, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def test_candidates(tmp_path):
    rows = []
    for p in range(1, 5):
        rows.append(["seda", "uni", "21", p, p, "Fam1", "", "Diagnosis", 2])
    rows.append(["sedas", "uni", "21", 9, 9, "Fam1", "", "Diagnosis", 1])
    for p in range(1, 4):
        rows.append(["ción", "uni", "22", p, p, "", "", "", 2])
        rows.append(["ciones", "uni", "22", p + 10, p, "", "", "", 1])
    for p in range(1, 4):  # freq 3 only -> dropped
        rows.append(["raro", "uni", "21", p, p, "", "", "", 1])
    for p in range(1, 3):  # pages 2 -> dropped
        rows.append(["pocas", "uni", "21", p, p, "", "", "", 9])
    for p in range(1, 4):  # -o/-a not merged
        rows.append(["blanco", "uni", "21", p, p, "", "", "", 2])
        rows.append(["blanca", "uni", "21", p, p, "", "", "", 2])
    for p in range(1, 6):
        rows.append(["seda blanca", "bi", "21", p, p, "F", "", "", 2])
    rows.append(["x y", "bi", "21", 1, 1, "F", "", "", 20])
    _write(tmp_path, rows)
    res = m.candidates(tmp_path)
    uni = {r["term"]: r for r in _read(tmp_path / "cand_uni.tsv")}
    assert set(uni) == {"seda", "ción", "blanco", "blanca"}
    assert uni["seda"]["freq"] == "9" and uni["seda"]["forms"] == "seda|sedas"
    assert uni["ción"]["forms"] == "ción|ciones" and uni["ción"]["n_pages"] == "6"
    assert list(uni["seda"]) == m.CAND_COLS
    b = _read(tmp_path / "batches" / "uni_01.tsv")
    assert list(b[0]) == m.BATCH_COLS and len(b) == 4
    ng = _read(tmp_path / "cand_ngram.tsv")
    assert [r["term"] for r in ng] == ["seda blanca"]
    assert res == {"uni": 4, "batches": 1, "ngram": 1}


def _ctx(**kw):
    base = dict(taxa=frozenset({"syllis", "abarenicola"}), epithets=frozenset({"claparedi"}),
                authors=frozenset({"grube"}), unknown_es=frozenset(), unknown_en=frozenset(),
                glossary=frozenset({"seda"}), stats={}, base_share=0.7)
    base.update(kw)
    return m.Ctx(**base)


def test_classify_word_rules():
    c = _ctx(unknown_es=frozenset({"syllis", "syllidae", "claparedi", "grube", "parápodo", "with", "xx"}),
             unknown_en=frozenset({"syllidae", "claparedi", "grube", "parápodo", "xx"}))
    assert m.classify_word("syllis", c) == ("taxon", "taxa_headings")
    assert m.classify_word("syllidae", c) == ("taxon", "taxon_suffix")
    assert m.classify_word("claparedi", c) == ("taxon", "species_epithet")
    assert m.classify_word("grube", c) == ("person", "taxon_author")
    assert m.classify_word("seda", c) == ("domain", "glossary")
    assert m.classify_word("casa", c) == ("general", "aspell_es")
    assert m.classify_word("with", c) == ("english", "aspell_en")
    assert m.classify_word("parápodo", c) == ("specialised", "aspell_unknown")
    assert m.classify_word("xx", c) == ("other", "short_unknown")
    assert m.classify_word("a-b", c) == ("other", "non_alpha")


def test_domain_by_section():
    c = _ctx(stats={"lóbulo": (95, 100, 6), "zona": (95, 100, 2), "casa": (70, 100, 7)})
    assert m.classify_word("lóbulo", c) == ("domain", "section_profile")
    assert m.classify_word("zona", c)[0] == "general"   # too few volumes
    assert m.classify_word("casa", c)[0] == "general"   # share not above baseline


def test_classify_ngram():
    c = _ctx(unknown_es=frozenset({"parápodo", "birrámeo"}), unknown_en=frozenset({"parápodo", "birrámeo"}))
    assert m.classify_ngram(["parápodo", "birrámeo"], c) == ("phrase", "has_specialised_or_glossary")
    assert m.classify_ngram(["parápodo", "de"], c) == ("general", "edge_general")
    assert m.classify_ngram(["syllis", "parápodo"], c)[0] == "taxon"
    assert m.classify_ngram(["seda", "simple"], c) == ("general", "edge_general")


def test_classify_cmd(tmp_path):
    hdr = m.CAND_COLS
    def w(name, rows):
        m.write_tsv(tmp_path / name, hdr, rows)
    base = {"forms": "", "freq": 9, "n_pages": 5, "n_vols": 5, "vols": "21", "top_families": "",
            "sections": "", "example_vol": "21", "example_page": 1}
    w("cand_uni.tsv", [dict(base, term=t, forms=t) for t in ("sedas", "syllis", "mesa")])
    w("cand_ngram.tsv", [dict(base, term="sedas simples")])
    with open(tmp_path / "taxa_headings.tsv", "w", encoding="utf-8") as f:
        f.write("rank\tname\tauthor\n")
        f.write("género\tSyllis\tSavigny\n")
    _write(tmp_path, [["sedas", "uni", "21", 1, 1, "", "", "Biología", 1]])
    r1 = m.classify(tmp_path)
    first = (tmp_path / "classified_uni.tsv").read_text(encoding="utf-8")
    r2 = m.classify(tmp_path)
    assert r1 == r2 and first == (tmp_path / "classified_uni.tsv").read_text(encoding="utf-8")
    rows = {r["term"]: r for r in _read(tmp_path / "classified_uni.tsv")}
    assert rows["syllis"]["class"] == "taxon"
    assert list(rows["mesa"]) == m.CLASS_COLS
    assert (tmp_path / "classify_stats.txt").exists()


def test_deliver_layout_matches_english_baseline(tmp_path):
    import openpyxl
    d = tmp_path / "中间"
    d.mkdir()
    cand = "term\tforms\tfreq\tn_pages\tn_vols\tvols\ttop_families\tsections\texample_vol\texample_page\n"
    (d / "cand_uni.tsv").write_text(cand + "sedas\tsedas|seda\t5\t3\t2\t21,25\tSyllidae:5\tBiología:5\t21\t12\n", encoding="utf-8")
    (d / "cand_ngram.tsv").write_text(cand, encoding="utf-8")
    cls = "term\tkind\tclass\trule\tfreq\tn_pages\tn_vols\tvols\n"
    (d / "classified_uni.tsv").write_text(cls + "sedas\tuni\tdomain\tglossary\t5\t3\t2\t21,25\nthe\tuni\tenglish\tx\t9\t1\t1\t21\n", encoding="utf-8")
    (d / "classified_ngram.tsv").write_text(cls, encoding="utf-8")
    (d / "taxa_headings.tsv").write_text("rank\tname\tvol\tpage\nfamilia\tSyllidae\t21\t10\n", encoding="utf-8")
    (d / "raw_term_occurrences.tsv").write_text("term\tkind\tvol\tpage\nsedas\tuni\t21\t12\n", encoding="utf-8")
    counts = m.deliver(d, tmp_path)
    assert counts["01_西语术语"] == 1
    assert (tmp_path / "05_出现位置明细.tsv").exists()
    ws = openpyxl.load_workbook(tmp_path / "01_西语术语.xlsx").active
    assert ws.freeze_panes == "A2" and ws.auto_filter.ref
    assert ws["A1"].font.bold and ws["A2"].value == "sedas"
