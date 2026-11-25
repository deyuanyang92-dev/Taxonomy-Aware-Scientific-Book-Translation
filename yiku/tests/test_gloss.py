from yiku import db as D
from yiku import gloss as G
from yiku import match as M


def _tsv(tmp_path):
    p = tmp_path / "g.tsv"
    p.write_text("term\tdefinition\tapplicable\tabbr\tsource\n"
                 "acicula\t{{!!title}} - supportive chaeta\tPolychaeta\taci\t{{Beesley 2000}}\n"
                 "palp\tsensory appendage\tPolychaeta\tpa\t\n"
                 "hair chaetae\tsee capillary chaeta\tOligochaeta\t\t\n", encoding="utf8")
    return p


def test_import_idempotent(tmp_path):
    con = D.connect(tmp_path / "y.db")
    assert G.import_tsv(con, _tsv(tmp_path), "annikey") == (3, 0)
    assert G.import_tsv(con, _tsv(tmp_path), "annikey") == (0, 3)
    r = con.execute("SELECT definition, ref FROM en_glossary WHERE en_norm='acicula'").fetchone()
    assert r["definition"].startswith("acicula - supportive") and r["ref"] == "Beesley 2000"


def test_gaps_skip_terms_with_zh(tmp_path):
    con = D.connect(tmp_path / "y.db")
    D.add_source(con, "s", "S", "authority")
    con.execute("INSERT INTO terms(en,en_norm,zh,source,status) VALUES('palp','palp','触手','s','已核')")
    G.import_tsv(con, _tsv(tmp_path), "annikey")
    names = [r["en"] for r in G.find_gaps(con, "The acicula and the palp and hair chaetae are seen.")]
    assert names == ["acicula", "hair chaetae"]
    con.execute("INSERT INTO terms(en,en_norm,zh,source,status) VALUES('capillary chaeta','capillary chaeta','毛状刚毛','s','已核')")
    out = G.render_gaps(G.find_gaps(con, "hair chaetae"), con=con)
    assert "毛状刚毛" in out
    con.execute("INSERT INTO terms(en,en_norm,zh,source,status) VALUES('aciculum','aciculum','足刺','s','已核')")
    assert [r["en"] for r in G.find_gaps(con, "acicula")] == []


def test_term_table_appends_gaps(tmp_path):
    con = D.connect(tmp_path / "y.db")
    G.import_tsv(con, _tsv(tmp_path), "annikey")
    out = M.term_table(con, "A stout acicula.", usage=False)
    assert "未定名术语" in out and "| acicula |" in out
    assert "未定名术语" not in M.term_table(con, "Nothing here.", usage=False)
