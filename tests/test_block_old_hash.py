import json as _j

import pytest as _pt

from booklayout.cli import main as _cli_main
from booklayout.normalize import apply_block_edits, block_src_hash, block_struct_digest


def _data():
    return {"pages": [{"page": 4, "blocks": [
        {"block_id": "p004_01", "role": "body", "text": "alpha", "translation": "甲"},
        {"block_id": "p004_02", "role": "body", "text": "beta", "translation": "乙"}]}]}


def test_matching_hash_applies():
    d = _data()
    h = block_src_hash(d["pages"][0]["blocks"][0])
    r = apply_block_edits(d, {"edits": [{"block_id": "p004_01", "old_hash": h, "translation": "丙"}]})
    assert r["applied"] == ["p004_01"] and r["stale"] == []
    assert d["pages"][0]["blocks"][0]["translation"] == "丙"


def test_resplit_id_drift_is_rejected():
    d = _data()
    h = block_src_hash(d["pages"][0]["blocks"][0])  # patch written against "alpha"
    d["pages"][0]["blocks"].insert(0, {"block_id": "p004_00", "text": "HEADER", "translation": "页眉"})
    d["pages"][0]["blocks"][1]["block_id"] = "p004_01"  # positional renumber: id now -> HEADER
    d["pages"][0]["blocks"][0]["block_id"] = "p004_01"
    d["pages"][0]["blocks"][1]["block_id"] = "p004_02"
    d["pages"][0]["blocks"][2]["block_id"] = "p004_03"
    r = apply_block_edits(d, {"edits": [{"block_id": "p004_01", "old_hash": h, "translation": "X"}]})
    assert r["stale"] == ["p004_01"] and r["applied"] == []
    assert d["pages"][0]["blocks"][0]["translation"] == "页眉"


def test_legacy_patch_without_hash_unchanged():
    d = _data()
    r = apply_block_edits(d, {"edits": [{"block_id": "p004_02", "translation": "丁"}]})
    assert r["applied"] == ["p004_02"] and d["pages"][0]["blocks"][1]["translation"] == "丁"


def test_translation_only_block_cannot_be_locked():
    d = {"pages": [{"page": 1, "blocks": [{"block_id": "b", "translation": "x"}]}]}
    r = apply_block_edits(d, {"edits": [{"block_id": "b", "old_hash": block_src_hash(d["pages"][0]["blocks"][0]),
                                         "translation": "y"}]})
    assert r["stale"] == ["b"] and d["pages"][0]["blocks"][0]["translation"] == "x"


def test_translation_edit_does_not_stale_later_patches():
    d = _data()
    h = block_src_hash(d["pages"][0]["blocks"][0])
    apply_block_edits(d, {"edits": [{"block_id": "p004_01", "old_hash": h, "translation": "丙"}]})
    r = apply_block_edits(d, {"edits": [{"block_id": "p004_01", "old_hash": h, "translation": "丁"}]})
    assert r["applied"] == ["p004_01"]


def test_remove_locked_and_version2_requires_hash():
    d = _data()
    h = block_src_hash(d["pages"][0]["blocks"][0])
    r = apply_block_edits(d, {"edits": [{"block_id": "p004_01", "old_hash": "bad", "remove": True}]})
    assert r["stale"] == ["p004_01"] and len(d["pages"][0]["blocks"]) == 2
    r = apply_block_edits(d, {"version": 2, "edits": [
        {"block_id": "p004_02", "page": 4, "old_translation": "乙", "translation": "z",
         "old_prev": "", "old_next": ""}]})
    assert len(r["invalid"]) == 1 and "old_hash" in r["invalid"][0] and not r["stale"]  # missing old_hash is a format error
    r = apply_block_edits(d, {"edits": [{"block_id": "p004_01", "old_hash": h, "remove": True}]})
    assert r["removed"] == ["p004_01"] and len(d["pages"][0]["blocks"]) == 1


def test_edit_after_remove_in_same_patch_is_missing():
    d = _data()
    r = apply_block_edits(d, {"edits": [{"block_id": "p004_01", "remove": True},
                                        {"block_id": "p004_01", "translation": "z"}]})
    assert r["applied"] == ["p004_01"] and r["missing"] == ["p004_01"]


# ---- CLI patch-blocks guards ----
import json as _json  # noqa: E402

from booklayout.cli import main as _main  # noqa: E402
from booklayout.normalize import block_src_hash as _h  # noqa: E402


def _setup(tmp_path, version=2, edits=None):
    blk = {"block_id": "b0", "role": "body", "text": "Src", "translation": "Old"}
    a = tmp_path / "a.json"
    a.write_text(_json.dumps({"pages": [{"page": 1, "blocks": [blk]}]}), encoding="utf-8")
    p = tmp_path / "p.json"
    p.write_text(_json.dumps({"version": version, "edits": edits or [
        {"block_id": "b0", "page": 1, "old_hash": _h(blk), "old_translation": "Old", "translation": "New",
         "old_prev": "", "old_next": ""},
        {"block_id": "gone", "page": 1, "old_hash": "x", "old_translation": "", "translation": "Z",
         "old_prev": "", "old_next": ""}]}), encoding="utf-8")
    return a, p


