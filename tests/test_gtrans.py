"""gtrans：Google 免费初译 → 脚本修正 → DeepSeek 核对润色。Google 与模型引擎全部用假实现，不联网。"""
import json
import os
import urllib.error
import urllib.parse
from pathlib import Path
from typing import Any

import pytest

import gtrans

TABLE = """领域：进化生物学

## HARD（必用）
| 英文 | 译名 | 依据 | 状态 | 其他译名（不用） |
|---|---|---|---|---|
| natural selection | 自然选择 | Futuyma p.651 | 已核 |  |

## SOFT（先判义项，再取舍）
| 英文 | 译名 | 依据 | 层级 | 状态 | 定义/出处语境 | 中文用例 |
|---|---|---|---|---|---|---|
| lineage | 谱系；世系 | x | 1 | 候选 |  |  |
"""

DOC = """## ORIGIN OF SPECIES

<!-- p.13 -->
Darwin proposed natural selection in 1859. Each lineage evolves significantly. The lineage splits later.

<!-- p.14 -->
Fig. 1. A diagram of natural selection.
"""

BODY_EN = "Darwin proposed natural selection in 1859. Each lineage evolves significantly. The lineage splits later."
ZH = {
    "Origin of Species": "物种起源",
    BODY_EN: "达尔文于1859年提出了自然淘汰。每个谱系都会显着进化。该世系后来分裂。",
    "Fig. 1. A diagram of natural selection.": "图1。自然淘汰示意图。",
    "natural selection": "自然淘汰",
}


class Net:
    def __init__(self) -> None:
        self.queries: list[str] = []
        self.sleeps: list[float] = []


@pytest.fixture
def net(monkeypatch: pytest.MonkeyPatch) -> Net:
    n = Net()

    def http_get(url: str, timeout: float = 30) -> str:
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["q"][0]
        n.queries.append(q)
        return json.dumps([[[ZH.get(q, "译:" + q), q, None, None, 1]], None, "en"])

    monkeypatch.setattr(gtrans, "http_get", http_get)
    monkeypatch.setattr(gtrans, "_sleep", n.sleeps.append)
    monkeypatch.setattr(gtrans, "yiku_table", lambda en, domain: TABLE)
    monkeypatch.setattr(gtrans, "open_yiku", lambda domain: None)
    monkeypatch.setattr(gtrans.fc, "load_persons", lambda *a, **k: {})
    monkeypatch.delenv("YZZ_DEEPSEEK_THINKING", raising=False)
    return n


class Engine:
    """假 engine_call：按 (是否开思考, 单元是正文还是图注) 选回复，记录每次调用。"""

    def __init__(self, replies: dict[str, str]):
        self.replies = replies
        self.calls: list[dict[str, Any]] = []

    def __call__(self, engine: str, system: str, user: str, *, max_tokens: int, tag: str) -> tuple[str, dict[str, Any]]:
        think = bool(os.environ.get("YZZ_DEEPSEEK_THINKING"))
        self.calls.append({"engine": engine, "user": user, "think": think, "tag": tag, "max_tokens": max_tokens})
        key = ("think" if think else "nothink") + (":body" if "Each lineage" in user else ":caption")
        return self.replies.get(key, "[]"), {"input_tokens": 100, "output_tokens": 10}


def go(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, replies: dict[str, str] | None = None, **kw: Any) -> tuple[Engine, Path]:
    eng = Engine(replies or {})
    monkeypatch.setattr(gtrans, "engine_call", eng)
    src = tmp_path / "in.txt"
    src.write_text(DOC, encoding="utf8")
    o = gtrans.Opts(cache=str(tmp_path / "cache.sqlite"), stem="in", **kw)
    out = tmp_path / "out"
    gtrans.run(src, out, o)
    return eng, out


# ---------------------------------------------------------------- 切块、缓存、重试

def test_split_sentences_keeps_abbreviations():
    s = gtrans.split_sentences("See Fig. 3 here. Smith et al. said so. A. R. Wallace agreed. Done.")
    assert s == ["See Fig. 3 here.", "Smith et al. said so.", "A. R. Wallace agreed.", "Done."]


def test_split_chunks_limit_and_order():
    sents = [f"Sentence number {i} is about evolution and speciation." for i in range(200)]
    text = " ".join(sents)
    chunks = gtrans.split_chunks(text, 1000)
    assert len(chunks) > 1 and all(len(c) <= 1000 for c in chunks)
    assert " ".join(chunks) == text                         # 只在句子边界切，顺序不变
    assert all(c.endswith(".") for c in chunks)
    assert gtrans.split_chunks("short text.") == ["short text."]


