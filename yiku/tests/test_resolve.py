"""语境感知的术语解析：HARD/SOFT 分类、跨领域回退、新术语表、决策日志、义项感知核对。全部用临时库。"""
import json

import pytest

from yiku import db as D
from yiku import match as M


@pytest.fixture
def con(tmp_path):
    c = D.connect(tmp_path / "t.db")
    c.execute("PRAGMA synchronous=OFF")  # 测试库用完即弃，省掉每次提交的 fsync
    D.add_source(c, "杨孙", "杨德渐孙瑞平", "authority", domain="分类学", year=1988)
    D.add_source(c, "动物志", "中国动物志", "authority", domain="分类学", year=2004)
    D.add_source(c, "名词委", "名词委动物学", "standard", domain="分类学")
    D.add_source(c, "Futuyma", "Futuyma 译本", "translation", domain="进化生物学")
    D.add_source(c, "洪德元", "洪德元", "zh_original", domain="进化生物学")
    D.add_source(c, "wiki", "Wikidata", "external")
    D.add_source(c, "user", "用户核定", "user", domain="分类学")
    return c


# ---------- 步骤 2：跨领域回退 ----------

def test_candidates_fallback_appended_after_own_domain(con):
    D.add_term(con, "homoplasy", "同塑", "user", domain="分类学", status="已核")
    D.add_term(con, "homoplasy", "同塑性", "Futuyma", domain="进化生物学", status="已核", context="非源自共同祖先的相似")
    hits = D.candidates(con, "homoplasy", "分类学", fallback_domains=["进化生物学"])
    assert [(h.zh, h.fallback) for h in hits] == [("同塑", False), ("同塑性", True)]
    assert hits[1].context.startswith("非源自")


def test_fallback_never_outranks_own_domain_verified_even_if_better_tier(con):
    D.add_source(con, "超级权威", "tier0 的回退来源", "user", domain="进化生物学")
    D.add_term(con, "x", "甲", "wiki", domain="分类学", status="已核")          # 自域：tier 8，已核
    D.add_term(con, "x", "乙", "超级权威", domain="进化生物学", status="已核")  # 回退：tier 0
    D.add_term(con, "x", "丙", "wiki", domain="分类学")                          # 自域候选
    hits = D.candidates(con, "x", "分类学", fallback_domains=["进化生物学"])
    assert [h.zh for h in hits] == ["甲", "丙", "乙"]
    assert D.best(con, "x", "分类学", fallback_domains=["进化生物学"]).zh == "甲"


def test_no_fallback_by_default_and_other_domains_stay_hidden(con):
    D.add_term(con, "homoplasy", "同塑性", "Futuyma", domain="进化生物学", status="已核")
    assert D.candidates(con, "homoplasy", "分类学") == []
    assert D.candidates(con, "homoplasy", "分类学", fallback_domains=["科学史"]) == []
    assert [h.zh for h in D.candidates(con, "homoplasy", "分类学", fallback_domains=["进化生物学"])] == ["同塑性"]


def test_fallback_still_applies_scope_and_rejection(con):
    D.add_term(con, "operculum", "壳盖", "Futuyma", domain="进化生物学", scope="Serpulidae", status="已核")
    D.add_term(con, "operculum", "鳃盖", "洪德元", domain="进化生物学", status="否决")
    assert D.candidates(con, "operculum", "分类学", fallback_domains=["进化生物学"]) == []
    got = D.candidates(con, "operculum", "分类学", {"Serpulidae"}, fallback_domains=["进化生物学"])
    assert [h.zh for h in got] == ["壳盖"]


def test_default_fallback_mapping():
    assert D.resolve_fallback("分类学", None) == ["进化生物学"]
    assert D.resolve_fallback("进化生物学", None) == []
    assert D.resolve_fallback("分类学", "none") == []
    assert D.resolve_fallback("分类学", "进化生物学;分子系统学") == ["进化生物学", "分子系统学"]
    assert D.resolve_fallback("分类学", "分类学,科学史") == ["科学史"]  # 自身领域不算回退
    assert D.resolve_fallback("*", None) == []


# ---------- 步骤 1：HARD / SOFT 分类 ----------

from yiku import classify as C  # noqa: E402


