import json
import zipfile
from pathlib import Path

from PIL import Image

from booklayout.cli import main as cli_main


def test_figure_group_embeds_both_pictures(tmp_path: Path):
    for n, c in (("a", "red"), ("b", "blue")):
        Image.new("RGB", (40, 30), c).save(tmp_path / f"{n}.png")
    (tmp_path / "source_figure_audit.json").write_text('{"figures": []}', encoding="utf-8")
    data = {"pages": [{"page": 1, "chapter": "A", "kind": "body", "blocks": [
        {"block_id": "b0", "role": "body", "text": "Uno.", "translation": "Uno.", "y0": 1},
        {"block_id": "b1", "role": "figure_group", "y0": 2,
         "figures": [{"crop": "a.png", "height_mm": 10}, {"crop": "b.png"}]}]}]}
    (tmp_path / "a.json").write_text(json.dumps(data), encoding="utf-8")
    (tmp_path / "m.json").write_text(json.dumps({"title": "T", "include_front_matter": False,
                                                 "include_contents": False, "title_page": False}), encoding="utf-8")
    cli_main(["build", "--aligned", str(tmp_path / "a.json"), "--figures", str(tmp_path),
              "--metadata", str(tmp_path / "m.json"), "--out", str(tmp_path / "o.docx")])
    z = zipfile.ZipFile(tmp_path / "o.DRAFT.docx")
    assert len([n for n in z.namelist() if n.startswith("word/media/")]) == 2