def test_cli_v2_missing_rejects_whole_patch(tmp_path):
    a, p = _setup(tmp_path)
    before = a.read_bytes()
    rep = tmp_path / "r.json"
    rc = _main(["patch-blocks", "--aligned", str(a), "--patch", str(p), "--report", str(rep)])
    assert rc == 1 and a.read_bytes() == before
    r = _json.loads(rep.read_text(encoding="utf-8"))
    assert r["applied"] == [] and r["rejected"] is True and r["missing"] == ["gone"]


def test_cli_allow_partial_writes(tmp_path):
    a, p = _setup(tmp_path)
    rc = _main(["patch-blocks", "--aligned", str(a), "--patch", str(p), "--allow-partial"])
    assert rc == 0
    assert _json.loads(a.read_text(encoding="utf-8"))["pages"][0]["blocks"][0]["translation"] == "New"


def test_cli_report_path_guard(tmp_path):
    a, p = _setup(tmp_path)
    before = a.read_bytes()
    rc = _main(["patch-blocks", "--aligned", str(a), "--patch", str(p), "--report", str(a)])
    assert rc == 2 and a.read_bytes() == before


def test_double_remove_second_is_missing():
    d = {"pages": [{"page": 1, "blocks": [{"block_id": "b", "text": "t", "translation": "x"}]}]}
    from booklayout.normalize import apply_block_edits
    rep = apply_block_edits(d, {"version": 1, "edits": [{"block_id": "b", "remove": True},
                                                        {"block_id": "b", "remove": True}]})
    assert rep["removed"] == ["b"] and rep["missing"] == ["b"]






def _hi(d, i):
    return block_src_hash(d["pages"][0]["blocks"][i])


def _nb(d, i):
    """old_prev / old_next of block i in global book order (strict v2 requires them)."""
    bl = [b for p in d["pages"] for b in p["blocks"]]
    return {"old_prev": block_src_hash(bl[i - 1]) if i else "",
            "old_next": block_src_hash(bl[i + 1]) if i + 1 < len(bl) else ""}


@_pt.mark.parametrize("bad", [
    {"block_id": "", "translation": "x"},
    {"block_id": None, "translation": "x"},
    {"block_id": 5, "translation": "x"},
    {"block_id": "p004_01", "remove": "false"},
    {"block_id": "p004_01", "remove": 1},
    {"block_id": "p004_01", "translations": "typo"},
    {"block_id": "p004_01"},
    {"block_id": "p004_01", "remove": True, "translation": "x"},
    {"block_id": "p004_01", "translation": 3},
    "not-an-object",
])
def test_invalid_edit_is_not_applied(bad):
    d = _data()
    before = _j.dumps(d)
    r = apply_block_edits(d, {"edits": [bad]})
    assert r["invalid"] and r["applied"] == [] and _j.dumps(d) == before


def test_v2_batch_is_all_or_nothing_in_memory():
    d = _data()
    before = _j.dumps(d)
    r = apply_block_edits(d, {"version": 2, "edits": [
        {"block_id": "p004_01", "page": 4, "old_hash": _hi(d, 0), "old_translation": "甲",
         "translation": "X", **_nb(d, 0)},
        {"block_id": "p004_02", "page": 4, "old_hash": "0" * 32, "old_translation": "乙",
         "translation": "Y", **_nb(d, 1)}]})
    assert r["stale"] == ["p004_02"] and r["applied"] == [] and _j.dumps(d) == before


def test_v2_allow_partial_applies_good_edits():
    d = _data()
    r = apply_block_edits(d, {"version": 2, "edits": [
        {"block_id": "p004_01", "page": 4, "old_hash": _hi(d, 0), "old_translation": "甲",
         "translation": "X", **_nb(d, 0)},
        {"block_id": "p004_02", "page": 4, "old_hash": "0" * 32, "old_translation": "乙",
         "translation": "Y", **_nb(d, 1)}]}, allow_partial=True)
    assert r["applied"] == ["p004_01"] and d["pages"][0]["blocks"][0]["translation"] == "X"


def test_old_translation_precondition():
    d = _data()
    r = apply_block_edits(d, {"edits": [{"block_id": "p004_01", "old_translation": "wrong", "translation": "X"}]})
    assert r["stale"] == ["p004_01"] and d["pages"][0]["blocks"][0]["translation"] == "甲"
    r = apply_block_edits(d, {"edits": [{"block_id": "p004_01", "old_translation": "甲", "translation": "X"}]})
    assert r["applied"] == ["p004_01"]