@pytest.mark.parametrize("name", [
    "Nereididae", "Nereis", "Annelida", "Nereis pelagica", "Sabellaria cf. nanella",
    "Scoloplos (Scoloplos) tumidus", "Nereis pelagica pelagica", "Fabriciinae", "Terebelliformia"])
def test_is_taxon_name_true(name):
    assert C.is_taxon_name(name)


@pytest.mark.parametrize("name", [
    "population", "adaptive radiation", "Biospecies", "Lamarckism", "Hennigian species", "Flora of China",
    "NEREIS", "N. pelagica", "f.", "chaetiger", "The Origin of Species", ""])
def test_is_taxon_name_false(name):
    assert not C.is_taxon_name(name)


def hits(con, en, domain="分类学", scope=None, fb=("进化生物学",)):
    return D.candidates(con, en, domain, scope, list(fb))


def test_taxon_single_zh_is_hard_even_if_only_checklist_candidate(con):
    D.add_source(con, "名录", "名录", "checklist", domain="分类学")
    D.add_term(con, "Nereididae", "沙蚕科", "名录", domain="分类学")  # 候选，tier 3
    c = C.classify(hits(con, "Nereididae"))
    assert (c.kind, c.reason, c.zh) == ("HARD", "taxon", "沙蚕科")


def test_taxon_from_weak_candidate_source_is_soft(con):
    D.add_source(con, "论文", "学位论文", "thesis", domain="分类学")
    D.add_term(con, "Nereis", "沙蚕属", "论文", domain="分类学")  # 候选，tier 6
    assert C.classify(hits(con, "Nereis")).kind == "SOFT"


def test_verified_unanimous_is_hard(con):
    D.add_term(con, "chaetiger", "刚节", "杨孙", domain="分类学", status="已核")
    D.add_term(con, "chaetiger", "刚节", "动物志", domain="分类学", status="已核")
    c = C.classify(hits(con, "chaetiger"))
    assert (c.kind, c.reason, c.zh) == ("HARD", "verified", "刚节")


def test_verified_disagreement_across_tiers_is_soft_with_preferred(con):
    """杨孙（tier 1）与名词委（tier 4）都已核却不同：SOFT（按语境判断），但标出最高层级的首选译名。"""
    D.add_term(con, "antenna", "触手", "杨孙", domain="分类学", status="已核")
    D.add_term(con, "antenna", "触角", "名词委", domain="分类学", status="已核")
    D.add_term(con, "antenna", "触须", "wiki", domain="分类学")
    c = C.classify(hits(con, "antenna"))
    assert (c.kind, c.reason, c.preferred, c.zh) == ("SOFT", "tier-split", "触手", None)


def test_verified_unanimous_ignores_candidate_disagreement(con):
    D.add_term(con, "antenna", "触手", "杨孙", domain="分类学", status="已核")
    D.add_term(con, "antenna", "触角", "wiki", domain="分类学")  # 候选不参与
    D.add_term(con, "antenna", "触角", "Futuyma", domain="进化生物学", status="已核")  # 回退不参与
    assert C.classify(hits(con, "antenna")).zh == "触手"


def test_newer_edition_in_same_tier_is_hard(con):
    D.add_term(con, "Ceratonereis mirabilis", "角沙蚕", "动物志", domain="分类学", status="已核")  # 2004
    D.add_term(con, "Ceratonereis mirabilis", "奇异角沙蚕", "杨孙", domain="分类学", status="已核")  # 1988
    assert C.classify(hits(con, "Ceratonereis mirabilis")).zh == "角沙蚕"


def test_same_rank_verified_conflict_is_soft(con):
    D.add_source(con, "志46", "志46", "authority", domain="分类学", year=2000)
    D.add_source(con, "志46b", "志46b", "authority", domain="分类学", year=2000)
    D.add_term(con, "Aspidosiphon", "盾管星虫属", "志46", domain="分类学", status="已核")
    D.add_term(con, "Aspidosiphon", "盾管亚属", "志46b", domain="分类学", status="已核")
    c = C.classify(hits(con, "Aspidosiphon"))
    assert (c.kind, c.reason) == ("SOFT", "conflict")