def test_split_chunks_oversize_sentence_hard_split():
    text = " ".join(["word"] * 300)                           # 一句，无句号
    chunks = gtrans.split_chunks(text, 200)
    assert all(len(c) <= 200 for c in chunks) and " ".join(chunks) == text


def test_cache_hit_across_instances(net: Net, tmp_path: Path):
    p = tmp_path / "c.sqlite"
    g1 = gtrans.Google(gtrans.Cache(p))
    assert g1.translate("natural selection") == "自然淘汰"
    assert g1.translate("natural selection") == "自然淘汰"
    g2 = gtrans.Google(gtrans.Cache(p))                     # 新实例、同一文件
    assert g2.translate("natural selection") == "自然淘汰"
    assert net.queries == ["natural selection"] and g2.requests == 0 and g2.hits == 1
    assert gtrans.Cache.key("x") == "11f6ad8ec52a2984abaafd7c3b516503785c2072"   # sha1


def test_long_text_is_chunked_into_requests(net: Net, tmp_path: Path):
    g = gtrans.Google(gtrans.Cache(tmp_path / "c.sqlite"))
    text = " ".join(f"Sentence number {i} is about evolution and speciation." for i in range(150))
    g.translate(text)
    assert len(net.queries) >= 2 and all(len(q) <= gtrans.CHUNK_MAX for q in net.queries)
    assert all(1.0 <= s <= 2.0 for s in net.sleeps)          # 礼貌间隔
    n = len(net.queries)
    g.translate(text)                                         # 各块已缓存
    assert len(net.queries) == n


