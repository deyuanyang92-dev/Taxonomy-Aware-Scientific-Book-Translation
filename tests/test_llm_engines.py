"""llm_engines：全部用 mock，不真调 API、不真起命令行。"""
import subprocess
import types

import anthropic
import httpx
import pytest

import llm_engines as le


class FakeStream:
    def __init__(self, msg, boom=None):
        self.msg, self.boom = msg, boom

    def __enter__(self):
        if self.boom:
            raise self.boom
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self.msg


def make_msg(text, out_tokens=10, stop="end_turn"):
    blocks = [types.SimpleNamespace(type="thinking", thinking="想"), types.SimpleNamespace(type="text", text=text)]
    usage = types.SimpleNamespace(input_tokens=123, output_tokens=out_tokens, cache_read_input_tokens=7)
    return types.SimpleNamespace(content=blocks, usage=usage, stop_reason=stop)


def make_client(*outcomes):
    """outcomes：依次返回的消息或要抛的异常；记录调用参数。"""
    calls = []
    queue = list(outcomes)

    def stream(**kw):
        calls.append(kw)
        o = queue.pop(0)
        return FakeStream(None, boom=o) if isinstance(o, Exception) else FakeStream(o)

    return types.SimpleNamespace(messages=types.SimpleNamespace(stream=stream)), calls


@pytest.fixture(autouse=True)
def isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_USAGE_TSV", str(tmp_path / "usage.tsv"))
    monkeypatch.setenv("YZZ_ALLOW_DEEPSEEK", "1")  # 旧 DeepSeek 测试保留；默认停用另有测试
    monkeypatch.setattr(le, "wait_offpeak", lambda *a, **k: None)
    monkeypatch.setattr(le.time, "sleep", lambda s: None)
    monkeypatch.delenv("LLM_SKIP_OFFPEAK", raising=False)


def conn_error():
    return anthropic.APIConnectionError(request=httpx.Request("POST", "https://x"))


def test_deepseek_returns_text_and_usage_and_logs(monkeypatch, tmp_path):
    client, calls = make_client(make_msg("你好"))
    monkeypatch.setattr(le, "_make_client", lambda: client)
    text, usage = le.call("deepseek-flash", "系统", "用户", tag="c00")
    assert text == "你好"
    assert usage["input_tokens"] == 123 and usage["output_tokens"] == 10 and usage["cache_read_tokens"] == 7
    assert calls[0]["model"] == "deepseek-flash" and calls[0]["max_tokens"] == 64000
    assert calls[0]["system"] == "系统" and calls[0]["messages"] == [{"role": "user", "content": "用户"}]
    rows = (tmp_path / "usage.tsv").read_text(encoding="utf8").splitlines()
    assert rows[0].startswith("时间\tengine") and len(rows) == 2
    cols = rows[1].split("\t")
    assert cols[1] == "deepseek-flash" and cols[2] == "c00" and cols[3] == "123" and cols[4] == "10"


def test_deepseek_waits_offpeak_unless_skipped(monkeypatch):
    waited = []
    monkeypatch.setattr(le, "wait_offpeak", lambda *a, **k: waited.append(1))
    client, _ = make_client(make_msg("a"), make_msg("b"))
    monkeypatch.setattr(le, "_make_client", lambda: client)
    le.call("deepseek-v4-pro", "s", "u")
    assert waited == [1]
    monkeypatch.setenv("LLM_SKIP_OFFPEAK", "1")
    le.call("deepseek-v4-pro", "s", "u")
    assert waited == [1]


def test_deepseek_retries_connection_error_three_times(monkeypatch):
    client, calls = make_client(conn_error(), conn_error(), make_msg("ok"))
    monkeypatch.setattr(le, "_make_client", lambda: client)
    assert le.call("deepseek-flash", "s", "u")[0] == "ok"
    assert len(calls) == 3
    client, calls = make_client(conn_error(), conn_error(), conn_error())
    monkeypatch.setattr(le, "_make_client", lambda: client)
    with pytest.raises(le.EngineError, match="重试 3 次"):
        le.call("deepseek-flash", "s", "u")
    assert len(calls) == 3


def test_deepseek_nonretryable_error_raises_immediately(monkeypatch):
    client, calls = make_client(ValueError("坏参数"), make_msg("不应到达"))
    monkeypatch.setattr(le, "_make_client", lambda: client)
    with pytest.raises(ValueError):
        le.call("deepseek-flash", "s", "u")
    assert len(calls) == 1


