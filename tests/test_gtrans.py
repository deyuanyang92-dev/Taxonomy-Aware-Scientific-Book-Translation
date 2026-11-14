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
    kw.setdefault("llm_mode", "edits")                    # 这里的旧用例测 edits 模式；rewrite 模式见 go_rw
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


# ---------------------------------------------------------------- rewrite 模式（默认）：整段改写 + 意义核对

DRAFT = "达尔文于1859年提出了自然选择。每个谱系都会显著进化。该世系后来分裂。"
GOOD = "1859年，达尔文提出了自然选择。每个谱系都在显著进化，后来该谱系又发生分裂。"


class RwEngine:
    """假引擎：改写调用返回 rewrites[body]（图注原样返回初稿），意义核对调用返回 meaning[nothink|think]。"""

    def __init__(self, rewrite: str | None = None, meaning: dict[str, str] | None = None, rewrite_exc: bool = False):
        self.rewrite, self.meaning, self.rewrite_exc = rewrite, meaning or {}, rewrite_exc
        self.calls: list[dict[str, Any]] = []

    def __call__(self, engine: str, system: str, user: str, *, max_tokens: int, tag: str) -> tuple[str, dict[str, Any]]:
        think = bool(os.environ.get("YZZ_DEEPSEEK_THINKING"))
        self.calls.append({"engine": engine, "system": system, "user": user, "think": think, "tag": tag})
        use = {"input_tokens": 100, "output_tokens": 10}
        if system.startswith("你是名家译者"):
            if self.rewrite_exc:
                raise gtrans.le.EngineError("连不上")
            if "Each lineage" in user and self.rewrite is not None:
                return self.rewrite, use
            return user.split("## 当前中文译文\n", 1)[1], use
        assert system.startswith("你是英中译文的意义核对员") and engine == "deepseek-flash"
        return self.meaning.get("think" if think else "nothink", "[]"), use


def go_rw(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, eng: RwEngine, **kw: Any) -> Path:
    monkeypatch.setattr(gtrans, "engine_call", eng)
    src = tmp_path / "in.txt"
    src.write_text(DOC, encoding="utf8")
    gtrans.run(src, tmp_path / "out", gtrans.Opts(cache=str(tmp_path / "cache.sqlite"), stem="in", **kw))
    return tmp_path / "out"


def body_calls(eng: RwEngine, kind: str) -> list[dict[str, Any]]:
    return [c for c in eng.calls if c["tag"].split("/")[-1].startswith(kind) and "Each lineage" in c["user"]]


def test_default_mode_is_rewrite_and_system_prompt_has_style_section():
    assert gtrans.Opts().llm_mode == "rewrite" and gtrans.Opts().rewrite_engine is None
    sysmsg = gtrans.rewrite_system()
    assert sysmsg.startswith("你是名家译者，把译文改写成地道、凝练的学术中文。忠实第一")
    assert "名家逻辑" in sysmsg and "先结论后条件" in sysmsg and sysmsg.endswith("只输出改写后的完整中文，不要解释。")
    assert "## 7." not in sysmsg


def test_term_lines_compact():
    assert gtrans.term_lines(TABLE, ["x=y"]) == "natural selection=自然选择\nlineage=谱系；世系\nx=y"


