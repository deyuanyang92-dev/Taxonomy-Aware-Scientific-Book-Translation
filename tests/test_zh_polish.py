"""中文润色：度量、候选选择、闸口、按段 ID 落实（模型用假实现，不联网）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import zh_polish as zp  # noqa: E402
from transqa import zh_style as Z  # noqa: E402

STIFF = ("该类群的胸部与腹部这两个术语也被使用。该群此前被称为 Polyodotidae。该名已被一个鱼类科名占用。"
         "然而该种以及该属的关系仍不清楚。关于该科的研究很少。它们被认为是原始类群。")
DESC = "体长 2–3 mm。口前叶圆锥形。触手 3 对。背须短。腹须短。刚毛复型。"
MD = f"<!-- PDF p.1 -->\n\n# 第一章\n\n{STIFF}\n\n{DESC}\n\n1(2) 体具疣足 …… 2\n"


def test_measure_flags_overused_markers_and_description_skip():
    r = Z.measure(STIFF * 5)
    assert "该" in r.over and "被" in r.over
    assert Z.is_description(DESC) and not Z.is_description(STIFF)
    assert Z.paragraph_score(STIFF) >= Z.PARA_THRESHOLD and Z.paragraph_score(DESC) < Z.PARA_THRESHOLD


def test_guard_rules():
    old = "该种体长 25 mm，可能见于 *Nereis zonata* 的管中，不具鳃。"
    assert zp.guard(old, "此种体长 25 mm，可能见于 *Nereis zonata* 的管中，不具鳃。") == []
    assert any("ASCII" in w for w in zp.guard(old, "此种体长 26 mm，可能见于 *Nereis zonata* 的管中，不具鳃。"))
    assert any("限定语" in w for w in zp.guard(old, "此种体长 25 mm，见于 *Nereis zonata* 的管中，不具鳃。"))
    assert any("否定词" in w for w in zp.guard(old, "此种体长 25 mm，可能见于 *Nereis zonata* 的管中，具鳃。"))
    assert any("篇幅" in w for w in zp.guard(old, "此种体长 25 mm，可能见于 *Nereis zonata* 管，不具鳃，" + "很" * 40))


def test_check_lines():
    codes = {i.code for i in Z.check_lines("# 标题。\n体具具疣足、但无鳃，值得注意的是它\"很\"小。の")}
    assert {"title_period", "dup_char", "dun_clause", "filler", "half_quote", "kana"} <= codes


def test_polish_only_candidates_and_applies_guarded(tmp_path, monkeypatch):
    seen = []

    def fake(engine, system, user, tag, usage):
        seen.append(user)
        sid = user.split("⟧")[0].strip("⟦\n")
        return (f"⟦{sid}⟧\n胸部和腹部这两个术语在此类群中也有使用。此群此前称 Polyodotidae，"
                "因这一名称已为一鱼类科名所用而改名。此种与此属的关系仍不清楚，这方面的研究很少，一般认为是原始类群。")

    monkeypatch.setattr(zp, "llm", fake)
    monkeypatch.setattr(zp, "pick", lambda e: "deepseek-flash")
    monkeypatch.setattr(zp, "examples", lambda n=3: "（范文）")
    monkeypatch.setattr(zp, "verify", lambda pairs, eng, work, k: {s.id: {"same": True} for s, _ in pairs})
    st = zp.polish(MD, tmp_path, threshold=1.0)
    assert st["candidates"] == 1 and len(seen) == 1                     # 只送叙述段；标题、描述、检索表不送
    assert DESC not in seen[0] and "1(2)" not in seen[0]
    out = (tmp_path / "polished.md").read_text(encoding="utf-8")
    assert "Polyodotidae" in out and DESC in out and out.startswith("<!-- PDF p.1 -->")
    assert (tmp_path / "polish_report.md").exists()


def test_polish_rejects_changed_facts(tmp_path, monkeypatch):
    monkeypatch.setattr(zp, "llm", lambda *a: "⟦p1_s2⟧\n此群过去称 Polyodota。")      # 改了学名
    monkeypatch.setattr(zp, "verify", lambda pairs, eng, work, k: {})
    monkeypatch.setattr(zp, "pick", lambda e: "x")
    monkeypatch.setattr(zp, "examples", lambda n=3: "")
    zp.polish(MD, tmp_path, threshold=1.0)
    assert STIFF in (tmp_path / "polished.md").read_text(encoding="utf-8")


def test_guard_quantifier_time_and_quotes():
    old = "此后未见任何记录，这些“触手”最初被误认。"
    assert any("范围词" in w for w in zp.guard(old, "此后少见记录，这些“触手”最初被误认，" + "是" * 2))
    assert any("时间词" in w for w in zp.guard(old, "未见任何记录，这些“触手”被误认为别物了。"))
    assert any("引号" in w for w in zp.guard(old, "此后未见任何记录，这些触手最初被误认为。"))


def test_second_model_rejection_keeps_original(tmp_path, monkeypatch):
    new = ("胸部和腹部这两个术语在此类群中也有使用。此群此前称 Polyodotidae，因这一名称已为一鱼类科名所用而改名。"
           "此种与此属的关系仍不清楚，这方面的研究很少，一般认为是原始类群。")
    monkeypatch.setattr(zp, "llm", lambda *a: f"⟦p1_s2⟧\n{new}")
    monkeypatch.setattr(zp, "pick", lambda e: "deepseek-flash")
    monkeypatch.setattr(zp, "examples", lambda n=3: "")
    monkeypatch.setattr(zp, "verify", lambda pairs, eng, work, k: {"p1_s2": {"same": False, "why": "指代变化"}})
    st = zp.polish(MD, tmp_path, threshold=1.0)
    assert st["applied"] == 0 and STIFF in (tmp_path / "polished.md").read_text(encoding="utf-8")


def test_same_model_for_polish_and_verify_refused(tmp_path, monkeypatch):
    import pytest
    monkeypatch.setattr(zp, "pick", lambda e: "codex-sol")
    monkeypatch.setattr(zp, "examples", lambda n=3: "")
    with pytest.raises(ValueError, match="同一模型"):
        zp.polish(MD, tmp_path, threshold=1.0, verify_engine="codex-sol")


def test_engine_failure_keeps_original_and_continues(tmp_path, monkeypatch):
    def boom(*a):
        raise RuntimeError("workspace routing discovery failed")

    monkeypatch.setattr(zp, "llm", boom)
    monkeypatch.setattr(zp, "pick", lambda e: "codex-sol")
    monkeypatch.setattr(zp, "examples", lambda n=3: "")
    st = zp.polish(MD, tmp_path, threshold=1.0, verify_engine="cursor-composer")
    assert st["applied"] == 0 and st["rejected"] == 1
    assert "调用失败" in (tmp_path / "polish_report.md").read_text(encoding="utf-8")


def test_guard_rejects_wholesale_rewrite():
    old = "阿尔文虫科是发现较晚的类群，仅见于太平洋与印度洋深海热液口，研究得相当充分。"
    new = "深海热液口才有这类较晚发现的动物，太平洋、印度洋两处皆可寻获，相关工作做得颇为扎实。"
    assert any("改动过大" in w for w in zp.guard(old, new))
