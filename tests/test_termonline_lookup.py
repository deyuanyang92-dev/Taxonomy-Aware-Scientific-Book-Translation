"""termonline_lookup：缓存路径可配置、写前自动建目录、不联网（mock urlopen）。"""
import io
import json

import pytest

import termonline_lookup as tl


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(tl.time, "sleep", lambda s: None)


def fake_urlopen_factory(calls):
    def fake(req, timeout=0):
        url = req.full_url
        calls.append(url)
        if "tmWord/tips" in url:
            body = {"result": {"wordEsVos": [{"cnName": "刚毛 (多毛类)"}, {"cnName": "无关词"}]}}
        else:
            body = {"result": {"cn": "刚毛", "en": "chaeta; seta", "source": "《动物学名词》", "bbh": "第二版",
                               "publishYear": 2020, "subjectFullName": "动物学", "wordNumber": "01.001",
                               "definition": "体表\t几丁质\n刚毛"}}
        return io.BytesIO(json.dumps(body).encode("utf8"))
    return fake


def test_cache_path_env_and_default(monkeypatch, tmp_path):
    monkeypatch.setenv("TERMONLINE_CACHE", str(tmp_path / "x" / "c.json"))
    assert tl.cache_path() == str(tmp_path / "x" / "c.json")
    monkeypatch.delenv("TERMONLINE_CACHE")
    monkeypatch.setenv("HOME", str(tmp_path))
    assert tl.cache_path() == str(tmp_path / ".cache" / "termonline" / "cache.json")


def test_save_cache_creates_missing_directories(monkeypatch, tmp_path):
    target = tmp_path / "不存在的目录" / "二级" / "cache.json"
    monkeypatch.setenv("TERMONLINE_CACHE", str(target))
    assert tl.load_cache() == {}
    tl.save_cache({"k": 1})
    assert json.loads(target.read_text(encoding="utf8")) == {"k": 1}
    assert tl.load_cache() == {"k": 1}


def test_main_end_to_end_with_cache_reuse(monkeypatch, tmp_path):
    monkeypatch.setenv("TERMONLINE_CACHE", str(tmp_path / "new" / "cache.json"))
    calls = []
    monkeypatch.setattr(tl.urllib.request, "urlopen", fake_urlopen_factory(calls))
    src, out = tmp_path / "in.tsv", tmp_path / "out.tsv"
    src.write_text("English\nchaeta\n", encoding="utf8")
    assert tl.main([str(src), str(out)]) == 0
    rows = out.read_text(encoding="utf8").splitlines()
    assert rows[0].startswith("English\t名词委中文")
    cols = rows[1].split("\t")
    assert cols[:2] == ["chaeta", "刚毛"] and cols[3] == "《动物学名词》" and "\t" not in cols[8]
    assert (tmp_path / "new" / "cache.json").exists()
    n = len(calls)
    assert n >= 2
    tl.main([str(src), str(out)])  # 第二次全部走缓存
    assert len(calls) == n


def test_failed_requests_return_none_and_retry_three_times(monkeypatch, tmp_path):
    monkeypatch.setenv("TERMONLINE_CACHE", str(tmp_path / "c.json"))
    calls = []

    def boom(req, timeout=0):
        calls.append(1)
        raise OSError("网络不通")

    monkeypatch.setattr(tl.urllib.request, "urlopen", boom)
    assert tl.get({}, "tips", "chaeta") is None
    assert len(calls) == 3


def test_publish_copy_identical():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent / "scripts"
    assert (root / "termonline_lookup.py").read_text(encoding="utf8") == (root / "publish" / "termonline_lookup.py").read_text(encoding="utf8")
