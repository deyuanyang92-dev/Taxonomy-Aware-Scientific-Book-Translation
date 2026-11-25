import keysplit


def test_split_merged_key_entries():
    t = "第1疣足に単一鉤状剛毛がない Ephesiella gallardi(図78)単一鉤状剛毛を生じるEphesiella brevicapitis(図77)単一鉤状剛毛を生じる"
    out = keysplit.split_keys(t)
    assert out.count("\n\n") == 2 and out.replace("\n\n", "") == t


def test_single_figure_reference_untouched():
    t = "体は細長い(図78)背面に突起がある。"
    assert keysplit.split_keys(t) == t