def test_duplicate_block_ids_rejected():
    d = _data()
    d["pages"][0]["blocks"][1]["block_id"] = "p004_01"
    with _pt.raises(ValueError):
        apply_block_edits(d, {"edits": [{"block_id": "p004_01", "translation": "X"}]})


def test_cli_out_equals_patch_rejected(tmp_path):
    a = tmp_path / "a.json"
    p = tmp_path / "p.json"
    a.write_text(_j.dumps(_data()), encoding="utf-8")
    p.write_text(_j.dumps({"edits": [{"block_id": "p004_01", "translation": "X"}]}), encoding="utf-8")
    pre = p.read_text(encoding="utf-8")
    assert _cli_main(["patch-blocks", "--aligned", str(a), "--patch", str(p), "--out", str(p)]) == 2
    assert p.read_text(encoding="utf-8") == pre


def test_cli_invalid_edit_rejects_without_write(tmp_path):
    a = tmp_path / "a.json"
    p = tmp_path / "p.json"
    a.write_text(_j.dumps(_data()), encoding="utf-8")
    p.write_text(_j.dumps({"edits": [{"block_id": "p004_01", "translations": "typo"}]}), encoding="utf-8")
    pre = a.read_text(encoding="utf-8")
    assert _cli_main(["patch-blocks", "--aligned", str(a), "--patch", str(p)]) == 1
    assert a.read_text(encoding="utf-8") == pre


def test_write_json_keeps_symlink_and_leaves_no_tmp(tmp_path):
    from booklayout.cli import _write_json
    real = tmp_path / "real.json"
    real.write_text("{}", encoding="utf-8")
    link = tmp_path / "link.json"
    link.symlink_to(real)
    _write_json(link, {"k": 1})
    assert link.is_symlink() and _j.loads(real.read_text(encoding="utf-8")) == {"k": 1}
    assert [x.name for x in tmp_path.iterdir() if x.name.endswith(".tmp")] == []


# ---- round 6: strict protocol ----
import pytest  # noqa: E402


def _v2(d, i, **kw):
    b = d["pages"][0]["blocks"][i]
    e = {"block_id": b["block_id"], "page": 4, "old_hash": _hi(d, i), **_nb(d, i)}
    if kw.get("remove"):
        e["old_struct"] = block_struct_digest(b)
    return {**e, **kw}


@pytest.mark.parametrize("patch", [
    {"version": False, "edits": []}, {"version": 3, "edits": []}, {"version": "2", "edits": []},
    {"edit": []}, {"edits": {}}, [], {"version": 2}])
def test_malformed_top_level_raises(patch):
    with pytest.raises(ValueError):
        apply_block_edits(_data(), patch)


def test_level_must_be_positive_int_and_role_known():
    d = _data()
    for bad in ({"level": "1"}, {"level": True}, {"level": 0}, {"role": "boby"}, {"role": 1}):
        r = apply_block_edits(d, {"edits": [{"block_id": "p004_01", **bad}]})
        assert r["invalid"] and not r["applied"], bad
    r = apply_block_edits(d, {"edits": [{"block_id": "p004_01", "level": 1, "role": "heading"}]})
    assert r["applied"] == ["p004_01"] and d["pages"][0]["blocks"][0]["level"] == 1


def test_v2_requires_old_values_and_page():
    d = _data()
    r = apply_block_edits(d, {"version": 2, "edits": [_v2(d, 0, translation="X")]})
    assert "old_translation" in r["invalid"][0]
    r = apply_block_edits(d, {"version": 2, "edits": [_v2(d, 0, role="heading")]})
    assert "old_role" in r["invalid"][0]
    r = apply_block_edits(d, {"version": 2, "edits": [_v2(d, 0, remove=True, old_translation="甲", old_level=None)]})
    assert "old_role" in r["invalid"][0]
    e = _v2(d, 0, translation="X", old_translation="甲")
    del e["page"]
    assert "page" in apply_block_edits(d, {"version": 2, "edits": [e]})["invalid"][0]


def test_v2_wrong_page_or_old_role_is_stale():
    d = _data()
    e = _v2(d, 0, translation="X", old_translation="甲")
    e["page"] = 5
    assert apply_block_edits(d, {"version": 2, "edits": [e]})["stale"] == ["p004_01"]
    r = apply_block_edits(d, {"version": 2, "edits": [_v2(d, 0, remove=True, old_translation="甲",
                                                          old_role="entry", old_level=None)]})
    assert r["stale"] == ["p004_01"] and len(d["pages"][0]["blocks"]) == 2


def test_cli_reject_reports_exact_ids_and_keeps_mode(tmp_path):
    import os
    a, p = _setup(tmp_path)
    os.chmod(a, 0o644)
    rep = tmp_path / "r.json"
    assert _main(["patch-blocks", "--aligned", str(a), "--patch", str(p), "--report", str(rep)]) == 1
    r = _json.loads(rep.read_text(encoding="utf-8"))
    assert r["not_written"] == ["b0"] and r["applied"] == []
    assert _main(["patch-blocks", "--aligned", str(a), "--patch", str(p), "--allow-partial"]) == 0
    assert os.stat(a).st_mode & 0o777 == 0o644


