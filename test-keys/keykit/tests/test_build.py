"""B1 DELTA KEY：小矩阵手算验收（手算过程见各用例注释）。"""
import math

from keykit.build import best_char, build, cost, kvalue, leaves
from keykit.matrix import INAPPLICABLE, UNKNOWN, Character, Matrix, Taxon


def fs(*x):
    return frozenset(x)


def small():
    # 4 个分类单元 A B C D，全部可靠度 5（cost=1），abundance 5（权重 1）
    chars = [Character(f"c{i}", ["1", "2", "3"]) for i in range(1, 5)]
    rows = {
        "A": [0, 0, 0, (0, 1)],
        "B": [0, 1, 0, 0],
        "C": [1, 2, 0, 1],
        "D": [1, 2, 1, 1],
    }
    taxa = []
    for name, vs in rows.items():
        taxa.append(Taxon(name, {i: fs(*v) if isinstance(v, tuple) else fs(v) for i, v in enumerate(vs)}))
    return Matrix(chars, taxa)


def test_cost():
    assert cost(5) == 1
    assert abs(cost(3) - 1.4**2) < 1e-12
    assert cost(10) == 1.4**-5
    assert cost(12) == cost(10)  # min(10, r)


def test_k_hand_computed():
    m = small()
    t = [0, 1, 2, 3]
    # c1: 子组 {A,B},{C,D}：Σf log2 n/Σf = (2*1+2*1)/4 = 1 -> K=1+1*1=2
    assert abs(kvalue(m, t, 0, 1.0) - 2.0) < 1e-12
    # c2: 子组 {A},{B},{C,D}：(0+0+2*1)/4 = 0.5 -> 1.5
    assert abs(kvalue(m, t, 1, 1.0) - 1.5) < 1e-12
    # c3: 子组 {A,B,C},{D}：3*log2(3)/4
    assert abs(kvalue(m, t, 2, 1.0) - (1 + 3 * math.log2(3) / 4)) < 1e-12
    # c4 多态 A=1/2：子组{A,B}(2),{A,C,D}(3)，Σn=5>4
    # sup0=(2*1+3*log2 3)/5；V=((1-.8)/.8)*((4+8)/(4*2))*(5-4)=0.25*1.5*1=0.375
    want = 1 + (2 + 3 * math.log2(3)) / 5 + 0.375
    assert abs(kvalue(m, t, 3, 1.0) - want) < 1e-12


def test_best_and_tree():
    m = small()
    assert best_char(m, [0, 1, 2, 3], [0, 1, 2, 3])[0] == 1  # c2 最小
    tree = build(m)
    assert tree.char == 1
    got = {tuple(m.taxa[t].name for t in ts): path for ts, path in leaves(tree)}
    # c2 → A | B | {C,D}；{C,D} 只有 c3 可分（c1/c2/c4 在该组单值）
    assert got[("A",)] == ((1, 0),)
    assert got[("B",)] == ((1, 1),)
    assert got[("C",)] == ((1, 2), (2, 0))
    assert got[("D",)] == ((1, 2), (2, 1))


def test_reliability_changes_choice():
    m = small()
    m.characters[1].reliability = 3  # c2 cost 1.96；cmin 仍为 1（其余可靠度 5）
    t = [0, 1, 2, 3]
    assert abs(kvalue(m, t, 1, 1.0) - (1.96 + 0.5)) < 1e-12
    assert best_char(m, t, [0, 1, 2, 3])[0] == 0  # c1 K=2 < 2.46


def test_unknown_and_inapplicable_make_char_unusable():
    m = small()
    m.taxa[0].values[1] = UNKNOWN
    assert kvalue(m, [0, 1, 2, 3], 1, 1.0) is None
    m.taxa[0].values[1] = INAPPLICABLE
    assert kvalue(m, [0, 1, 2, 3], 1, 1.0) is None


def test_improper_subgroup_excluded_by_default():
    # A=1/2, B=1, C=2 的性状：子组 {A,B}(2)... 构造与原组同大小的子组
    chars = [Character("x", ["1", "2"])]
    taxa = [Taxon("A", {0: fs(0, 1)}), Taxon("B", {0: fs(0)}), Taxon("C", {0: fs(1)})]
    m = Matrix(chars, taxa)
    # 子组1={A,B}(2)，子组2={A,C}(2)，n=3 无同大小；改为 A,B 都多态
    taxa2 = [Taxon("A", {0: fs(0, 1)}), Taxon("B", {0: fs(0, 1)})]
    m2 = Matrix(chars, taxa2)
    assert kvalue(m2, [0, 1], 0, 1.0) is None  # 两个子组都与原组同大小，m=2
    assert kvalue(m2, [0, 1], 0, 1.0, allow_improper=True) is not None
    assert kvalue(m, [0, 1, 2], 0, 1.0) is not None


def test_tie_lowest_char_number():
    chars = [Character("a", ["1", "2"]), Character("b", ["1", "2"])]
    taxa = [Taxon("A", {0: fs(0), 1: fs(0)}), Taxon("B", {0: fs(1), 1: fs(1)})]
    assert best_char(Matrix(chars, taxa), [0, 1], [1, 0])[0] == 0