def test_deepseek_reasoning_exhausted(monkeypatch):
    client, _ = make_client(make_msg("", out_tokens=64000, stop="max_tokens"))
    monkeypatch.setattr(le, "_make_client", lambda: client)
    with pytest.raises(le.EngineError, match="推理耗尽"):
        le.call("deepseek-v4-pro", "s", "u")
    # 有正文但 stop_reason=max_tokens：同样报错（被截断的输出不能当成功），且不写用量之外的任何产物
    client, _ = make_client(make_msg("有正文但被截断", out_tokens=64000, stop="max_tokens"))
    monkeypatch.setattr(le, "_make_client", lambda: client)
    with pytest.raises(le.EngineError, match="输出被截断"):
        le.call("deepseek-v4-pro", "s", "u")
    client, _ = make_client(make_msg("未达上限的短输出", out_tokens=500, stop="max_tokens"))
    monkeypatch.setattr(le, "_make_client", lambda: client)
    with pytest.raises(le.EngineError, match="输出被截断"):  # 只要 stop_reason 是 max_tokens 就报，不看 token 数
        le.call("deepseek-v4-pro", "s", "u")
    client, _ = make_client(make_msg("正常结束", out_tokens=64000, stop="end_turn"))
    monkeypatch.setattr(le, "_make_client", lambda: client)
    assert le.call("deepseek-v4-pro", "s", "u")[0] == "正常结束"


def test_token_from_env_then_script(monkeypatch, tmp_path):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key")
    assert le.deepseek_token() == "env-key"
    monkeypatch.delenv("DEEPSEEK_API_KEY")
    sh = tmp_path / "ds.sh"
    sh.write_text("export ANTHROPIC_BASE_URL=x\nexport ANTHROPIC_AUTH_TOKEN='file-key'\n", encoding="utf8")
    monkeypatch.setenv("DEEPSEEK_ENV_FILE", str(sh))
    assert le.deepseek_token() == "file-key"
    sh.write_text("export OTHER=1\n", encoding="utf8")
    with pytest.raises(le.EngineError, match="DEEPSEEK_API_KEY"):
        le.deepseek_token()


def test_claude_cli_command_and_stdin(monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen.update(cmd=cmd, **kw)
        return subprocess.CompletedProcess(cmd, 0, stdout="译文", stderr="")

    monkeypatch.setattr(le.subprocess, "run", fake_run)
    text, usage = le.call("claude-opus", "SYS", "USR")
    assert text == "译文" and usage["input_tokens"] is None
    assert seen["cmd"] == ["claude", "-p", "--model", "opus", "--tools", ""]
    assert seen["cwd"] == "/tmp" and "SYS" in seen["input"] and "USR" in seen["input"]
    le.call("claude-sonnet", "S", "U")
    assert seen["cmd"][3] == "sonnet"


def test_claude_cli_failure(monkeypatch):
    monkeypatch.setattr(le.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "出错了"))
    with pytest.raises(le.EngineError, match="出错了"):
        le.call("claude-sonnet", "s", "u")


def test_codex_reads_output_file(monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        out = cmd[cmd.index("-o") + 1]
        with open(out, "w", encoding="utf8") as f:
            f.write("codex 的译文")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(le.subprocess, "run", fake_run)
    text, _ = le.call("codex", "s", "u")
    assert text == "codex 的译文"
    assert seen["cmd"][:6] == ["codex", "exec", "--skip-git-repo-check", "-s", "read-only", "-o"] and seen["cmd"][-1] == "-"
    assert "-m" not in seen["cmd"]
    le.call("codex-sol", "s", "u")
    assert seen["cmd"][seen["cmd"].index("-m") + 1] == "gpt-6.1-sol" and seen["cmd"][-1] == "-"


def test_cursor_engine_command(monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="疣足具两束刚毛。", stderr="")

    monkeypatch.setattr(le.subprocess, "run", fake_run)
    text, _ = le.call("cursor-grok", "s", "u")
    assert text == "疣足具两束刚毛。" and seen["cmd"][seen["cmd"].index("--model") + 1] == "cursor-grok-4.5-high"


def test_deepseek_disabled_by_default(monkeypatch):
    monkeypatch.delenv("YZZ_ALLOW_DEEPSEEK", raising=False)
    with pytest.raises(le.EngineError, match="DeepSeek 已停用"):
        le.call("deepseek-flash", "s", "u")


def test_unknown_engine():
    with pytest.raises(le.EngineError, match="未知 engine"):
        le.call("gpt-x", "s", "u")


def test_usage_file_argument_overrides_env(monkeypatch, tmp_path):
    client, _ = make_client(make_msg("x"))
    monkeypatch.setattr(le, "_make_client", lambda: client)
    target = tmp_path / "sub" / "my.tsv"
    le.call("deepseek-flash", "s", "u", usage_file=target)
    assert target.exists() and not (tmp_path / "usage.tsv").exists()