def test_cli_concurrent_writers_keep_both_edits(tmp_path):
    import subprocess
    import sys
    blks = [{"block_id": f"b{i}", "role": "body", "text": f"s{i}", "translation": "o"} for i in range(2)]
    a = tmp_path / "a.json"
    a.write_text(_json.dumps({"pages": [{"page": 1, "blocks": blks}]}), encoding="utf-8")
    procs = []
    for i in range(2):
        pp = tmp_path / f"p{i}.json"
        pp.write_text(_json.dumps({"version": 2, "edits": [
            {"block_id": f"b{i}", "page": 1, "old_hash": _h(blks[i]), "old_translation": "o",
             "translation": f"n{i}",
             "old_prev": _h(blks[i - 1]) if i else "", "old_next": _h(blks[i + 1]) if i + 1 < 2 else ""}]}), encoding="utf-8")
        procs.append(subprocess.Popen([sys.executable, "-m", "booklayout", "patch-blocks", "--aligned", str(a),
                                       "--patch", str(pp)], stdout=subprocess.DEVNULL))
    assert [x.wait() for x in procs] == [0, 0]
    got = [b["translation"] for b in _json.loads(a.read_text(encoding="utf-8"))["pages"][0]["blocks"]]
    assert got == ["n0", "n1"]


def test_neighbour_hash_rejects_same_text_block_after_resplit():
    d = {"pages": [{"page": 4, "blocks": [
        {"block_id": "a", "role": "body", "text": "X", "translation": "t"},
        {"block_id": "b", "role": "body", "text": "same", "translation": "t"},
        {"block_id": "c", "role": "body", "text": "Y", "translation": "t"}]}]}
    blk = d["pages"][0]["blocks"]
    h = block_src_hash(blk[1])
    edit = {"block_id": "b", "old_hash": h, "page": 4, "old_translation": "t", "translation": "n",
            "old_prev": block_src_hash(blk[0]), "old_next": block_src_hash(blk[2])}
    ok = _j.loads(_j.dumps(d))
    assert apply_block_edits(ok, {"version": 2, "edits": [edit]})["applied"] == ["b"]
    moved = _j.loads(_j.dumps(d))
    moved["pages"][0]["blocks"][0]["text"] = "Z"  # neighbour changed: same-text block is elsewhere
    r = apply_block_edits(moved, {"version": 2, "edits": [edit]})
    assert r["stale"] == ["b"] and r["applied"] == []
    bad = dict(edit, old_prev=5)
    r = apply_block_edits(_j.loads(_j.dumps(d)), {"version": 2, "edits": [bad]})
    assert r["invalid"] and r["applied"] == []


# ---- round 7 ----
@_pt.mark.parametrize("patch", [
    {"verison": 2, "edits": []}, {"version": 1.0, "edits": []}, {"version": True, "edits": []}])
def test_round7_top_level_typo_and_version_type(patch):
    with _pt.raises(ValueError):
        apply_block_edits(_data(), patch)


def test_round7_old_level_bool_invalid_and_stale_remove():
    d = _data()
    r = apply_block_edits(d, {"version": 2, "edits": [
        _v2(d, 0, remove=True, old_translation="甲", old_role="body", old_level=True)]})
    assert r["invalid"] and len(d["pages"][0]["blocks"]) == 2
    e = _v2(d, 0, remove=True, old_translation="甲", old_role="body", old_level=None)
    d["pages"][0]["blocks"][0]["level"] = 2  # level changed since the patch was written
    r = apply_block_edits(d, {"version": 2, "edits": [e]})
    assert r["stale"] == ["p004_01"] and len(d["pages"][0]["blocks"]) == 2


def test_round7_role_transition_needs_structure():
    d = _data()
    r = apply_block_edits(d, {"edits": [{"block_id": "p004_01", "role": "table"}]})
    assert r["invalid"] and not r["applied"]
    r = apply_block_edits(d, {"edits": [{"block_id": "p004_01", "role": "list"}]})
    assert r["invalid"] and not r["applied"]
    d["pages"][0]["blocks"][0]["rows"] = [["a"]]
    r = apply_block_edits(d, {"edits": [{"block_id": "p004_01", "role": "table"}]})
    assert r["applied"] == ["p004_01"]


def test_round7_unhashable_ids_give_structured_results():
    from booklayout.blockid import check_coverage, remap
    d = {"pages": [{"page": 1, "blocks": [{"block_id": ["x"], "text": "a"}, {"block_id": {"k": 1}, "text": "b"},
                                          {"block_id": ["x"], "text": "c"}]}]}
    r = apply_block_edits(d, {"edits": [{"block_id": "p", "translation": "z"}]})
    assert r["missing"] == ["p"]
    assert not check_coverage(d, [1], pages_only=True)["ok"]
    assert remap([], d)["invalid_new_ids"]


