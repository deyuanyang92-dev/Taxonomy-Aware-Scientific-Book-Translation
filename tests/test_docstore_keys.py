"""docstore.keys：检索表偶句重建（合成行框，不含书籍原文；issue #38）。

坐标按 200 dpi 页宽 W=1900：文本左缘 Tm=300，条目栏 x0<262 且 x1<288，终点在右缘约 1750。
"""

import json

from docstore import keys

W = 1900.0
TM = 300


def row(x0, y0, x1, y1, text, conf=0.95):
    return [[[x0, y0], [x1, y0], [x1, y1], [x0, y1]], text, conf]


def lead(y, marker, text, target=None):
    """一个条目：条目号框 + 正文框 + 右栏终点框。正文要 ≥8 字，否则页内校准（G6）取不到文本左缘。"""
    assert len(text) >= 8, text
    rows = []
    if marker is not None:
        rows.append(row(190, y, 240, y + 40, marker))
    rows.append(row(TM, y, 1100, y + 40, text))
    if target:
        rows.append(row(1550, y, 1750, y + 40, target))
    return rows


def heading(y=100, text="ウロコムシ類の検索表"):
    return [row(TM, y, 700, y + 40, text)]


def parse(*pages, grammar=None):
    """pages: 每页一个原始行列表；页号从 1 起。"""
    return keys.extract([(i + 1, W, keys.rows_from_raw(p)) for i, p in enumerate(pages)], grammar)


def terms(res):
    return {c["lead"]: c["terminals"] for c in res["couplets"]}


def basic_page():
    return (heading()
            + lead(200, "1.", "体は細長く頭部が明瞭", "……2")
            + lead(280, "—", "体は短く頭部がない", "……ウロコムシ科")
            + lead(360, "2.", "背面に鱗片がある", "……Harmothoe imbricata")
            + lead(440, "—", "背面に鱗片がない", "……Lepidonotus clava"))


def test_grammar_loads_all_rules():
    gr = keys.Grammar()
    assert gr.is_dash("—") and gr.is_dash("一") and not gr.is_dash("2")
    assert gr.is_marker("12.") and gr.is_marker("—") and not gr.is_marker("体は")
    assert gr.lead_merged.match("3．体は細長い").group(2) == "体は細長い"
    assert gr.inline.match("4'.体は").group(2) == "'"
    for k in ("lead_left", "lead_right", "right_tol", "target_far", "new_lead_gap"):
        assert k in gr.g


def test_column_key_is_rebuilt_with_lead_order_and_terminals():
    res = parse(basic_page())
    assert [c["lead"] for c in res["couplets"]] == ["1", "1'", "2", "2'"]
    assert terms(res) == {"1": ["2"], "1'": ["ウロコムシ科"],
                          "2": ["Harmothoe imbricata"], "2'": ["Lepidonotus clava"]}
    assert res["couplets"][0]["text"] == "体は細長く頭部が明瞭"
    assert res["keys"] == [{"key": 1, "first_page": 1, "last_page": 1, "couplets": 4, "problems": []}]


def test_check_flags_missing_alternate_missing_terminal_and_bad_jump():
    res = parse(heading()
                + lead(200, "1.", "体は細長く頭部が明瞭", "……9")        # 跳到不存在的 9
                + lead(280, "—", "体は短く頭部がない")                     # 无终点
                + lead(360, "2.", "背面に鱗片がある", "……Harmothoe imbricata")
                + lead(440, "3.", "腹面に毛が密生する", "……Lepidonotus clava"))
    probs = res["keys"][0]["problems"]
    assert "jump to unknown 9 from 1 p1" in probs
    assert "no terminal: 1' p1" in probs
    assert "missing alternate for 2" in probs and "missing alternate for 3" in probs


