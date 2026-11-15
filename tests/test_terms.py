"""术语按本地库规范化：以原文为锚，只换登记的异写；原文自己的用法、学名、译注不动。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from transqa.terms import Term, load, normalize  # noqa: E402

LIB = [Term("четинка", "chaeta", {"setae": "chaetae", "seta": "chaeta", "bristles": "chaetae"}),
       Term("параподий", "parapodium", {"parapods": "parapodia", "parapod": "parapodium"})]


def test_replaces_registered_variants_only_where_source_has_term():
    src = "Параподите с прости четинки."
    out, log = normalize(src, "Parapods with simple setae. Seta long.", LIB)
    assert out == "Parapodia with simple chaetae. Chaeta long."
    assert ("setae", "chaetae", 1) in log


def test_source_anchor_keeps_original_usage():
    # 原文这一段没有「четинка」（例如英文原作者自己写的 setae、引文里的旧用法）：不规范
    out, log = normalize("Тялото късо.", "Body short; setae as in Fauvel's usage.", LIB)
    assert out == "Body short; setae as in Fauvel's usage." and log == []


def test_italics_and_translator_notes_untouched():
    src = "четинки"
    out, _ = normalize(src, "*Setae* sp. and setae [TN: printed setae]", LIB)
    assert out == "*Setae* sp. and chaetae [TN: printed setae]"


def test_load_table_with_variants(tmp_path):
    f = tmp_path / "g.md"
    f.write_text("| Български | English | variants |\n| --- | --- | --- |\n| четинка | chaeta | setae=chaetae; seta |\n",
                 encoding="utf-8")
    t = [x for x in load(f) if x.source == "четинка"][0]
    assert t.variants == {"setae": "chaetae", "seta": "chaeta"}
