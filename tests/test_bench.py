"""scripts/bench/bench.py：评分、盲评目录与映射、汇总。翻译调用全部 mock。"""
import json

import pytest

import bench
import llm_engines

TERMS = """领域：分类学；类群：Nereididae

| 英文 | 译名 | 依据 | 状态 | 出处语境 | 其他译名 |
|---|---|---|---|---|---|
| parapodium | 疣足 | yzz_核定 | 已核 |  |  |
| notopodial ligule | 背足叶（背叶） | yzz_核定 | 已核 |  |  |
| chaeta | 刚毛 | 刘凌云2009 | 候选 |  |  |
| pygidium | 尾节 | yzz_核定 | 已核 |  |  |
"""
SRC = ("The parapodium bears 3 or 4 notopodial ligules in Nereididae Blainville, 1818, from 10-12 mm. " * 8
       + "Platynereis dumerilii is common.")
GOOD = "疣足具 3 或 4 个背足叶，见沙蚕科 Nereididae Blainville, 1818，体长 10–12 mm。" * 8 + "Platynereis dumerilii 常见。"


def test_verified_terms_only_keeps_checked_rows():
    assert bench.verified_terms(TERMS) == [("parapodium", "疣足"), ("notopodial ligule", "背足叶（背叶）"), ("pygidium", "尾节")]


def test_score_terms_numbers_latin_and_pending():
    s = bench.score(SRC, TERMS, GOOD + "\n\n### 待定术语\na｜b｜c\nd｜e｜f\n")
    assert s["terms"] == (2, 2)  # pygidium 原文没出现，不计；背足叶（括注变体）命中
    assert s["nums"][0] == s["nums"][1] and s["nums"][1] > 0  # 10-12 与 10–12 等价
    assert s["latin"][0] == s["latin"][1] and s["latin"][1] >= 2
    assert s["pending"] == 2 and not s["refused"] and s["miss"] == []


def test_score_detects_misses_and_refusal():
    bad = "出于版权原因我无法翻译这段内容。"
    s = bench.score(SRC, TERMS, bad)
    assert s["refused"] is True and s["terms"] == (0, 2)
    assert [e for e, _ in s["miss"]] == ["parapodium", "notopodial ligule"]
    short_src = "parapodium"
    assert bench.score(short_src, TERMS, "疣足")["refused"] is False  # 短原文不判拒译


@pytest.fixture
def work(tmp_path):
    for seg in ("P1", "P2"):
        (tmp_path / "src").mkdir(exist_ok=True)
        (tmp_path / "src" / f"{seg}.txt").write_text(SRC, encoding="utf8")
        (tmp_path / "terms").mkdir(exist_ok=True)
        (tmp_path / "terms" / f"{seg}.md").write_text(TERMS, encoding="utf8")
    return tmp_path


def fake_call_factory(refuse=()):
    def fake(engine, system, user, **kw):
        assert system.startswith("用途说明")  # 系统提示词带用途说明
        assert "本块术语表" in user and "请翻译以下英文原文" in user
        if engine in refuse:
            raise llm_engines.EngineError("推理耗尽")
        return GOOD + f"\n（{engine}）", {"output_tokens": 5}
    return fake


def test_run_writes_outputs_skips_existing_and_records_failures(work, monkeypatch):
    monkeypatch.setattr(bench.llm_engines, "call", fake_call_factory(refuse=("deepseek-v4-pro",)))
    assert bench.main(["run", str(work), "--engines", "claude-sonnet,deepseek-v4-pro"]) == 0
    assert (work / "out/claude-sonnet/P1.md").exists() and (work / "out/claude-sonnet/P2.md").exists()
    assert not (work / "out/deepseek-v4-pro/P1.md").exists()
    assert "推理耗尽" in (work / "失败记录.txt").read_text(encoding="utf8")
    assert (work / "system.md").read_text(encoding="utf8").startswith("用途说明")
    calls = []
    monkeypatch.setattr(bench.llm_engines, "call", lambda *a, **k: calls.append(a) or ("x", {}))
    bench.main(["run", str(work), "--engines", "claude-sonnet"])
    assert calls == []  # 已有产物不重跑
    assert bench.main(["run", str(work), "--engines", "gpt-x"]) == 2


