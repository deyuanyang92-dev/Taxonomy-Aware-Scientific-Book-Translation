import tm


def test_pair_isolated(tmp_path):
    db = tmp_path / "tm.sqlite"
    tm.store("Hallo Welt", "Hello world", "de", "en", "google", db)
    tm.store("Hello world", "你好世界", "en", "zh-CN", "google", db)
    assert tm.lookup("Hallo Welt", "de", "en", db) == "Hello world"
    assert tm.lookup("Hallo Welt", "de", "zh-CN", db) is None
    assert tm.lookup("Hello world", "en", "zh-CN", db) == "你好世界"


def test_whitespace_normalised_and_overwrite(tmp_path):
    db = tmp_path / "tm.sqlite"
    tm.store("a  b\nc", "x", "ru", "en", "google", db)
    assert tm.lookup("a b c", "ru", "en", db) == "x"
    tm.store("a b c", "y", "ru", "en", "codex", db)
    assert tm.lookup("a  b c", "ru", "en", db) == "y"


def test_empty_not_stored(tmp_path):
    db = tmp_path / "tm.sqlite"
    tm.store("", "x", "ru", "en", "g", db)
    tm.store("a", " ", "ru", "en", "g", db)
    assert tm.lookup("", "ru", "en", db) is None
    assert tm.lookup("a", "ru", "en", db) is None
