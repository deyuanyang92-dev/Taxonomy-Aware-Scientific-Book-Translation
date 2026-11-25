import os
from pathlib import Path

import pytest

from keykit.ir import KeyIR, from_imajima_json, from_markdown, split_fig

# 样本是书稿译文数据，不进仓库；KEYKIT_SAMPLES 指向含 keys_2001.json 的目录，否则取 test-keys/imajima_keys
J = Path(os.environ.get("KEYKIT_SAMPLES") or Path(__file__).resolve().parents[2] / "imajima_keys") / "keys_2001.json"
NEED_SAMPLE = pytest.mark.skipif(not J.exists(), reason="无 Imajima 样本（设 KEYKIT_SAMPLES）")


@NEED_SAMPLE
def test_imajima_page5():
    irs = from_imajima_json(J)
    k = irs[0]
    assert k.heading.startswith("多鳞虫科")
    assert len(k.couplets) == 7
    c1 = k.couplets[0]
    assert [ld.kind for ld in c1.leads] == ["jump", "jump"]
    assert [ld.target for ld in c1.leads] == ["2", "3"]
    c2 = k.couplets[1]
    assert c2.leads[0].kind == "taxon" and "Branchinotogluminae" in c2.leads[0].target


def test_split_fig():
    assert split_fig("Genus sp. （图12）") == ("Genus sp.", "（图12）")
    assert split_fig("Genus sp.") == ("Genus sp.", "")


@NEED_SAMPLE
def test_json_roundtrip():
    k = from_imajima_json(J)[0]
    assert KeyIR.from_json(k.to_json()) == k


def test_markdown():
    md = "<!-- page 1 -->\n1. 背鳞 10 对 ... 2\n1' 背鳞 11 对 ... Exogone\n"
    assert isinstance(from_markdown(md), list)
