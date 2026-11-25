"""落实后复检：只报改动引入的阻断问题；回滚只动被点名的页。"""
from __future__ import annotations

from transqa import postgate as pg

P1 = "<!-- PDF p.1 | x -->\n\n"
P2 = "<!-- PDF p.2 | x -->\n\n"


def test_new_blocking_reports_only_issues_introduced_by_the_edit():
    src = P1 + "Length 12 mm.\n"
    r = pg.new_blocking(src, P1 + "Length 12 mm.\n", P1 + "Length long.\n", "en", "en", {1})
    assert 1 in r and all(i.blocking for i in r[1])


def test_new_blocking_ja_en_fixture():
    src = P1 + "体長は12mm。\n"
    r = pg.new_blocking(src, P1 + "Body length 12 mm.\n", P1 + "Body length long.\n", "ja", "en", {1})
    assert [i.code for i in r[1]] == ["number.missing"]


def test_new_blocking_ignores_preexisting_issues():
    bad = P1 + "Length long.\n"
    assert pg.new_blocking(P1 + "Length 12 mm.\n", bad, bad, "en", "en", {1}) == {}


def test_new_blocking_only_looks_at_named_pages():
    src = P1 + "Length 12 mm.\n\n" + P2 + "Width 3 mm.\n"
    before = P1 + "Length 12 mm.\n\n" + P2 + "Width 3 mm.\n"
    after = P1 + "Length 12 mm.\n\n" + P2 + "Width thin.\n"
    assert pg.new_blocking(src, before, after, "en", "en", {1}) == {}
    assert list(pg.new_blocking(src, before, after, "en", "en", {2})) == [2]


def test_rollback_restores_old_text_and_reports_failures():
    after = P1 + "Body slender.\n"
    out, res = pg.rollback(after, [{"pdf_page": 1, "old": "Body short.", "new": "Body slender."}], {1})
    assert "Body short." in out and res[0]["result"] == "rolled_back"
    out2, res2 = pg.rollback(after, [{"pdf_page": 1, "old": "a", "new": "not there"}], {1})
    assert out2 == after and res2[0]["result"] == "rollback_failed"


def test_rollback_touches_only_named_pages_and_keeps_other_bytes():
    after = P1 + "Body slender.\n\n" + P2 + "Body slender.\n"
    out, res = pg.rollback(after, [{"pdf_page": 1, "old": "Body short.", "new": "Body slender."},
                                   {"pdf_page": 2, "old": "Body short.", "new": "Body slender."}], {1})
    assert out == P1 + "Body short.\n\n" + P2 + "Body slender.\n"
    assert [r["result"] for r in res] == ["rolled_back", "kept"]


def test_rollback_new_appearing_twice_on_page_fails_and_leaves_text():
    after = P1 + "Body slender. Body slender.\n"
    out, res = pg.rollback(after, [{"pdf_page": 1, "old": "Body short.", "new": "Body slender."}], {1})
    assert out == after and res[0]["result"] == "rollback_failed"


def test_rollback_chained_edits_on_one_page_undo_in_reverse_order():
    after = P1 + "Body very slender.\n"
    applied = [{"pdf_page": 1, "old": "Body short.", "new": "Body slender."},
               {"pdf_page": 1, "old": "Body slender.", "new": "Body very slender."}]
    out, res = pg.rollback(after, applied, {1})
    assert out == P1 + "Body short.\n" and [r["result"] for r in res] == ["rolled_back", "rolled_back"]


def test_split_join_is_identity_with_preamble_and_no_trailing_newline():
    for md in ("pre\n\n" + P1 + "a\n\n" + P2 + "b", P1 + "a", "", "no markers\nat all\n", P1 + "a\n\n\n" + P2 + "\n"):
        assert pg._join(pg._split(md)) == md
