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
