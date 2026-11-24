import math

import pytest

from keykit.build import Node, build
from keykit.matrix import INAPPLICABLE, UNKNOWN, Character, Matrix, Taxon
from keykit.metrics import comp, e_dicho, e_shape, lmax, lmin, parent_pd, pd, step_counts


def fs(*x):
    return frozenset(x)


def kerner():
    # Kerner 2025 示例表（survey/papers/kerner2025.txt 262-267 行）
    cols = {
        "wings": [fs(0), fs(0, 1), fs(1), fs(0), fs(1)],
        "antenna": [UNKNOWN, fs(0), fs(1), fs(0), fs(1)],
        "cerci": [fs(0), fs(0), fs(1), fs(0), fs(1)],
        "surface": [fs(0), fs(0, 1), fs(1), fs(0), fs(1)],
    }
    chars = [Character(n, ["a", "b"]) for n in cols]
    taxa = [Taxon(c, {i: cols[n][t] for i, n in enumerate(cols)}) for t, c in enumerate("ABCDE")]
    return Matrix(chars, taxa)


def test_pd_hand_computed():
    m = kerner()
    # wings 不相容对：A-C A-E C-D D-E = 4
    assert pd(m, 0) == 4
    # antenna：A 未知计 0；B-C B-E C-D D-E = 4
    assert pd(m, 1) == 4
    # cerci：{A,B,D}=a vs {C,E}=b → 3*2 = 6
    assert pd(m, 2) == 6
    assert pd(m, 3) == 4


def test_comp_inapplicable_not_counted():
    m = kerner()
    m.taxa[0].values[2] = INAPPLICABLE
    assert comp(m, 0, 2, 2) is None
    assert pd(m, 2) == 2 * 2  # {B,D} x {C,E}


def test_parent_pd_is_max():
    assert parent_pd([4, 6, 1]) == 6


def test_lmin_lmax_small():
    assert lmin(4) == 2 and lmax(4) == 2.25  # n=4：平衡树 2；梳状树 (1+2+3+3)/4 = 2.25
    assert lmin(2) == 1 and lmax(2) == 1


def _tree(shape):
    """shape: 叶下标(int)或 (左,右)。"""
    if isinstance(shape, int):
        return Node(taxa=[shape])
    n = Node(taxa=[], char=0)
    n.children = {0: _tree(shape[0]), 1: _tree(shape[1])}
    return n


def test_e_shape_extremes():
    balanced = _tree(((0, 1), (2, 3)))
    comb = _tree((0, (1, (2, 3))))
    assert e_shape(balanced) == pytest.approx(1.0)
    assert e_shape(comb) == pytest.approx(0.0)


def test_e_dicho_balanced_is_one_and_comb_less():
    assert e_dicho(_tree(((0, 1), (2, 3)))) == pytest.approx(1.0)
    assert e_dicho(_tree((0, (1, (2, 3))))) < 1.0
    assert step_counts(_tree((0, (1, (2, 3))))) == {0: 1, 1: 2, 2: 3, 3: 3}


def test_e_shape_rejects_multiway():
    chars = [Character("c", ["1", "2", "3"])]
    taxa = [Taxon(s, {0: fs(i)}) for i, s in enumerate("ABC")]
    with pytest.raises(ValueError):
        e_shape(build(Matrix(chars, taxa)))


def test_e_dicho_matches_survey_formula():
    steps = [1, 2, 3, 3]
    tot = sum(steps)
    want = -sum(s / tot * math.log(s / tot) for s in steps) / math.log(4)
    assert e_dicho(_tree((0, (1, (2, 3))))) == pytest.approx(want)