def test_eval_writes_scores_and_miss(work, monkeypatch, capsys):
    (work / "out/m1").mkdir(parents=True)
    (work / "out/m1/P1.md").write_text(GOOD, encoding="utf8")
    (work / "out/m2").mkdir(parents=True)
    (work / "out/m2/P1.md").write_text("无关译文。" * 100, encoding="utf8")
    assert bench.cmd_eval(work) == 0
    rows = (work / "scores.tsv").read_text(encoding="utf8").splitlines()
    assert rows[0].startswith("engine\t段\t术语落实") and len(rows) == 3
    assert any(r.startswith("m1\tP1\t2/2") for r in rows)
    assert (work / "term_miss.tsv").read_text(encoding="utf8").count("m2\tP1\tparapodium") == 1
    assert "m1" in capsys.readouterr().out


def test_blind_random_letters_key_and_reproducible(work):
    for e in ("a-engine", "b-engine", "c-engine"):
        (work / "out" / e).mkdir(parents=True)
        (work / "out" / e / "P1.md").write_text(f"译文来自{e}" + "x" * 300, encoding="utf8")
    assert bench.cmd_blind(work, seed=7) == 0
    key = json.loads((work / "blind_key_P1.json").read_text(encoding="utf8"))["P1"]
    assert sorted(key) == ["A", "B", "C"] and sorted(key.values()) == ["a-engine", "b-engine", "c-engine"]
    for letter, engine in key.items():
        assert engine in (work / "blind" / "P1" / f"{letter}.md").read_text(encoding="utf8")
    assert not (work / "blind" / "P2").exists()  # 没有译文的段不生成
    sheet = (work / "盲评_P1.md").read_text(encoding="utf8")
    assert "| A |" in sheet and "a-engine" not in sheet  # 记录表不泄露映射
    first = dict(key)
    bench.cmd_blind(work, seed=7)
    assert json.loads((work / "blind_key_P1.json").read_text(encoding="utf8"))["P1"] == first  # 同种子同映射
    bench.cmd_blind(work, seed=8)
    # 盲评表已存在时不覆盖评者填的内容
    sheet_f = work / "盲评_P1.md"
    sheet_f.write_text(sheet.replace("| A |  |  |  |", "| A | 1 | 2 | 测 |"), encoding="utf8")
    bench.cmd_blind(work, seed=7)
    assert "| A | 1 | 2 | 测 |" in sheet_f.read_text(encoding="utf8")


def test_tally_sums_per_engine_across_segments(work):
    (work / "盲评_P1.md").write_text("| 编号 | 重大 | 轻微 | 记录 |\n|---|---|---|---|\n| A | 1 | 0 | x |\n| B | 0 | 2 | y |\n| C |  |  | 未评 |\n",
                                   encoding="utf8")
    (work / "blind_key_P1.json").write_text(json.dumps({"P1": {"A": "s", "B": "o", "C": "z"}}), encoding="utf8")
    (work / "盲评_P2.md").write_text("| A | 0 | 1 | x |\n| B | 2 | 3 | y |\n", encoding="utf8")
    (work / "blind_key_P2.json").write_text(json.dumps({"P2": {"B": "s", "A": "o"}}), encoding="utf8")
    t = bench.tally(work)
    assert t["s"] == [3, 3, 2] and t["o"] == [0, 3, 2] and "z" not in t


def test_terms_subcommand_uses_yiku(work, monkeypatch):
    (work / "terms" / "P1.md").unlink()
    monkeypatch.setattr(bench.direct_mode, "yiku_table", lambda f, d, s: f"表 {d} {s}")
    assert bench.main(["terms", str(work), "--scope", "Nereididae"]) == 0
    assert (work / "terms" / "P1.md").read_text(encoding="utf8") == "表 分类学 Nereididae"
    assert (work / "terms" / "P2.md").read_text(encoding="utf8") == TERMS  # 已有的不动
