from booklayout.blockid import check_coverage, fingerprint_table, remap


def _d(texts, page=4, sp=None):
    return {"pages": [{"page": page, "blocks": [
        {"block_id": f"p{page:03d}_{i:02d}", "text": t, **({"source_page": sp} if sp else {})}
        for i, t in enumerate(texts)]}]}


def test_remap_after_header_insert():
    d = _d(["a", "b", "c"])
    tab = fingerprint_table(d)
    d2 = _d(["HDR", "a", "b", "c"])
    r = remap(tab, d2)
    assert r["map"] == {"p004_00": "p004_01", "p004_01": "p004_02", "p004_02": "p004_03"}
    assert not r["ambiguous"] and not r["orphans"]


def test_duplicate_titles_disambiguated_by_neighbours():
    d = _d(["Intro", "Key", "x", "Key", "y"])
    tab = fingerprint_table(d)
    d2 = _d(["HDR", "Intro", "Key", "x", "Key", "y"])
    r = remap(tab, d2)
    assert r["map"]["p004_01"] == "p004_02" and r["map"]["p004_03"] == "p004_04"


def test_identical_blocks_stay_ambiguous_not_guessed():
    tab = fingerprint_table(_d(["Key", "Key"]))
    r = remap(tab, _d(["Key", "Key", "Key"]))
    assert r["map"] == {} and r["ambiguous"]
    assert len(set(r["map"].values())) == len(r["map"])


def test_changed_text_is_orphan():
    r = remap(fingerprint_table(_d(["a"])), _d(["a2"]))
    assert r["orphans"] == ["p004_00"] and not r["map"]


def test_coverage_skipped_page_registered():
    d = {"pages": [{"page": n, "blocks": [{"block_id": f"p{n}_0", "text": "t"}]} for n in (1, 2, 4)]}
    bad = check_coverage(d, [1, 2, 3, 4])
    assert bad["missing"] == [3] and not bad["ok"]
    good = check_coverage(d, [1, 2, 3, 4], skipped={3: "references continuation"}, pages_only=True)
    assert good["ok"]


def test_coverage_source_page_mismatch_needs_justification():
    d = _d(["a"], page=6, sp=5)
    assert check_coverage(d, [6])["source_page_mismatch"] == [6]
    assert check_coverage(d, [6], source_page_ok={("p006_00", 5, 6): "key continuation"}, pages_only=True)["ok"]


def test_coverage_dup_and_empty():
    d = {"pages": [{"page": 1, "blocks": []}, {"page": 2, "blocks": [{"block_id": "x"}, {"block_id": "x"}]}]}
    r = check_coverage(d, [1, 2])
    assert r["empty"] == [1] and r["duplicate_ids"] == ["x"]


def test_remap_order_independent():
    d = _d(["Key", "x", "Key", "y"])
    tab = fingerprint_table(d)
    d2 = _d(["HDR", "Key", "x", "Key", "y"])
    a, b = remap(tab, d2), remap(list(reversed(tab)), d2)
    qa, qb = a.pop("queue"), b.pop("queue")
    assert a == b
    strip = lambda q: sorted((e["raw_id"], e["status"], tuple(e["candidates"])) for e in q)  # noqa: E731
    assert strip(qa) == strip(qb)


def test_cross_page_move_not_silently_mapped():
    old = fingerprint_table(_d(["a"], page=4))
    r = remap(old, _d(["a"], page=9))
    assert not r["map"] and "p004_00" in r["ambiguous"]


def test_coverage_expected_blocks_detects_loss_and_order():
    from booklayout.normalize import block_src_hash
    d = _d(["a", "b", "c"])
    exp = [(4, block_src_hash(b)) for b in d["pages"][0]["blocks"]]
    assert check_coverage(d, [4], expected_blocks=exp)["ok"]
    d["pages"][0]["blocks"].pop(1)
    assert check_coverage(d, [4], expected_blocks=exp)["block_gaps"]["lost"]
    d2 = _d(["c", "b", "a"])
    assert check_coverage(d2, [4], expected_blocks=exp)["block_gaps"]["out_of_order"]


def test_coverage_blank_reason_empty_block_dup_page():
    d = {"pages": [{"page": 1, "blocks": [{"block_id": "a"}]}, {"page": 1, "blocks": []}]}
    r = check_coverage(d, [1, 2], skipped={2: "  "})
    assert r["blank_reasons"] == [2] and r["duplicate_pages"] == [1] and r["textless_blocks"] == ["a"]
    assert not r["ok"]


def test_duplicate_group_size_change_not_mapped():
    old = fingerprint_table(_d(["K", "K"]))
    r = remap(old, _d(["K", "K", "K"]))
    assert r["map"] == {}
    assert set(r["ambiguous"]) == {"p004_00", "p004_01"}


