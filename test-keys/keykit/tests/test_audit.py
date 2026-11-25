from keykit.audit import audit_pairs
from keykit.matrix import UNKNOWN, Character, Matrix, Taxon


def fs(*x):
    return frozenset(x)


def mk(rows):
    chars = [Character(f"c{i}", ["a", "b"]) for i in range(len(next(iter(rows.values()))))]
    return Matrix(chars, [Taxon(n, dict(enumerate(v))) for n, v in rows.items()])


def tiers(m):
    return {(m.taxa[r.a].name, m.taxa[r.b].name): r for r in audit_pairs(m)}


def test_three_tiers():
    m = mk({
        "A": [fs(0), fs(0)],
        "B": [fs(1), fs(0)],      # 与 A：c0 分开，仅 1 个 → 弱边界
        "C": [fs(0), fs(0)],      # 与 A：全相同 → matrix_silent
        "D": [UNKNOWN, fs(0)],    # 与 A：c1 相同，c0 未知 → evidence_gap
    })
    t = tiers(m)
    assert t[("A", "B")].tier == "separated" and t[("A", "B")].weak and t[("A", "B")].separating == [0]
    assert t[("A", "C")].tier == "matrix_silent"
    assert t[("A", "D")].tier == "evidence_gap" and t[("A", "D")].gaps == [0]
    assert t[("B", "C")].tier == "separated"


def test_two_separating_not_weak():
    m = mk({"A": [fs(0), fs(0)], "B": [fs(1), fs(1)]})
    r = audit_pairs(m)[0]
    assert r.tier == "separated" and not r.weak and r.separating == [0, 1]


def test_polymorphic_overlap_is_not_separation():
    m = mk({"A": [fs(0, 1)], "B": [fs(1)]})
    assert audit_pairs(m)[0].tier == "matrix_silent"
