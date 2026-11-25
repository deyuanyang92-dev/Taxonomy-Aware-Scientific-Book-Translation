import docstore.textify as t


def test_ru_and_la_add_eng_for_latin_names(monkeypatch):
    monkeypatch.setattr(t, "_USER_TESS_LANG", None)
    assert t.tess_lang_for("ru") == "rus+eng"
    assert t.tess_lang_for("la") == "lat+eng"


def test_fr_de_unchanged_and_default(monkeypatch):
    monkeypatch.setattr(t, "_USER_TESS_LANG", None)
    assert t.tess_lang_for("fr") == "fra"
    assert t.tess_lang_for("de") == "deu"
    assert t.tess_lang_for(None) == "chi_sim+eng"


def test_user_env_wins(monkeypatch):
    monkeypatch.setattr(t, "_USER_TESS_LANG", "eng")
    assert t.tess_lang_for("ru") == "eng"
