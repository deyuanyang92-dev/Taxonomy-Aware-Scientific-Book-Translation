"""德文参考文献行：判为 reference（不送机翻），确定性处理只换缩写（S.→p.、Taf.→pl.），作者、年份、刊名不动。"""
from transqa import blocks

REFS = [
    "AUGENER, H. (1922): Polychaeta von Südwest-Australien. Mitt. Zool. Mus. Hamburg 39: 1-64, Taf. 2.",
    "EHLERS, E. (1901): Die Polychaeten des magellanischen und chilenischen Strandes. Festschr. Leipzig, 232 S.",
    "HARTMANN-SCHRÖDER, G. 1962. Zur Kenntnis des Eulitorals. Mitt. hamb. zool. Mus. Inst. 60: 57-270.",
]


def test_classified_reference():
    assert all(blocks.classify(r, "de") == "reference" for r in REFS)


# 真实页面（Hartmann-Schröder 1962 p.210/212 的 OCR）：折行、「— ‚, 年份」重复作者、OCR 杂符、1→l
REAL = [
    "Dana, J. D.. 1852: United States Exploring Expedition. U.S.N., vol. XIV, pt. I\nZoophytes.",
    "— ‚, 190la: Die Polychaeten des magellanischen und chilenischen Strandes. Ein\nBeitrag zur Faunistik.",
    "— ‚1957: The Polychaete Fauna of South Africa. Pt. 4. New species and records",
    "Hana1, T., 1957—1959: Studies on the Ostracoda from Japan. I—V and Historical",
    "MoeIntosu W.C., 1885: Report on the Annelida Polychaeta collected by H. M. S. Challenger",
    "| Pur1, H.S., 1952: Ostracode Genus Cytherideis and its allies. Jour. Paleont.",
    "pp. 1—84.",
    "Friedrichsen & Co., 148 pp., 9 pls.",
]


def test_real_page_references_not_sent_to_translator():
    assert [blocks.classify(r, "de") for r in REAL] == ["reference"] * len(REAL)


def test_ocr_junk_and_orphan_fragments_protected():
    for j in ("IE", "'", "HC 2 eG", "» 7", "pls."):
        assert blocks.classify(j, "de") == "index", j
    assert blocks.classify("Die Art ist 2 mm lang.", "de") == "free"


def test_running_header_translated_deterministically():
    assert blocks.deterministic("Literaturverzeichnis 267", "de") == "References 267"


def test_running_header_protected():
    assert blocks.classify("Literaturverzeichnis 267", "de") == "index"
    assert blocks.classify("Literaturverzeichnis der Polychaeten von Hamburg und Umgebung", "de") == "free"


def test_narrative_with_year_not_reference():
    t = "Die Art wurde von FAUVEL 1923 zuerst gefunden und lebt im Sand der Gezeitenzone bei Hamburg."
    assert blocks.classify(t, "de") == "free"
    assert blocks.classify("<!-- PDF p.210 -->", "de") == "free"


def test_deterministic_keeps_authors_years_and_swaps_abbrev():
    out = blocks.deterministic(REFS[0], "de")
    assert "AUGENER, H. (1922)" in out and "Mitt. Zool. Mus. Hamburg 39: 1-64" in out and "pl. 2" in out
    assert blocks.deterministic(REFS[1], "de").endswith("232 S.")   # 页数后缀不是「S. 数字」，不改
