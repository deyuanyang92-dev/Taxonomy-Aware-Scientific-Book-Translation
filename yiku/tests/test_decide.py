"""术语决策日志：term_decisions.jsonl 的校验、待裁清单、写回术语库。全部用临时库。"""
import json

import pytest

from yiku import cli
from yiku import db as D
from yiku import decide as DC


@pytest.fixture
def con(tmp_path):
    c = D.connect(tmp_path / "t.db")
    c.execute("PRAGMA synchronous=OFF")
    D.add_source(c, "杨孙", "杨德渐孙瑞平", "authority", domain="分类学", year=1988)
    D.add_source(c, "Futuyma", "Futuyma 译本", "translation", domain="进化生物学")
    D.add_term(c, "chaetiger", "刚节", "杨孙", domain="分类学", status="已核")
    D.add_term(c, "cirrus", "须", "杨孙", domain="分类学")
    D.add_term(c, "cirrus", "触须", "杨孙", domain="分类学")
    D.add_term(c, "adaptive radiation", "适应辐射", "Futuyma", domain="进化生物学", status="已核")
    D.add_term(c, "dorsal", "背部", "杨孙", domain="分类学")
    c.commit()
    return c


def rec(en, zh, sense="s", reason="语境", source="杨孙 p.3", chunk="ch05/c01", **kw):
    return {"en": en, "zh": zh, "sense": sense, "reason": reason, "source": source, "chunk": chunk, **kw}


# ---------- validate ----------

def test_validate_record_ok_and_errors():
    assert DC.validate_record(rec("cirrus", "须")) == []
    assert DC.validate_record(rec("cirrus", "须", source="")) == []        # 无出处合法，由 review 提示
    assert DC.validate_record({**rec("cirrus", "须"), "source": None}) == []
    assert DC.validate_record({**rec("cirrus", "须"), "extra": 1}) == []   # 多余字段允许
    errs = DC.validate_record({"en": "cirrus", "zh": "", "sense": 3})
    joined = "；".join(errs)
    assert "zh" in joined and "sense" in joined and "reason" in joined and "chunk" in joined
    assert DC.validate_record([1]) == ["不是 JSON 对象"]
    assert DC.validate_record(rec("", "须"))  # en 为空
    assert DC.validate_record({**rec("cirrus", "须"), "accept": "yes"})  # accept 只能是布尔


def test_parse_decisions_lines_fences_and_errors():
    text = ("```jsonl\n" + json.dumps(rec("cirrus", "须"), ensure_ascii=False) + "\n```\n"
            "说明文字\n{坏json\n" + json.dumps({"en": "x"}) + "\n\n")
    ok, errs = DC.parse_decisions(text)
    assert [r["en"] for r in ok] == ["cirrus"]
    assert len(errs) == 3 and errs[0].startswith("第 4 行") and "不是合法 JSON" in errs[0]
    assert "缺" in errs[2] or "zh" in errs[2]


def test_validate_cli_exit_codes(tmp_path, con, capsys):
    good, bad = tmp_path / "g.jsonl", tmp_path / "b.jsonl"
    good.write_text(json.dumps(rec("cirrus", "须"), ensure_ascii=False) + "\n", encoding="utf8")
    bad.write_text('{"en":"x"}\n', encoding="utf8")
    with pytest.raises(SystemExit) as e:
        cli.main(["--db", str(tmp_path / "t.db"), "decide", "validate", str(good)])
    assert e.value.code == 0 and "1 条合法" in capsys.readouterr().out
    with pytest.raises(SystemExit) as e:
        cli.main(["--db", str(tmp_path / "t.db"), "decide", "validate", str(good), str(bad)])
    assert e.value.code == 1


# ---------- review ----------

def flags_of(con, records, **kw):
    out = DC.review(con, records, "分类学", **kw)
    return {(r["en"], r["zh"]): r["flags"] for r in out}


def test_review_flags_multi_zh_soft_no_source_and_zh_not_candidate(con):
    f = flags_of(con, [
        rec("cirrus", "须"),                                  # SOFT，库里有须、触须两个译名
        rec("dorsal", "背部"),                                # SOFT 单译名、有来源、zh 在候选里：无需裁定
        rec("dorsal", "背面", sense="方位", source=""),        # zh 不在候选 + 无出处
        rec("adaptive radiation", "适应辐射"),                  # 回退领域已核，单一：无需裁定
        rec("unknown term", "新词"),                           # 库里没有
    ])
    assert any("多译名" in x for x in f[("cirrus", "须")])
    assert ("dorsal", "背部") not in f
    assert any("无出处" in x for x in f[("dorsal", "背面")]) and any("不在候选" in x for x in f[("dorsal", "背面")])
    assert ("adaptive radiation", "适应辐射") not in f
    assert any("不在候选" in x for x in f[("unknown term", "新词")])


