from booklayout.audit import audit_aligned, detect_source_lang, format_table
from booklayout.cli import build_parser

DOTS = " . . . . . . . . . . . . "


def book(*blocks, lang="en"):
    return {"metadata": {"lang": lang},
            "pages": [{"page": 1, "blocks": [dict(b, block_id=f"b{i}") for i, b in enumerate(blocks)]}]}


def count(data, key):
    return audit_aligned(data, source_lang="es")["items"][key]["count"]


def key(tr, text="x"):
    return {"role": "key", "text": text, "translation": tr}


def test_key_inline():
    assert count(book(key(f"Cirri absent{DOTS}2 • Cirri present{DOTS}5")), "key_inline") == 1
    assert count(book(key(f"Cirri absent{DOTS}2"), key(f"Cirri present{DOTS}5")), "key_inline") == 0


def test_key_split():
    assert count(book(key(f"Cirri absent{DOTS}")), "key_split") == 1
    assert count(book(key(f"Cirri absent{DOTS}2")), "key_split") == 0


def test_key_short_leader():
    assert count(book(key("Cirri absent . .2")), "key_short_leader") == 1
    assert count(book(key(f"Cirri absent{DOTS}2")), "key_short_leader") == 0


def test_caption_breaks():
    cap = lambda t: {"role": "caption", "text": "Fig", "translation": t}  # noqa: E731
    assert count(book(cap("Re­vised map")), "caption_text_breaks") == 1
    assert count(book(cap("Revised map")), "caption_text_breaks") == 0


def test_duplicates():
    t = "A long repeated paragraph about setae and parapodia. " * 3
    b = {"role": "body", "text": "x", "translation": t}
    assert count(book(b, dict(b)), "duplicate_paragraphs") == 1
    assert count(book(b, dict(b, translation=t + "other")), "duplicate_paragraphs") == 0


def test_truncated():
    mk = lambda t: {"role": "body", "text": "x", "translation": t}  # noqa: E731
    assert count(book(mk("Setae present, and"), mk("then absent.")), "truncated_endings") == 1
    assert count(book(mk("Setae present with"), mk("a hook.")), "truncated_endings") == 1
    assert count(book(mk("Setae present."), mk("A hook.")), "truncated_endings") == 0
    assert count(book(mk("Setae present with"), mk("A hook.")), "truncated_endings") == 0


def test_residue_es_and_ja():
    es = {"role": "body", "text": "x",
          "translation": "Nombre de reemplazo injustificado of the genus"}
    ok = {"role": "body", "text": "x", "translation": "Unjustified replacement name"}
    assert count(book(es), "source_residue") == 1
    assert count(book(ok), "source_residue") == 0
    ja = book({"role": "body", "text": "ゴカイ", "translation": "ゴカイ worm"})
    assert audit_aligned(ja, source_lang="ja")["items"]["source_residue"]["count"] == 1
    ja2 = book({"role": "body", "text": "ゴカイ", "translation": "worm"})
    assert audit_aligned(ja2, source_lang="ja")["items"]["source_residue"]["count"] == 0


def test_coverage():
    d = book({"role": "body", "text": "Texto uno", "translation": ""},
             {"role": "body", "text": "Texto dos", "translation": "Text two"})
    r = audit_aligned(d, source_lang="es")
    assert (r["coverage"]["source_blocks"], r["coverage"]["translated_blocks"]) == (2, 1)
    assert r["items"]["uncovered_blocks"]["count"] == 1
    full = audit_aligned(book({"role": "body", "text": "Texto", "translation": "Text"}), source_lang="es")
    assert full["items"]["uncovered_blocks"]["count"] == 0


def test_detect_and_table_and_parser():
    assert detect_source_lang(book({"role": "body", "text": "ゴカイの仲間です", "translation": ""})) == "ja"
    assert detect_source_lang(book({"role": "body", "text": "The worm is long", "translation": ""})) == "unknown"
    assert "TOTAL" in format_table(audit_aligned(book(key("a")), source_lang="es"))
    assert build_parser().parse_args(["audit", "a.json", "--json"]).json is True


def test_han_residue_in_english_target():
    h = {"role": "heading", "text": "ウロコムシ科", "translation": "多鳞虫科 Polynoidae"}
    ref = {"role": "ref", "text": "今島 1968", "translation": "今島 1968"}
    data = book(h, ref, lang="en")
    assert audit_aligned(data, source_lang="ja")["items"]["source_residue"]["count"] == 1
