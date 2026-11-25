"""fill 模式两遍排版：点线过短的分支改按 L5(B) 排（2026-11-23）。需要 soffice，没有就跳过。"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

MD = """Key to genera

1. Dorsal cirri much longer than dorsal lobe, annulated throughout; prostomium with two pairs of eyes in trapezoid arrangement ........ 2
— Dorsal cirri short or reduced ........ 3
2. Ventral fascicle with 1-4 heterogomph falcigers, blade length/width ratio below 3; pharynx with cone-shaped tooth near the anterior margin of the pharynx and a long proventricle ........ Exogone naidina
— Ventral fascicle with 5-10 falcigers ........ Exogone verugera
3. Palps fused along their whole length ........ Sphaerosyllis erinaceus
— Palps free distally ........ Brania clavata
"""


@pytest.mark.skipif(shutil.which("soffice") is None, reason="无 LibreOffice")
def test_fill_two_pass_no_short_leader(tmp_path: Path):
    import json
    src = tmp_path / "en.md"
    src.write_text(MD, "utf-8")
    root = Path(__file__).resolve().parents[2]
    r = subprocess.run([sys.executable, "-m", "keykit", "make", str(src), "--lang", "en", "--source-style", "dash",
                        "-o", str(tmp_path / "k.docx")], cwd=root, capture_output=True, text=True, timeout=300)
    rep = json.loads((tmp_path / "k.report.json").read_text("utf-8"))
    assert rep["profile"]["overflow"] == "fill"
    assert rep["verify"] == [], rep["verify"]
    assert r.returncode == 0