def test_retry_with_exponential_backoff(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    sleeps: list[float] = []
    codes = [429, 503]

    def flaky(url: str, timeout: float = 30) -> str:
        if codes:
            raise urllib.error.HTTPError(url, codes.pop(0), "busy", {}, None)  # type: ignore[arg-type]
        return json.dumps([[["好", "ok", None, None, 1]]])

    monkeypatch.setattr(gtrans, "http_get", flaky)
    monkeypatch.setattr(gtrans, "_sleep", sleeps.append)
    g = gtrans.Google(gtrans.Cache(tmp_path / "c.sqlite"))
    assert g.translate("ok") == "好" and g.requests == 3
    backoff = sleeps[1:]                                      # 第 0 个是请求前的礼貌间隔
    assert len(backoff) == 2 and backoff[0] >= 5 and backoff[1] >= 10


def test_gives_up_after_max_retries(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    def bad(url: str, timeout: float = 30) -> str:
        raise urllib.error.HTTPError(url, 500, "boom", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr(gtrans, "http_get", bad)
    monkeypatch.setattr(gtrans, "_sleep", lambda s: None)
    g = gtrans.Google(gtrans.Cache(tmp_path / "c.sqlite"))
    with pytest.raises(gtrans.GoogleError):
        g.translate("x")
    assert g.requests == gtrans.MAX_RETRIES + 1


def test_client_error_not_retried(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    def bad(url: str, timeout: float = 30) -> str:
        raise urllib.error.HTTPError(url, 403, "no", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr(gtrans, "http_get", bad)
    monkeypatch.setattr(gtrans, "_sleep", lambda s: None)
    g = gtrans.Google(gtrans.Cache(tmp_path / "c.sqlite"))
    with pytest.raises(gtrans.GoogleError):
        g.translate("x")
    assert g.requests == 1


# ---------------------------------------------------------------- 解析

def test_parse_blocks_kinds_and_page_join():
    text = ("INTEGUMENT\n\n<!-- p.5 -->\nThe lineage that was split\n\n<!-- p.6 -->\nlater on again.\n\n"
            "Fig. 2. A worm.\n\n# Title Line\n\nNew para.\n")
    b = gtrans.parse_blocks(text)
    assert [(x.kind, x.en) for x in b] == [
        ("heading", "INTEGUMENT"), ("marker", "<!-- p.5 -->"),
        ("para", "The lineage that was split later on again."), ("marker", "<!-- p.6 -->"),   # 标记移到合并段之后
        ("caption", "Fig. 2. A worm."), ("heading", "# Title Line"), ("para", "New para.")]
    assert b[0].level == 2 and b[5].level == 1


def test_build_units_merge_and_boundaries():
    paras = "\n\n".join(f"<!-- p.{i} -->\n" + " ".join(["word"] * 40) + "." for i in range(1, 6))
    units = gtrans.build_units(gtrans.parse_blocks(paras), max_words=100)
    body = [u for u in units if u.kind == "body"]
    assert [u.words for u in body] == [80, 80, 40]            # 按序合并，不超 100 词
    assert sum(u.kind == "marker" for u in units) == 3        # 单元之间的标记（p.1、p.3、p.5）单独成单元，不丢
    assert sum("<!--" in u.en for u in body) == 2             # 单元内部的标记（p.2、p.4）留在单元里，随文送审


# ---------------------------------------------------------------- 脚本修正

def test_apply_fixes_term_trigger(tmp_path: Path):
    f = tmp_path / "fix.tsv"
    f.write_text("# 注释\n显着\t显著\t错字\n兄弟物种\t同胞种\tFutuyma\tsibling species\n", encoding="utf8")
    fixes = gtrans.load_fixes(f)
    zh, ap = gtrans.apply_fixes("显着的兄弟物种", "Sibling species are cool.", fixes)
    assert zh == "显著的同胞种" and len(ap) == 2
    zh, ap = gtrans.apply_fixes("显着的兄弟物种", "Nothing relevant here.", fixes)    # 英文没有触发词：只改无触发词的
    assert zh == "显著的兄弟物种" and len(ap) == 1


def test_seed_table_present():
    rows = {f.wrong: f for f in gtrans.load_fixes()}
    assert {"显着", "兄弟物种", "脑电波", "本质主义"} <= set(rows)
    assert rows["脑电波"].right == "灵感" and rows["显着"].term == ""
    zh, _ = gtrans.apply_fixes("他记下了脑电波", "He wrote down his brain waves.", list(rows.values()))
    assert zh == "他记下了灵感"
    zh, _ = gtrans.apply_fixes("脑电波", "Electroencephalography", list(rows.values()))
    assert zh == "脑电波"


def test_parse_table_hard_soft():
    hard, soft = gtrans.parse_table(TABLE)
    assert hard == [("natural selection", "自然选择")] and soft == [("lineage", "谱系；世系")]


def test_replace_google_terms_and_guards():
    probe = {"natural selection": "自然淘汰", "selection": "选择", "gene": "基因"}.get
    zh, ap = gtrans.replace_google_terms("自然淘汰是自然选择的一种，自然淘汰很重要。", [("natural selection", "自然选择")],
                                         lambda t: probe(t, ""))
    assert zh == "自然选择是自然选择的一种，自然选择很重要。" and "×2" in ap[0]
    # Google 译法落在定名内部（选择 ⊂ 自然选择）：不动，免得叠字
    zh, ap = gtrans.replace_google_terms("自然选择与选择", [("selection", "自然选择")], lambda t: probe(t, ""))
    assert zh == "自然选择与选择" and not ap


def test_consistency_warning():
    en = "Each lineage evolves. The lineage splits. Sibling species arise. Sibling species persist."
    hard, soft = [("sibling species", "同胞种")], [("lineage", "谱系；世系")]
    var = {"sibling species": {"姐妹种"}}
    w = gtrans.consistency("谱系进化。世系分裂。同胞种出现。同胞种存续。", en, hard, soft, var)
    assert len(w) == 1 and "lineage" in w[0] and "谱系" in w[0] and "世系" in w[0]
    w = gtrans.consistency("谱系进化。谱系分裂。同胞种出现。姐妹种存续。", en, hard, soft, var)
    assert len(w) == 1 and "sibling species" in w[0]
    assert gtrans.consistency("谱系进化。世系分裂。", "Each lineage evolves once.", [], soft, {}) == []   # 英文只出现 1 次不报


def test_tidy_spaces():
    assert gtrans.tidy("1837 年夏天，达尔文。 Kohn （1981）等人 提出第 3 章") == "1837年夏天，达尔文。Kohn（1981）等人 提出第3章"
    assert gtrans.tidy("甲\n乙 丙") == "甲\n乙 丙"


def test_place_name_latin_warning_does_not_escalate(net: Net, tmp_path: Path):
    r = gtrans.Runner(gtrans.Opts(dry=True), gtrans.Google(gtrans.Cache(tmp_path / "c.sqlite")))
    place = gtrans.fc.Issue("拉丁名", "Patagonia", "中文里没有出现")
    assert not r.actionable(place, "He crossed Patagonia in 1833.")
    assert r.actionable(place, "He crossed *Patagonia* in 1833.")              # 斜体：确是学名
    assert r.actionable(gtrans.fc.Issue("拉丁名", "Nereis virens", "缺"), "x")  # 双名一律报
    assert r.actionable(gtrans.fc.Issue("数字", "12 mm", "缺"), "x")


# ---------------------------------------------------------------- 带护栏的改动

def test_apply_edits_guard():
    zh = "达尔文于1859年提出了自然选择。该世系后来分裂。该世系很大。"
    edits = [
        {"old": "该世系后来分裂", "new": "该谱系后来分裂", "type": "术语"},       # 通过
        {"old": "该世系", "new": "该谱系", "type": "术语"},                       # 前一条改完后「该世系」只剩一处，故也通过
        {"old": "1859年", "new": "1860年", "type": "误译"},                        # 年份被改 → polish_guard 拒绝
        {"old": "自然选择", "new": "天择", "type": "术语"},                        # HARD 术语减少 → 拒绝
        {"old": "不存在的片段", "new": "x", "type": "润色"},                       # old 不存在
        {"old": "", "new": "x"},                                                  # 空 old
    ]
    new, ok, bad = gtrans.apply_edits(zh, edits, ["自然选择"])
    assert new == "达尔文于1859年提出了自然选择。该谱系后来分裂。该谱系很大。"
    assert [e["orig_type"] for e in ok] == ["术语", "术语"]
    reasons = " ".join(e["reject"] for e in bad)
    assert "年份" in reasons and "HARD" in reasons and "0 次" in reasons and "old" in reasons
    assert len(bad) == 4


def test_apply_edits_old_ambiguous_rejected():
    new, ok, bad = gtrans.apply_edits("世系甲。世系乙。", [{"old": "世系", "new": "谱系"}], [])
    assert new == "世系甲。世系乙。" and not ok and "2 次" in bad[0]["reject"]


def test_parse_edits_tolerates_fences_and_garbage():
    assert gtrans.parse_edits('```json\n[{"old":"a","new":"b"}]\n```') == [{"old": "a", "new": "b"}]
    assert gtrans.parse_edits("没有问题") == [] and gtrans.parse_edits("[坏 json]") == []


# ---------------------------------------------------------------- 端到端（假 Google、假引擎）

def test_e2e_markers_terms_and_edits(net: Net, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    fix = json.dumps([{"old": "该世系后来分裂", "new": "该谱系后来分裂", "type": "术语"}], ensure_ascii=False)
    eng, out = go(tmp_path, monkeypatch, {"nothink:body": fix})
    zh = (out / "zh.md").read_text(encoding="utf8")
    assert all("<!--" not in q for q in net.queries)                       # 页码标记不送 Google
    assert zh.index("<!-- p.13 -->") < zh.index("达尔文") < zh.index("<!-- p.14 -->") < zh.index("图1")
    assert "## 物种起源（Origin of Species）" in zh                          # 标题双语
    assert "自然淘汰" not in zh and zh.count("自然选择") == 2                 # Google 的术语译法换成 yiku 定名（正文、图注各一处）
    assert "显着" not in zh and "显著" in zh                                 # 修正表
    assert "该谱系后来分裂" in zh and "世系" not in zh                       # LLM 改动被采纳
    assert len(eng.calls) == 2 and not any(c["think"] for c in eng.calls)  # 正文、图注各一次，不开思考
    assert eng.calls[0]["engine"] == "deepseek-flash" and "## HARD" in eng.calls[0]["user"]
    assert "YZZ_DEEPSEEK_THINKING" not in os.environ
    rep = (out / "report.md").read_text(encoding="utf8")
    assert "采纳 1，拒绝 0" in rep and "输入 200 / 输出 20 token" in rep and "显着→显著" in rep
    assert "natural selection: 自然淘汰→自然选择" in rep
    edits = [json.loads(x) for x in (out / "edits.jsonl").read_text(encoding="utf8").splitlines()]
    assert [e["status"] for e in edits] == ["applied"]


def test_e2e_rerun_costs_nothing(net: Net, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    go(tmp_path, monkeypatch, no_llm=True)
    n = len(net.queries)
    assert n >= 3
    go(tmp_path, monkeypatch, no_llm=True)
    assert len(net.queries) == n


def test_e2e_rejected_edit_logged(net: Net, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    bad = json.dumps([{"old": "1859年", "new": "1860年", "type": "误译"}], ensure_ascii=False)
    _, out = go(tmp_path, monkeypatch, {"nothink:body": bad})
    zh = (out / "zh.md").read_text(encoding="utf8")
    assert "1859年" in zh and "1860" not in zh
    rep = (out / "report.md").read_text(encoding="utf8")
    assert "采纳 0，拒绝 1" in rep and "年份被改动" in rep
    assert json.loads((out / "edits.jsonl").read_text(encoding="utf8").splitlines()[0])["status"] == "rejected"


def test_e2e_no_llm_reports_consistency_warning(net: Net, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def boom(*a: Any, **k: Any) -> None:
        raise AssertionError("--no-llm 不得调用模型")

    monkeypatch.setattr(gtrans, "engine_call", boom)
    src = tmp_path / "in.txt"
    src.write_text(DOC, encoding="utf8")
    gtrans.run(src, tmp_path / "o", gtrans.Opts(no_llm=True, cache=str(tmp_path / "c.sqlite")))
    rep = (tmp_path / "o" / "report.md").read_text(encoding="utf8")
    assert "多种译法：谱系、世系" in rep and "未调用 LLM" in rep


def test_e2e_escalate_thinks_only_flagged_units(net: Net, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    fix = json.dumps([{"old": "该世系后来分裂", "new": "该谱系后来分裂", "type": "术语"}], ensure_ascii=False)
    eng, out = go(tmp_path, monkeypatch, {"nothink:body": "[]", "think:body": fix}, think_escalate=True)
    kinds = [(c["tag"].rsplit("/", 1)[1], c["think"]) for c in eng.calls]
    assert kinds == [("nothink", False), ("think", True), ("nothink", False)]   # 正文有警告才升级；图注无警告，不升级
    think = eng.calls[1]
    assert "脚本报警" in think["user"] and "谱系" in think["user"] and think["max_tokens"] > eng.calls[0]["max_tokens"]
    assert "YZZ_DEEPSEEK_THINKING" not in os.environ                          # 环境变量已恢复
    zh = (out / "zh.md").read_text(encoding="utf8")
    assert "该谱系后来分裂" in zh
    rep = (out / "report.md").read_text(encoding="utf8")
    assert "思考：是，入/出 100/10" in rep and "开思考的单元 1" in rep and "多种译法" not in rep


def test_e2e_no_escalate_without_flag(net: Net, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    eng, out = go(tmp_path, monkeypatch, {"nothink:body": "[]"})
    assert len(eng.calls) == 2                                                # 有警告但没加 --think-escalate
    assert "多种译法：谱系、世系" in (out / "report.md").read_text(encoding="utf8")


def test_engine_failure_keeps_google_text(net: Net, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def fail(*a: Any, **k: Any) -> None:
        raise gtrans.le.EngineError("连不上")

    monkeypatch.setattr(gtrans, "engine_call", fail)
    src = tmp_path / "in.txt"
    src.write_text(DOC, encoding="utf8")
    gtrans.run(src, tmp_path / "o", gtrans.Opts(cache=str(tmp_path / "c.sqlite")))
    assert "达尔文" in (tmp_path / "o" / "zh.md").read_text(encoding="utf8")
    assert "调用失败：连不上" in (tmp_path / "o" / "report.md").read_text(encoding="utf8")


def test_dry_run_no_network_no_model(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    def forbidden(*a: Any, **k: Any) -> None:
        raise AssertionError("--dry 不得联网或调模型")

    monkeypatch.setattr(gtrans, "http_get", forbidden)
    monkeypatch.setattr(gtrans, "engine_call", forbidden)
    monkeypatch.setattr(gtrans, "yiku_table", lambda en, domain: TABLE)
    src = tmp_path / "in.txt"
    src.write_text(DOC, encoding="utf8")
    rc = gtrans.main([str(src), "-o", str(tmp_path / "o"), "--dry", "--cache", str(tmp_path / "c.sqlite")])
    assert rc == 0 and not (tmp_path / "o").exists()
    out = capsys.readouterr().out
    assert "[dry]" in out and "单元 3" in out and "LLM 2 次" in out