def test_candidate_only_and_fallback_only_are_soft(con):
    D.add_term(con, "dorsal", "背部", "杨孙", domain="分类学")
    assert C.classify(hits(con, "dorsal")).reason == "candidate-only"
    D.add_term(con, "adaptive radiation", "适应辐射", "Futuyma", domain="进化生物学", status="已核")
    c = C.classify(hits(con, "adaptive radiation"))
    assert (c.kind, c.reason) == ("SOFT", "fallback-only")
    assert C.classify([]).kind == "SOFT"


def test_own_candidate_plus_fallback_verified_is_soft_not_hard(con):
    D.add_term(con, "population", "种群", "杨孙", domain="分类学")  # 候选
    D.add_term(con, "population", "居群", "洪德元", domain="进化生物学", status="已核")
    assert C.classify(hits(con, "population")).kind == "SOFT"


def test_own_verified_beats_fallback_different_zh(con):
    D.add_term(con, "population", "种群", "user", domain="分类学", status="已核")
    D.add_term(con, "population", "居群", "洪德元", domain="进化生物学", status="已核")
    c = C.classify(hits(con, "population"))
    assert (c.kind, c.zh) == ("HARD", "种群")


def test_fallback_only_taxon_is_soft(con):
    D.add_term(con, "Drosophila", "果蝇属", "洪德元", domain="进化生物学")
    assert C.classify(hits(con, "Drosophila")).kind == "SOFT"


# ---------- 步骤 3a：docstore 中文用例（可选依赖） ----------

from yiku import usage as U  # noqa: E402


@pytest.fixture
def store(tmp_path):
    from docstore.store import Store, make_version
    st = Store(tmp_path / "lib")
    st.register(None, key="Futuyma_zh", kind="译本", lang="zh", domain="进化生物学", tier="5", title="Futuyma")
    st.register(None, key="动物志33", kind="志书", lang="zh", domain="分类学", tier="1", title="动物志")
    st.register(None, key="Handbook译稿", kind="本项目译稿", lang="zh", domain="分类学", title="本项目译稿")
    st.register(None, key="Rouse_en", kind="英文原著", lang="en", domain="分类学", title="Rouse")

    def put(key, n, text):
        st.put_version(key, n, make_version(text, "text_layer", producer="t"))
    put("Futuyma_zh", 7, "第一段无关文字很长很长很长很长很长很长很长很长很长很长很长很长。同塑性是指两个物种拥有相似的性状，"
                         "但并非源自共同祖先，包括趋同和平行进化。后面还有很长很长很长很长很长很长很长很长很长的文字。")
    put("动物志33", 3, "本科的体前部刚节明显，同塑性状较多；后面接着一段无关的很长很长很长很长很长很长很长很长很长文字。")
    put("Handbook译稿", 1, "我们的译稿里也写到同塑性，但这不能当作用例。")
    put("Rouse_en", 2, "homoplasy 同塑性 appears here in English book")
    return st


def test_kwic_window_and_cite(store):
    f = U.UsageFinder(store, width=12)
    ex = f.examples("同塑性", ["Futuyma_zh"], n=2)
    assert len(ex) == 1 or len(ex) == 2
    first = ex[0]
    assert "【同塑性】" in first and "Futuyma_zh p.7" in first
    inner = first.split("【同塑性】")
    assert len(inner[0].lstrip("…")) <= 12 + 1  # 左窗 12 字（加省略号）


def test_prefers_source_book_then_fills_from_other_zh_books(store):
    f = U.UsageFinder(store, width=15)
    ex = f.examples("同塑性", ["动物志33"], n=2)
    assert ex[0].endswith("（动物志33 p.3）") or "动物志33 p.3" in ex[0]
    assert any("Futuyma_zh p.7" in e for e in ex)
    assert not any("Handbook译稿" in e or "Rouse_en" in e for e in ex)  # 不取本项目译稿和英文书


def test_short_zh_and_missing_store_give_no_examples(store):
    assert U.UsageFinder(store).examples("性", [], n=2) == []
    assert U.UsageFinder(None).examples("同塑性", [], n=2) == []
    assert U.default_finder().store is None  # conftest 把 DOCSTORE_ROOT 指向了不存在的目录


