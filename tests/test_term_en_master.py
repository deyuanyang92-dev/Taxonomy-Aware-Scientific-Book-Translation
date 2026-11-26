import term_en_master as M


def test_lemma():
    assert M.lemma("neuropodial chaetae") == "neuropodial chaeta"
    assert M.lemma("dorsal cirri") == "dorsal cirrus"
    assert M.lemma("chaetal lobes") == "chaetal lobe"
    assert M.lemma("anal cirrus") == "anal cirrus"
    assert M.lemma("gills") == "gill"
    assert M.lemma("palps") == "palp" and M.lemma("protonephridia") == "protonephridium"


def test_parse_rouse_glossary():
    t = ("GLOSSARY\nintro line\nabdomen: body region posterior to the thorax. Varies among\nannelid groups.\n"
         "acicula, aciculae: stout supportive chaeta found inter-\nnally.\nannulated: ringed.\n")
    d = dict(M.parse_rouse_glossary(t))
    assert d["abdomen"] == "body region posterior to the thorax. Varies among annelid groups."
    assert d["acicula"] == "stout supportive chaeta found internally."
    assert "annulated" in d
    t2 = "GLOSSARY\nabdomen: body region posterior\n336 GLOSSARY\nto the thorax.\n"
    assert dict(M.parse_rouse_glossary(t2))["abdomen"] == "body region posterior to the thorax."


def test_handbook_units_split(tmp_path):
    d = tmp_path / "src_en"
    d.mkdir()
    (d / "s7_3.txt").write_text("7.3 Sedentaria\n7.3.1.1 Paraonidae Cerruti, 1909\nBody 2.5 mm long.\n"
                                "7.3.1.2 Cirratulidae Ryckholt, 1851\nGrooved palps.\n", encoding="utf8")
    u = M.handbook_units(tmp_path)
    fams = [x[1] for x in u]
    assert "Paraonidae" in fams and "Cirratulidae" in fams
    assert all("2.5 mm" not in x[2] for x in u)
