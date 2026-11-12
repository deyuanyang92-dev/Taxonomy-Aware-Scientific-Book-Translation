import argparse
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
    assert "| 候选 |" in t and "刚节" in t


def test_table_shows_source_context(con):
    """译名要连同出处语境给出：洪德元的「突变体(variant)」出自概念列举，不能套到 Ray 的 variants 上。"""
    D.add_term(con, "variant", "突变体", "hong2016", domain="进化生物学",
               context="饰变(modification)、基因型(genotype)、突变体(variant)、多态现象")
    t = M.term_table(con, "an assemblage of all variants", "进化生物学")
    assert "突变体" in t and "基因型(genotype)" in t and "出处语境" in t


def test_table_flags_same_rank_conflict(con):
    D.add_source(con, "classicA", "经典译作甲", "authority", domain="进化生物学")
    D.add_source(con, "classicB", "经典译作乙", "authority", domain="进化生物学")
    D.add_term(con, "population", "种群", "classicA", domain="进化生物学", status="已核")
    D.add_term(con, "population", "居群", "classicB", domain="进化生物学", status="已核")
    t = M.term_table(con, "two populations", "进化生物学")
    assert "⚠冲突" in t
    D.add_term(con, "population", "居群", "user", domain="进化生物学", status="已核")
    assert "⚠冲突" not in M.term_table(con, "two populations", "进化生物学")  # 用户核定层级更高，不算冲突


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


def test_find_terms_ignores_figure_letters(con):
    D.add_term(con, "f.", "变型", "hong2016", domain="进化生物学")
    assert M.find_terms(con, "radioles (Figs. 38.1c, 38.2f).", "进化生物学") == {}
    assert M.find_terms(con, "Carex f. alba", "进化生物学") == {"f": 1}


def test_same_tier_newer_source_wins(con):
    """同层级来源用名不一致时，以出版年新者为准（用户 2026-11-12：杨孙 1988 vs 2004/2014）。"""
    D.add_source(con, "jinhai1988", "近海1988", "authority", domain="分类学", year=1988)
    D.add_source(con, "dzz33", "动物志33", "authority", domain="分类学", year=2004)
    D.add_term(con, "Namalycastis", "单叶沙蚕属", "jinhai1988", domain="分类学", status="已核")
    D.add_term(con, "Namalycastis", "溪沙蚕属", "dzz33", domain="分类学", status="已核")
    cs = D.candidates(con, "Namalycastis", "分类学")
    assert [h.zh for h in cs] == ["溪沙蚕属", "单叶沙蚕属"]
    assert cs[0].year == 2004


def test_source_set_keeps_other_fields(con):
    D.set_source(con, "dzz54", year=2014, tier=1)
    r = con.execute("SELECT * FROM sources WHERE key='dzz54'").fetchone()
    assert (r["year"], r["tier"], r["title"]) == (2014, 1, "中国动物志54 缨鳃虫目")
    D.add_source(con, "dzz54", "中国动物志54 缨鳃虫目", "authority", tier=1, domain="分类学")
    assert con.execute("SELECT year FROM sources WHERE key='dzz54'").fetchone()[0] == 2014


def test_stats_newer_edition_not_conflict(con, capsys):
    D.add_source(con, "a1988", "旧版", "authority", domain="分类学", year=1988)
    D.add_source(con, "b2004", "新版", "authority", domain="分类学", year=2004)
    D.add_source(con, "c2004", "同年另一本", "authority", domain="分类学", year=2004)
    D.add_term(con, "Leocrates", "结海虫属", "a1988", domain="分类学", status="已核")
    D.add_term(con, "Leocrates", "海结虫属", "b2004", domain="分类学", status="已核")
    D.add_term(con, "Synelmis", "刺毛虫属", "b2004", domain="分类学", status="已核")
    D.add_term(con, "Synelmis", "甲毛虫属", "c2004", domain="分类学", status="已核")
    cli.cmd_stats(None, con)
    out = capsys.readouterr().out
    assert "未解决冲突 1 条" in out and "Synelmis" in out
    assert "新版取代旧版 1 条" in out and "Leocrates" in out


def test_table_newer_edition_not_flagged(con):
    D.add_source(con, "old", "旧版", "authority", domain="分类学", year=1988)
    D.add_source(con, "new", "新版", "authority", domain="分类学", year=2004)
    D.add_term(con, "Leocrates", "结海虫属", "old", domain="分类学", status="已核")
    D.add_term(con, "Leocrates", "海结虫属", "new", domain="分类学", status="已核")
    t = M.term_table(con, "Leocrates chinensis", "分类学")
    assert "海结虫属" in t and "⚠冲突" not in t


def test_lookup_hints_other_domains(con, capsys):
    """不带 --domain 查到空时，提示其他领域有译名，而不是说库中没有（2026-11-13 homoplasy 实例）。"""
    D.add_source(con, "futu", "Futuyma 生物进化", "translation", domain="进化生物学")
    D.add_term(con, "homoplasy", "同塑性", "futu", domain="进化生物学", status="已核")
    cli.cmd_lookup(argparse.Namespace(term="homoplasy", domain="*", scope=None), con)
    assert "其他领域有（进化生物学）" in capsys.readouterr().out
    cli.cmd_lookup(argparse.Namespace(term="nonexistent", domain="*", scope=None), con)
    assert "库中无此术语" in capsys.readouterr().out