def test_examples_cell_is_markdown_safe(store):
    from docstore.store import make_version
    store.put_version("Futuyma_zh", 9, make_version("表格里的 | 竖线同塑性 和\n换行同塑性结束", "text_layer", producer="t"))
    for e in U.UsageFinder(store).examples("同塑性", ["Futuyma_zh"], n=3):
        assert "|" not in e and "\n" not in e


# ---------- 步骤 3b：新术语表（HARD / SOFT） ----------

SRC = ("Nereididae have a homoplasy of the antenna. Platynereis shows adaptive radiation; "
       "the chaetiger bears a cirrus and dorsal cirri.")


def tbl(con, text=SRC, **kw):
    kw.setdefault("usage", False)
    return M.term_table(con, text, "分类学", {"Nereididae"}, **kw)


def section(t, name):
    """取 '## name' 小节（到下一个 '## ' 为止）。"""
    i = t.index(f"## {name}")
    j = t.find("\n## ", i + 3)
    return t[i:j if j != -1 else len(t)]


@pytest.fixture
def lib(con):
    D.add_term(con, "Nereididae", "沙蚕科", "动物志", domain="分类学", page="64", status="已核")
    D.add_term(con, "Platynereis", "阔沙蚕属", "动物志", domain="分类学", page="209", status="已核")
    D.add_term(con, "Platynereis", "扁沙蚕属", "wiki", domain="分类学")
    D.add_term(con, "chaetiger", "刚节", "user", domain="分类学", status="已核")
    D.add_term(con, "antenna", "触手", "杨孙", domain="分类学", page="12", status="已核")
    D.add_term(con, "antenna", "触角", "wiki", domain="分类学")
    D.add_term(con, "homoplasy", "同塑", "user", domain="分类学", status="已核", context="termonline 古生物学名词")
    D.add_term(con, "homoplasy", "同塑性", "名词委", domain="分类学", status="已核", context="亲缘关系较远的生物体间的相似特性")
    D.add_term(con, "homoplasy", "同塑性", "Futuyma", domain="进化生物学", page="75,666", status="已核",
               context="同塑性、非同源相似性（homoplasy）：两个或多个物种拥有相似或相同的性状状态，并非源自共同祖先")
    D.add_term(con, "adaptive radiation", "适应辐射", "Futuyma", domain="进化生物学", page="500", status="已核",
               context="一个祖先谱系在较短时间内分化出多种适应不同生态位的类型")
    D.add_term(con, "cirrus", "须", "杨孙", domain="分类学", page="30")
    D.add_term(con, "cirrus", "阴茎", "洪德元", domain="进化生物学", context="阴茎（cirrus）位于阴茎囊内")
    D.add_term(con, "dorsal", "背部", "wiki", domain="分类学")
    return con


def test_table_has_hard_and_soft_sections_and_classes(lib):
    t = tbl(lib)
    hard, soft = section(t, "HARD"), section(t, "SOFT")
    assert "| Nereididae | 沙蚕科 |" in hard and "| Platynereis | 阔沙蚕属 |" in hard
    assert "| chaetiger | 刚节 |" in hard and "| antenna | 触手 |" in hard
    assert "扁沙蚕属" in hard and "触角" in hard          # 落选译名也列出，但在「其他译名」列
    assert "Nereididae" not in soft and "chaetiger" not in soft
    for en in ("homoplasy", "adaptive radiation", "cirrus", "dorsal"):
        assert f"| {en} |" in soft and f"| {en} |" not in hard


def test_homoplasy_soft_lists_every_zh_with_source_tier_status_and_fallback(lib):
    soft = section(tbl(lib), "SOFT")
    rows = [r for r in soft.splitlines() if r.startswith("| homoplasy |")]
    assert len(rows) == 3  # 同塑（user）、同塑性（名词委，自域）、同塑性（Futuyma，回退）：自域与回退分行，层级/页码不混
    zhs = {r.split("|")[2].strip() for r in rows}
    assert zhs == {"同塑", "同塑性"}
    fu = next(r for r in rows if "Futuyma" in r)
    assert "名词委" not in fu
    assert "〔回退〕" in fu and "p.75,666" in fu and "| 5 |" in fu and "| 已核 |" in fu
    assert "非同源相似性（homoplasy）" in fu                 # Futuyma 的中文定义
    user_row = next(r for r in rows if r.split("|")[2].strip() == "同塑")
    assert "user" in user_row and "| 0 |" in user_row and "〔回退〕" not in user_row


