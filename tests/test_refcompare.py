"""scripts/bench/refcompare.py：配置、防泄漏过滤、续跑与过期检查、核译替换、盲评解盲、汇总。模型调用全部用假引擎，不联网。"""
import json
import sqlite3

import pytest

import llm_engines
import refcompare as rc
from direct_mode import StaleOutputError

EN = "Species concepts changed. The population is a unit of evolution."
TERMS = """领域：进化生物学；类群：通用；回退领域：无

## HARD（必用）
| 英文 | 译名 | 依据 | 状态 | 其他译名（不用） |
|---|---|---|---|---|
| population | 种群、群体 | Futuyma p.1 | 已核 |  |

## SOFT（先判义项，再取舍）
| 英文 | 译名 | 依据 | 状态 | 定义 |
|---|---|---|---|---|
| species | 物种 | X | 候选 |  |
"""
DRAFT = "物种概念变了。种群是进化的单位。\n\n### 待定术语\nspecies｜物种｜通用\n"


def make_cfg(tmp_path, extra=None, passages=("S1", "S2")):
    d = {"name": "t", "passages": list(passages), "domain": "进化生物学", "term_domains": ["进化生物学", "科学史"],
         "engines": {"judges": ["codex-sol", "cursor-grok"]}, **(extra or {})}
    (tmp_path / "refcompare.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf8")
    (tmp_path / "terms").mkdir(exist_ok=True)
    for p in passages:
        (tmp_path / f"{p}_en.txt").write_text(EN + "\n", encoding="utf8")
        (tmp_path / f"{p}_pub.txt").write_text("物种概念变了。群体是进化的单位。GOOD\n" if p == "S1" else "物种概念变了。\n", encoding="utf8")
        (tmp_path / "terms" / f"{p}.md").write_text(TERMS, encoding="utf8")
    return rc.load_config(tmp_path / "refcompare.json")


class Fake:
    """假引擎：按 tag 末段区分初译、核译、盲评；记录每次调用。"""

    def __init__(self, issues="NO_ISSUES", draft=DRAFT):
        self.calls = []
        self.issues, self.draft = issues, draft

    @staticmethod
    def kind(tag):
        parts = tag.split("/")
        return "judge" if "_vs_" in parts[0] else parts[2]

    def __call__(self, engine, system, user, *, tag="", usage_file=None, **kw):
        self.calls.append((engine, tag, system, user))
        kind = self.kind(tag)
        if kind == "draft":
            return self.draft, {}
        if kind == "review":
            return self.issues, {}
        a = user.split("=== Translation A ===")[1].split("=== Translation B ===")[0]
        b = user.split("=== Translation B ===")[1]
        sa, sb = (95, 70) if "GOOD" in a else (70, 95) if "GOOD" in b else (80, 80)
        err = [{"category": "mistranslation", "severity": "major", "source_span": "x", "target_span": "y", "comment": "c"}]
        o = {"A": {"errors": [] if sa > sb else err, "score": sa}, "B": {"errors": [] if sb > sa else err, "score": sb},
             "preferred": "A" if sa > sb else "B", "reason": "r"}
        return json.dumps(o), {}

    def n(self, kind):
        return sum(1 for c in self.calls if self.kind(c[1]) == kind)


def test_load_config_json_and_yaml(tmp_path):
    cfg = make_cfg(tmp_path)
    assert cfg.root == tmp_path and cfg.passages == ["S1", "S2"] and cfg.term_domains == ["进化生物学", "科学史"]
    assert cfg.engine("draft") == "claude-sonnet" and cfg.engine("review") == "codex-sol"   # 缺省引擎
    assert cfg.leakage["no_usage"] is True and cfg.hard_term_filter is True and cfg.terms_dir == tmp_path / "terms"
    (tmp_path / "c.yaml").write_text("passages: [A]\ndomain: 分类学\nruns:\n  r9: {review: codex-luna}\n", encoding="utf8")
    y = rc.load_config(tmp_path / "c.yaml")
    assert y.term_domains == ["分类学"] and y.engine("review", "r9") == "codex-luna" and y.engine("review", "r1") == "codex-sol"


