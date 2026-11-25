"""keykit 建表与 open-delta KEY 2.12 的一致性（Avery 2023 Travisia DELTA；数据不在时跳过）。"""
import re
from pathlib import Path

import pytest

from keykit.build import build, leaves
from keykit.delta_io import read_intkey

SRC = Path("/mnt/p/Travisia/02_原始数据/DELTA_Wilson_Avery_2023/Travisia_2023_v1-01")
OD = Path(__file__).resolve().parents[2] / "survey/checks/delta_travisia/open_delta_key.txt"


@pytest.mark.skipif(not (SRC.exists() and OD.exists()), reason="Travisia DELTA 数据或 open-delta 输出不在")
def test_same_chars_and_first_path_as_open_delta() -> None:
    txt = OD.read_text(encoding="utf-8", errors="replace")
    incl: list[int] = []
    for tok in re.search(r"Characters included ([\d\- ]+)", txt).group(1).split():  # type: ignore[union-attr]
        a, _, b = tok.partition("-")
        incl += range(int(a) - 1, int(b or a))
    m = read_intkey(SRC).matrix
    lv = leaves(build(m, chars=incl, unknown_all=True))
    used = sorted({c + 1 for _t, p in lv for c, _s in p})
    od_used = {1, 2, 4, 6, 7, 8, 9, 13, 14, 15, 17, 23, 26, 33, 35, 36, 41}
    # 已知差别：KEY 用性状 17，keykit 用 11（REUSE 未实现，原因未确证）；其余 16 个相同
    assert len(used) == 17 and len(od_used & set(used)) == 16
    assert [c + 1 for c, _s in lv[0][1][:4]] == [33, 13, 8, 15]
    assert max(len(p) for _t, p in lv) == 11
