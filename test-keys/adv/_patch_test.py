
import pathlib
p = pathlib.Path("tests/test_booklayout_keys_layout.py")
L = p.read_text(encoding="utf-8").split("\n")
i = next(k for k, s in enumerate(L) if s.strip().startswith("assert texts[-1].replace("))
L[i:i+1] = [
 "    # 去向可能拆成多个 run（窄不换行空格 U+202F 单独成 run），比较最后一个制表位之后的全部文本",
 '    last_tab = len(texts) - 1 - texts[::-1].index("\\t")',
 '    after = "".join(texts[last_tab + 1:])',
 "    for sp in (chr(0x202F), chr(0xA0)):",
 '        after = after.replace(sp, " ")',
 '    assert after == "(p. 76)"',
]
p.write_text("\n".join(L), encoding="utf-8")
print(i)
