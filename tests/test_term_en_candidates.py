import json
import sys

import term_en_candidates as T


def test_pdf_text_missing_file_no_zero_pages(tmp_path):
    assert T.pdf_text(tmp_path / "nope.pdf")[1] >= 1


def test_heads_and_ngrams():
    heads = T.heads_from_glossary(["neuropodial chaetae", "notopodial chaetae", "dorsal cirrus", "ventral cirrus"])
    assert heads == {"chaetae", "cirrus"}
    c = T.ngrams("The neuropodial chaetae are simple. With a long dorsal cirrus; and hyaline chaetae.", heads)
    assert c["neuropodial chaetae"] == 1 and c["dorsal cirrus"] == 1 and c["hyaline chaetae"] == 1
    assert "the neuropodial chaetae" not in c and "with a long dorsal cirrus" not in c
    assert "chaetae" not in c
    assert "starting from chaetae" not in T.ngrams("starting from chaetae", heads)
    assert "chaetae per parapodium" not in T.ngrams("chaetae per cirrus", heads)


def test_lemma():
    assert T.lemma("palps") == "palp"
    assert T.lemma("antennae") == "antenna"
    assert T.lemma("branchiae") == "branchia"
    assert T.lemma("grooved palps") == "grooved palp"
    assert T.lemma("protonephridia") == "protonephridium"
    assert T.lemma("cyrtocytes") == "cyrtocyte"
    assert T.lemma("dorsal cirri") == "dorsal cirrus"
    assert T.lemma("anal cirrus") == "anal cirrus" and T.lemma("pouches") == "pouch"


def test_singular_glossary_matches_plural_text():
    heads = T.heads_from_glossary(["palp", "antenna", "branchia"])
    c = T.ngrams("Grooved palps present. Lateral antennae short, dorsal branchiae long.", heads)
    assert c["grooved palps"] == 1 and c["lateral antennae"] == 1 and c["dorsal branchiae"] == 1
    e = T.extract("Grooved palps present. Lateral antennae short.", heads)
    assert e["grooved palp"]["label"] == "A" and e["palp"]["kind"] == "head" and e["lateral antenna"]["freq"] == 1


def test_single_glossary_head_enters_candidates():
    heads = T.heads_from_glossary(["protonephridium", "cyrtocyte", "dorsal cirrus", "ventral cirrus"])
    assert {"protonephridium", "cyrtocyte"} <= heads
    e = T.extract("Three pairs of U-shaped protonephridia with cyrtocytes.", heads)
    assert e["protonephridium"]["label"] == "A" and e["cyrtocyte"]["label"] == "A"
    assert T.heads_from_glossary(["protonephridium", "dorsal cirrus", "ventral cirrus"], min_n=2) == {"cirrus"}


def test_proper_names():
    e = T.extract("Phyllodocidae and Nereidinae. Nereis pelagica Linnaeus, 1758 was compared with N. pelagica. "
                  "Described by Örsted, 1843; see Kerbl et al. 2015 and Rieger 1981.", set())
    assert e["Phyllodocidae"]["label"] == "C" and e["Phyllodocidae"]["kind"] == "family"
    assert e["Nereidinae"]["kind"] == "family"
    assert e["Nereis pelagica"]["kind"] == "binomial" and e["Nereis pelagica"]["citation"] == 0
    assert e["N. pelagica"]["kind"] == "binomial"
    for k in ("Örsted, 1843", "Kerbl et al., 2015", "Rieger, 1981", "Linnaeus, 1758"):
        assert e[k]["label"] == "C" and e[k]["kind"] == "citation" and e[k]["citation"] == 1
    assert not any(k.startswith(("Dorsal ", "The ", "Ventral ")) for k in e)


def test_no_false_binomial_from_sentence_start():
    e = T.extract("Dorsal cirri long. Posterior cirri short. This area is small. In 1990 they were found.", set())
    assert not [d for d in e.values() if d["kind"] in ("binomial", "citation")]


