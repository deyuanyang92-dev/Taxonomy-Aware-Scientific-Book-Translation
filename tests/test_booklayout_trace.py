import json

from booklayout import trace


def _al(path, blocks, lineage=None):
    d = {"pages": [{"page": 1, "blocks": blocks}]}
    if lineage:
        d["lineage"] = lineage
    path.write_text(json.dumps(d), encoding="utf8")


def test_lineage_find_flags_and_set(tmp_path):
    es = tmp_path / "es.json"
    en = tmp_path / "en.json"
    _al(es, [{"block_id": "p001_b00", "role": "key", "text": "Palpos ..... 3", "translation": "Palpos ..... 3"}])
    _al(en, [{"block_id": "p001_b00", "role": "key", "text": "Palpos ..... 3", "translation": "Palps"}],
        {"derived_from": str(es), "stage": "google-translate"})
    db = tmp_path / "w" / "trace.db"
    db.parent.mkdir()
    info = trace.build(en, db)
    assert info["stages"] == 2 and info["blocks"] == 1
    con = trace._db(str(db))
    res = trace.find(con, "Palpos")
    blk = res[0]["blocks"][0]
    assert [x["stage"] for x in blk["layers"]] == ["final", "ancestor1"]
    assert any("digits lost" in f for f in blk["flags"])  # the target "3" vanished in the final
    e = trace.set_text(db, en, "p001_b00", "translation", "Palps ..... 3", "restore target")
    assert e["old"] == "Palps"
    trace.build(en, db)
    blk = trace.lineage(trace._db(str(db)), "p001_b00")
    assert blk["edits"][0]["reason"] == "restore target" and not blk["flags"]


def test_lost_numbers():
    assert trace.lost_numbers("a 12 b 3", "a 12") == ["3"]
    assert trace.lost_numbers("", "x") == []


def test_key_target_lost_check(tmp_path):
    es, en = tmp_path / "es.json", tmp_path / "en.json"
    _al(es, [{"block_id": "b1", "role": "key", "text": "Palpos ..... 3", "translation": "Palpos ..... 3"},
             {"block_id": "b2", "role": "key", "text": "Eusyllinae ..... (p. 47)", "translation": "x"}])
    _al(en, [{"block_id": "b1", "role": "key", "text": "Palpos ..... 3", "translation": "Palps"},
             {"block_id": "b2", "role": "key", "text": "Eusyllinae .....", "translation": "Eusyllinae ..... (p. 47)"}],
        {"derived_from": str(es)})
    bad = trace.key_target_losses(en)
    assert [b["block_id"] for b in bad] == ["b1"]  # b2 target kept; b1 "3" lost


def test_gtranslate_heading_and_names():
    from booklayout import gtranslate as g

    assert g.fixed_heading("Clave de géneros", "zh-CN") == "属检索表"
    assert g.fixed_heading("Clave de géneros", "en") == "Genus key"
    assert g.fixed_heading("ÍNDICE", "en") == "Contents"
    assert g.fixed_heading("Familia SYLLIDAE Grube, 1850", "zh-CN") == "科 SYLLIDAE Grube, 1850"
    assert g.fixed_heading("Familia que se estudia en el libro", "en") is None
    masked, table = g.mask_names("Petitia amphophthalma Siewing, 1956. Vie", frozenset())
    assert "Petitia amphophthalma" in table.values() and "Petitia" not in masked
    masked, table = g.mask_names("Neopetitia amphophthalma (Siewing, 1956) comb. n.", frozenset())
    assert "comb. n." in table.values()
    assert g.zh_punct("Pierantoni (1903) 的 图 97A ，107A") == "Pierantoni（1903）的图97A，107A"


def test_gtranslate_caption_linebreak_keeps_space(tmp_path):
    import json
    from booklayout import gtranslate as g

    class Fake:
        tl = "en"
        name_check: list = []
    # the joiner regex used for legends OCR'd as body: "of\nS." must not become "ofS."
    import re
    s = "male stolon free of\nS. gerlachi (D)"
    assert re.sub(r"(?<=[a-z,;])[ \t]*\n[ \t]*(?=\S)", " ", s) == "male stolon free of S. gerlachi (D)"
    assert g.LEADER_RE.match("Familia X ..... 11")
