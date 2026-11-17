#!/usr/bin/env python3
"""把误升「已核」的噪声条退回「候选」。"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "yiku"))
from yiku import db as D  # noqa: E402

YIKU = Path("/mnt/p/翻译-译作/yiku/yiku.db")

BAD_ZH = re.compile(r"(重新确立|一文|标志着|有说服力|该文|浮蚕科.*|应用支序)")
# 粘连学名/作者串、明显拼写错误来源
BAD_EN = re.compile(
    r"(?i)(uschakov|milne.?edwards|audouin|famlly|famliy|"
    r"^[a-z]{20,}$|"  # 超长无空格粘连
    r"\d{4})"  # 带年份的文献串当术语
)


def main() -> None:
    con = D.connect(YIKU)
    rows = list(
        con.execute(
            "SELECT id, en, zh, note, status FROM terms "
            "WHERE note LIKE '%promote_auth_consensus_2026-11-17%' AND status='已核'"
        )
    )
    n = 0
    for r in rows:
        en, zh = r["en"], r["zh"]
        bad = False
        if BAD_ZH.search(zh) or len(zh) > 12:
            bad = True
        if BAD_EN.search(en):
            bad = True
        if " " not in en and len(en) > 18 and en.islower():
            bad = True
        if bad:
            con.execute(
                "UPDATE terms SET status='候选', note=REPLACE(note, '|promote_auth_consensus_2026-11-17', '|demoted_noise_2026-11-17') "
                "WHERE id=?",
                (r["id"],),
            )
            n += 1
            print("demote", en, "→", zh)
    con.commit()
    print("demoted", n)


if __name__ == "__main__":
    main()
