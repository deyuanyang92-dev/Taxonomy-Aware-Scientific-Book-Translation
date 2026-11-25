"""taxadb 切分与规则测试。全部用自造样本，不含书籍正文。"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from taxadb.db import TREATMENT_COLS, USAGE_COLS, open_db
from taxadb.rules import load_rules, resolve_rules_path
from taxadb.split import (
    despace,
    epithet_split,
    fmt_author,
    match_title,
    normalize,
    split_rest,
    split_volume,
    usages,
)

REPO = Path(__file__).resolve().parent.parent
RULES = str(REPO / "taxadb" / "rules" / "动物志.toml")


MIN_RULES = """\
[work]
body_pages = [1, 500]
page_offset = 0

[inventory]
expected_species = 1
source = "测试"

[heading]
species = '^\\s*[（(]\\s*(?P<num>\\d{1,3})\\s*[)）]?\\s*(?P<zh>[^A-Za-z（(\\d]{1,24}?)\\s*(?P<rest>[A-Z].*)$'
zh_suffix = '\\s*[，,、]?\\s*(新种|新亚种|新纪录|新记录)$'
max_wrap_lines = 2
stop = [
  '^\\s*\\d{1,2}\\s*[.．，,、]\\s*[^\\sA-Za-z]{1,12}属\\s*[A-Z]',
  '^\\s*参考文献\\s*$',
]
genus = '^\\s*\\d{1,2}\\s*[.．，,、]\\s*(?P<zh>[^\\sA-Za-z]{1,12}属)\\s*(?P<latin>[A-Z][a-z]+)'

[sections]
names = { "标本采集地" = "标本采集地", "形态特征" = "形态特征", "地理分布" = "地理分布", "讨论" = "讨论" }
required = ["标本采集地", "形态特征", "地理分布"]
sentence_end = "。．.)）;；"

[legend]
start = '^\\s*图\\s*\\d{1,3}\\s*(?:$|[^\\dA-Za-z）)，,、。；;：:\\s])'
item = '^\\s*[A-Z1Il]\\s*(?:[一—\\-–]\\s*[A-Z]\\s*)?[.。，,、:：]?\\s*[一-鿿第（(]'
inner_item = '[：:；;]\\s*[A-Z1Il]\\s*(?:[一—\\-–]\\s*[A-Z]\\s*)?[.。，,、]'
tail = '^\\s*[（(](仿|引自|据)'
short_tail = 12

[page]
header_max_lines = 5
header = [
  '^\\d{1,3}$',
  '^《?中国动物志》?$',
  '^环节动物门\\s*(多毛纲)?$',
  '^多毛纲\\s*(Ⅱ.{0,2}沙蚕.)?$',
  '^[ⅠⅡⅢIl正].{0,2}沙蚕[目自]$',
  '^[^\\sA-Za-z\\d]{1,10}(科|属|亚科)$',
  '^(总论|各论)$',
]
noise = []

[merge]
enabled = false