def test_round7_neighbours_are_global_book_order():
    from booklayout.blockid import fingerprint_table
    d = {"pages": [{"page": 1, "blocks": [{"block_id": "a", "text": "A"}]},
                   {"page": 2, "blocks": [{"block_id": "b", "text": "B"}, {"block_id": "c", "text": "C"}]}]}
    fp = {r["block_id"]: r for r in fingerprint_table(d)}
    from booklayout.normalize import block_neighbours
    nb = block_neighbours(d)
    for k in "abc":
        assert nb[k] == (fp[k]["prev"], fp[k]["next"])


def test_round7_lock_symlink_alias_and_mode(tmp_path):
    import os
    from booklayout.cli import _lock_file
    real = tmp_path / "a.json"
    real.write_text("{}", encoding="utf-8")
    link = tmp_path / "l.json"
    link.symlink_to(real)
    fd1, fd2 = _lock_file(real), _lock_file(link)
    try:
        assert os.fstat(fd1).st_ino == os.fstat(fd2).st_ino  # alias -> same lock file
        assert os.fstat(fd1).st_mode & 0o666 == 0o666  # openable by other users whatever the umask
    finally:
        os.close(fd1)
        os.close(fd2)
    other = tmp_path / "a.json.lock"
    other.write_text("keep", encoding="utf-8")
    os.close(_lock_file(real))
    assert other.read_text(encoding="utf-8") == "keep"  # lock file never collides with sibling names


def _tbl():
    return {"pages": [{"page": 4, "blocks": [
        {"block_id": "p004_01", "role": "table", "text": "t", "translation": "表", "rows": [["a", "b"]]},
        {"block_id": "p004_02", "role": "body", "text": "beta", "translation": "乙"}]}]}


def test_v2_delete_after_cell_edit_is_stale():
    d = _tbl()
    e = _v2(d, 0, remove=True, old_translation="表", old_role="table", old_level=None)
    d["pages"][0]["blocks"][0]["rows"][0][0] = "A"  # a cell changed after the patch was written
    r = apply_block_edits(d, {"version": 2, "edits": [e]})
    assert r["stale"] == ["p004_01"] and len(d["pages"][0]["blocks"]) == 2


def test_v2_delete_requires_old_struct():
    d = _tbl()
    e = _v2(d, 0, remove=True, old_translation="表", old_role="table", old_level=None)
    del e["old_struct"]
    r = apply_block_edits(d, {"version": 2, "edits": [e]})
    assert "old_struct" in r["invalid"][0] and len(d["pages"][0]["blocks"]) == 2


def test_v2_missing_old_hash_is_invalid_not_stale():
    d = _data()
    e = _v2(d, 0, translation="X", old_translation="甲")
    del e["old_hash"]
    r = apply_block_edits(d, {"version": 2, "edits": [e]})
    assert "old_hash" in r["invalid"][0] and not r["stale"]


def test_neighbour_sentinel_book_start_vs_textless_neighbour():
    from booklayout.normalize import NOHASH, block_neighbours
    d = _data()
    nb = block_neighbours(d)
    assert nb["p004_01"][0] == "" and nb["p004_02"][1] == ""  # book start / end
    d["pages"][0]["blocks"].insert(0, {"block_id": "p004_00", "role": "figure", "text": "", "translation": ""})
    nb = block_neighbours(d)
    assert nb["p004_01"][0] == NOHASH  # a neighbour exists but has no hash: not "book start"
    assert nb["p004_00"][0] == ""


def test_insert_at_book_start_makes_old_prev_empty_stale():
    d = _data()
    e = _v2(d, 0, translation="X", old_translation="甲")  # written when block 0 was first (prev "")
    d["pages"][0]["blocks"].insert(0, {"block_id": "p004_00", "role": "figure", "text": "", "translation": ""})
    r = apply_block_edits(d, {"version": 2, "edits": [e]})
    assert r["stale"] == ["p004_01"]


def test_role_change_to_table_needs_nonempty_rows_and_figure_group_needs_figures():
    d = _data()
    d["pages"][0]["blocks"][0]["rows"] = []
    r = apply_block_edits(d, {"version": 2, "edits": [_v2(d, 0, role="table", old_role="body")]})
    assert r["invalid"] and d["pages"][0]["blocks"][0]["role"] == "body"
    d = _data()
    r = apply_block_edits(d, {"version": 2, "edits": [_v2(d, 0, role="figure_group", old_role="body")]})
    assert r["invalid"] and d["pages"][0]["blocks"][0]["role"] == "body"


