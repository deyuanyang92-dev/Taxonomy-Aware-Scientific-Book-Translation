"""Handbook_Annelida 真实 PDF 只读验收（docs/probe_spec.md §4 T5）。

HANDBOOK_DIR 缺文件则整组跳过。只开 PDF 少数页，总耗时应 < 3 分钟。
"""
import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

HB = Path(os.environ.get("HANDBOOK_DIR", "/mnt/p/翻译-译作/Handbook_Annelida"))
GREG = HB / "Greg_Annelida_2022.pdf"
VOL1 = HB / "Handbook of Zoology, Annelida, Basal groups and pleistoannelida Sedentaria I.pdf"
VOL2 = HB / "Handbook of Zoology Volume 2-full.pdf"
VOL3 = HB / "Handbook of Zoology-Annelida-Volume3.pdf"
VOL4 = HB / "Handbook of Zoology Annelida Volume 4 Pleistoannelida Erratia II-2022.pdf"


def _need(*paths):
    return pytest.mark.skipif(not all(p.exists() for p in paths),
                              reason="Handbook PDF 缺失（设 HANDBOOK_DIR）")


@_need(VOL3)
def test_vol3_contents():
    import chapter_split as cs
    got = cs.contents_from_pdf(VOL3)
    assert len(got) >= 10
    assert any(t.startswith("7.4") for t, _n, _lv in got)
    t74 = next((t, n, lv) for t, n, lv in got if t.startswith("7.4 "))
    assert "Sedentaria" in t74[0] and t74[1] == 1 and t74[2] == 1


@_need(VOL1)
def test_vol1_contents_two_columns():
    import chapter_split as cs
    got = cs.contents_from_pdf(VOL1)
    assert len(got) >= 15
    assert all(len(t) <= 160 for t, _n, _lv in got)       # 不得把整栏并成一个标题
    assert any(t.startswith("1.1 ") for t, _n, _lv in got)


@_need(GREG, VOL1, VOL2, VOL3, VOL4)
def test_probe_kinds():
    from docstore.probe import probe_pdf
    assert probe_pdf(GREG)["kind"] == "scan"
    for v in (VOL1, VOL2, VOL3, VOL4):
        assert probe_pdf(v)["kind"] == "native", v.name
    assert probe_pdf(VOL1)["bookmarks"]["usable"] is False


def test_caption_re_four_level_label():
    from booklayout.pdffigures import CAPTION_RE
    m = CAPTION_RE.match("Fig. 7.11.2.3: Some caption text")
    assert m is not None
    assert re.sub(r"\s", "", m.group("label")) == "7.11.2.3"


@_need(VOL3)
def test_vol3_pilot_ingest_build_restyle(tmp_path):
    """T7: Vol3 p13-14 端到端 ingest-native -> build -> restyle --style（只用英文原文，不碰译文 md）。

    标题层级须与 booklayout heading-levels 一致；restyle 改 Body 字号后样式生效且不重排。
    """
    import json

    from docx import Document

    from booklayout import cli
    from booklayout.profile import validate_aligned

    pages = "13-14"
    al, hl = tmp_path / "a.json", tmp_path / "hl.json"
    assert cli.main(["ingest-native", str(VOL3), "--pages", pages, "-o", str(al)]) == 0
    assert cli.main(["heading-levels", str(VOL3), "--pages", pages, "--json", str(hl)]) == 0
    data = json.loads(al.read_text(encoding="utf-8"))
    assert data["schema"] == "aligned/2"
    assert validate_aligned(data) == []
    mine = {(p["page"], b["text"].lower()): b["level"]
            for p in data["pages"] for b in p["blocks"] if b["role"] == "heading"}
    ref = {(h["page"], h["text"].lower()): h["level"]
           for h in json.loads(hl.read_text(encoding="utf-8"))["headings"]}
    common = set(mine) & set(ref)
    assert len(common) >= 3
    # T2b: ingest-native now drops the 8 pt running head "7.4 Sedentaria..." (furniture) that heading-levels
    # still counts as level 1, so levels are compared as a constant offset (here 1), not absolutely.
    offs = {mine[k] - ref[k] for k in common}
    assert len(offs) == 1 and offs <= {0, -1}, {k: (mine[k], ref[k]) for k in common}
    # 英文单语试点：译文字段取原文（派生文件，不写回任何译文 md）
    for p in data["pages"]:
        for b in p["blocks"]:
            b["translation"] = b["text"]
    en = tmp_path / "en.json"
    en.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    figs = tmp_path / "figs"
    figs.mkdir()
    (figs / "source_figure_audit.json").write_text("{}", encoding="utf-8")
    meta = tmp_path / "meta.json"
    meta.write_text(json.dumps({"title": "pilot", "include_front_matter": False, "include_contents": False,
                                "title_page": False}), encoding="utf-8")
    out = tmp_path / "v3.docx"
    cli.main(["build", "--aligned", str(en), "--figures", str(figs), "--metadata", str(meta),
              "--strict-schema", "--out", str(out)])
    built = next(tmp_path.glob("v3*.docx"))          # 无验收则输出名带 .DRAFT
    prof = tmp_path / "prof.json"
    prof.write_text(json.dumps({}), encoding="utf-8")
    rs = tmp_path / "restyled.docx"
    assert cli.main(["restyle", "--docx", str(built), "--profile", str(prof), "--out", str(rs),
                     "--style", "Body.size=11"]) == 0
    d0, d1 = Document(str(built)), Document(str(rs))
    assert d1.styles["Body"].font.size.pt == 11
    assert d0.styles["Body"].font.size.pt != 11
    assert [p.text for p in d0.paragraphs] == [p.text for p in d1.paragraphs]
    n_h1 = sum(1 for p in d1.paragraphs if p.style.name == "Heading 1")
    assert n_h1 >= 1