def test_review_hard_violation_and_same_sense_conflict(con):
    f = flags_of(con, [rec("chaetiger", "体节"), rec("chaetiger", "刚节", sense="s2"),
                       rec("dorsal", "背部", sense="方位"), rec("dorsal", "背侧", sense="方位")])
    assert any("HARD" in x and "刚节" in x for x in f[("chaetiger", "体节")])
    assert ("chaetiger", "刚节") not in f
    assert any("同一义项" in x for x in f[("dorsal", "背部")]) and any("同一义项" in x for x in f[("dorsal", "背侧")])


def test_review_dedupes_and_ignores_rejected_accept(con):
    out = DC.review(con, [rec("cirrus", "须"), rec("cirrus", "须", chunk="ch05/c02")], "分类学")
    assert len(out) == 1 and out[0]["count"] == 2
    assert DC.review(con, [rec("cirrus", "须", accept=False)], "分类学") == []


# ---------- apply ----------

def test_apply_writes_candidates_with_decision_source_and_note(con):
    r = DC.apply(con, [rec("cirrus", "须", sense="沙蚕背须", reason="背须而非阴茎")], book="Handbook", domain="分类学")
    assert (r.added, r.skipped) == (1, 0)
    src = con.execute("SELECT kind, tier FROM sources WHERE key='决策_Handbook'").fetchone()
    assert (src["kind"], src["tier"]) == ("model", 9)
    row = con.execute("SELECT * FROM terms WHERE source='决策_Handbook'").fetchone()
    assert (row["en"], row["zh"], row["status"], row["domain"], row["note"]) == ("cirrus", "须", "候选", "分类学", "背须而非阴茎")
    assert row["page"] == "ch05/c01" and "沙蚕背须" in row["context"] and "杨孙 p.3" in row["context"]


def test_apply_verified_marks_verified_and_is_idempotent(con):
    DC.apply(con, [rec("cirrus", "须")], book="B", domain="分类学")
    r = DC.apply(con, [rec("cirrus", "须")], book="B", domain="分类学", verified=True)
    assert r.added == 0 and r.upgraded == 1
    assert con.execute("SELECT status FROM terms WHERE source='决策_B'").fetchone()[0] == "已核"
    assert con.execute("SELECT count(*) FROM terms WHERE source='决策_B'").fetchone()[0] == 1


def test_apply_skips_rejected_accept_false_and_keeps_source_tier(con):
    r = DC.apply(con, [rec("cirrus", "须", accept=False), rec("dorsal", "背面")], book="B", domain="分类学")
    assert (r.added, r.skipped) == (1, 1)
    D.set_source(con, "决策_B", tier=2)
    DC.apply(con, [rec("palp", "触须")], book="B", domain="分类学")
    assert con.execute("SELECT tier FROM sources WHERE key='决策_B'").fetchone()[0] == 2  # 再次写回不重置用户调过的层级


def test_applied_candidate_never_outranks_verified_authority(con):
    DC.apply(con, [rec("chaetiger", "体节")], book="B", domain="分类学", verified=True)
    assert D.best(con, "chaetiger", "分类学").zh == "刚节"  # 杨孙层级 1 胜过决策层级 9（已核同级别内按层级排）


def test_decide_cli_review_and_apply(tmp_path, con, capsys):
    f = tmp_path / "d.jsonl"
    f.write_text(json.dumps(rec("cirrus", "须"), ensure_ascii=False) + "\n", encoding="utf8")
    db = str(tmp_path / "t.db")
    with pytest.raises(SystemExit):
        cli.main(["--db", db, "decide", "review", str(f), "--domain", "分类学"])
    out = capsys.readouterr().out
    assert "cirrus" in out and "多译名" in out
    with pytest.raises(SystemExit) as e:
        cli.main(["--db", db, "decide", "apply", str(f), "--book", "Handbook", "--domain", "分类学"])
    assert e.value.code == 0 and "新增 1" in capsys.readouterr().out
    con2 = D.connect(db)
    assert con2.execute("SELECT count(*) FROM terms WHERE source='决策_Handbook' AND status='候选'").fetchone()[0] == 1
