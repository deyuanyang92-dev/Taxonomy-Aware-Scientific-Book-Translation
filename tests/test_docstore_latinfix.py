"""docstore.latinfix：德文 OCR 后处理（样例取自 Hartmann-Schröder 金标准页的 Tesseract 实际错误）。"""
from collections import Counter

from docstore.latinfix import fix_page, fix_sex, fix_smallcaps, fix_units, fix_vocab


def test_sex_symbols():
    t = "nur beim 9 hier etwas kürzer; im 40.\nNotopod bei & und @ jedoch; als beim &”. Neuropodien bei 9 und c& unter"
    out, ch = fix_sex(t)
    assert out == "nur beim ♀ hier etwas kürzer; im 40.\nNotopod bei ♂ und ♀ jedoch; als beim ♂. Neuropodien bei ♀ und ♂ unter"
    assert len(ch) == 6


def test_sex_keeps_authors_and_numbers():
    t = "DAY & HUTCHINGS 1979; Day & Hutchings; beim 9. Segment; bei 9 mm; und 9 Borsten"
    assert fix_sex(t)[0] == t


def test_smallcaps():
    out, _ = fix_smallcaps("nach KoTT und GIsLEN, WıLSON; PERKINs; glauCopsis; McIntosh; HARTMANN")
    assert out == "nach KOTT und GISLEN, WILSON; PERKINS; glauCopsis; McIntosh; HARTMANN"


def test_units():
    assert fix_units("Borsten 50 um lang, 12um.")[0] == "Borsten 50 µm lang, 12µm."
    assert fix_units("bis 50 um die Ecke")[0] == "bis 50 um die Ecke"


def test_vocab_umlaut_and_c_e():
    v = Counter({"Zähne": 40, "trägt": 30, "steht": 50, "Zahne": 1, "stcht": 1, "tragt": 0})
    out, ch = fix_vocab("Zahne tragt stcht", v)
    assert out == "Zähne trägt steht"


def test_vocab_leaves_common_and_ambiguous():
    v = Counter({"schon": 50, "schön": 5, "Haken": 30, "Hakcn": 1})
    assert fix_vocab("schon", v)[0] == "schon"  # 常见词不动
    assert fix_vocab("Hakcn", v)[0] == "Haken"


def test_fix_page_log():
    out, log = fix_page("beim & 50 um lang", Counter())
    assert out == "beim ♂ 50 µm lang"
    assert {r for r, _, _ in log} == {"sex", "units"}


def test_cli_postfix_writes_version_and_audit(tmp_path, monkeypatch):
    import json

    from docstore import cli, open_store
    from docstore.store import make_version

    monkeypatch.setenv("DOCSTORE_AGENT", "pytest")
    st = open_store(tmp_path / "lib")
    pdf = tmp_path / "Muster, 1970-Die Polychaeten der Nordsee.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    key, _ = st.register(pdf, by="pytest")
    st.update_doc(key, lang="de")
    st.put_version(key, 1, make_version("Notopod beim & und beim 9 hier; Borsten 50 um lang.", "ocr",
                                        producer="tesseract"))
    st.put_version(key, 2, make_version("ohne Fehler", "ocr", producer="tesseract"))
    assert cli.main(["--root", str(st.root), "postfix", key]) == 0
    pg = st.read_page(key, 1)
    assert pg["producer"] == "latinfix"
    assert pg["text"] == "Notopod beim ♂ und beim ♀ hier; Borsten 50 µm lang."
    assert pg["alternates"][0]["producer"] == "tesseract"
    assert st.read_page(key, 2)["producer"] == "tesseract"
    log = [json.loads(x) for x in (st.root / "_audit" / f"latinfix_{key}.jsonl").read_text().splitlines()]
    assert {r["rule"] for r in log} == {"sex", "units"}
    # 再跑不重复改
    assert cli.main(["--root", str(st.root), "postfix", key]) == 0
    assert len(st.read_page(key, 1)["alternates"]) == 1


def test_reflow_german():
    from docstore.store import reflow
    t = "der Unterfamilie Eusyl-\nlinae, bei der\nder Pharynx-Zahn. Vorder-\nund Hinterende; HARTMANN-\nSCHRÖDER\n\nNeuer Absatz"
    assert reflow(t) == ("der Unterfamilie Eusyllinae, bei der der Pharynx-Zahn. Vorder- und Hinterende; "
                         "HARTMANN-SCHRÖDER\n\nNeuer Absatz")


def test_glyphs():
    from docstore.latinfix import fix_glyphs
    t = ("die Typusart, 0. morena; VON O0. MORENA; O0. pterochaeta; Taf. ı Fig. 2; Fig. ıa, b; aus ı3. Parapod; "
         "Ann. Inst. Oc&anogr.; l’&tude; Salzgehalt 19.35%00 Cl; 8%o; Day & Hutchings; 10 0. 5")
    out, _ = fix_glyphs(t)
    assert out == ("die Typusart, O. morena; VON O0. MORENA; O. pterochaeta; Taf. 1 Fig. 2; Fig. 1a, b; aus 13. Parapod; "
                   "Ann. Inst. Océanogr.; l’étude; Salzgehalt 19.35‰ Cl; 8‰; Day & Hutchings; 10 0. 5")