def test_fallback_only_term_appears_with_definition(lib):
    soft = section(tbl(lib), "SOFT")
    row = next(r for r in soft.splitlines() if r.startswith("| adaptive radiation |"))
    assert "适应辐射" in row and "〔回退〕" in row and "较短时间内分化" in row


def test_fallback_can_be_disabled_and_cross_domain_sense_is_marked(lib):
    t = tbl(lib, fallback_domains=[])
    assert "adaptive radiation" not in t and "同塑性、非同源相似性" not in t
    assert "回退领域：无" in t
    t2 = tbl(lib)
    assert "回退领域：进化生物学" in t2
    assert "阴茎" in section(t2, "SOFT")  # cirrus 的另一义项（植物/他域）照列，由译者按语境判断


def test_soft_conflict_flag_kept(lib):
    D.add_source(lib, "志A", "志A", "authority", domain="分类学", year=2000)
    D.add_source(lib, "志B", "志B", "authority", domain="分类学", year=2000)
    D.add_term(lib, "palp", "触须", "志A", domain="分类学", status="已核")
    D.add_term(lib, "palp", "触角", "志B", domain="分类学", status="已核")
    t = tbl(lib, "A palp is present.")
    assert "⚠冲突" in section(t, "SOFT") and "| palp |" not in section(t, "HARD")


def test_table_size_cap_keeps_all_hard_and_reports_omitted_soft(lib):
    for i in range(80):
        D.add_term(lib, f"term{i}", f"术语甲{i}", "wiki", domain="分类学", context="很长的上下文" * 20)
        D.add_term(lib, f"term{i}", f"术语乙{i}", "杨孙", domain="分类学", context="另一个很长的上下文" * 20)
    text = SRC + " " + " ".join(f"term{i}" for i in range(80))
    t = tbl(lib, text, max_chars=6000)
    assert "| Nereididae | 沙蚕科 |" in section(t, "HARD") and "| chaetiger | 刚节 |" in section(t, "HARD")
    assert len(t) <= 6000 + 400                                  # 上限只约束 SOFT；允许末尾省略说明
    assert "因篇幅省略" in t
    full = tbl(lib, text, max_chars=200000)
    assert len(full) > len(t) and "因篇幅省略" not in full


def test_hard_never_truncated_even_beyond_cap(lib):
    t = tbl(lib, max_chars=100)
    assert "| Nereididae | 沙蚕科 |" in t and "| antenna | 触手 |" in t


def test_usage_examples_in_soft_rows_only(lib, store):
    f = U.UsageFinder(store, width=10)
    t = tbl(lib, "homoplasy; chaetiger", usage=f)
    soft, hard = section(t, "SOFT"), section(t, "HARD")
    rows = [r for r in soft.splitlines() if r.startswith("| homoplasy |") and "同塑性" in r.split("|")[2]]
    assert rows and "【同塑性】" in rows[0] and "Futuyma_zh p.7" in rows[0]
    assert "【" not in hard
    assert len(re.findall(r"【同塑性】", rows[0])) <= 2


def test_usage_off_or_unavailable_still_renders(lib):
    t = tbl(lib, "homoplasy", usage=None)  # 默认 finder：DOCSTORE_ROOT 不存在
    assert "| homoplasy |" in t and "【" not in t


def test_no_hit_message(lib):
    assert "原文未命中术语库" in tbl(lib, "nothing here at all")


import re  # noqa: E402


def test_tier_split_marks_preferred_row(lib):
    soft = section(tbl(lib, "homoplasy"), "SOFT")
    user_row = next(r for r in soft.splitlines() if r.startswith("| homoplasy | 同塑 |"))
    assert "★首选" in user_row
    assert all("★首选" not in r for r in soft.splitlines() if r.startswith("| homoplasy | 同塑性 |"))


# ---------- 步骤 5：义项感知的 check ----------

def dec(en, zh, sense="s", **kw):
    return {"en": en, "zh": zh, "sense": sense, "reason": "r", "source": "杨孙 p.1", "chunk": "ch01/c00", **kw}


