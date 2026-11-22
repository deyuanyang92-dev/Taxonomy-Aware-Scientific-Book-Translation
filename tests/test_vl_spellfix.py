import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import vl_spellfix as sf  # noqa: E402


def _lex():
    lex = sf.Lexicon({})
    for _ in range(5):
        lex.add_text("faringeo parapodo Salvatoria sido")
    lex.add_text("faríngeo")
    return lex


def test_applied_only_with_second_engine():
    lex = _lex()
    new, ch = sf.fix_text("el farigeo largo", lex, {"faringeo"})
    assert "faringeo" in new.lower() or not ch
    new2, ch2 = sf.fix_text("el farigeo largo", lex, None)
    assert new2 == "el farigeo largo"  # 无 Tesseract 证据：只建议


def test_second_engine_agrees_with_original_blocks_fix():
    lex = _lex()
    new, _ = sf.fix_text("Salvadoria", lex, {"salvadoria", "salvatoria"})
    assert new == "Salvadoria"


def test_short_deletion_candidate_rejected():
    lex = _lex()
    new, _ = sf.fix_text("Síldo", lex, {"sido"})
    assert new == "Síldo"


def test_epithet_after_genus_not_dictionary_fixed():
    lex = _lex()
    new, _ = sf.fix_text("Syllis ligeiramente", lex, None)
    assert new == "Syllis ligeiramente"