[normalize]
range_dash = true
"""


def mk_rules(tmp_path: Path, overrides: str = "") -> str:
    """在 tmp_path 写一份最小规则；overrides 为追加段落（不可与模板重复）。"""
    p = tmp_path / "rules.toml"
    p.write_text(MIN_RULES + overrides, encoding="utf-8")
    return str(p)


def mk_page(n: int, text: str, engine: str = "RapidOCR 300dpi", alternates: list | None = None) -> dict:
    return {"page": n, "text": text, "engine": engine, "producer": "codex", "alternates": alternates or []}


# ---------------------------------------------------------------- 规则加载
def test_load_rules():
    r = load_rules(RULES)
    assert r.expected_species == 203
    assert r.body_pages == (63, 451)
    assert r.page_offset == 0
    assert "标本采集地" in r.section_names
    assert r.range_dash is True
    assert r.species.match("(19）羊角沙蚕Ceratonereishircinicola（Eisig，1869）")


def test_resolve_rules_path():
    assert resolve_rules_path("动物志").name == "动物志.toml"
    assert resolve_rules_path(RULES) == Path(RULES)
    with pytest.raises(FileNotFoundError):
        resolve_rules_path("不存在的规则")


# ---------------------------------------------------------------- 标题行
def test_match_title_basic():
    r = load_rules(RULES)
    m = match_title("(19）羊角沙蚕Ceratonereishircinicola（Eisig，1869）", r)
    assert m and m["num"] == 19 and m["zh"] == "羊角沙蚕"
    assert "Ceratonereishircinicola" in m["rest"]
    # 新种后缀剥离
    m = match_title("(124）柳珊瑚单裂虫，新种Haplosyllis gorgoniacolo Sun et Yang，sp.nov.", r)
    assert m and m["zh"] == "柳珊瑚单裂虫" and m["tag"] == "新种"
    # 编号独立成行后的合并形式
    m = match_title("(114) 单钩鳃裂虫Branchiosyllis abranchiata Hartmann-Schroder,1965（图171)", r)
    assert m and m["num"] == 114 and m["zh"] == "单钩鳃裂虫"


def test_match_title_rejects_non_cjk():
    r = load_rules(RULES)
    assert match_title("(1) English name Latinus species Linnaeus, 1758", r) is None


# ---------------------------------------------------------------- 学名与命名人
def test_split_rest():
    d = split_rest("CeratonereismirabilisKinberg，1866（图53，图54)", ["Ceratonereis"], "Ceratonereis")
    assert d["genus"] == "Ceratonereis"
    assert d["run"] == "mirabilis"
    assert d["author_raw"] == "Kinberg，1866"
    assert "图53" in d["figures"] and "图54" in d["figures"]


def test_split_rest_parenthesized_year():
    d = split_rest("Perinereiscavifrons（Ehlers，1920）（图105)", ["Perinereis"], "Perinereis")
    assert d["genus"] == "Perinereis"
    assert d["run"] == "cavifrons"
    assert d["author_raw"] == "（Ehlers，1920）"
    assert "图105" in d["figures"]


def test_fmt_author():
    assert fmt_author("SunetYang，sp.nov.") == "Sun et Yang, sp. nov."
    assert fmt_author("（Eisig，1869）") == "(Eisig, 1869)"
    assert fmt_author("ImajimaetHartman，1964") == "Imajima et Hartman, 1964"
    assert fmt_author("Malmgren，1867") == "Malmgren, 1867"


def test_epithet_split_votes():
    sources = ["Nereis zonata Malmgren, 1867", "Nereis pelagica Linnaeus, 1758"]
    assert epithet_split("zonata", "Nereis", sources)[0] == ["zonata"]
    # 无空格串拆成 种加词+亚种加词，由异名列表投票
    eps, why = epithet_split("aciculataorientalis", "Typosyllis",
                             ["Typosyllis aciculata orientalis Imajima et Hartman, 1964"])
    assert eps == ["aciculata", "orientalis"] and not why


# ---------------------------------------------------------------- 规范化（范围号）
def test_normalize_range_dash():
    r = load_rules(RULES)
    t, c = normalize("第17一20刚节，水深37一54m，2一3斜排", r)
    assert t == "第17—20刚节，水深37—54m，2—3斜排"
    assert c["范围号→—"] == 3
    # 年份不受影响
    t2, _ = normalize("1869年", r)
    assert t2 == "1869年"


def test_normalize_off():
    r = load_rules(RULES)
    r.range_dash = False
    t, c = normalize("17一20", r)
    assert t == "17一20" and not c


# ---------------------------------------------------------------- 图注剥离
SAMPLE_PAGE = """中国动物志
环节动物门
多毛纲
100
Ⅱ.沙蚕目
19.沙蚕属Ceratonereis
(19）羊角沙蚕Ceratonereishircinicola（Eisig，1869）
Ceratonereis hircinicola (Eisig, 1869)
标本采集地 南海北部（水深37一54m）。
形态特征 体细长。吻上具齿，前伸可达第17一20刚节（图53C）。
地理分布 分布于南海；日本。
图53 羊角沙蚕Ceratonereis hircinicola (Eisig)
A.体前部背面观：B.吻腹面观。
"""


def test_split_volume_basic():
    r = load_rules(RULES)
    pages = [mk_page(100, SAMPLE_PAGE)]
    res = split_volume(pages, r, key="样本")
    assert len(res["treatments"]) == 1
    t = res["treatments"][0]
    assert t["num"] == 19
    assert t["taxon"] == "Ceratonereis hircinicola"
    assert t["author_year"] == "(Eisig, 1869)"
    assert t["zh_name"] == "羊角沙蚕"
    assert t["pdf_page_start"] == 100
    assert "37—54" in t["标本采集地"]            # 范围号已规范化
    assert "17—20" in t["形态特征"]
    # 图注剥离：不入地理分布
    assert "体前部背面观" not in t["地理分布"]
    assert "图53" in t["figure_legend"]           # 图注进入 figure_legend
    assert "A.体前部背面观" in t["figure_legend"]


def test_legend_in_text_citation_kept():
    """正文中「（图53C）」是引用，不是图注，不得剥离。"""
    r = load_rules(RULES)
    pages = [mk_page(100, SAMPLE_PAGE)]
    t = split_volume(pages, r, key="样本")["treatments"][0]
    assert "（图53C）" in t["形态特征"]


def test_standalone_number_title():
    """编号独立成行的标题（卷33 种114 版式）合并后识别。"""
    r = load_rules(RULES)
    text = """裂虫科
296
单裂虫属
(114)
单钩鳃裂虫Branchiosyllis abranchiata Hartmann-Schroder,1965（图171)
标本采集地 南海。
形态特征 体细长。
地理分布 分布于南海：太平洋（萨摩亚群岛）。
"""
    pages = [mk_page(296, text)]
    res = split_volume(pages, r, key="样本")
    assert len(res["treatments"]) == 1
    t = res["treatments"][0]
    assert t["num"] == 114
    assert t["taxon"] == "Branchiosyllis abranchiata"
    assert t["author_year"] == "Hartmann-Schroder, 1965"
    assert t["zh_name"] == "单钩鳃裂虫"


def test_treatment_boundaries_and_stop():
    """下一属标题或检索表终止记述。"""
    r = load_rules(RULES)
    pages = [mk_page(100, """各论