def test_check_hard_strict_like_before(lib):
    issues = M.check(lib, "Nereididae here, antenna too", "沙蚕科有触角。", "分类学", {"Nereididae"})
    assert [(i.en, i.level, i.expected, i.found_alternatives) for i in issues] == [("antenna", "error", "触手", ["触角"])]
    hard = M.check(lib, "A chaetiger is present.", "有一个体节。", "分类学")
    assert len(hard) == 1 and hard[0].level == "error" and hard[0].expected == "刚节"
    assert M.check(lib, "A chaetiger is present.", "有一个刚节。", "分类学") == []


def test_check_soft_without_log_is_hint_not_error(lib):
    issues = M.check(lib, "A homoplasy is shown.", "这里出现了趋同相似。", "分类学")
    assert [(i.en, i.level) for i in issues] == [("homoplasy", "提示")]
    assert issues[0].line().startswith("提示：")
    assert M.check(lib, "A homoplasy is shown.", "这里出现了同塑性。", "分类学") == []     # 任一已核译名出现即可
    assert M.check(lib, "A homoplasy is shown.", "这里出现了同塑。", "分类学") == []


def test_check_soft_candidate_only_not_reported(lib):
    assert M.check(lib, "the dorsal side", "背面", "分类学") == []


def test_check_soft_with_log_same_sense_must_agree(lib):
    log = [dec("cirrus", "须", "背须"), dec("cirrus", "触须", "背须")]
    issues = M.check(lib, "dorsal cirrus", "背须与触须。", "分类学", decisions=log)
    assert any(i.level == "error" and "同一义项" in i.line() and "背须" in i.line() for i in issues)


def test_check_soft_with_log_different_sense_allowed(lib):
    log = [dec("cirrus", "须", "沙蚕背须"), dec("cirrus", "阴茎", "寡毛类交接器")]
    assert M.check(lib, "dorsal cirrus", "背部的须。", "分类学", decisions=log) == []
    assert M.check(lib, "the cirrus of the male", "雄性的阴茎。", "分类学", decisions=log) == []


def test_check_soft_with_log_requires_logged_zh_in_text(lib):
    log = [dec("cirrus", "须", "沙蚕背须")]
    issues = M.check(lib, "dorsal cirrus", "背部的触手。", "分类学", decisions=log)
    assert [(i.en, i.level) for i in issues] == [("cirrus", "error")]
    assert "须" in issues[0].line() and "决策" in issues[0].line()


def test_check_log_covers_terms_not_in_db(lib):
    log = [dec("parapodial lobe", "疣足叶", "叶"), dec("parapodial lobe", "足叶", "叶")]
    issues = M.check(lib, "A parapodial lobe is long.", "疣足叶很长。", "分类学", decisions=log)
    assert any("同一义项" in i.line() for i in issues)
    assert M.check(lib, "A parapodial lobe is long.", "疣足叶很长。", "分类学", decisions=[dec("parapodial lobe", "疣足叶")]) == []


def test_check_fallback_term_hint(lib):
    issues = M.check(lib, "adaptive radiation occurred", "发生了辐射。", "分类学")
    assert [(i.en, i.level, i.expected) for i in issues] == [("adaptive radiation", "提示", "适应辐射")]
    assert M.check(lib, "adaptive radiation occurred", "发生了辐射。", "分类学", fallback_domains=[]) == []


# ---------- CLI ----------

from yiku import cli  # noqa: E402


def _cli(tmp_path, *argv):
    with pytest.raises(SystemExit) as e:
        cli.main(["--db", str(tmp_path / "t.db"), *argv])
    return e.value.code


