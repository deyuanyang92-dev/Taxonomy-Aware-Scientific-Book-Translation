from booklayout.profilegen import fit_heading_styles
from booklayout.profile import StyleProfile


def test_seven_measured_levels_fold_into_builder_levels():
    hs = {str(i): {"size": 20 - i, "bold": True} for i in range(1, 8)}
    fit_heading_styles(hs)
    assert sorted(hs, key=int) == ["1", "2", "3", "4", "5", "6"]
    StyleProfile.from_dict({"name": "t", "heading_styles": hs})   # validates


def test_two_measured_levels_are_padded_to_four():
    hs = {"1": {"size": 20}, "2": {"size": 14}}
    fit_heading_styles(hs)
    assert sorted(hs, key=int) == ["1", "2", "3", "4"] and hs["4"] == hs["2"]