@pytest.mark.parametrize("raw", [
    '{"edits": [{"block_id": "p004_01", "translation": "X", "translation": "Y"}]}',
    '{"edits": [], "edits": [{"block_id": "p004_01", "remove": true}]}',
    '{"version": 2, "version": 1, "edits": []}',
])
def test_cli_patch_duplicate_keys_rejected_original_unchanged(tmp_path, raw, capsys):
    a = tmp_path / "a.json"
    p = tmp_path / "p.json"
    rep = tmp_path / "r.json"
    a.write_text(_j.dumps(_data()), encoding="utf-8")
    p.write_text(raw, encoding="utf-8")
    pre = a.read_text(encoding="utf-8")
    rc = _cli_main(["patch-blocks", "--aligned", str(a), "--patch", str(p), "--report", str(rep)])
    assert rc == 2 and a.read_text(encoding="utf-8") == pre and not rep.exists()
    assert "duplicate JSON key" in capsys.readouterr().err


def test_round8_lock_root_fixed_and_business_paths_rejected(tmp_path, monkeypatch):
    import json
    import subprocess
    import sys
    from pathlib import Path
    lockd = tmp_path / "locks"
    monkeypatch.setenv("BOOKLAYOUT_LOCK_DIR", str(lockd))
    monkeypatch.setenv("TMPDIR", str(tmp_path / "other"))
    from booklayout.cli import _lock_dir
    assert _lock_dir() == lockd
    a = tmp_path / "a.json"
    a.write_text(json.dumps({"pages": []}), encoding="utf-8")
    lockd.mkdir()
    bad = lockd / "r.json"
    r = subprocess.run([sys.executable, "-m", "booklayout", "patch-blocks", "--aligned", str(a), "--patch", str(a),
                        "--report", str(bad)], capture_output=True, text=True,
                       cwd=str(Path(__file__).resolve().parents[1]))
    assert r.returncode == 2 and "lock directory" in r.stderr and not bad.exists()


def test_round8_write_json_mode_and_umask_untouched(tmp_path):
    import os
    from pathlib import Path
    from booklayout.cli import _current_umask, _write_json
    old = os.umask(0o027)
    try:
        assert _current_umask() == 0o027
        p = Path(tmp_path / "n.json")
        _write_json(p, {"a": 1})
        assert p.stat().st_mode & 0o777 == 0o640
        assert os.umask(0o027) == 0o027
    finally:
        os.umask(old)


def test_round9_page_patch_validated_before_write(tmp_path):
    import copy
    from booklayout.normalize import apply_page_patch
    d = _data()
    orig = copy.deepcopy(d)
    for bad in ({"pages": {"4": {}}}, {"pages": {"4": [{"role": "body"}]}}, {"pages": {"9": []}},
                {"pages": {"x": []}}, {"pages": []}):
        with _pt.raises(ValueError):
            apply_page_patch(d, bad)
        assert d == orig  # nothing mutated
    apply_page_patch(d, {"pages": {"4": []}})  # explicit [] still clears the page
    assert d["pages"][0]["blocks"] == []


def test_round9_page_patch_source_page_kept_for_existing_int_for_new():
    from booklayout.normalize import apply_page_patch
    d = _data()
    apply_page_patch(d, {"pages": {"4": [{"block_id": "p004_01"}, {"block_id": "p004_99", "role": "body", "text": "N", "translation": "x"}]}})
    b = d["pages"][0]["blocks"]
    assert "source_page" not in b[0] and b[1]["source_page"] == 4


def test_round9_delete_stale_when_couplet_target_changes():
    d = _data()
    blk = d["pages"][0]["blocks"][0]
    blk["couplet"] = {"target": "12", "name": "X"}
    patch = {"version": 2, "edits": [{
        "block_id": "p004_01", "remove": True, "page": 4, "old_hash": block_src_hash(blk),
        "old_prev": "", "old_next": block_src_hash(d["pages"][0]["blocks"][1]),
        "old_translation": "甲", "old_role": "body", "old_level": blk.get("level"),
        "old_struct": block_struct_digest(blk)}]}
    blk["couplet"]["target"] = "13"  # human fixed only the jump target
    r = apply_block_edits(d, patch, allow_partial=True)
    assert r["stale"] == ["p004_01"] and r["removed"] == []


def test_round9_colspan_must_be_positive_int():
    d = {"pages": [{"page": 1, "blocks": [
        {"block_id": "b1", "role": "body", "text": "t", "translation": "x", "rows": [[{"text": "a", "colspan": "x"}]]}]}]}
    r = apply_block_edits(d, {"edits": [{"block_id": "b1", "role": "table"}]})
    assert r["applied"] == [] and r["invalid"] and d["pages"][0]["blocks"][0]["role"] == "body"
    d["pages"][0]["blocks"][0]["rows"] = [[{"text": "a", "colspan": 2}, "b"]]
    r = apply_block_edits(d, {"edits": [{"block_id": "b1", "role": "table"}]})
    assert r["applied"] == ["b1"]