def test_filtered_db_drops_sources_and_noted_terms_and_is_cached(tmp_path):
    src = tmp_path / "y.db"
    con = sqlite3.connect(src)
    con.executescript("CREATE TABLE sources(key TEXT PRIMARY KEY, title TEXT); CREATE TABLE terms(id INTEGER PRIMARY KEY, en TEXT, zh TEXT, source TEXT, note TEXT);"
                      "INSERT INTO sources VALUES('A','a'),('B','b');"
                      "INSERT INTO terms(en,zh,source,note) VALUES('x','甲','A',NULL),('y','乙','B','与某中译本一致'),('z','丙','B','无'),('w','丁','B','%');")
    con.commit()
    con.close()
    cfg = make_cfg(tmp_path, {"leakage": {"yiku_db": str(src), "exclude_sources": ["A"], "exclude_note_like": ["某中译本", "%"]}})
    out = rc.filtered_db(cfg)
    assert out == tmp_path / "terms" / "yiku_filtered.db"
    c = sqlite3.connect(out)
    assert [r[0] for r in c.execute("select zh from terms order by id")] == ["丙"]   # '%' 按子串而非通配符匹配
    assert [r[0] for r in c.execute("select key from sources")] == ["B"]
    c.close()
    side = json.loads(out.with_suffix(".json").read_text(encoding="utf8"))
    assert side["removed_terms"] == 3
    mtime = out.stat().st_mtime_ns
    assert rc.filtered_db(cfg) == out and out.stat().st_mtime_ns == mtime          # 过滤条件与源库不变：不重建
    assert src.stat().st_size > 0 and sqlite3.connect(src).execute("select count(*) from terms").fetchone()[0] == 4   # 不动原库


def test_filtered_db_without_filters_uses_default_db(tmp_path):
    cfg = make_cfg(tmp_path)
    assert rc.filtered_db(cfg) is None
    cfg2 = make_cfg(tmp_path, {"leakage": {"yiku_db": str(tmp_path / "z.db")}})
    assert rc.filtered_db(cfg2) == tmp_path / "z.db"


def test_merge_tables_adds_only_new_long_english_rows():
    a = TERMS
    b = ("领域：科学史；类群：通用\n\n## HARD（必用）\n| 英文 | 译名 | 依据 | 状态 | 其他译名（不用） |\n|---|---|---|---|---|\n"
         "| population | 人口 | S | 已核 |  |\n| theory | 学说 | S | 已核 |  |\n| f. | 噪声 | S | 已核 |  |\n\n"
         "## SOFT（x）\n| 英文 | 译名 | 依据 | 状态 | 定义 |\n|---|---|---|---|---|\n| species | 种 | S | 候选 |  |\n| race | 宗 | S | 候选 |  |\n")
    m = rc.merge_tables([a, b], ["进化生物学", "科学史"])
    assert m.splitlines()[0] == "领域：进化生物学 + 科学史（合并）；类群：通用；回退领域：无"
    assert "| theory | 学说" in m and "| race | 宗" in m
    assert "人口" not in m and "噪声" not in m and "| species | 种 |" not in m       # 重复条目与过短英文不补
    assert rc.merge_tables([a], ["进化生物学"]) == a
    assert rc.hard_terms(m) == ["种群", "学说"]


def test_build_terms_uses_table_fn_and_skips_existing(tmp_path):
    cfg = make_cfg(tmp_path, passages=("S1",))
    (tmp_path / "terms" / "S1.md").unlink()
    seen = []

    def fake_table(src, domain):
        seen.append((src.name, domain))
        return TERMS

    (path,) = rc.build_terms(cfg, table_fn=fake_table)
    assert path.exists() and seen == [("S1_en.txt", "进化生物学"), ("S1_en.txt", "科学史")]
    rc.build_terms(cfg, table_fn=fake_table)
    assert len(seen) == 2   # 已有术语表不重做