def test_duplicate_old_ids_ambiguous():
    old = fingerprint_table(_d(["a", "b"]))
    old[1]["block_id"] = old[0]["block_id"]
    r = remap(old, _d(["a", "b"]))
    assert r["map"] == {} and old[0]["block_id"] in r["ambiguous"]


def test_none_source_page_normalised_to_page():
    d = _d(["a"])
    d["pages"][0]["blocks"][0]["source_page"] = None
    assert fingerprint_table(d)[0]["source_page"] == 4
    assert remap(fingerprint_table(_d(["a"])), d)["map"] == {"p004_00": "p004_00"}


def test_coverage_expected_multiset_counts_duplicates():
    d = _d(["K", "K"])
    exp = [(4, h) for h in [r["hash"] for r in fingerprint_table(d)]] + [(4, fingerprint_table(d)[0]["hash"])]
    r = check_coverage(d, [4], expected_blocks=exp)
    assert not r["ok"] and len(r["block_gaps"]["lost"]) == 1


def test_coverage_skipped_page_not_reported_empty():
    d = {"pages": [{"page": 7, "blocks": []}]}
    r = check_coverage(d, [7], skipped={7: "refs"})
    assert 7 not in r["empty"]


def test_coverage_not_ok_without_expected_blocks():
    d = _d(["a"], page=1, sp=1)
    r = check_coverage(d, [1])
    assert not r["ok"] and r["block_level_checked"] is False
    assert check_coverage(d, [1], pages_only=True)["ok"]


def test_coverage_invalid_block_ids():
    d = {"pages": [{"page": 1, "blocks": [{"block_id": "", "text": "a"}, {"block_id": 5, "text": "b"}]}]}
    r = check_coverage(d, [1], pages_only=True)
    assert r["invalid_ids"] == ["", 5] and not r["ok"]


def test_coverage_skip_excluded_by_source_page_both_sides():
    # logical page 6 holds blocks whose source is skipped page 7
    d = {"pages": [{"page": 6, "blocks": [
        {"block_id": "a", "text": "x", "source_page": 6},
        {"block_id": "b", "text": "y", "source_page": 7}]}]}
    from booklayout.normalize import block_src_hash as h
    exp = [(6, h({"text": "x"})), (7, h({"text": "y"}))]
    r = check_coverage(d, [6], skipped={7: "refs"}, source_page_ok={("b", 7, 6): "spill"}, expected_blocks=exp)
    # excluded block must NOT be in output: expected side drops it, got side keeps it -> extra + error
    assert r["block_gaps"]["extra"] == [(7, h({"text": "y"}))]
    assert r["excluded_present"] == [7] and not r["ok"]


def test_remap_rejects_duplicate_or_invalid_new_ids():
    old = fingerprint_table(_d(["a", "b"], page=4, sp=4))
    new = {"pages": [{"page": 4, "blocks": [
        {"block_id": "n1", "text": "a", "source_page": 4},
        {"block_id": "n1", "text": "b", "source_page": 4}]}]}
    r = remap(old, new)
    assert r["map"] == {} and r["invalid_new_ids"] == ["n1"]


def test_remap_unaddressable_candidate_blocks_auto_confirm():
    old = fingerprint_table({"pages": [{"page": 4, "blocks": [
        {"block_id": "o1", "text": "dup", "source_page": 4}]}]})
    # one old, two new same-text; one new id invalid -> must not confirm the valid one
    new = {"pages": [{"page": 4, "blocks": [
        {"block_id": "", "text": "dup", "source_page": 4},
        {"block_id": "n2", "text": "dup", "source_page": 4}]}]}
    r = remap(old, new)
    assert r["map"] == {} and "o1" in r["ambiguous"]


def test_remap_int_and_str_ids_do_not_merge():
    old = [{"block_id": 1, "hash": "h1", "source_page": 1, "prev": "", "next": ""},
           {"block_id": "1", "hash": "h2", "source_page": 1, "prev": "", "next": ""}]
    r = remap(old, {"pages": []})
    assert r["orphans"] == ["#0:1", "1"]  # invalid old id is keyed by row, never merges with "1"
    assert remap([old[0]], {"pages": [{"page": 1, "blocks": [{"block_id": "1", "text": "z"}]}]})["map"] == {}
    r2 = remap([{"block_id": ["x"], "hash": "h", "source_page": 1, "prev": "", "next": ""}], {"pages": []})
    assert r2["orphans"] == ["#0:['x']"]