def test_taxonomic_seeds():
    e = T.extract("Holotype and two paratypes. Type species: Nereis pelagica. Material examined. "
                  "Remarks. Etymology. Synonyms listed below. Eunice sp. nov. and Foo gen. nov.", set())
    for k in ("holotype", "paratype", "type species", "material examined", "remarks", "etymology", "synonym",
              "sp.nov.", "gen.nov."):
        assert e[k]["label"] == "B", k
    assert "type species" in T.TAXO_SEEDS and "diagnosis" in T.TAXO_SEEDS


def test_reference_line_marked_citation():
    txt = ("The family is diverse.\n"
           "Fauchald, K. (1977) The polychaete worms. Natural History Museum of Los Angeles County, "
           "Science Series 28: 1-188.\n"
           "Hartman, O. 1959. Catalogue of the polychaetous annelids. Bulletin of the Zoological Society.\n")
    e = T.extract(txt, set())
    assert e["Fauchald, 1977"]["citation"] == 1
    assert e["Bulletin of the Zoological Society"]["kind"] == "journal"
    assert e["Bulletin of the Zoological Society"]["citation"] == 1


def test_spacy_missing_degrades(monkeypatch):
    monkeypatch.setitem(sys.modules, "spacy", None)  # import spacy -> ImportError
    monkeypatch.setattr(T, "_NLP", [])
    heads = T.heads_from_glossary(["palp"])
    assert T._nlp() is None
    assert T.extract("Grooved palps.", heads, use_spacy=True) == T.extract("Grooved palps.", heads)


def test_cvalue_nested():
    cv = T.cvalues({"anterior ventral cirrus": 4, "ventral cirrus": 10, "long ventral cirrus": 2})
    assert cv["ventral cirrus"] == round(1 * (10 - 3), 2)
    assert cv["anterior ventral cirrus"] == round(1.585 * 4, 1) or abs(cv["anterior ventral cirrus"] - 6.34) < 0.01


def test_pages_cli_deterministic(tmp_path):
    d = tmp_path / "pg"
    d.mkdir()
    (d / "Book_p0001.txt").write_text("# header line\nGrooved palps. Phyllodocidae Örsted, 1843. Holotype.\n",
                                      encoding="utf8")
    (d / "Book_p0002.txt").write_text("Grooved palps and dorsal palps. Holotype lost.\n", encoding="utf8")
    g = tmp_path / "g.tsv"
    g.write_text("term\npalp\n", encoding="utf8")
    outs = []
    for i in range(2):
        out, js = tmp_path / f"o{i}.tsv", tmp_path / f"o{i}.json"
        assert T.main([str(d), "--pages", "--glossary", str(g), "--yiku", str(tmp_path / "none.db"),
                       "--out", str(out), "--json", str(js), "--min-freq", "1", "--min-docs", "1"]) == 0
        outs.append((out.read_text(encoding="utf8"), js.read_text(encoding="utf8")))
    assert outs[0] == outs[1]
    rows = [r.split("\t") for r in outs[0][0].splitlines()]
    hdr = rows[0]
    assert hdr[-5:] == ["label", "kind", "citation", "cvalue", "source_page"]
    byterm = {r[0]: dict(zip(hdr, r)) for r in rows[1:]}
    assert byterm["grooved palp"]["source_page"] == "p0001" and byterm["grooved palp"]["docs"] == "2"
    assert byterm["palp"]["in_glossary"] == "1" and byterm["holotype"]["label"] == "B"
    assert byterm["Örsted, 1843"]["label"] == "C"
    pages = json.loads(outs[0][1])["pages"]
    assert [p["page"] for p in pages] == ["p0001", "p0002"]
    assert any(c["term"] == "Phyllodocidae" for c in pages[0]["candidates"])
    out2 = tmp_path / "nc.tsv"
    T.main([str(d), "--pages", "--out", str(out2), "--min-freq", "1", "--min-docs", "1", "--no-citation",
            "--yiku", str(tmp_path / "none.db")])
    assert "Örsted" not in out2.read_text(encoding="utf8")
