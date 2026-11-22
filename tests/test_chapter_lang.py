import re

import chapter_split as cs


def _pat():
    for v in vars(cs).values():
        if isinstance(v, re.Pattern) and "Глава" in v.pattern:
            return v
    raise AssertionError("no chapter pattern")


def test_headings_all_languages():
    p = _pat()
    for h in ["Глава 3. Морфология", "Kapitel 2 Systematik", "Chapitre 4", "Caput III", "第3章 总论", "Chapter 1"]:
        assert p.match(h), h