def test_merged_marker_and_text_is_split():
    # OCR 把「3．」和正文并成一框，框左缘在条目栏里
    page = (heading()
            + [row(200, 200, 1100, 240, "1．体は細長く頭部が明瞭"), row(1550, 200, 1750, 240, "……2")]
            + lead(280, "—", "体は短く頭部がない", "……ウロコムシ科")
            + lead(360, "2.", "背面に鱗片がある", "……Harmothoe imbricata")
            + lead(440, "—", "背面に鱗片がない", "……Lepidonotus clava"))
    res = parse(page)
    assert [c["lead"] for c in res["couplets"]] == ["1", "1'", "2", "2'"]
    assert res["couplets"][0]["text"] == "体は細長く頭部が明瞭"


def test_dropped_dash_becomes_implicit_lead():
    # 第二条的「—」没被 OCR 出来：终点之后左缘的新行就是新条目
    page = (heading()
            + lead(200, "1.", "体は細長く頭部が明瞭", "……2")
            + lead(280, None, "体は短く頭部がない", "……ウロコムシ科")
            + lead(360, "2.", "背面に鱗片がある", "……Harmothoe imbricata")
            + lead(440, "—", "背面に鱗片がない", "……Lepidonotus clava"))
    res = parse(page)
    assert [c["lead"] for c in res["couplets"]] == ["1", "1'", "2", "2'"]
    assert {"page": 1, "event": "IMPLICIT", "detail": "1'"} in res["events"]
    assert res["keys"][0]["problems"] == []


def test_lost_terminal_is_flagged_not_swallowed():
    # 第一条短行结束又没有终点（OCR 丢了右栏）；下一行仍须当新条目，并且图检查报缺终点
    page = (heading()
            + lead(200, "1.", "体は細長く頭部が明瞭", None)
            + lead(280, None, "体は短く頭部がない", "……ウロコムシ科")
            + lead(360, "2.", "背面に鱗片がある", "……Harmothoe imbricata")
            + lead(440, "—", "背面に鱗片がない", "……Lepidonotus clava"))
    res = parse(page)
    assert any(e["event"] == "IMPLICIT_LOST" for e in res["events"])
    assert "no terminal: 1 p1" in res["keys"][0]["problems"]


def test_page_number_is_not_a_lead_or_terminal():
    # 右下角页码（孤立数字，离正文很远）：不能当跳转终点；校准要求正文行够长（≥8 字），合成数据照此
    p1 = (heading() + lead(200, "1.", "体は細長く頭部が明瞭", "……2")
          + lead(280, "—", "体は短く頭部がない", "……ウロコムシ科")
          + lead(360, "2.", "背面に鱗片がある", "……Harmothoe imbricata")
          + [row(1680, 700, 1750, 740, "7")])
    p2 = (lead(120, "—", "背面に鱗片がない", "……Lepidonotus clava")
          + lead(200, "3.", "腹面に長い毛がある", "……Nereis")
          + lead(280, "—", "腹面に毛がなく滑らか", "……Glycera"))
    res = parse(p1, p2)
    assert [c["lead"] for c in res["couplets"]] == ["1", "1'", "2", "2'", "3", "3'"]
    assert {"page": 1, "event": "PAGENO", "detail": "7"} in res["events"]
    assert terms(res)["2"] == ["Harmothoe imbricata"]   # 页码 7 没有串进条目 2 的终点


def test_key_continues_across_pages_and_new_heading_starts_new_key():
    p1 = heading() + lead(200, "1.", "体は細長く頭部が明瞭", "……2") + lead(280, "—", "体は短く頭部がない", "……ウロコムシ科")
    p2 = (lead(120, "2.", "背面に鱗片がある", "……Harmothoe imbricata")
          + lead(200, "—", "背面に鱗片がない", "……Lepidonotus clava"))
    p3 = (heading(80, "ゴカイ類の検索表") + lead(200, "1.", "頭部に触手がある", "……Nereis"))
    res = parse(p1, p2, p3)
    ks = res["keys"]
    assert [(k["key"], k["first_page"], k["last_page"], k["couplets"]) for k in ks] == [(1, 1, 2, 4), (2, 3, 3, 1)]


