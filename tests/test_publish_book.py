"""Issue #13: scripts/publish_book.py end to end on a synthetic book (no model, no LibreOffice)."""
import json
import sys
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import publish_book  # noqa: E402

SRC = """<!-- PDF p.1 -->
# Annelida

Intro paragraph of the book.

<!-- PDF p.2 -->
Key to genera
1. Eyes present ........ 2
• Eyes absent ........ Alpha (p. 4)
2. Setae long ........ Beta bella (p. 5)
• Setae short ........ Gamma (p. 6)

Figure 1. A worm.
"""
TGT = SRC.replace("Intro paragraph of the book.", "Párrafo de introducción.") \
    .replace("Eyes present", "Ojos presentes").replace("Eyes absent", "Ojos ausentes") \
    .replace("Setae long", "Setas largas").replace("Setae short", "Setas cortas") \
    .replace("A worm.", "Un gusano.")


def _pdf(path):
    doc = fitz.open()
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 300, 200), False)
    pix.set_rect(pix.irect, (200, 200, 200))
    doc.new_page(width=420, height=600)
    p2 = doc.new_page(width=420, height=600)
    p2.insert_image(fitz.Rect(60, 100, 360, 300), stream=pix.tobytes("png"))
    p2.insert_text((60, 330), "Figure 1. A worm.", fontsize=9)
    doc.save(str(path))


def test_dry_plan_lists_every_stage_without_running(tmp_path, capsys):
    rc = publish_book.main(["run", "--key", "K", "--pdf", "b.pdf", "--work", str(tmp_path / "w"), "--sl", "de",
                            "--tl", "en", "--dry"])
    out = capsys.readouterr().out
    assert rc == 0 and not (tmp_path / "w" / "publish_run.json").exists()
    for stage in publish_book.STAGES:
        assert f"[{stage}]" in out
    assert "auto_translate.py" in out and "--sl de" in out and "booklayout gate" not in out.split("[gate]")[0]


def test_end_to_end_without_pdf_conversion_records_commands_and_blocks_release(tmp_path):
    src, tgt, pdf, w = tmp_path / "s.md", tmp_path / "t.md", tmp_path / "b.pdf", tmp_path / "w"
    src.write_text(SRC, encoding="utf-8")
    tgt.write_text(TGT, encoding="utf-8")
    _pdf(pdf)
    rc = publish_book.main(["run", "--source-md", str(src), "--translation-md", str(tgt), "--pdf", str(pdf),
                            "--work", str(w), "--no-pdf", "--title", "T"])
    rec = json.loads((w / "publish_run.json").read_text())
    stages = [s["stage"] for s in rec["steps"]]
    assert stages[:2] == ["export", "translate"]
    ok = {s["stage"]: s["rc"] for s in rec["steps"] if "rc" in s}
    assert ok["figures"] == 0 and ok["align"] == 0 and ok["keycheck"] == 0, rec["steps"]
    assert (w / "figures" / "source_figure_audit.json").exists() and (w / "aligned.json").exists()
    assert (w / "key_model.json").exists()
    assert rec["releasable"] is False and rec["versions"]["python"] and rec["inputs_sha256"]["pdf"]
    assert rc in (0, 1)


def test_failed_stage_stops_and_names_itself(tmp_path):
    src, tgt, w = tmp_path / "s.md", tmp_path / "t.md", tmp_path / "w"
    src.write_text(SRC, encoding="utf-8")
    tgt.write_text(TGT, encoding="utf-8")
    rc = publish_book.main(["run", "--source-md", str(src), "--translation-md", str(tgt), "--work", str(w),
                            "--pdf", str(tmp_path / "missing.pdf"), "--no-pdf"])
    rec = json.loads((w / "publish_run.json").read_text())
    assert rc == 1 and rec["failed"] == "figures"
