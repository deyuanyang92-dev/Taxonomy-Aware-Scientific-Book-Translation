import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import vl_proofread as P  # noqa: E402


def test_parse_and_sample():
    assert P.parse('前缀 [{"i":0,"verdict":"ok","issue":""}] 后缀')[0]["verdict"] == "ok"
    al = {"pages": [{"page": 1, "blocks": [{"role": "body", "text": "x" * 30, "translation": "译"}, {"role": "heading", "text": "y" * 30}, {"role": "body", "text": "短"}]}]}
    s = P.sample(al, 5, 1)
    assert len(s) == 1 and s[0]["zh"] == "译"