def test_page_without_markers_and_caption_end_the_key():
    p1 = heading() + lead(200, "1.", "体は細長く頭部が明瞭", "……2") + lead(280, "—", "体は短く頭部がない", "……ウロコムシ科")
    p2 = [row(TM, 200, 1100, 240, "本文の続きで条目ではない長い文章がここに入る"),
          row(TM, 280, 1100, 320, "もう一行の本文がここに入る")]
    p3 = lead(200, "3.", "腹面に毛が密生する", "……Nereis") + lead(280, "—", "腹面に毛がなく滑らか", "……Glycera")
    res = parse(p1, p2, p3)
    # 无条目号的 p2 结束该表（p2 的正文可能先漏成隐含条目，见 keys.py G7 说明）；p3 没有标题，不属于任何表
    assert 3 not in {c["page"] for c in res["couplets"]}
    assert [c["lead"] for c in res["couplets"]][:2] == ["1", "1'"]

    cap = (heading() + lead(200, "1.", "体は細長く頭部が明瞭", "……2") + lead(280, "—", "体は短く頭部がない", "……ウロコムシ科")
           + [row(TM, 360, 900, 400, "図 12. 体の背面観")])
    res = parse(cap)
    assert [c["lead"] for c in res["couplets"]] == ["1", "1'"]
    assert any(e["event"] == "ENDKEY" for e in res["events"])


def test_inline_profile_2009_style():
    # 条目号和正文在一个框里，条目栏没有单独的号：重复出现的号是备择条目
    def inl(y, text, target=None):
        r = [row(100, y, 1100, y + 40, text)]
        if target:
            r.append(row(1550, y, 1750, y + 40, target))
        return r

    page = (heading()
            + inl(200, "1.体は細長く頭部が明瞭", "……2")
            + inl(280, "1'.体は短く頭部がない", "……ウロコムシ科")
            + inl(360, "2.背面に鱗片がある", "……Harmothoe imbricata")
            + inl(440, "2'.背面に鱗片がない", "……Lepidonotus clava"))
    res = parse(page)
    assert [c["lead"] for c in res["couplets"]] == ["1", "1'", "2", "2'"]
    assert res["couplets"][1]["text"] == "体は短く頭部がない"
    assert res["keys"][0]["problems"] == []


def test_rules_are_data_not_code(tmp_path):
    # 改规则文件即可改行为：把「検索」标题词换掉后，原标题不再开新表
    src = keys.RULES_PATH.read_text(encoding="utf-8").replace("検索|Key to|KEY TO", "ZZZ")
    f = tmp_path / "keys.toml"
    f.write_text(src, encoding="utf-8")
    res = parse(basic_page(), grammar=keys.Grammar(f))
    assert res["couplets"] == []


def test_read_cache_pages_reports_missing_without_ocr(tmp_path):
    (tmp_path / "p0001.json").write_text(
        json.dumps({"width": W, "rows": [row(TM, 100, 700, 140, "検索表")]}), encoding="utf-8")
    pages, missing = keys.read_cache_pages(tmp_path, 1, 3)
    assert [p[0] for p in pages] == [1] and missing == [2, 3]
    assert pages[0][2][0]["t"] == "検索表"


# ---- CLI（合成缓存目录，不碰真库）----

def _write_cache(tmp_path, pages):
    for i, rows in enumerate(pages, start=1):
        (tmp_path / f"p{i:04d}.json").write_text(json.dumps({"width": W, "rows": rows}), encoding="utf-8")


def test_cli_extract_and_check_roundtrip(tmp_path, capsys):
    from docstore.cli import main

    cache = tmp_path / "cache"
    cache.mkdir()
    _write_cache(cache, [basic_page()])
    out = tmp_path / "keys.json"
    assert main(["--root", str(tmp_path / "root"), "keys", "extract", "--cache", str(cache),
                 "--last", "1", "--out", str(out)]) == 0
    assert "共 1 张表，1 张自洽" in capsys.readouterr().err
    data = json.loads(out.read_text(encoding="utf-8"))
    assert [c["lead"] for c in data["couplets"]] == ["1", "1'", "2", "2'"] and data["missing_pages"] == []

    # 人工删掉一个备择条目后，check 必须报缺陷
    data["couplets"] = [c for c in data["couplets"] if c["lead"] != "2'"]
    out.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert main(["--root", str(tmp_path / "root"), "keys", "check", str(out), "--problems"]) == 0
    cap = capsys.readouterr()
    assert "missing alternate for 2" in cap.out and "共 1 张表，0 张自洽" in cap.err


