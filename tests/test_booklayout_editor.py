import json
from pathlib import Path

from booklayout.editor import build_editor, edits_to_patch, html_to_md, md_to_html
from booklayout.cli import main as cli_main


def test_md_html_roundtrip():
    md = "Familia *Nereididae* con **negrita**\nlínea 2"
    assert html_to_md(md_to_html(md)) == md


def test_html_variants_to_md():
    assert html_to_md("a <i>b</i> <b>c</b><br>d") == "a *b* **c**\nd"
    assert html_to_md("<span style='font-style: italic'>x</span> y") == "*x* y"
    assert html_to_md("a&nbsp;b") == "a b"


def _data():
    return {"pages": [{"page": 1, "blocks": [
        {"block_id": "p001_b00", "role": "body", "text": "Nereis diversicolor vive aqui.",
         "translation": "*Nereis diversicolor* vive aqui."}]}]}


def test_edit_html_and_apply(tmp_path: Path):
    d = _data()
    al = tmp_path / "a.json"
    al.write_text(json.dumps(d), encoding="utf-8")
    out = tmp_path / "e.html"
    info = build_editor(d, None, out)
    assert info["blocks"] == 1 and "data-id='p001_b00'" in out.read_text(encoding="utf-8")
    ed = {"edits": [{"block_id": "p001_b00", "html": "<i>Nereis diversicolor</i> vive <b>aquí</b><br>fin"}],
          "comments": [{"block_id": "p001_b00", "quote": "vive", "note": "check"}]}
    patch, rep = edits_to_patch(ed, d)
    assert patch["edits"][0]["translation"] == "*Nereis diversicolor* vive **aquí**\nfin"
    edp = tmp_path / "ed.json"
    edp.write_text(json.dumps(ed), encoding="utf-8")
    new = tmp_path / "n.json"
    rc = cli_main(["apply-html-edits", "--aligned", str(al), "--edits", str(edp), "--out", str(new)])
    assert rc == 0
    got = json.loads(new.read_text(encoding="utf-8"))["pages"][0]["blocks"][0]["translation"]
    assert got.endswith("**aquí**\nfin")


def test_unchanged_edit_is_dropped():
    d = _data()
    patch, _ = edits_to_patch({"edits": [{"block_id": "p001_b00",
                               "html": "<i>Nereis diversicolor</i> vive aqui."}]}, d)
    assert patch["edits"] == []