def test_round9_repair_out_equals_patch_rejected(tmp_path, monkeypatch):
    import os
    monkeypatch.setenv("BOOKLAYOUT_LOCK_DIR", str(tmp_path / "locks"))
    a = tmp_path / "a.json"
    a.write_text(_j.dumps(_data()), encoding="utf-8")
    p = tmp_path / "p.json"
    p.write_text(_j.dumps({"pages": {"4": []}}), encoding="utf-8")
    link = tmp_path / "link.json"
    os.symlink(p, link)
    before = p.read_bytes()
    rc = _cli_main(["repair", "--aligned", str(a), "--patch", str(p), "--out", str(link)])
    assert rc == 2 and p.read_bytes() == before


def test_round9_lock_dir_symlink_refused_and_existing_lock_reopened(tmp_path, monkeypatch):
    import os
    from pathlib import Path
    from booklayout.cli import _lock_file
    real = tmp_path / "biz"
    real.mkdir()
    os.chmod(real, 0o755)
    link = tmp_path / "lk"
    os.symlink(real, link)
    monkeypatch.setenv("BOOKLAYOUT_LOCK_DIR", str(link))
    with _pt.raises(OSError):
        _lock_file(Path(tmp_path / "t.json"))
    assert real.stat().st_mode & 0o777 == 0o755  # business dir mode untouched
    monkeypatch.setenv("BOOKLAYOUT_LOCK_DIR", str(tmp_path / "ok"))
    fd1 = _lock_file(tmp_path / "t.json")
    fd2 = _lock_file(tmp_path / "t.json")
    assert os.fstat(fd1).st_ino == os.fstat(fd2).st_ino
    os.close(fd1)
    os.close(fd2)


# ---- round 10 regressions ----
def test_round10_page_patch_old_digest_mismatch_rejected():
    import pytest
    from booklayout.normalize import apply_page_patch, page_digest
    d = _data()
    dg = page_digest(d["pages"][0])
    d["pages"][0]["blocks"].append({"block_id": "late", "role": "body", "text": "L"})
    with pytest.raises(ValueError):
        apply_page_patch(d, {"pages": {"4": [{"block_id": "p004_01"}]}, "old_page_digests": {"4": dg}})
    assert any(b["block_id"] == "late" for b in d["pages"][0]["blocks"])


def test_round10_page_patch_duplicate_canonical_pages_rejected():
    import pytest
    from booklayout.normalize import apply_page_patch
    d = _data()
    with pytest.raises(ValueError):
        apply_page_patch(d, {"pages": {"4": [], "04": []}})
    assert d["pages"][0]["blocks"]


def test_round10_page_patch_duplicate_ids_and_wrong_patch_rejected():
    import pytest
    from booklayout.normalize import apply_page_patch
    d = _data()
    with pytest.raises(ValueError):
        apply_page_patch(d, {"pages": {"4": [{"block_id": "p004_01"}, {"block_id": "p004_01"}]}})
    with pytest.raises(ValueError):
        apply_page_patch(d, {"version": 2, "edits": []})


def test_round10_page_patch_new_block_keeps_rows():
    from booklayout.normalize import apply_page_patch
    d = _data()
    apply_page_patch(d, {"pages": {"4": [{"block_id": "t", "role": "table", "translation": "表",
                                          "text": "Table", "rows": [["a", "1"]]}]}})
    b = d["pages"][0]["blocks"][0]
    assert b["rows"] == [["a", "1"]] and b["text"] == "Table"


def test_round10_old_struct_checked_on_update():
    d = _data()
    b = d["pages"][0]["blocks"][0]
    e = dict(block_id="p004_01", page=4, role="heading", old_role=b["role"], old_hash=block_src_hash(b),
             old_prev="", old_next=block_src_hash(d["pages"][0]["blocks"][1]),
             old_translation=b.get("translation"), old_level=b.get("level"),
             old_struct=block_struct_digest(b))
    b["translation"] = "人工新校"
    r = apply_block_edits(d, {"version": 2, "edits": [e]}, allow_partial=True)
    assert r["stale"] == ["p004_01"] and r["applied"] == []


def test_round10_load_aligned_rejects_duplicate_keys(tmp_path):
    import pytest
    from booklayout.builder import load_aligned
    f = tmp_path / "a.json"
    f.write_text('{"pages":[{"page":1,"blocks":[]}],"pages":[]}', encoding="utf-8")
    with pytest.raises(ValueError):
        load_aligned(f)


def test_round10_col_widths_longer_than_columns_rejected_role_kept():
    d = _data()
    b = d["pages"][0]["blocks"][0]
    b.update(rows=[["only"]], col_widths_mm=[20, 20])
    r = apply_block_edits(d, {"edits": [{"block_id": "p004_01", "role": "table"}]}, allow_partial=True)
    assert r["applied"] == [] and b["role"] != "table"