def test_cli_extract_needs_key_or_cache_with_last(tmp_path):
    import pytest

    from docstore.cli import main

    with pytest.raises(SystemExit):
        main(["--root", str(tmp_path / "root"), "keys", "extract", "--cache", str(tmp_path)])


# ---- 真实三卷回归：行框缓存不入库，缺则跳过。数字是 issue #38 记录的原型结果（只有计数，无书文）----

IMAJIMA = {  # 缓存目录哈希 → (页数, 表数, 偶句数, 自洽表数, 缺陷数)
    "966b8423a9d4": (406, 14, 422, 11, 3),   # 2001（孤立「…」作条目横线后 419→420；粘在描述末尾的终点拆回后缺陷 6→5；整行拉丁名认作终点、同行按 x 排序后 420→422、缺陷 5→3）
    "858f37873e50": (363, 8, 288, 4, 9),     # 2007（同上；条目号框贴近正文也算条目号后 p219 的 28 个偶句找回，253→288）
    "c1ac037a042b": (361, 10, 555, 6, 6),    # 2009（内联页自校准 493→566；左缘页码与表后正文页不再开幽灵条目 566→555，缺陷 23→6）
}


def test_real_volumes_match_recorded_counts():
    import os
    from pathlib import Path

    import pytest

    root = Path(os.environ.get("DOCSTORE_PPOCR_CACHE", str(Path.home() / ".cache" / "docstore_ppocr")))
    ran = 0
    for h, (n, nkeys, ncoup, nok, nprob) in IMAJIMA.items():
        cache = root / h / "PP-OCRv5_server_200_v2"
        if not cache.is_dir():
            continue
        pages, missing = keys.read_cache_pages(cache, 1, n)
        assert not missing
        res = keys.extract(pages)
        assert len(res["keys"]) == nkeys, h
        assert len(res["couplets"]) == ncoup, h
        assert sum(not k["problems"] for k in res["keys"]) == nok, h
        assert sum(len(k["problems"]) for k in res["keys"]) == nprob, h
        ran += 1
    if not ran:
        pytest.skip("本机没有 Imajima 行框缓存")


# ---- 结构化终点与整页版面（交给排版：名称栏 / 目标栏 / 整页替换）----

def test_slots_split_name_column_and_target_column():
    gr = keys.default_grammar()
    assert keys.term_struct(gr, "12") == {"kind": "jump", "num": "12"}
    assert keys.term_struct(gr, "Syllis spongicola (図63) -> 14") == {
        "kind": "name_jump", "name": "Syllis spongicola (図63)", "num": "14"}
    assert keys.term_struct(gr, "ウロコムシ亜科 -> Harmothoe sp. (図12)") == {
        "kind": "group_taxon", "group": "ウロコムシ亜科", "taxon": "Harmothoe sp. (図12)"}
    # OCR 把「図」认成「区」只在其后紧跟图号时改回；前导点线丢掉
    assert keys.term_struct(gr, "…Nothria paxtonae(区106)")["taxon"] == "Nothria paxtonae(図106)"
    assert keys.term_struct(gr, "区別")["taxon"] == "区別"


def test_layout_lists_page_items_in_reading_order():
    res = parse(basic_page())
    items = res["layout"]["1"]
    assert [i["t"] for i in items] == ["heading", "couplet", "couplet", "couplet", "couplet"]
    assert [i["i"] for i in items if i["t"] == "couplet"] == [0, 1, 2, 3]
    assert res["couplets"][0]["slots"][0]["kind"] in {"jump", "taxon", "group_taxon", "name_jump"}


def test_lone_ellipsis_in_lead_column_is_a_dash_lead():
    gr = keys.default_grammar()
    assert gr.is_dash("…") and gr.is_marker("…")


