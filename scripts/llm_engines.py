"""直接调用模型的统一入口：call(engine, system, user) -> (正文, usage 字典)。

engine 取值：
  deepseek-flash / deepseek-v4-pro   anthropic SDK 调 DeepSeek 的 Anthropic 兼容端点（流式）
  claude-sonnet / claude-opus        subprocess 调 `claude -p --model sonnet|opus --tools ""`（订阅额度，无工具）
  codex                              `codex exec --skip-git-repo-check -s read-only -o <tmp> -`

DeepSeek 凭证：环境变量 DEEPSEEK_API_KEY；缺省时读 DEEPSEEK_ENV_FILE（默认
/mnt/p/纤毛虫-环节动物定殖/claude-deepseek.sh）里 `export ANTHROPIC_AUTH_TOKEN=` 一行。凭证不写进仓库、不进日志。
DeepSeek 调用前先 wait_offpeak()（忙时等到闲时，半价）；LLM_SKIP_OFFPEAK=1 可跳过。

每次调用向 usage.tsv 追加一行：时间、engine、标签、输入 token、输出 token、缓存读 token、耗时。
路径取 call(usage_file=…)，其次环境变量 LLM_USAGE_TSV，缺省 ~/.cache/yzz-translate/usage.tsv。
命令行自测：python3 llm_engines.py <engine> "<系统提示>" "<用户消息>"
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import tempfile
import time
from typing import Any

from deepseek_offpeak import wait_offpeak

DEEPSEEK_ENGINES = ("deepseek-flash", "deepseek-v4-pro")
CLAUDE_ENGINES = {"claude-sonnet": "sonnet", "claude-opus": "opus"}
ENGINES = (*DEEPSEEK_ENGINES, *CLAUDE_ENGINES, "codex")

DEEPSEEK_BASE_URL = "https://api.deepseek.com/anthropic"
DEEPSEEK_ENV_FILE = "/mnt/p/纤毛虫-环节动物定殖/claude-deepseek.sh"
MAX_TOKENS = 64000
RETRIES = 3
CLI_TIMEOUT = 1800
USAGE_HEADER = "时间\tengine\t标签\t输入token\t输出token\t缓存读token\t耗时秒\n"


class EngineError(RuntimeError):
    """调用失败：凭证缺失、连接重试耗尽、推理耗尽、命令行退出码非零等。"""


def deepseek_token() -> str:
    """先读环境变量 DEEPSEEK_API_KEY，再读 DEEPSEEK_ENV_FILE 里的 export ANTHROPIC_AUTH_TOKEN= 行。"""
    tok = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if tok:
        return tok
    path = os.environ.get("DEEPSEEK_ENV_FILE", DEEPSEEK_ENV_FILE)
    try:
        lines = pathlib.Path(path).read_text(encoding="utf8").splitlines()
    except OSError:
        lines = []
    for line in lines:
        if line.startswith("export ANTHROPIC_AUTH_TOKEN="):
            tok = line.split("=", 1)[1].strip().strip("'\"")
            if tok:
                return tok
    raise EngineError(f"找不到 DeepSeek 凭证：请设环境变量 DEEPSEEK_API_KEY，或在 {path} 里写 export ANTHROPIC_AUTH_TOKEN=")


def _make_client() -> Any:
    import anthropic

    return anthropic.Anthropic(base_url=DEEPSEEK_BASE_URL, auth_token=deepseek_token(), api_key=None)


def _retryable(exc: Exception) -> bool:
    """连接错误、超时、429、5xx 才重试；其余（鉴权、参数错误）直接抛。"""
    try:
        import anthropic
    except ImportError:  # pragma: no cover
        return False
    if isinstance(exc, anthropic.APIConnectionError):
        return True
    status = getattr(exc, "status_code", None)
    return isinstance(exc, anthropic.APIStatusError) and (status == 429 or (status or 0) >= 500)


def _deepseek(engine: str, system: str, user: str, max_tokens: int) -> tuple[str, dict[str, Any]]:
    client = _make_client()
    last: Exception | None = None
    for k in range(RETRIES):
        try:
            with client.messages.stream(
                model=engine, max_tokens=max_tokens, system=system,
                messages=[{"role": "user", "content": user}],
            ) as stream:
                msg = stream.get_final_message()
            break
        except Exception as exc:  # noqa: BLE001 - 只对可重试的错误重试，其余原样抛出
            if not _retryable(exc):
                raise
            last = exc
            print(f"[llm_engines] {engine} 连接错误，第 {k + 1}/{RETRIES} 次：{type(exc).__name__}", file=sys.stderr)
            if k < RETRIES - 1:
                time.sleep(3 * (k + 1))
    else:
        raise EngineError(f"{engine} 连接重试 {RETRIES} 次仍失败：{last}")
    text = "".join(getattr(b, "text", "") for b in msg.content if getattr(b, "type", "") == "text")
    u = msg.usage
    out_tokens = int(getattr(u, "output_tokens", 0) or 0)
    usage = {
        "input_tokens": int(getattr(u, "input_tokens", 0) or 0),
        "output_tokens": out_tokens,
        "cache_read_tokens": int(getattr(u, "cache_read_input_tokens", 0) or 0),
    }
    if not text.strip() and (out_tokens >= max_tokens or getattr(msg, "stop_reason", "") == "max_tokens"):
        raise EngineError(f"{engine} 推理耗尽：输出 {out_tokens} token 达上限 {max_tokens}，正文为空（调大 max_tokens 或换模型）")
    return text, usage


def _cli(cmd: list[str], prompt: str, name: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=CLI_TIMEOUT, cwd="/tmp")
    except FileNotFoundError as exc:
        raise EngineError(f"{name}：找不到命令 {cmd[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise EngineError(f"{name}：超过 {CLI_TIMEOUT} 秒未返回") from exc


def _claude(engine: str, system: str, user: str) -> tuple[str, dict[str, Any]]:
    cmd = ["claude", "-p", "--model", CLAUDE_ENGINES[engine], "--tools", ""]
    r = _cli(cmd, system + "\n\n---\n\n" + user, engine)
    if r.returncode != 0 or not r.stdout.strip():
        raise EngineError(f"{engine} 退出码 {r.returncode}：{r.stderr[-300:].strip()}")
    return r.stdout, {"input_tokens": None, "output_tokens": None, "cache_read_tokens": None}


def _codex(system: str, user: str) -> tuple[str, dict[str, Any]]:
    with tempfile.TemporaryDirectory() as td:
        out = pathlib.Path(td) / "codex_out.txt"
        cmd = ["codex", "exec", "--skip-git-repo-check", "-s", "read-only", "-o", str(out), "-"]
        r = _cli(cmd, system + "\n\n---\n\n" + user, "codex")
        text = out.read_text(encoding="utf8") if out.exists() else ""
    if r.returncode != 0 or not text.strip():
        raise EngineError(f"codex 退出码 {r.returncode}：{r.stderr[-300:].strip()}")
    return text, {"input_tokens": None, "output_tokens": None, "cache_read_tokens": None}


def usage_path(usage_file: str | os.PathLike[str] | None = None) -> pathlib.Path:
    p = usage_file or os.environ.get("LLM_USAGE_TSV") or "~/.cache/yzz-translate/usage.tsv"
    return pathlib.Path(p).expanduser()


def log_usage(engine: str, usage: dict[str, Any], tag: str = "",
              usage_file: str | os.PathLike[str] | None = None) -> None:
    path = usage_path(usage_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists() or path.stat().st_size == 0

    def cell(v: Any) -> str:
        return "-" if v is None else str(v)

    row = [time.strftime("%Y-%m-%d %H:%M:%S"), engine, tag.replace("\t", " "),
           cell(usage.get("input_tokens")), cell(usage.get("output_tokens")),
           cell(usage.get("cache_read_tokens")), f"{usage.get('seconds', 0):.1f}"]
    with open(path, "a", encoding="utf8") as f:
        if new:
            f.write(USAGE_HEADER)
        f.write("\t".join(row) + "\n")


def call(engine: str, system: str, user: str, *, max_tokens: int = MAX_TOKENS, tag: str = "",
         usage_file: str | os.PathLike[str] | None = None, offpeak: bool = True) -> tuple[str, dict[str, Any]]:
    """调用 engine，返回 (正文, usage)。usage 含 input_tokens/output_tokens/cache_read_tokens（命令行引擎为 None）、
    seconds、engine。失败抛 EngineError。"""
    if engine not in ENGINES:
        raise EngineError(f"未知 engine {engine!r}，可选：{', '.join(ENGINES)}")
    t0 = time.time()
    if engine in DEEPSEEK_ENGINES:
        if offpeak and not os.environ.get("LLM_SKIP_OFFPEAK"):
            wait_offpeak()
        t0 = time.time()
        text, usage = _deepseek(engine, system, user, max_tokens)
    elif engine == "codex":
        text, usage = _codex(system, user)
    else:
        text, usage = _claude(engine, system, user)
    usage = {**usage, "engine": engine, "seconds": time.time() - t0}
    log_usage(engine, usage, tag, usage_file)
    return text, usage


def main(argv: list[str] | None = None) -> int:
    a = sys.argv[1:] if argv is None else argv
    if len(a) != 3 or a[0] not in ENGINES:
        print(f"用法: llm_engines.py <{'|'.join(ENGINES)}> <系统提示> <用户消息>", file=sys.stderr)
        return 2
    text, usage = call(a[0], a[1], a[2], tag="cli")
    print(text)
    print(usage, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
