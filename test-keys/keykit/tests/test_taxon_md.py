from keykit.tabkey import taxon_md


def test_authority_roman():
    assert taxon_md("Travisia profundi Chamberlin, 1919") == "*Travisia profundi* Chamberlin, 1919"
    assert taxon_md("Travisia fusus (Chamberlin, 1919)") == "*Travisia fusus* (Chamberlin, 1919)"


def test_qualifier_and_code_roman():
    assert taxon_md("Travisia sp NHM_1244") == "*Travisia* sp NHM_1244"
    assert taxon_md("Travisia sp NHM_1244", abbr=True) == "*T.* sp NHM_1244"


def test_abbr_drops_authority_and_stray_dot():
    n = "Travisia cf. kerguelensis. Ehlers, 1897 (not McIntosh, 1885)"
    assert taxon_md(n, abbr=True) == "*T.* cf. *kerguelensis*"
    assert taxon_md(n) == "*Travisia* cf. *kerguelensis* Ehlers, 1897 (not McIntosh, 1885)"
