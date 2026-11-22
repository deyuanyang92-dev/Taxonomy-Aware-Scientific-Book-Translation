"""零模型评分器的正则：中文里「1922年」「如Typosyllis anoculata n. sp.」不能因 \\b 失配而被误报缺失。"""
import zero_model_score as z


def test_year_and_binomial_next_to_cjk():
    assert z.YEAR.findall("1922年和1923年，AUGENER (1922)") == ["1922", "1923", "1922"]
    m = z.BIN.search("附录可能，如Typosyllis anoculata n. sp.，眼睛")
    assert m and m.group(0) == "Typosyllis anoculata"