(1）甲种Genusuna Linnaeus，1758
标本采集地 东海。
形态特征 体小。
地理分布 分布于东海。
1.乙属Genusduo
(2）乙种Genusduo b Marenzeller，1879
标本采集地 南海。
形态特征 体大。
地理分布 分布于南海。
""")]
    res = split_volume(pages, r, key="样本")
    ts = res["treatments"]
    assert [t["num"] for t in ts] == [1, 2]
    assert ts[0]["genus"] == "Genusuna"
    assert "Genusduo" not in ts[0]["original_text"]
    assert ts[1]["genus"] == "Genusduo"


def test_usages():
    r = load_rules(RULES)
    pages = [mk_page(100, SAMPLE_PAGE)]
    t = split_volume(pages, r, key="样本")["treatments"][0]
    us = usages(t)
    assert us[0]["usage_type"] == "有效名（本书采用）"
    assert us[0]["taxon"] == "Ceratonereis hircinicola"
    syn = [u for u in us if u["usage_type"] != "有效名（本书采用）"]
    assert any(u["name_as_printed"] == "Ceratonereis hircinicola" for u in syn)


def test_inventory_mismatch_flagged(tmp_path):
    """清单（金标准）与标题不一致时报 flags。"""
    inv_block = """[inventory]
expected_species = 1
source = "测试清单"
pages = [2, 2]
line = '^\\s*[（(]\\s*(?P<num>\\d{1,3})\\s*[)）]\\s*(?P<zh>[^A-Za-z（(]+?)\\s*(?P<latin>[A-Z][A-Za-z\\s.\\-/]*)$'
"""
    rules_text = MIN_RULES.replace("""[inventory]
expected_species = 1
source = "测试"
""", inv_block)
    p = tmp_path / "rules.toml"
    p.write_text(rules_text, encoding="utf-8")
    r = load_rules(str(p))
    pages = [mk_page(2, "(1）甲种Genusuna Linnaeus，1758"),
             mk_page(100, """(1）甲种Genusuna Linnaeus，1758
标本采集地 东海。
形态特征 体小。
地理分布 分布于东海。
""")]
    res = split_volume(pages, r, key="样本")
    t = res["treatments"][0]
    assert t["zh_name"] == "甲种"


def test_despace():
    assert despace("Ceratonereis hircinicola") == "Ceratonereishircinicola"
    assert despace("（Eisig， 1869）") == "（Eisig，1869）"


# ---------------------------------------------------------------- 数据库
def test_db_schema(tmp_path):
    con = open_db(tmp_path / "taxa.sqlite")
    for table in ("work", "treatment", "name_usage", "field_check"):
        n = con.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()[0]
        assert n == 1, table
    assert "taxon" in TREATMENT_COLS and "地理分布" in TREATMENT_COLS
    assert "usage_type" in USAGE_COLS
    con.close()


# ---------------------------------------------------------------- CLI（自造库根）
def _mk_docstore(root: Path, key: str, pages: list[dict]) -> None:
    """在临时目录造一个最小 docstore 库（registry.tsv + pages/<key>/pNNNN.json）。"""
    import json
    from docstore.store import FIELDS
    (root / "pages" / key).mkdir(parents=True)
    for p in pages:
        (root / "pages" / key / f"p{p['page']:04d}.json").write_text(json.dumps(p), encoding="utf-8")
    row = {k: "" for k in FIELDS}
    row.update({"key": key, "pages": str(len(pages)), "kind": "志书", "lang": "zh", "domain": "分类学",
                "title": "样本书", "page_offset": "0", "status": "registered", "note": "测试样本",
                "added_by": "测试"})
    (root / "registry.tsv").write_text(
        "\t".join(FIELDS) + "\n" + "\t".join(str(row[k]) for k in FIELDS) + "\n", encoding="utf-8")


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "taxadb.cli", *args], capture_output=True, text=True, cwd=REPO)


def test_cli_split_dry_and_db(tmp_path, monkeypatch):
    root = tmp_path / "store"
    _mk_docstore(root, "样本", [mk_page(100, SAMPLE_PAGE)])
    rules = mk_rules(tmp_path)
    db = tmp_path / "taxa.sqlite"
    monkeypatch.setenv("DOCSTORE_ROOT", str(root))
    monkeypatch.setenv("TAXADB_PATH", str(db))
    monkeypatch.setenv("TAXADB_AGENT", "deepseek")
    p = _run("split", "样本", "--rules", rules, "--dry")
    assert p.returncode == 0, p.stderr
    assert "切分 1" in p.stdout
    p = _run("split", "样本", "--rules", rules)
    assert p.returncode == 0, p.stderr
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    r = con.execute("SELECT * FROM treatment WHERE work_id='样本'").fetchone()
    assert r["taxon"] == "Ceratonereis hircinicola"
    assert r["verify_status"] == "机器初识"
    w = con.execute("SELECT expected_species, split_by FROM work WHERE work_id='样本'").fetchone()
    assert w["expected_species"] == 1 and w["split_by"] == "deepseek"
    p = _run("export", "--work", "样本", "--format", "tsv")
    assert p.returncode == 0 and "Ceratonereis" in p.stdout
    p = _run("verify", "样本")
    assert p.returncode == 0
    p = _run("status")
    assert p.returncode == 0 and "样本" in p.stdout


def test_cli_check_import(tmp_path, monkeypatch):
    import json
    root = tmp_path / "store"
    _mk_docstore(root, "样本", [mk_page(100, SAMPLE_PAGE)])
    rules = mk_rules(tmp_path)
    db = tmp_path / "taxa.sqlite"
    monkeypatch.setenv("DOCSTORE_ROOT", str(root))
    monkeypatch.setenv("TAXADB_PATH", str(db))
    _run("split", "样本", "--rules", rules)
    f = tmp_path / "check.jsonl"
    f.write_text(json.dumps({"treatment_id": "样本:019", "field": "地理分布", "db_value": "分布于南海；日本。",
                             "page_value": "分布于南海；日本。", "ok": 1, "pdf_page": 100, "note": "测试"}, ensure_ascii=False)
                 + "\n" + json.dumps({"treatment_id": "样本:019", "field": "taxon", "db_value": "x",
                                      "page_value": "Ceratonereis hircinicola", "ok": 0, "pdf_page": 100}) + "\n")
    p = _run("check", str(f), "--key", "样本")
    assert p.returncode == 0, p.stderr
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    r = con.execute("SELECT taxon, verify_status FROM treatment WHERE work_id='样本'").fetchone()
    assert r["taxon"] == "Ceratonereis hircinicola"   # 修正生效（仅 2 个字段已核，不算全部关键字段）
