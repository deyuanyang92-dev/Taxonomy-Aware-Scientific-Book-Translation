import fusion_exp as f


def test_vote_overrides_when_two_others_agree():
    assert f.vote3("abXd", ["abcd", "abcd"]) == "abcd"


def test_vote_keeps_base_when_others_disagree():
    assert f.vote3("abXd", ["abcd", "abYd"]) == "abXd"


def test_vote_needs_two_others():
    assert f.vote3("abXd", ["abcd"]) == "abXd"
