import zipfile

import pytest

from yiku import cli
from yiku import db as D
from yiku import extract as X
from yiku import ingest as I
from yiku import match as M


@pytest.fixture
def con(tmp_path):
    c = D.connect(tmp_path / "t.db")
    D.add_source(c, "dzz54", "中国动物志54 缨鳃虫目", "authority", domain="分类学")
    D.add_source(c, "hong2016", "洪德元 2016", "zh_original", domain="进化生物学")
    D.add_source(c, "wiki", "Wikidata", "external")
    D.add_source(c, "user", "用户裁定", "user")
    return c


def test_domain_keeps_disciplines_apart(con):
    D.add_term(con, "population", "种群", "user", domain="分类学", status="已核")
    D.add_term(con, "population", "居群", "hong2016", domain="进化生物学", status="已核")
    assert D.best(con, "population", "分类学").zh == "种群"
    assert D.best(con, "population", "进化生物学").zh == "居群"


def test_ranking_status_scope_tier(con):
    D.add_term(con, "operculum", "鳃盖", "wiki")                          # 候选、通用、低层级
    D.add_term(con, "operculum", "壳盖", "dzz54", scope="Serpulidae", status="已核")
    D.add_term(con, "operculum", "盖", "dzz54", status="已核")
    assert D.best(con, "operculum", scope={"Serpulidae"}).zh == "壳盖"
    assert D.best(con, "operculum").zh == "盖"          # 不在龙介虫科：类群专条不适用
    assert [h.zh for h in D.candidates(con, "Operculum")][-1] == "鳃盖"


def test_rejected_never_returned(con):
    D.add_term(con, "palp", "触须", "wiki", status="否决")
    assert D.best(con, "palp") is None


def test_unknown_source_raises(con):
    with pytest.raises(KeyError):
        D.add_term(con, "a", "甲", "nope")


def test_find_terms_plural_and_longest(con):
    D.add_term(con, "palp", "触角", "dzz54", status="已核")
    D.add_term(con, "palpal organ", "触角器", "dzz54", status="已核")
    D.add_term(con, "cirrus", "须", "dzz54", status="已核")
    f = M.find_terms(con, "Palps paired; a palpal organ; dorsal cirri long.")
    assert f == {"palp": 1, "palpal organ": 1, "cirrus": 1}


def test_check_reports_rejected_variant(con):
    D.add_term(con, "antenna", "触手", "dzz54", status="已核")
    D.add_term(con, "antenna", "触角", "wiki")
    issues = M.check(con, "Three antennae present.", "具3个触角。")
    assert len(issues) == 1 and issues[0].expected == "触手" and issues[0].found_alternatives == ["触角"]
    assert M.check(con, "Three antennae present.", "具3个触手。") == []


def test_table_flags_candidates(con):
    D.add_term(con, "chaetiger", "刚节", "wiki")
    t = M.term_table(con, "first chaetiger")
    assert "⚠候选" in t and "刚节" in t


def test_paren_pairs():
    txt = "广义的分类学研究的内容包括分类(classification)、系统发生(phylogeny)和进化，具有隐种(sibling species)。"
    got = {(c.en, c.zh) for c in X.paren_pairs(txt)}
    assert ("classification", "分类") in got
    assert ("phylogeny", "系统发生") in got
    assert ("sibling species", "隐种") in got


def test_pair_terms_finds_translator_choice():
    en_ctx = ["Darwin doubted that", "Mayr argued that", "In birds", "Among plants", "Dobzhansky showed",
              "Field data confirm", "Hybrid zones reveal", "Some authors deny"]
    zh_ctx = ["达尔文怀疑", "迈尔认为", "鸟类中", "植物里", "杜布赞斯基表明", "野外资料证实", "杂交带揭示", "有些作者否认"]
    fill_en = [f"Paragraph {j} discusses unrelated history and method. " for j in range(60)]
    fill_zh = [f"第{j}段讨论无关的历史与方法问题。" for j in range(60)]
    en = zh = ""
    for i in range(8):
        en += "".join(fill_en) + f"{en_ctx[i]} reproductive isolation evolves. "
        zh += "".join(fill_zh) + f"{zh_ctx[i]}生殖隔离会演变。"
    res = X.pair_terms(en, zh, ["reproductive isolation"], window=40)
    assert res["reproductive isolation"][0].zh in ("生殖隔离", "生殖隔离会演变")


def test_split_chapters():
    zh = "前言\n第一章 绪论\n文字\n第二章 分类\n文字"
    assert len(X.split_chapters(zh, "zh")) == 3


def test_join_lines():
    assert I.join_lines("物种\n概念") == "物种概念"
    assert I.join_lines("species con-\ncept is") == "species concept is"


def test_epub(tmp_path):
    p = tmp_path / "b.epub"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("META-INF/container.xml", '<rootfile full-path="OEBPS/c.opf"/>')
        z.writestr("OEBPS/c.opf", '<item id="a" href="a.xhtml"/><item id="b" href="b.xhtml"/>'
                   '<itemref idref="b"/><itemref idref="a"/>')
        z.writestr("OEBPS/a.xhtml", "<p>second</p>")
        z.writestr("OEBPS/b.xhtml", "<p>first</p>")
    assert [t.strip() for _, t in I.read(p)] == ["first", "second"]


def test_cli_import_and_review(tmp_path, capsys):
    dbp = str(tmp_path / "c.db")
    tsv = tmp_path / "t.tsv"
    tsv.write_text("en\tzh\tp\nspecies concept\t物种概念\t979\nfoo\t—\t1\n", encoding="utf8")
    run = lambda *a: cli.main(["--db", dbp, *a])  # noqa: E731
    for args in (["source", "add", "h", "--kind", "zh_original"],
                 ["import", str(tsv), "--source", "h", "--page-col", "p"],
                 ["review", "export", str(tmp_path / "r.tsv")]):
        with pytest.raises(SystemExit):
            run(*args)
    r = (tmp_path / "r.tsv").read_text(encoding="utf8").splitlines()
    assert len(r) == 2  # 「—」行被跳过
    cols = r[1].split("\t")
    cols[8] = "已核"
    (tmp_path / "r.tsv").write_text(r[0] + "\n" + "\t".join(cols) + "\n", encoding="utf8")
    with pytest.raises(SystemExit):
        run("review", "apply", str(tmp_path / "r.tsv"))
    assert D.best(D.connect(dbp), "Species concept").status == "已核"


def test_paren_quote_and_hyphen():
    got = {(c.en, c.zh) for c in X.paren_pairs("他在物种概念中提出“间断性”(discontinuity)，即古生物学物种(paleo- species)。")}
    assert ("discontinuity", "间断性") in got and ("paleospecies", "古生物学物种") in got


def test_variants():
    assert {"中位", "中位的"} <= M.variants("中位的")
    assert "环节动物" in M.variants("环节动物门")
    assert "补充" in M.variants("补充（加入）")
    assert "环纹" in M.variants("具环纹的")
    assert "吻" in M.variants("吻")