def test_long_taxon_line_folded_below_description_is_a_target_and_number_sorts_after_text():
    # 长学名折到下一行，起点（x0=600）比 target_far 更靠左；右栏的「6」框中心略高于描述行，
    # 只按中心 y 排序会把它并给上一条、描述行再被判成隐含条目。
    rows = (heading()
            + [row(190, 200, 240, 240, "5."),
               row(TM, 200, 1750, 240, "下部剛毛束に針状複剛毛と被嚢二叉鉤状複剛毛が生じる ………"),
               row(600, 245, 1750, 285, "Marphysa bellii (Audouin & Milne Edwards) (図122)"),
               row(TM, 290, 1100, 330, "下部剛毛束に針状複剛毛か被嚢二叉鉤状複剛毛のいずれかがある"),
               row(1700, 285, 1750, 315, "6")]
            + lead(340, "6.", "下部剛毛束に針状複剛毛のみ", "……Marphysa kinbergi"))
    res = parse(rows)
    t = terms(res)
    assert t["5"] == ["Marphysa bellii (Audouin & Milne Edwards) (図122)"], t
    assert t["5'"] == ["6"], t
    assert [c["kind"] for c in res["couplets"][:2]] == ["num", "implicit"]


def test_number_box_touching_the_text_margin_is_still_a_lead():
    rows = (heading() + lead(200, "1.", "体は細長く頭部が明瞭", "……2")
            + [row(220, 280, TM - 2, 320, "2.")]
            + lead(280, None, "背面に鱗片がある", "……Harmothoe imbricata"))
    res = parse(rows)
    assert [c["lead"] for c in res["couplets"]] == ["1", "2"], res["events"]
    assert terms(res)["2"] == ["Harmothoe imbricata"]


def test_term_struct_splits_single_ellipsis_and_glued_group_name():
    gr = keys.default_grammar()
    assert keys.term_struct(gr, "Eunoe…14") == {"kind": "name_jump", "name": "Eunoe", "num": "14"}
    assert keys.term_struct(gr, "Nephtys .13")["kind"] == "name_jump"
    assert keys.term_struct(gr, "Aricidea (Acmira)…14")["name"] == "Aricidea (Acmira)"
    # 「sp. 3」是种名的一部分，不是跳转
    assert keys.term_struct(gr, "Syllis sp. 3") == {"kind": "taxon", "taxon": "Syllis sp. 3"}
    assert keys.term_struct(gr, "シンカイウロコムシ亜科Branchinotogluminae") == {
        "kind": "group_taxon", "group": "シンカイウロコムシ亜科", "taxon": "Branchinotogluminae"}
    assert keys.term_struct(gr, "Iphione ovata (図38)")["kind"] == "taxon"


def test_rest_items_carry_position_and_widths():
    res = parse(basic_page())
    assert set(res["widths"]) == set(res["layout"])
    for items in res["layout"].values():
        for it in items:
            if it["t"] == "rest":
                assert {"x0", "y0"} <= set(it)


def test_inline_page_with_left_shifted_markers_calibrates_on_marker_rows():
    """2009 卷 p200 型页：条目号并进正文框且整页偏左（x0≈18），全页众数会误取续行缩进（≈75）。"""
    def row(x0, y, t, x1=None):
        return {"x0": x0, "x1": x1 or x0 + 400, "y0": y, "y1": y + 30, "t": t}
    rows = [row(19, 100 + 40 * i, f"{30 + i}.前口葉に斑紋はない；体前方は普通", 1100) for i in range(6)]
    rows += [row(74, 120 + 40 * i, "続く", 300) for i in range(6)]
    tm, _right = keys.calibrate(keys.default_grammar(), 1276.0, rows)
    assert tm < 30