def test_round11_report_symlink_alias_guard(tmp_path):
    import os
    a, p = _setup(tmp_path)
    before = a.read_bytes()
    alias = tmp_path / "alias.json"
    os.symlink(a, alias)
    rc = _main(["patch-blocks", "--aligned", str(a), "--patch", str(p), "--report", str(alias)])
    assert rc == 2 and a.read_bytes() == before


def test_round11_normalize_report_must_not_overwrite_input(tmp_path):
    a, _ = _setup(tmp_path)
    before = a.read_bytes()
    rc = _main(["normalize", "--aligned", str(a), "--report", str(a)])
    assert rc == 2 and a.read_bytes() == before


def test_round11_lock_shared_by_symlink_alias(tmp_path, monkeypatch):
    import os
    from booklayout import cli
    monkeypatch.setenv("BOOKLAYOUT_LOCK_DIR", str(tmp_path / "locks"))
    a, _ = _setup(tmp_path)
    alias = tmp_path / "alias.json"
    os.symlink(a, alias)
    assert cli._lock_ident(a) == cli._lock_ident(alias)


def test_round11_repair_rejects_structural_fields_on_existing_block():
    from booklayout.normalize import apply_page_patch
    d = {"pages": [{"page": 1, "blocks": [{"block_id": "a", "role": "body", "text": "A", "translation": "甲"}]}]}
    p = {"pages": {"1": [{"block_id": "a", "rows": [["x"]]}]}}
    with pytest.raises(ValueError):
        apply_page_patch(d, p)
    assert "rows" not in d["pages"][0]["blocks"][0]


def test_round12_page_repair_rejects_dup_pages_dup_ids_cross_page():
    from booklayout.normalize import apply_page_patch
    b = lambda i, t: {"block_id": i, "role": "body", "text": t, "translation": "x"}  # noqa: E731
    d = {"pages": [{"page": 1, "blocks": [b("a", "A")]}, {"page": 1, "blocks": [b("z", "Z")]}]}
    with _pt.raises(ValueError, match="duplicate page"):
        apply_page_patch(d, {"pages": {"1": []}})
    d = {"pages": [{"page": 1, "blocks": [b("a", "A"), b("a", "A2")]}]}
    with _pt.raises(ValueError, match="duplicate block_ids"):
        apply_page_patch(d, {"pages": {"1": [{"block_id": "a"}]}})
    d = {"pages": [{"page": 1, "blocks": [b("a", "A")]}, {"page": 2, "blocks": [b("m", "M")]}]}
    with _pt.raises(ValueError, match="across pages"):
        apply_page_patch(d, {"pages": {"1": [{"block_id": "a"}, {"block_id": "m"}]}})
    assert [x["block_id"] for x in d["pages"][1]["blocks"]] == ["m"]


def test_round12_v1_explicit_page_mismatch_is_stale():
    d = _data()
    r = apply_block_edits(d, {"edits": [{"block_id": "p004_01", "page": 9, "translation": "丙"}]})
    assert r["stale"] == ["p004_01"] and r["applied"] == []


def test_round12_with_locks_retries_after_inode_replace(tmp_path, monkeypatch):
    from booklayout import cli
    monkeypatch.setenv("BOOKLAYOUT_LOCK_DIR", str(tmp_path / "locks"))
    f = tmp_path / "book.json"
    f.write_text("{}")
    calls = []

    def fn():
        calls.append(1)
        return 0
    real = cli._lock_ident
    state = {"n": 0}

    def flaky(t):  # identity changes once, as if a writer replaced the file while we waited
        state["n"] += 1
        return real(t) + ("x" if state["n"] == 3 else "")
    monkeypatch.setattr(cli, "_lock_ident", flaky)
    assert cli._with_locks([f], fn) == 0 and calls == [1]
    assert state["n"] >= 4


def test_round12_report_alias_of_out_rejected_after_write(tmp_path, monkeypatch):
    import os
    monkeypatch.setenv("BOOKLAYOUT_LOCK_DIR", str(tmp_path / "locks"))
    book = tmp_path / "book.json"
    book.write_text(_j.dumps(_data()))
    patch = tmp_path / "p.json"
    patch.write_text(_j.dumps({"edits": [{"block_id": "p004_01", "translation": "丙"}]}))
    out, rep = tmp_path / "out.json", tmp_path / "rep.json"
    real_write = __import__("booklayout.cli", fromlist=["x"])._write_json

    def write_then_alias(path, data):
        real_write(path, data)
        if path == out and not rep.exists():
            os.symlink(out, rep)  # report path becomes an alias of out only after out exists
    monkeypatch.setattr("booklayout.cli._write_json", write_then_alias)
    rc = _cli_main(["patch-blocks", "--aligned", str(book), "--patch", str(patch), "--out", str(out), "--report", str(rep)])
    assert rc == 2
    assert "applied" not in out.read_text()[:20]  # out still the aligned book, not clobbered by report
