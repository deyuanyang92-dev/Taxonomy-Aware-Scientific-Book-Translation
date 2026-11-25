from keykit.build import build, subgroups
from keykit.matrix import UNKNOWN, Character, Matrix, Taxon


def _m() -> Matrix:
    ch = [Character("c", ["a", "b"])]
    return Matrix(ch, [Taxon("X", {0: frozenset({0})}), Taxon("Y", {0: frozenset({1})}), Taxon("Z", {0: UNKNOWN})])


def test_default_unknown_blocks() -> None:
    assert subgroups(_m(), [0, 1, 2], 0) is None
    assert build(_m()).char is None


def test_unknown_all_goes_to_every_branch() -> None:
    g = subgroups(_m(), [0, 1, 2], 0, True)
    assert g == {0: [0, 2], 1: [1, 2]}
    assert build(_m(), unknown_all=True).char == 0