def test_apply_issues_gate_rules():
    text = "甲乙丙。种群很大。重复重复。Mendel 说了 3 次。"
    issues = [
        {"old": "甲乙丙", "new": "甲乙丁", "type": "误译"},                      # 应用
        {"old": "重复", "new": "重", "type": "语序"},                            # old 出现 2 次
        {"old": "不存在", "new": "x", "type": "误译"},                           # 出现 0 次
        {"old": "乙", "new": "乙", "type": "误译"},                              # 新旧相同
        {"old": "Mendel 说了 3 次", "new": "他说了次", "type": "语序"},          # 非术语类丢英文/数字
        {"old": "Mendel 说了 3 次", "new": "孟德尔说了三次", "type": "误译"},      # 允许丢英文
        {"old": "种群很大", "new": "群体很大", "type": "术语"},                    # 改掉 HARD 术语
    ]
    out, ok, bad = rc.apply_issues(text, issues, ["种群"])
    assert out == "甲乙丁。种群很大。重复重复。孟德尔说了三次。"
    assert len(ok) == 2 and [b["reject"].split(" ")[0] for b in bad] == ["old", "old", "新旧相同", "丢失英文/数字", "改掉"]
    out2, ok2, _ = rc.apply_issues("种群很大。", [{"old": "种群很大", "new": "", "type": "增译"}], ["种群"])   # 纯删除不算改术语
    assert out2 == "。" and len(ok2) == 1
    out3, _, bad3 = rc.apply_issues("甲乙。", [{"old": "甲", "new": "丙", "type": "误译"}, {"old": "甲", "new": "丁", "type": "误译"}])
    assert out3 == "丙乙。" and "出现 0 次" in bad3[0]["reject"]                # 依次应用：第二条的 old 已被第一条改掉


def good_judge(**over):
    o = {"A": {"errors": [], "score": 90}, "B": {"errors": [], "score": 80}, "preferred": "A", "reason": "r"}
    o.update(over)
    return json.dumps(o)


@pytest.mark.parametrize("bad", [
    "not json", "{}", good_judge(preferred="C"), good_judge(A={"errors": [], "score": 101}),
    good_judge(A={"errors": [], "score": "90"}), good_judge(A={"errors": [{"category": "fluency", "severity": "minor"}], "score": 9}),
    good_judge(B={"errors": [{"category": "omission", "severity": "medium"}], "score": 9}), good_judge(reason=3),
])
def test_parse_judge_rejects_malformed(bad):
    with pytest.raises(ValueError):
        rc.parse_judge(bad)


def test_parse_judge_accepts_fenced_json():
    assert rc.parse_judge("```json\n" + good_judge() + "\n```")["preferred"] == "A"


def test_draft_resume_stale_and_force(tmp_path):
    cfg, fake = make_cfg(tmp_path), Fake()
    rc.draft(cfg, "r1", caller=fake)
    assert (tmp_path / "r1" / "system_draft.md").stat().st_size > 1000          # 留底系统提示词
    assert fake.n("draft") == 2 and (tmp_path / "r1" / "S1_draft.txt").read_text(encoding="utf8").strip() == "物种概念变了。种群是进化的单位。"
    assert (tmp_path / "r1" / "S1_pending.txt").read_text(encoding="utf8").strip().startswith("species")
    rc.draft(cfg, "r1", caller=fake)
    assert fake.n("draft") == 2                                         # 已有且一致：全部跳过
    (tmp_path / "terms" / "S1.md").write_text(TERMS + "| x | 乙 | s | 已核 |  |\n", encoding="utf8")
    with pytest.raises(RuntimeError, match="1 项失败"):                 # S1 术语表变了：报过期，S2 照常跳过
        rc.draft(cfg, "r1", caller=fake)
    assert fake.n("draft") == 2
    rc.review(cfg, "r1", ["S2"], caller=fake)
    assert cfg.file("S2", "r1").exists()
    rc.draft(cfg, "r1", ["S1"], caller=fake, force=True)
    assert fake.n("draft") == 3
    rc.draft(cfg, "r2", ["S1"], caller=fake)                            # 新的运行目录互不影响
    assert fake.n("draft") == 4


def test_draft_force_clears_downstream_review(tmp_path):
    cfg, fake = make_cfg(tmp_path), Fake(issues=json.dumps({"old": "单位", "new": "基本单位", "type": "误译"}))
    rc.draft(cfg, "r1", ["S1"], caller=fake)
    rc.review(cfg, "r1", ["S1"], caller=fake)
    assert "基本单位" in cfg.file("S1", "r1").read_text(encoding="utf8")
    (tmp_path / "terms" / "S1.md").write_text(TERMS + "\n", encoding="utf8")
    rc.draft(cfg, "r1", ["S1"], caller=fake, force=True)
    assert not cfg.file("S1", "r1").exists() and not (tmp_path / "r1" / "S1_issues.jsonl").exists()


