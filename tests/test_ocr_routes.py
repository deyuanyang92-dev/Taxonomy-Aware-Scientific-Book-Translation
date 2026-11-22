import pytest

import docstore.textify as t
from docstore.engines import ENGINE_MAP
from docstore.engines import paddle_vl
from docstore.ocr_routes import route_for


def test_route_table_matches_bench():
    assert route_for("ru").primary == "tesseract"
    assert route_for("fr").primary == "ppocr"
    assert route_for("la").primary == "paddle_vl"  # 默认云端（用户 2026-11-22）
    assert route_for("la").fallback[0] == "ppocr"
    for lang in ("fr", "la", "zh", "ja"):
        assert route_for(lang).env["DOCSTORE_PPOCR_MODEL"] == "PP-OCRv6_medium"


def test_unrouted_languages_fall_back_to_old_default():
    assert route_for("de") is None
    assert route_for("en") is None
    assert route_for(None) is None


def test_all_route_engines_registered():
    for lang in ("ru", "fr", "la", "zh", "ja"):
        r = route_for(lang)
        for e in (r.primary, *r.fallback):
            assert e in ENGINE_MAP


def test_fallback_on_primary_failure(monkeypatch):
    calls = []

    def boom(p, n, d):
        calls.append("a")
        raise RuntimeError("no network")

    monkeypatch.setitem(ENGINE_MAP, "paddle_vl", boom)
    monkeypatch.setitem(ENGINE_MAP, "ppocr", lambda p, n, d: ("local text", 0.9))
    used, txt, conf = t._run_with_fallback("paddle_vl", ("ppocr",), "x.pdf", 1, 300)
    assert (used, txt, conf) == ("ppocr", "local text", 0.9) and calls == ["a"]


def test_unknown_engine_is_config_error_not_fallback():
    with pytest.raises(ValueError):
        t._run_with_fallback("nope", ("ppocr",), "x.pdf", 1, 300)


def test_all_fail_raises_last(monkeypatch):
    def bad(p, n, d):
        raise RuntimeError("x")

    monkeypatch.setitem(ENGINE_MAP, "paddle_vl", bad)
    monkeypatch.setitem(ENGINE_MAP, "ppocr", bad)
    with pytest.raises(RuntimeError):
        t._run_with_fallback("paddle_vl", ("ppocr",), "x.pdf", 1, 300)


def test_missing_token_raises_runtime_error(monkeypatch, tmp_path):
    monkeypatch.delenv("PADDLEOCR_TOKEN", raising=False)
    monkeypatch.setattr(paddle_vl.Path, "home", staticmethod(lambda: tmp_path))
    with pytest.raises(RuntimeError, match="密钥"):
        paddle_vl._token()


def test_clean_md_strips_markup():
    assert paddle_vl.clean_md("# **Title**\n![x](a.png)\n<div>t</div>") == "Title\n\nt"