def test_rewrite_accepted(net: Net, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    eng = RwEngine(rewrite=GOOD)
    out = go_rw(tmp_path, monkeypatch, eng)
    zh = (out / "zh.md").read_text(encoding="utf8")
    assert GOOD in zh and "世系" not in zh and "<!-- p.14 -->" in zh
    rw = body_calls(eng, "rewrite")[0]
    assert rw["engine"] == "deepseek-flash" and not rw["think"]
    assert "natural selection=自然选择" in rw["user"] and "## 英文原文" in rw["user"] and DRAFT in rw["user"]
    assert len(body_calls(eng, "meaning")) == 1                              # 一单元一次意义核对，关思考
    rep = (out / "report.md").read_text(encoding="utf8")
    assert "改写：采用" in rep and "意义核对：发现 0，已修 0，未修 0" in rep
    kinds = [json.loads(x)["status"] for x in (out / "edits.jsonl").read_text(encoding="utf8").splitlines()]
    assert "rewrite_used" in kinds


def test_rewrite_engine_override(net: Net, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    eng = RwEngine(rewrite=GOOD)
    go_rw(tmp_path, monkeypatch, eng, rewrite_engine="claude-sonnet")
    assert [c["engine"] for c in eng.calls if c["tag"].endswith("/rewrite")] == ["claude-sonnet"] * 2
    assert {c["engine"] for c in eng.calls if "/meaning" in c["tag"]} == {"deepseek-flash"}


@pytest.mark.parametrize("bad,why", [
    ("达尔文于1860年提出了自然选择。每个谱系都会显著进化。该谱系后来分裂。", "年份"),
    ("达尔文提出了自然选择。每个谱系都会显著进化。该谱系后来分裂。", "年份"),                    # 丢了年份
    ("达尔文于1859年提出了自然选择。每个谱系都会显著进化。\n\n该谱系后来分裂。", "段数改变"),      # 拆段
    ("达尔文于1859年提出了自然演化。每个谱系都会显著进化。该谱系后来分裂。", "HARD"),
])
def test_rewrite_rejected_keeps_draft(net: Net, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad: str, why: str):
    eng = RwEngine(rewrite=bad)
    out = go_rw(tmp_path, monkeypatch, eng)
    zh = (out / "zh.md").read_text(encoding="utf8")
    assert DRAFT in zh                                                       # 初稿原样保留
    assert bad not in zh
    assert not body_calls(eng, "meaning")                                    # 改写被拒，不再做意义核对
    rep = (out / "report.md").read_text(encoding="utf8")
    assert "改写：拒绝，保留初稿" in rep and why in rep


def test_rewrite_rejected_on_dropped_citation_and_latin():
    before = "这一点见 Smith (1999) 的研究。*Nereis virens* 与 Homo sapiens 都有。"
    assert gtrans.rewrite_violations(before, before, []) == []
    assert any("引证" in w or "年份" in w for w in gtrans.rewrite_violations(before, "这一点见前人研究。*Nereis virens* 与 Homo sapiens 都有。", []))
    assert any("拉丁双名" in w for w in gtrans.rewrite_violations(before, "这一点见 Smith (1999) 的研究。*Nereis virens* 与人类都有。", []))
    assert gtrans.rewrite_violations(before, "", []) == ["改写稿为空"]


def test_meaning_fix_applied(net: Net, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    drift = "1859年，达尔文提出了自然选择。每个谱系都无须灭绝。该谱系后来分裂。"
    fix = json.dumps([{"zh_old": "都无须灭绝", "zh_new": "都在显著进化", "why": "漏译 significantly evolves"}], ensure_ascii=False)
    eng = RwEngine(rewrite=drift, meaning={"nothink": "```json\n" + fix + "\n```"})
    out = go_rw(tmp_path, monkeypatch, eng)
    zh = (out / "zh.md").read_text(encoding="utf8")
    assert "每个谱系都在显著进化" in zh and "灭绝" not in zh
    rep = (out / "report.md").read_text(encoding="utf8")
    assert "意义核对：发现 1，已修 1，未修 0" in rep
    st = [json.loads(x) for x in (out / "edits.jsonl").read_text(encoding="utf8").splitlines()]
    assert [e["status"] for e in st if e["status"] == "applied"] == ["applied"] and st[1]["pass"] == "meaning"


def test_meaning_fix_rejected_by_guard_or_ambiguity_stays_flagged(net: Net, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    fixes = json.dumps([
        {"zh_old": "1859年", "zh_new": "1860年", "why": "x"},                  # 护栏：年份
        {"zh_old": "谱系", "zh_new": "世系", "why": "y"},                       # 出现 2 次
    ], ensure_ascii=False)
    eng = RwEngine(rewrite=GOOD.replace("又发生分裂", "又分裂；谱系"), meaning={"nothink": fixes, "think": "[]"})
    out = go_rw(tmp_path, monkeypatch, eng, think_escalate=True)
    zh = (out / "zh.md").read_text(encoding="utf8")
    assert "1859年" in zh and "1860" not in zh
    rep = (out / "report.md").read_text(encoding="utf8")
    assert "意义核对：发现 2，已修 0，未修 0" in rep                           # 思考复核返回 []，未修清零
    think = body_calls(eng, "meaning-think")
    assert len(think) == 1 and think[0]["think"]                              # 仍有未修警告 → 开思考再核一次
    assert "YZZ_DEEPSEEK_THINKING" not in os.environ


def test_no_think_escalation_when_all_flags_fixed(net: Net, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    fix = json.dumps([{"zh_old": "又发生分裂", "zh_new": "又分裂", "why": "z"}], ensure_ascii=False)
    eng = RwEngine(rewrite=GOOD, meaning={"nothink": fix})
    go_rw(tmp_path, monkeypatch, eng, think_escalate=True)
    assert not body_calls(eng, "meaning-think")


def test_malformed_checker_keeps_rewrite_and_flags_unit(net: Net, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    eng = RwEngine(rewrite=GOOD, meaning={"nothink": "这里没有 JSON，意思都对。"})
    out = go_rw(tmp_path, monkeypatch, eng)
    assert GOOD in (out / "zh.md").read_text(encoding="utf8")
    rep = (out / "report.md").read_text(encoding="utf8")
    assert "须人工复核：意义核对返回格式错误" in rep


def test_parse_meaning():
    assert gtrans.parse_meaning("[]") == [] and gtrans.parse_meaning("无问题") is None
    assert gtrans.parse_meaning("[坏") is None and gtrans.parse_meaning('["a"]') is None
    assert gtrans.parse_meaning('x [{"zh_old":"a","zh_new":"b","why":"c"}] y') == [{"zh_old": "a", "zh_new": "b", "why": "c"}]


def test_rewrite_engine_failure_keeps_draft(net: Net, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    out = go_rw(tmp_path, monkeypatch, RwEngine(rewrite_exc=True))
    assert "该世系后来分裂" in (out / "zh.md").read_text(encoding="utf8")
    assert "调用失败：连不上" in (out / "report.md").read_text(encoding="utf8")


def test_edits_mode_still_works_via_cli(net: Net, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    fix = json.dumps([{"old": "该世系后来分裂", "new": "该谱系后来分裂", "type": "术语"}], ensure_ascii=False)
    eng = Engine({"nothink:body": fix})
    monkeypatch.setattr(gtrans, "engine_call", eng)
    src = tmp_path / "in.txt"
    src.write_text(DOC, encoding="utf8")
    assert gtrans.main([str(src), "-o", str(tmp_path / "o"), "--llm-mode", "edits", "--cache", str(tmp_path / "c.sqlite")]) == 0
    assert "该谱系后来分裂" in (tmp_path / "o" / "zh.md").read_text(encoding="utf8")
    assert len(eng.calls) == 2 and "采纳 1，拒绝 0" in (tmp_path / "o" / "report.md").read_text(encoding="utf8")


def test_prefetch_fills_cache_concurrently_and_skips_cached(tmp_path, monkeypatch):
    import json as _json
    calls = []

    def http_get(url, timeout=30):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["q"][0]
        calls.append(q)
        return _json.dumps([[[f"ZH:{q}", q]]])

    monkeypatch.setattr(gtrans, "http_get", http_get)
    monkeypatch.setattr(gtrans, "_sleep", lambda s: None)
    g = gtrans.Google(gtrans.Cache(tmp_path / "c.sqlite"))
    g.cache.put("cached one", "已有")
    n = g.prefetch(["alpha", "beta", "alpha", "cached one", "  "], workers=4)
    assert n == 2 and sorted(calls) == ["alpha", "beta"]
    assert g.translate("alpha") == "ZH:alpha" and g.pause == (1.0, 2.0)
    assert len(calls) == 2  # translate 命中缓存


def test_google_uses_configured_languages_and_cools_down_on_429(tmp_path, monkeypatch):
    import json as _json
    seen, sleeps, state = [], [], {"n": 0}

    def http_get(url, timeout=30):
        seen.append(urllib.parse.parse_qs(urllib.parse.urlparse(url).query))
        state["n"] += 1
        if state["n"] == 1:
            raise urllib.error.HTTPError(url, 429, "Too Many", {}, None)
        return _json.dumps([[["Body short.", "x"]]])

    monkeypatch.setattr(gtrans, "http_get", http_get)
    monkeypatch.setattr(gtrans, "_sleep", sleeps.append)
    g = gtrans.Google(gtrans.Cache(tmp_path / "c.sqlite"), sl="bg", tl="en", pause=(0.0, 0.0))
    assert g.translate("Тялото късо.") == "Body short."
    assert seen[0]["sl"] == ["bg"] and seen[0]["tl"] == ["en"]
    assert g._cool_until > 0 and sleeps  # 429 后设了全体冷却并等待