def test_draft_refusal_is_retried_then_fails(tmp_path):
    cfg = make_cfg(tmp_path, passages=("S1",))
    (tmp_path / "S1_en.txt").write_text("word " * 200, encoding="utf8")
    fake = Fake(draft="I cannot translate this.")
    with pytest.raises(RuntimeError, match="1 项失败"):
        rc.draft(cfg, "r1", caller=fake)
    assert fake.n("draft") == 3 and not (tmp_path / "r1" / "S1_draft_raw.md").exists()
    assert (tmp_path / "r1" / "S1_draft_raw.md.fail0").exists()


def test_review_applies_issues_logs_rejects_and_retries(tmp_path):
    cfg = make_cfg(tmp_path, passages=("S1",))
    issues = "\n".join(json.dumps(i, ensure_ascii=False) for i in (
        {"old": "进化的单位", "new": "进化的基本单位", "type": "误译", "reason": "r"},
        {"old": "种群", "new": "群体", "type": "术语"},
        {"old": "没有这句", "new": "x", "type": "误译"}))
    seq = iter(["这不是 JSONL", issues])

    class Retry(Fake):
        def __call__(self, engine, system, user, **kw):
            out = super().__call__(engine, system, user, **kw)
            return (next(seq), {}) if self.kind(kw["tag"]) == "review" else out

    fake = Retry()
    rc.draft(cfg, "r1", caller=fake)
    rc.review(cfg, "r1", caller=fake)
    assert fake.n("review") == 2                                          # 第一次输出不合格，重试一次
    assert cfg.file("S1", "r1").read_text(encoding="utf8").strip() == "物种概念变了。种群是进化的基本单位。"
    rej = [json.loads(x) for x in (tmp_path / "r1" / "S1_rejects.jsonl").read_text(encoding="utf8").splitlines()]
    assert [r["reject"].split(" ")[0] for r in rej] == ["改掉", "old"]
    assert len((tmp_path / "r1" / "S1_applied.jsonl").read_text(encoding="utf8").splitlines()) == 1
    rc.review(cfg, "r1", caller=fake)
    assert fake.n("review") == 2                                          # 续跑：不重核


def test_non_claude_engines_get_isolation_notice(tmp_path):
    cfg, fake = make_cfg(tmp_path, passages=("S1",)), Fake()
    rc.draft(cfg, "r1", caller=fake)
    rc.review(cfg, "r1", caller=fake)
    rc.judge_pair(cfg, "pub", "r1", caller=fake)
    sys_of = {Fake.kind(c[1]): c[2] for c in fake.calls}
    assert rc.ISOLATION in sys_of["review"] and rc.ISOLATION in sys_of["judge"]
    assert rc.ISOLATION not in sys_of["draft"]                            # claude-sonnet 本就无工具，提示词不加


