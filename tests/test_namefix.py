import json
import sqlite3

import pytest

from docstore import namefix


@pytest.fixture()
def worms(tmp_path):
    p = tmp_path / "w.sqlite"
    db = sqlite3.connect(p)
    db.execute("CREATE TABLE worms_taxa (aphia_id INTEGER PRIMARY KEY, status TEXT, valid_name TEXT, "
               "valid_aphia_id INTEGER, rank TEXT)")
    db.executemany("INSERT INTO worms_taxa VALUES (?,?,?,?,?)", [
        (1, "accepted", "Aphrodita aculeata", 1, "Species"),
        (2, "accepted", "Aphrodita alta", 2, "Species"),
        (3, "accepted", "Aphrodita alba", 3, "Species"),
        (4, "accepted", "Aphrodita", 9, "Genus"),
        (5, "accepted", "Acinetidae", 5, "Family"),
    ])
    db.commit()
    db.close()
    return namefix.Worms(p)


def test_exact(worms):
    r = namefix.fix_text("Aphrodita aculeata Linnaeus, 1758", worms)
    assert r == [{"ocr": "Aphrodita aculeata", "worms": "Aphrodita aculeata", "aphia_id": 1, "status": "exact"}]


def test_ocr_misread_fixed(worms):
    r = namefix.fix_text("Aphrodita aculeta Linnaeus, 1758", worms)
    assert r[0]["worms"] == "Aphrodita aculeata" and r[0]["status"] == "fuzzy"


def test_ambiguous_left_alone(worms):
    # alta 与 alba 离 alsa 都是 1，不猜
    r = namefix.fix_text("Aphrodita alsa Linnaeus, 1758", worms)
    assert r[0]["status"] == "unresolved" and r[0]["worms"] is None


def test_unknown_with_author_is_unresolved(worms):
    r = namefix.fix_text("Aphrodita daiyumaruae Imajima, 2005", worms)
    assert r[0]["status"] == "unresolved"


def test_plain_english_not_recorded(worms):
    assert namefix.fix_text("Zoological journal from Japan", worms) == []


def test_family_not_matched_to_other_family(worms):
    r = namefix.fix_text("Acoetidae", worms)
    assert r == []


def test_set_extra_keeps_text(tmp_path):
    from docstore.store import Store, make_version

    st = Store(tmp_path)
    st.put_version("K", 1, make_version("abc", "ocr", producer="t"))
    st.set_extra("K", 1, "names", [{"ocr": "x"}])
    pg = json.loads(st.page_path("K", 1).read_text(encoding="utf-8"))
    assert pg["text"] == "abc" and pg["extra"]["names"] == [{"ocr": "x"}]