def test_cross_page_permission_bound_to_block():
    d = {"pages": [{"page": 6, "blocks": [
        {"block_id": "a", "text": "x", "source_page": 5},
        {"block_id": "b", "text": "y", "source_page": 5}]}]}
    ok = {("a", 5, 6): "continuation"}
    assert check_coverage(d, [6], source_page_ok=ok, pages_only=True)["source_page_mismatch"] == [6]
    both = {("a", 5, 6): "c", ("b", 5, 6): "c"}
    assert check_coverage(d, [6], source_page_ok=both, pages_only=True)["ok"]


def test_null_source_page_normalised_everywhere():
    d = {"pages": [{"page": 3, "blocks": [{"block_id": "a", "text": "x", "source_page": None}]}]}
    assert fingerprint_table(d)[0]["source_page"] == 3
    assert check_coverage(d, [3], pages_only=True)["ok"]


def test_check_coverage_unhashable_ids_and_source_page_no_crash():
    from booklayout.blockid import check_coverage
    d = {"pages": [{"page": 1, "blocks": [
        {"block_id": ["x"], "role": "paragraph", "text": "a", "source_page": [2]},
        {"block_id": {"k": 1}, "role": "paragraph", "text": "b"}]}]}
    r = check_coverage(d, [1], pages_only=True)
    assert r["ok"] is False and r["invalid_ids"]


def test_remap_queue_is_per_row_and_order_independent():
    from booklayout.blockid import fingerprint_table, remap
    d = {"pages": [{"page": 1, "blocks": [
        {"block_id": "a", "role": "paragraph", "text": "same"},
        {"block_id": "b", "role": "paragraph", "text": "same"}]}]}
    old = fingerprint_table(d)
    old[0]["block_id"] = 1       # invalid ids on two rows, must not collide
    old[1]["block_id"] = "1"
    old.append({**old[1], "block_id": ["1"], "hash": "zz"})
    q1 = remap(old, d)["queue"]
    q2 = remap(list(reversed(old)), d)["queue"]
    assert len({e["row"] for e in q1}) == len(q1)
    ids1 = sorted((e["raw_id"], e["status"]) for e in q1)
    ids2 = sorted((e["raw_id"], e["status"]) for e in q2)
    assert ids1 == ids2 and len(q1) >= 2


def test_round9_queue_candidates_per_row_not_per_id():
    from booklayout.normalize import block_src_hash
    new = {"pages": [{"page": 1, "blocks": [{"block_id": "a", "text": "A"}, {"block_id": "b", "text": "B"}]}]}
    old = [{"block_id": "dup", "hash": block_src_hash({"text": "A"}), "page": 1, "index": 0, "source_page": 1,
            "prev": "", "next": ""},
           {"block_id": "dup", "hash": block_src_hash({"text": "B"}), "page": 1, "index": 1, "source_page": 1,
            "prev": "", "next": ""}]
    for rows in (old, old[::-1]):
        q = remap(rows, new)["queue"]
        got = {x["row"]: x["candidates"] for x in q}
        for n, o in enumerate(rows):
            assert got[n] == [("a" if o["hash"] == block_src_hash({"text": "A"}) else "b")]


def test_round9_coverage_with_expected_blocks_unhashable_source_page_no_crash():
    from booklayout.normalize import block_src_hash
    d = {"pages": [{"page": 1, "blocks": [{"block_id": "a", "text": "A", "source_page": [1]}]}]}
    r = check_coverage(d, [1], expected_blocks=[(1, block_src_hash({"text": "A"}))])
    assert r["ok"] is False and r["block_gaps"]["bad_source_page"] == ["a"]


def test_round9_numeric_string_source_page_equals_int():
    from booklayout.normalize import block_src_hash
    d = {"pages": [{"page": 1, "blocks": [{"block_id": "a", "text": "A", "source_page": "1"}]}]}
    r = check_coverage(d, [1], expected_blocks=[(1, block_src_hash({"text": "A"}))])
    assert r["ok"] is True


def test_round10_bool_source_page_not_page_one():
    from booklayout.blockid import check_coverage
    from booklayout.normalize import block_src_hash
    b = {"block_id": "a", "role": "body", "text": "A", "source_page": True}
    d = {"pages": [{"page": 1, "blocks": [b]}]}
    r = check_coverage(d, [1], expected_blocks=[(1, block_src_hash(b))])
    assert not r["ok"]


def test_round10_remap_mixed_orphan_and_ambiguous_keeps_candidates():
    from booklayout.blockid import fingerprint_table, remap
    d = {"pages": [{"page": 1, "blocks": [{"block_id": "a", "role": "body", "text": "A"}]}]}
    row = {**fingerprint_table(d)[0], "block_id": "dup"}
    for old in ([row, {**row, "hash": "missing"}], [{**row, "hash": "missing"}, row]):
        q = remap(old, d)["queue"]
        by_status = {x["status"]: x["candidates"] for x in q}
        assert by_status["ambiguous"] == ["a"] and by_status["orphan"] == []
