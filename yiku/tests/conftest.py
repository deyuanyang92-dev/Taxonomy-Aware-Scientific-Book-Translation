"""yiku 测试默认不碰真实资料库：DOCSTORE_ROOT 指向空目录，用例（中文用例）功能自动关闭。需要时用例自己传 Store。"""
import pytest


@pytest.fixture(autouse=True)
def _no_real_docstore(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCSTORE_ROOT", str(tmp_path / "no_docstore_here"))