def test_pull_text_from_slots_moves_description_back_into_text():
    c = {"text": "", "terminals": ["体表面は粘着性の突起で覆われる；疣足の背触糸は洋ナシ形………Sphaerosyllis -> 3"],
         "slots": [{"kind": "name_jump", "name": "体表面は粘着性の突起で覆われる；疣足の背触糸は洋ナシ形………Sphaerosyllis", "num": "3"}]}
    assert keys.pull_text_from_slots(c)
    assert c["text"] == "体表面は粘着性の突起で覆われる；疣足の背触糸は洋ナシ形"
    assert c["slots"] == [{"kind": "name_jump", "name": "Sphaerosyllis", "num": "3"}]
    d = {"text": "—", "terminals": ["鰓先端の各鰓枝は多数って短く，密に分岐する -> Euphrosine sp.C（図155)"],
         "slots": [{"kind": "group_taxon", "group": "鰓先端の各鰓枝は多数って短く，密に分岐する", "taxon": "Euphrosine sp.C（図155)"}]}
    assert keys.pull_text_from_slots(d)
    assert d["text"].startswith("鰓先端") and d["slots"] == [{"kind": "taxon", "taxon": "Euphrosine sp.C（図155)"}]
    ok = {"text": "体は小さい", "terminals": ["2"], "slots": [{"kind": "jump", "num": "2"}]}
    assert not keys.pull_text_from_slots(ok)
    jp = {"text": "", "terminals": ["シンカイウロコムシ亜科 -> Branchinotogluminae"],
          "slots": [{"kind": "group_taxon", "group": "シンカイウロコムシ亜科", "taxon": "Branchinotogluminae"}]}
    assert not keys.pull_text_from_slots(jp)


# ---- 幽灵条目：页码、表后正文页、粘在描述末尾的终点（2009 卷实测）----

def test_bare_number_at_left_margin_is_a_page_number_not_an_implicit_couplet():
    foot = [row(TM, 1850, TM + 50, 1890, "62")]  # 文本左缘的页脚页码，离最后一条很远
    res = parse(basic_page() + foot)
    assert [c["lead"] for c in res["couplets"]] == ["1", "1'", "2", "2'"]
    assert any(e["event"] == "PAGENO" and e["detail"] == "62" for e in res["events"])
    assert res["layout"]["1"][-1] == {"t": "rest", "text": "62", "why": "pageno", "x0": TM, "y0": 1850}


def test_page_after_the_key_without_markers_or_targets_does_not_spawn_couplets():
    prose = [row(100, 300, 1100, 340, "Brania Quatrefages, 1865"),
             row(100, 400, 1100, 440, "ホソテシリス 体長2.5~3mm，体幅約0.6mm"),
             row(100, 500, 1100, 540, "分布 日本各地；世界各地")]
    folio = [row(1500, 1850, 1560, 1890, "7")]  # 右下角页码形似「跳到 7」，不能算终点
    res = parse(basic_page(), prose + folio)
    assert [c["lead"] for c in res["couplets"]] == ["1", "1'", "2", "2'"]
    assert [i["why"] for i in res["layout"]["2"] if i["t"] == "rest"][:3] == ["outside"] * 3


def test_target_glued_to_description_tail_is_split_back_into_a_slot():
    ok = lambda text: {"text": text, "terminals": [], "slots": []}  # noqa: E731
    gr = keys.Grammar()
    for text, kind, head in (
        ("背剛毛は太く短い..*11", "jump", "背剛毛は太く短い"),
        ("指状か樹枝状の鰓がある.17", "jump", "指状か樹枝状の鰓がある"),
        ("刺葉は平滑.Nephtyslongosetosa(図145)", "taxon", "刺葉は平滑"),
        ("背叶が短い……Perinereis…21", "name_jump", "背叶が短い"),
    ):
        c = ok(text)
        assert keys.recover_tail_target(gr, c), text
        assert c["text"] == head and c["slots"][0]["kind"] == kind, text
    for text in ("体長は2.5mm.", "var. 2", "背面は平滑…", "口前葉は2.5"):  # 小数、拉丁缩写、无号的点线都不拆
        c = ok(text)
        assert keys.recover_tail_target(gr, c) is None and c["slots"] == [], text
    done = {"text": "体は小さい…6", "terminals": ["2"], "slots": [{"kind": "jump", "num": "2"}]}
    assert keys.recover_tail_target(gr, done) is None  # 已有栏位的条目不动