def test_cli_table_check_lookup_with_fallback_and_decisions(tmp_path, lib, capsys):
    lib.commit()
    src = tmp_path / "s.txt"
    src.write_text("A homoplasy and adaptive radiation near the dorsal cirrus.", encoding="utf8")
    zh = tmp_path / "z.md"
    zh.write_text("背部的须附近出现了辐射。", encoding="utf8")
    assert _cli(tmp_path, "table", str(src), "--domain", "分类学", "--no-usage") == 0
    t = capsys.readouterr().out
    assert "回退领域：进化生物学" in t and "adaptive radiation" in t
    assert _cli(tmp_path, "table", str(src), "--domain", "分类学", "--no-usage", "--fallback", "none") == 0
    t = capsys.readouterr().out
    assert "回退领域：无" in t and "adaptive radiation" not in t
    # check：提示不算错误，退出码 0
    assert _cli(tmp_path, "check", str(src), str(zh), "--domain", "分类学") == 0
    cap = capsys.readouterr()
    assert "提示：" in cap.out and "错误 0" in cap.err
    # 决策日志登记了 cirrus 的译名但译文没用 -> 错误，退出码 1
    log = tmp_path / "d.jsonl"
    log.write_text(json.dumps(dec("cirrus", "触须", "背须"), ensure_ascii=False) + "\n", encoding="utf8")
    assert _cli(tmp_path, "check", str(src), str(zh), "--domain", "分类学", "--decisions", str(log)) == 1
    assert "决策日志" in capsys.readouterr().out
    assert _cli(tmp_path, "lookup", "adaptive radiation", "--domain", "分类学") == 0
    assert "(回退)" in capsys.readouterr().out


def test_find_terms_prefilter_keeps_plural_and_hyphen_matches(con):
    D.add_term(con, "cirrus", "须", "杨孙", domain="分类学")
    D.add_term(con, "parapodium", "疣足", "杨孙", domain="分类学")
    D.add_term(con, "dorsal cirrus", "背须", "杨孙", domain="分类学")
    D.add_term(con, "Nereis pelagica", "游沙蚕", "杨孙", domain="分类学")
    D.add_term(con, "absent term", "无", "杨孙", domain="分类学")
    f = M.find_terms(con, "The parapodia bear dorsal cirri; cirri are long; Nereis\npelagica occurs.", "分类学")
    assert f == {"dorsal cirrus": 1, "cirrus": 1, "parapodium": 1, "nereis pelagica": 1}


def test_kwic_skips_toc_and_garbled_windows(store):
    from docstore.store import make_version
    store.put_version("Futuyma_zh", 20, make_version("等级 3.4.2 抱子纲 11 49 1.6.3 同塑性的概念 3. 4. 3 抱子纲 50 1.6.4 完", "text_layer", producer="t"))
    store.put_version("Futuyma_zh", 21, make_version("ab12 cd34 xx同塑性yy ef56 gh78 ij90 kl11", "text_layer", producer="t"))
    pages = {e.rsplit("p.", 1)[1].rstrip("）") for e in U.UsageFinder(store, width=40).examples("同塑性", ["Futuyma_zh"], n=5)}
    assert "20" not in pages and "21" not in pages and "7" in pages


def test_kwic_skips_occurrences_inside_longer_sibling_zh(store):
    from docstore.store import make_version
    store.put_version("Futuyma_zh", 30, make_version("这里只有同塑性很常见这一种说法而已，别无其他的任何内容。", "text_layer", producer="t"))
    store.put_version("Futuyma_zh", 31, make_version("在系统发生分析中，同塑状态需要额外的步骤来解释这种相似性。", "text_layer", producer="t"))
    f = U.UsageFinder(store, width=10)
    pages = {e.rsplit("p.", 1)[1].rstrip("）") for e in f.examples("同塑", ["Futuyma_zh"], n=5, longer=["同塑性"])}
    assert "31" in pages and "30" not in pages and "7" not in pages  # p.7 也只有「同塑性」
    assert {e.rsplit("p.", 1)[1].rstrip("）") for e in f.examples("同塑", ["Futuyma_zh"], n=5)} >= {"30", "31", "7"}


def test_table_gives_examples_once_per_zh_and_avoids_longer_sibling(lib, store):
    f = U.UsageFinder(store, width=10)
    t = tbl(lib, "homoplasy", usage=f)
    rows = [r for r in section(t, "SOFT").splitlines() if r.startswith("| homoplasy |")]
    shortrow = next(r for r in rows if r.split("|")[2].strip() == "同塑")
    assert "【同塑】" not in shortrow  # 库里「同塑」只出现在「同塑性」里，不算用例
    same = [r for r in rows if r.split("|")[2].strip() == "同塑性"]
    assert sum("【同塑性】" in r for r in same) == 1  # 自域行与回退行相同译名：用例只出现一次
