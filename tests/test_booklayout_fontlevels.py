"""Issue #60: heading levels from font family/bold/size (probe_spec §2, test 6)."""
import fitz

from booklayout import cli, fontlevels


def _pdf(path):
    doc = fitz.open()
    page = doc.new_page(width=420, height=600)
    y = 80
    page.insert_text((50, y), "7.4.1 Fabriciidae", fontname="hebo", fontsize=12)
    page.insert_text((50, y + 25), "Introduction", fontname="hebo", fontsize=9.5)
    page.insert_text((50, y + 45), "Family Sabellidae", fontname="hebo", fontsize=9.5)
    for i in range(12):
        page.insert_text((50, y + 70 + 12 * i), f"Body text line number {i} of the paragraph goes here.",
                         fontname="tiro", fontsize=9.5)
    page.insert_text((50, y + 230), "Diagnosis:", fontname="tibo", fontsize=9.5)
    page.insert_text((200, 570), "139", fontname="hebo", fontsize=9.5)
    doc.save(str(path))
    doc.close()
    return fitz.open(str(path))


def test_number_depth():
    assert fontlevels.number_depth("7.13.1.5.2 Sigalionidae") == ("7.13.1.5.2", 5)
    assert fontlevels.number_depth("7.4.1. Name") == ("7.4.1", 3)
    assert fontlevels.number_depth("Introduction") is None
    assert fontlevels.number_depth("139 pages") is None


def test_family_and_serif():
    assert fontlevels.family_of("ABCDEF+DGMetaScience-Bold5") == "DGMetaScience"
    assert not fontlevels.is_serif("DGMetaScience-Bold")
    assert fontlevels.is_serif("DGMetaSerifScience-Bold")
    assert fontlevels.is_serif("Times-Roman")


def test_candidates_and_levels(tmp_path):
    doc = _pdf(tmp_path / "a.pdf")
    page = doc.load_page(0)
    body = fontlevels.body_style([page])
    assert body["size"] == 9.5 and body["serif"] and not body["bold"]
    cands = fontlevels.heading_candidates(page, body)
    texts = [c["text"] for c in cands]
    assert texts == ["7.4.1 Fabriciidae", "Introduction", "Family Sabellidae"]
    assert cands[0]["number"] == "7.4.1" and cands[0]["depth"] == 3
    res = fontlevels.assign_levels(cands)
    h = {x["text"]: x for x in res["headings"]}
    assert h["7.4.1 Fabriciidae"]["source"] == "number"
    assert h["Introduction"]["source"] == "style" and h["Introduction"]["level"] == 2
    assert h["Introduction"]["conflict"] is None
    assert "taxon=1" in h["Family Sabellidae"]["conflict"]
    assert [r["level"] for r in res["ladder"]] == [1, 2]
    assert res["conflicts"] == [h["Family Sabellidae"]]


def test_number_vs_style_conflict():
    mk = lambda t, size, num, depth: dict(  # noqa: E731
        page=1, text=t, style={"family": "F", "size": size, "bold": True}, number=num, depth=depth)
    res = fontlevels.assign_levels([mk("7.4 A", 12, "7.4", 2), mk("7.4.1 B", 12, "7.4.1", 3)])
    assert res["headings"][0]["conflict"] is None
    assert "number=2 vs style=1" in res["headings"][1]["conflict"]


def test_cli(tmp_path, capsys):
    _pdf(tmp_path / "a.pdf")
    out = tmp_path / "o.json"
    rc = cli.main(["heading-levels", str(tmp_path / "a.pdf"), "--pages", "1", "--json", str(out)])
    assert rc == 0
    assert "7.4.1 Fabriciidae" in capsys.readouterr().out
    assert out.exists()
