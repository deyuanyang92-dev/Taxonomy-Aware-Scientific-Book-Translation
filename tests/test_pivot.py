from pathlib import Path

import auto_translate as at


def test_needs_pivot():
    assert at.needs_pivot("ru", "zh-CN")
    assert at.needs_pivot("de", "zh")
    assert at.needs_pivot("ja", "zh-CN")
    assert not at.needs_pivot("en", "zh-CN")
    assert not at.needs_pivot("ru", "en")
    assert not at.needs_pivot("ru", "zh-CN", direct=True)


def test_strip_opts_both_forms():
    argv = ["run", "S.md", "-o", "W", "--sl=ru", "--tl", "zh-CN", "--engine", "none", "--direct"]
    out = at._strip_opts(argv, {**at._PIVOT_DROP, "--direct": 0})
    assert out == ["run", "S.md", "--engine", "none"]


def test_run_pivot_two_hops(tmp_path, monkeypatch):
    calls = []

    def fake_main(argv):
        calls.append(argv)
        w = Path(argv[argv.index("-o") + 1])
        w.mkdir(parents=True, exist_ok=True)
        (w / "final.md").write_text("x", encoding="utf-8")

    monkeypatch.setattr(at, "main", fake_main)
    argv = ["run", "S.md", "-o", str(tmp_path), "--sl", "ru", "--tl", "zh-CN", "--engine", "none",
            "--glossary", "G.tsv"]
    a = type("A", (), dict(work=str(tmp_path), sl="ru", tl="zh-CN", src="S.md", presub=None,
                           glossary="G.tsv", stop_after=None))()
    at.run_pivot(a, argv)
    assert len(calls) == 2
    h1, h2 = calls
    assert h1[h1.index("--sl") + 1] == "ru" and h1[h1.index("--tl") + 1] == "en"
    assert "--glossary" in h1 and "--glossary" not in h2
    assert h2[1].endswith("hop1_ru-en/final.md")
    assert h2[h2.index("--sl") + 1] == "en" and h2[h2.index("--tl") + 1] == "zh-CN"
    assert (tmp_path / "hop2_en-zh" / "final.md").exists()
    assert h1.count("--engine") == 1 and h2.count("--engine") == 1
