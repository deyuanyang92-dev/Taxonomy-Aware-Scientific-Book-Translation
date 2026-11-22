"""德文参考文献行：判为 reference（不送机翻），确定性处理只换缩写（S.→p.、Taf.→pl.），作者、年份、刊名不动。"""
from transqa import blocks

REFS = [
    "AUGENER, H. (1922): Polychaeta von Südwest-Australien. Mitt. Zool. Mus. Hamburg 39: 1-64, Taf. 2.",
    "EHLERS, E. (1901): Die Polychaeten des magellanischen und chilenischen Strandes. Festschr. Leipzig, 232 S.",
    "HARTMANN-SCHRÖDER, G. 1962. Zur Kenntnis des Eulitorals. Mitt. hamb. zool. Mus. Inst. 60: 57-270.",
]


def test_classified_reference():
    assert all(blocks.classify(r, "de") == "reference" for r in REFS)


def test_deterministic_keeps_authors_years_and_swaps_abbrev():
    out = blocks.deterministic(REFS[0], "de")
    assert "AUGENER, H. (1922)" in out and "Mitt. Zool. Mus. Hamburg 39: 1-64" in out and "pl. 2" in out
    assert blocks.deterministic(REFS[1], "de").endswith("232 S.")   # 页数后缀不是「S. 数字」，不改
