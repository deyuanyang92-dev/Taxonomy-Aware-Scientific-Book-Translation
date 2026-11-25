"""fill 模式：引导文字放得下、但加上长去向就超出行宽时，去向不得冲出版心（2026-11-24 Travisia D 表偶句 5）。

leader_gaps 找不到行尾去向的分支（去向被挤出、折断）也要按 L5(B) 重排。需要 soffice，没有就跳过。
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

MD = """Key to species

1. Posterior parapodia (developed into lappets, or not): similar to anterior parapodia ........ *T. forbesii*, *T.* cf. *kerguelensis*, *T. kerguelensis trianulata*
— Posterior parapodia (developed into lappets, or not): developed into lateral lappets ........ 2
2. Prostomium rounded ........ 3
— Prostomium pointed ........ *T. sp0*
3. Prostomium rounded ........ 4
— Prostomium pointed ........ *T. sp1*
4. Prostomium rounded ........ 5
— Prostomium pointed ........ *T. sp2*
5. Prostomium rounded ........ 6
— Prostomium pointed ........ *T. sp3*
6. Prostomium rounded ........ 7
— Prostomium pointed ........ *T. sp4*
7. Prostomium rounded ........ 8
— Prostomium pointed ........ *T. sp5*
8. Prostomium rounded ........ 9
— Prostomium pointed ........ *T. sp6*
9. Prostomium rounded ........ *T. last*
— Prostomium pointed ........ *T. sp7*
"""


@pytest.mark.skipif(shutil.which("soffice") is None, reason="无 LibreOffice")
def test_long_dest_after_long_lead_is_wrapped(tmp_path: Path):
    src = tmp_path / "en.md"
    src.write_text(MD, "utf-8")
    root = Path(__file__).resolve().parents[2]
    r = subprocess.run([sys.executable, "-m", "keykit", "make", str(src), "--lang", "en", "--source-style", "dash",
                        "-o", str(tmp_path / "k.docx")], cwd=root, capture_output=True, text=True, timeout=300)
    rep = json.loads((tmp_path / "k.report.json").read_text("utf-8"))
    assert [x for x in rep["verify"] if x["code"] == "L3"] == [], rep["verify"]
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.mark.skipif(shutil.which("soffice") is None, reason="无 LibreOffice")
def test_real_travisia_d_no_l3(tmp_path: Path):
    """真实 IR（多种并列去向多、去向栏取上限宽）：偶句 5 原先去向冲出版心。"""
    root = Path(__file__).resolve().parents[2]
    src = Path(__file__).parent / "data" / "travisia_d_ir.json"
    subprocess.run([sys.executable, "-m", "keykit", "make", str(src), "--lang", "en", "--source-style", "dash",
                    "-o", str(tmp_path / "k.docx")], cwd=root, capture_output=True, text=True, timeout=600)
    rep = json.loads((tmp_path / "k.report.json").read_text("utf-8"))
    # 偶句 5（长引导 + 3 种并列去向）原先冲出版心；偶句 40 的 6 种并列去向比整行长，属数据问题，另报
    assert [x for x in rep["verify"] if x["code"] == "L3" and "偶句 5 " in x["detail"]] == [], rep["verify"][:3]