def test_judge_blind_key_resume_aggregate_and_compare_runs(tmp_path):
    cfg, fake = make_cfg(tmp_path), Fake()
    rc.draft(cfg, "r1", caller=fake)
    rc.review(cfg, "r1", caller=fake)
    (tmp_path / "S1_r2.txt").write_text("物种概念变了。种群是进化的单位。GOOD\n", encoding="utf8")
    (tmp_path / "S2_r2.txt").write_text("物种概念变了。种群是进化的单位。GOOD\n", encoding="utf8")
    pair = rc.judge_pair(cfg, "r1", "r2", caller=fake, jobs=4)
    assert pair == "r1_vs_r2" and fake.n("judge") == 4
    key = json.loads((tmp_path / "judge" / pair / "key.json").read_text(encoding="utf8"))
    assert all(set(m.values()) == {"r1", "r2"} for d in key.values() for m in d.values())
    flips = {m["A"] for d in key.values() for m in d.values()}
    assert flips == {"r1", "r2"}                                          # 4 个（段 x 评委）里 A/B 两种顺序都出现（固定种子）
    rows = rc.unblind(cfg, pair)
    assert len(rows) == 4 and all(r["preferred"] == "r2" and r["score"] == {"r2": 95, "r1": 70} for r in rows)
    n = len(fake.calls)
    rc.judge_pair(cfg, "r1", "r2", caller=fake)
    assert len(fake.calls) == n                                           # 续跑：评过的不重评
    (tmp_path / "S1_r3.txt").write_text("乙\n", encoding="utf8")
    rc.judge_pair(cfg, "pub", "r3", ["S1"], ["codex-sol"], caller=fake)    # pub 含 GOOD，r3 不含：pub 必胜
    md = rc.aggregate(cfg, [pair, "pub_vs_r3"])
    assert "| Passage | Judge | r1 | r2 | preferred |" in md and "| S1 | codex-sol | 70 | 95 | r2 |" in md
    assert "preferred: r1 0, r2 4, tie 0 (of 4)" in md and "MQM penalty" in md
    assert "| mistranslation | 2 | 0 | 0 | 0 |" in md                       # r1 在 4 次评审中各被标 1 条 major 误译
    tail = md.split("Error counts per version")[1]
    assert "| category | r1@r1_vs_r2 | r2@r1_vs_r2 | pub@pub_vs_r3 | r3@pub_vs_r3 |" in tail
    assert "| mistranslation | 4/0 | 0/0 | 0/0 | 1/0 |" in tail
    assert "preferred: pub 1, r3 0, tie 0 (of 1)" in md
    assert "物种" not in md                                               # 汇总表不含书中文字


def test_judge_stale_when_version_text_changes(tmp_path):
    cfg, fake = make_cfg(tmp_path, passages=("S1",)), Fake()
    (tmp_path / "S1_r1.txt").write_text("甲\n", encoding="utf8")
    rc.judge_pair(cfg, "pub", "r1", caller=fake)
    (tmp_path / "S1_r1.txt").write_text("乙\n", encoding="utf8")
    with pytest.raises(RuntimeError):
        rc.judge_pair(cfg, "pub", "r1", caller=fake)
    n = len(fake.calls)
    rc.judge_pair(cfg, "pub", "r1", caller=fake, force=True)
    assert len(fake.calls) == n + 2
    n = len(fake.calls)
    with pytest.raises(RuntimeError, match="2 项失败"):                   # 版本文件不存在：不调模型
        rc.judge_pair(cfg, "pub", "nope", caller=fake)
    assert len(fake.calls) == n


def test_stale_error_class_is_direct_mode_one(tmp_path):
    cfg = make_cfg(tmp_path, passages=("S1",))
    raw = tmp_path / "o.txt"
    raw.write_text("x", encoding="utf8")
    with pytest.raises(StaleOutputError, match="缺 meta.json"):
        rc.run_step(raw, "e", "s", "u", caller=Fake(), tag="t", usage_file=cfg.usage, validate=lambda t: None)


def test_cli_end_to_end(tmp_path, monkeypatch, capsys):
    make_cfg(tmp_path, passages=("S1",))
    fake = Fake()
    monkeypatch.setattr(llm_engines, "call", fake)
    cfgp = str(tmp_path / "refcompare.json")
    assert rc.main(["draft", cfgp, "--run", "r1"]) == 0
    assert rc.main(["review", cfgp, "--run", "r1"]) == 0
    assert rc.main(["judge", cfgp, "--run", "r1", "--judges", "codex-sol", "-j", "2"]) == 0
    assert rc.main(["compare-runs", cfgp, "pub", "r1", "--judges", "codex-sol"]) == 0   # 同一对：续跑，不重评
    assert fake.n("judge") == 1
    capsys.readouterr()
    assert rc.main(["aggregate", cfgp, "pub_vs_r1"]) == 0
    assert "## pub_vs_r1" in capsys.readouterr().out and (tmp_path / "agg_pub_vs_r1.md").exists()
    with pytest.raises(SystemExit):
        rc.main(["draft", cfgp])
    (tmp_path / "terms" / "S1.md").write_text(TERMS + "\n", encoding="utf8")           # 术语表变了：过期产物报错、退出码 1
    assert rc.main(["draft", cfgp, "--run", "r1"]) == 1
    cap = capsys.readouterr()
    assert "不一致" in cap.out and "项失败" in cap.err
