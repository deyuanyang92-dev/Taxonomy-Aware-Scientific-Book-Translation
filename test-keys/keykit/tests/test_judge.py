from keykit.judge import apply, judge
from keykit.matrix import UNKNOWN, Character, Matrix, Taxon


def _m() -> Matrix:
    ch = [Character("shape", ["a", "b"]), Character("body_length_mm", ["s", "l"]), Character("sparse", ["x", "y"]),
          Character("dup", ["a", "b"])]
    f = frozenset
    t = [Taxon("A", {0: f({0}), 1: f({0}), 2: UNKNOWN, 3: f({0})}), Taxon("B", {0: f({1}), 1: f({1}), 2: UNKNOWN, 3: f({1})}),
         Taxon("C", {0: f({0}), 1: f({0, 1}), 2: f({1}), 3: f({0})})]
    return Matrix(ch, t)


def test_prior_and_redundancy() -> None:
    js = {j.name: j for j in judge(_m())}
    assert js["body_length_mm"].prior == "caution"  # 通则 G3
    assert js["dup"].redundant_with == "shape" or js["shape"].redundant_with == "dup"
    assert js["sparse"].coverage < 0.5
    assert js["shape"].reliability > js["sparse"].reliability


def test_avoid_excluded() -> None:
    m = _m()
    js = judge(m, [("^dup$", "avoid", "test")])
    use = apply(m, js)
    assert 3 not in use and 0 in use
