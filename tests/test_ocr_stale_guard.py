"""旧代码进程防护：源码在进程导入后被改过，run 必须拒绝启动（B10 根因防复发）。"""

import pytest

from docstore import ocr_batch


def test_stale_detected_when_import_is_older_than_mtime(monkeypatch):
    monkeypatch.setattr(ocr_batch, "_IMPORT_TS", 0.0)
    assert set(ocr_batch.stale_code_files()) == {"ocr_batch.py", "paddle_vl.py"}


def test_no_stale_when_import_is_newer(monkeypatch):
    monkeypatch.setattr(ocr_batch, "_IMPORT_TS", 4e9)
    assert ocr_batch.stale_code_files() == []


def test_cmd_run_refuses_stale_process(monkeypatch):
    monkeypatch.setattr(ocr_batch, "stale_code_files", lambda: ["ocr_batch.py"])
    monkeypatch.delenv("DOCSTORE_ALLOW_STALE", raising=False)
    with pytest.raises(SystemExit):
        ocr_batch.cmd_run(None, None)  # 必须在触碰 p 之前退出
