"""v7 偶句排版的最短点线必须与闸口一致（21 卷偶句 23 曾因 8 mm vs 40 mm 不一致而 FAIL）。"""
from booklayout import builder, cli


def test_couplet_leader_floor_matches_gate():
    assert builder.COUPLET_MIN_LEADER_MM == cli.MIN_KEY_LEADER_MM
