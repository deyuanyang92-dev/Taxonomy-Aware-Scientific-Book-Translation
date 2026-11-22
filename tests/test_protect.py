import protect


def test_mask_binomial_author_tag_date():
    t = "Typosyllis Magdalena (WESENBERG-LUND 1961) und Cirriformia quetalmahuensis n. sp.; 29. 12. 59; Hololepidella commensalis Willey, 1905, pp. 1-2"
    m, s = protect.mask(t)
    assert "n. sp." not in m and "29. 12. 59" not in m and "1905" not in m
    assert protect.restore(m, s) == t


def test_restore_tolerates_spaces_and_mangle():
    m, s = protect.mask("a Nereis virens n. sp. b")
    assert m == "a [[1]] b"
    assert protect.restore("甲 [[ 1 ]] 乙", s) == "甲 Nereis virens n. sp. 乙"


def test_lost_reports_swallowed_placeholder():
    _, s = protect.mask("x Nereis virens n. sp. y 12. 3. 59")
    assert protect.lost("x [[1]] y", s) == [2]


def test_plain_text_untouched():
    t = "Die Parapodien sind kurz und 4gliedrig. 2 km vom Meer."
    assert protect.mask(t) == (t, [])


def test_bare_year_date_not_confused_with_numbers():
    t = "Salinität 30.9 und Tiefe 12.5 m"
    assert protect.mask(t)[1] == []


def test_ocr_comma_date_and_bare_authority_year():
    t = "10, 3. 60; Indischer Ozean (FAUVEL, 1953), W-Amerika (O. HARTMAN, 1940); (Abb. 27, 1957)"
    m, s = protect.mask(t)
    assert "10, 3. 60" not in m and "FAUVEL" not in m and "HARTMAN" not in m
    assert "(Abb. 27, 1957)" in m
    assert protect.restore(m, s) == t


def test_unicode_caps_author_and_caps_name_year():
    t = "Peru (HARTMANN-SCHRÖDER, 1962); O. HARTMAN (1959) und AUGENER (1922) sind bekannt; Die Art (1959 Stück) bleibt"
    m, s = protect.mask(t)
    assert "SCHRÖDER" not in m and "HARTMAN" not in m and "AUGENER" not in m
    assert protect.restore(m, s) == t
    assert "Die Art" in m


def test_ja_number_before_counter_protected():
    t = "吻の先端に13対の肉質突起と2対の顎がある，背鱗は15対あって"
    m, s = protect.mask(t)
    assert s == ["13", "2", "15"] and "15対" not in m
    assert protect.restore(m, s) == t


def test_line_break_inside_citation():
    t = "Indischer Ozean (FAUVVEL,\n1953), Callao (EHLERS,\n1901 a), Typosyllis anoculata\nn. sp."
    m, s = protect.mask(t)
    assert "FAUVVEL" not in m and "EHLERS" not in m and "n. sp" not in m
    assert protect.restore(m, s) == t
