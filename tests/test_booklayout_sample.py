from booklayout import sample


def test_parse_range():
    assert sample.parse_range("78-85") == (78, 85)
    assert sample.parse_range("7") == (7, 7)
    for bad in ("0-3", "9-3"):
        try:
            sample.parse_range(bad)
        except ValueError:
            continue
        raise AssertionError(bad)


def test_meta_body_start():
    m = sample.make_meta("T", 78)
    assert m["body_start_page"] == 78 and m["include_contents"] is False


def test_summary_three_parts():
    rep = {"blocks": 3, "chars": 10, "google_requests": 1, "cache_hits": 2, "glossary_applied": 4}
    mk = {"ok": False, "problems": ["qa not ok: ['5 content blocks have no translation']"], "files": {"pdf": "/x.pdf"}}
    s = sample.summarize(rep, mk, 12.0)
    assert s[0].startswith("translate: 3 blocks") and "FAIL" in s[1] and "1 about untranslated" in s[1] and "/x.pdf" in s[2]
