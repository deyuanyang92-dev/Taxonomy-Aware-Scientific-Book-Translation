"""vote() 不得在两引擎分歧时静默返回「0 未决」（计划 Task 3a；Codex 评审 consensus.py:79）。"""
from docstore.consensus import Reading, vote


def _two(a: str, b: str):
    return [Reading("rapidocr", a, 0.9), Reading("tesseract", b, 0.9)]


def test_identical_engines_have_zero_unresolved():
    text, _conf, dis, un = vote(_two("Nereis virens Sars", "Nereis virens Sars"))
    assert text == "Nereis virens Sars" and un == 0 and dis == []


def test_rapid_tess_disagreement_is_reported_not_silent():
    text, _conf, dis, un = vote(_two("Nereis virens Sars 1835", "Nereis vlrens Sars 1B35"))
    assert text == "Nereis virens Sars 1835"  # 文本仍取主引擎，行为不变
    assert un >= 2
    assert dis and dis[0]["kind"] == "engine_disagreement"


def test_low_similarity_fallback_is_reported_not_silent():
    text, _conf, dis, un = vote([Reading("a", "完全不同的一段话", 0.9), Reading("b", "xyz 123 qqq", 0.8)])
    assert text == "完全不同的一段话"
    assert un > 0 and dis and dis[0]["kind"] == "engine_disagreement"
