import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location("tes", Path(__file__).resolve().parents[1] / "scripts" / "term_es_extract.py")
tes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tes)

TOC = (
    "Introducción ........ 9\nLos Polychaeta ibéricos ........ 15\nClave de familias ........ 20\n"
    "Familia Nephtyidae ........ 30\nFamilia Aphroditidae ........ 40\nSubfamilia Aphroditinae ........ 41\n"
    "Bibliografía ........ 90\nÍndice alfabético ........ 99\n"
)


def pages():
    return [
        (1, TOC),
        (2, "Introducción\n\nTexto inicial sobre poliquetos marinos."),
        (3, "Clave de familias\n\nFamilia Nephtyidae Grube, 1850\n1. Con setas largas"),
        (4, "Familia Nepbtyidae Grube, 1850\n\nGénero Nephtys Cuvier, 1817\n\n"
            "Nephtys hombergii Savigny, 1818 (fig. 3)\n\nDistribución geográfica.— Atlántico norte."),
        (5, "Familia Apbroditidae Malmgren, 1867\n\nSubfamilia Aphroditinae Malmgren, 1867\n\nTexto del cuerpo."),
        (6, "Familia Nepbtyidae Grube, 1850\n\nTexto repetido."),
        (7, "Bibliografía\n\nGrube, A. 1850. Algo."),
    ]


def run_walk():
    toc = tes.parse_toc(pages())
    out = list(tes.walk(pages(), toc, 25))
    return toc, out, tes.dedupe_taxa(out[-1][2])


def row_of(out, page, idx=-1):
    return [p for p in out if p[0] == page][0][1][idx][1]


def test_chapter_switches_and_clears():
    _, out, _ = run_walk()
    assert row_of(out, 2)["chapter"] == "Introducción"
    assert row_of(out, 4)["chapter"] == "Familia Nephtyidae"
    assert row_of(out, 5)["chapter"] == "Familia Aphroditidae"
    r = row_of(out, 7, 0)
    assert r["chapter"] == "Bibliografía"
    assert r["family"] == r["genus"] == r["species"] == r["section"] == ""


def test_toc_and_key_pages_not_taxa_and_dedupe():
    _, out, taxa = run_walk()
    fam = [t for t in taxa if t["rank"] == "familia"]
    assert sorted(t["name"] for t in fam) == ["Aphroditidae", "Nephtyidae"]
    neph = [t for t in fam if t["name"] == "Nephtyidae"][0]
    assert (neph["first_page"], neph["last_page"]) == (4, 6)
    assert row_of(out, 3)["family"] == ""  # 检索表页里的 Familia 行不改状态


def test_ocr_fix_from_toc():
    _, _, taxa = run_walk()
    d = {t["name"]: t["fixed_from"] for t in taxa if t["rank"] == "familia"}
    assert d == {"Nephtyidae": "Nepbtyidae", "Aphroditidae": "Apbroditidae"}


def test_species_heading_and_section():
    _, out, taxa = run_walk()
    sp = [t for t in taxa if t["rank"] == "especie"][0]
    assert sp["name"] == "Nephtys hombergii" and sp["author"] == "Savigny" and sp["year"] == "1818"
    r = row_of(out, 4)
    assert r["section"] == "Distribución geográfica" and r["species"] == "Nephtys hombergii" and r["genus"] == "Nephtys"
    assert any(t["rank"] == "subfamilia" and t["name"] == "Aphroditinae" for t in taxa)


def test_toc_page_not_heading_and_no_occurrences():
    _, out, _ = run_walk()
    assert all(skip for _, _, skip in out[0][1])


def test_classification_list_page_not_taxa():
    lst = "Orden A\n\nFamilia Nephtyidae Grube, 1850\n\nFamilia Aphroditidae Malmgren, 1867\n\nFamilia Otheridae X, 1900"
    pp = [(1, TOC), (2, lst), (3, "Familia Nephtyidae Grube, 1850\n\nTexto.")]
    out = list(tes.walk(pp, tes.parse_toc(pp), 25))
    taxa = tes.dedupe_taxa(out[-1][2])
    assert [(t["name"], t["first_page"]) for t in taxa if t["rank"] == "familia"] == [("Nephtyidae", 3)]


def test_apendice_sentence_does_not_switch_chapter_and_last_page_scoped():
    toc = "Introducción ..... 9\nFamilia Nephtyidae ..... 30\nApéndice ..... 80\nBibliografía ..... 90\n"
    pp = [
        (1, toc),
        (2, "Familia Nephtyidae Grube, 1850\n\nTexto."),
        (3, "apéndice radiolar dorsal bien desarrollado.\n\nApéndice radiolar dorsal bien desarrollado, con setas."),
        (4, "Texto del cuerpo."),
        (5, "Bibliografía\n\nFamilia Nephtyidae Grube, 1850 referencia citada"),
        (6, "Texto de referencias."),
    ]
    out = list(tes.walk(pp, tes.parse_toc(pp), 47))
    assert row_of(out, 3)["family"] == "Nephtyidae" and row_of(out, 4)["family"] == "Nephtyidae"
    assert row_of(out, 4)["chapter"] != "Apéndice"
    assert row_of(out, 6)["family"] == "" and row_of(out, 6)["chapter"] == "Bibliografía"


def test_run_end_to_end(tmp_path):
    key = tes.VOLS[25]
    d = tmp_path / "pages" / key
    d.mkdir(parents=True)
    for no, text in pages():
        (d / f"p{no:04d}.json").write_text(json.dumps({"text": text}), encoding="utf-8")
    res = tes.run(tmp_path, tmp_path / "out", [25])
    assert res["stats"][25]["familia"] == 2 and res["stats"][25]["toc_families"] == 2
    head = (tmp_path / "out" / "taxa_headings.tsv").read_text(encoding="utf-8").splitlines()[0]
    assert "fixed_from" in head and "first_page" in head
