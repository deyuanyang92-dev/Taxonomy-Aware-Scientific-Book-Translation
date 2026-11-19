"""直接调用模型的统一入口：call(engine, system, user) -> (正文, usage 字典)。

engine 取值：
  deepseek-flash / deepseek-v4-pro   anthropic SDK 调 DeepSeek 的 Anthropic 兼容端点（流式）
  claude-sonnet / claude-opus        subprocess 调 `claude -p --model sonnet|opus --tools ""`（订阅额度，无工具）
  codex                              `codex exec --skip-git-repo-check -s read-only -o <tmp> -`

DeepSeek 凭证：环境变量 DEEPSEEK_API_KEY；缺省时读 DEEPSEEK_ENV_FILE（默认
/mnt/p/纤毛虫-环节动物定殖/claude-deepseek.sh）里 `export ANTHROPIC_AUTH_TOKEN=` 一行。凭证不写进仓库、不进日志。
DeepSeek 调用前先 wait_offpeak()（忙时等到闲时，半价）；LLM_SKIP_OFFPEAK=1 可跳过。

省 token（见 token_economy.py / skill/TOKEN_ECONOMY.md）：
  - profile=json|revise|translate|default|long 控制 max_tokens（默认 default=8192，不再默认 64000）
  - DeepSeek system 自动加 cache_control，稳定前缀走缓存价
  - YZZ_TOKEN_BUDGET=N 设进程累计预算，超限抛 BudgetExceeded
  - 默认关 thinking（YZZ_DEEPSEEK_THINKING=1 才开）

每次调用向 usage.tsv 追加一行：时间、engine、标签、输入 token、输出 token、缓存读 token、耗时。
路径取 call(usage_file=…)，其次环境变量 LLM_USAGE_TSV，缺省 ~/.cache/yzz-translate/usage.tsv。
命令行自测：python3 llm_engines.py <engine> "<系统提示>" "<用户消息>"
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any

from deepseek_offpeak import is_peak, seconds_to_offpeak, wait_offpeak
from token_economy import BudgetExceeded, check_budget, out_budget, record_usage, system_blocks

_USAGE_LOCK = threading.Lock()

DEEPSEEK_ENGINES = ("deepseek-flash", "deepseek-v4-pro")
CLAUDE_ENGINES = {"claude-sonnet": "sonnet", "claude-opus": "opus"}
# Codex（ChatGPT Pro 账号）按任务选模型：sol 核译/盲评，astra 只用于最难的少数段，luna 简单任务；"codex" = config 默认
CODEX_ENGINES = {"codex": None, "codex-luna": "gpt-6-luna", "codex-sol": "gpt-6.1-sol", "codex-astra": "gpt-6-astra"}
# Cursor：本地区只开放非 Anthropic/OpenAI 的模型（2026-11-13 实测 Claude、GPT 均报 region 不支持）
CURSOR_ENGINES = {"cursor-grok": "cursor-grok-4.5-high", "cursor-composer": "composer-2.5"}
ENGINES = (*DEEPSEEK_ENGINES, *CLAUDE_ENGINES, *CODEX_ENGINES, *CURSOR_ENGINES)

DEEPSEEK_BASE_URL = "https://api.deepseek.com/anthropic"
DEEPSEEK_ENV_FILE = "/mnt/p/纤毛虫-环节动物定殖/claude-deepseek.sh"
MAX_TOKENS = 64000  # 绝对上限；日常请用 profile= / out_budget()，不要直接传 64000
RETRIES = 3
# 高峰前最多等半小时；更长说明离折扣时段还远，直接抛错让任务延期，
# 不要把进程挂几个小时（用户 2026-11-17：只在官方折扣时段调用）。
MAX_OFFPEAK_WAIT = 1800
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


def _deepseek(engine: str, system: str, user: str, max_tokens: int,
              check_window: bool = False) -> tuple[str, dict[str, Any]]:
    client = _make_client()
    last: Exception | None = None
    sys_arg: str | list[dict[str, Any]] = system_blocks(system, cache=True)
    for k in range(RETRIES):
        if check_window and k and is_peak():  # 重试前再查一次：夜间窗口已过就停，任务延期而不是越界调用
            raise EngineError("DeepSeek 已进入高峰时段，不再重试；任务延期到下一个折扣时段")
        try:
            # 默认关闭 thinking：2026-11-14 实测，关闭后审校同样抓到误译，输出 token 约为开启时的 1/17；
            # budget_tokens 不被 DeepSeek 遵守（照样长思考且可能无正文）。确需深思时设 YZZ_DEEPSEEK_THINKING=1。
            extra: dict[str, Any] = ({} if os.environ.get("YZZ_DEEPSEEK_THINKING")
                                     else {"thinking": {"type": "disabled"}})
            with client.messages.stream(
                model=engine, max_tokens=max_tokens, system=sys_arg,
                messages=[{"role": "user", "content": user}], **extra,
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
    truncated = getattr(msg, "stop_reason", "") == "max_tokens"
    if not text.strip() and (truncated or out_tokens >= max_tokens):
        raise EngineError(f"{engine} 推理耗尽：输出 {out_tokens} token 达上限 {max_tokens}，正文为空（调大 max_tokens 或换模型）")
    if truncated:  # 有正文也不放行：被截断的译文或问题单会悄悄丢掉后半
        raise EngineError(f"{engine} 输出被截断：stop_reason=max_tokens，输出 {out_tokens} token 达上限 {max_tokens}（调大 max_tokens，或缩小输入块）")
    return text, usage


def _cli(cmd: list[str], prompt: str, name: str, cwd: str = "/tmp") -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=CLI_TIMEOUT, cwd=cwd)
    except FileNotFoundError as exc:
        raise EngineError(f"{name}：找不到命令 {cmd[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise EngineError(f"{name}：超过 {CLI_TIMEOUT} 秒未返回") from exc


# claude -p 精简参数：不加载用户/项目设置、CLAUDE.md、技能、MCP、插件钩子，系统提示词只用我们的。
# 2026-11-14 实测：默认每次调用约 35,000 token 固定开销，精简后约 580。
CLAUDE_LEAN = ["--tools", "", "--setting-sources", "", "--strict-mcp-config", "--disable-slash-commands",
               "--exclude-dynamic-system-prompt-sections", "--output-format", "json"]


# 2026-11-19：每次调用不落会话文件；单次预算默认 1 美元（防失控，可用 YZZ_CLAUDE_MAX_USD 改，off 关闭）；
# 思考档位默认不传（用 CLI 默认），可用 YZZ_CLAUDE_EFFORT=low|medium|high|xhigh|max 指定。
# claude 2.x 的 `claude -p --help` 没有 --max-turns；CLAUDE_LEAN 已关掉全部工具，本来就只有一轮。
CLAUDE_GUARD = ["--no-session-persistence"]
CLAUDE_EFFORTS = ("low", "medium", "high", "xhigh", "max")
CLAUDE_DEFAULT_MAX_USD = "1"


def _claude_guard_args() -> list[str]:
    args = list(CLAUDE_GUARD)
    usd = os.environ.get("YZZ_CLAUDE_MAX_USD", CLAUDE_DEFAULT_MAX_USD).strip()
    if usd.lower() not in ("off", "none", "0"):
        try:
            ok = float(usd) > 0
        except ValueError:
            ok = False
        if not ok:
            raise EngineError(f"YZZ_CLAUDE_MAX_USD={usd!r} 无效：需正数，或 off 关闭")
        args += ["--max-budget-usd", usd]
    effort = os.environ.get("YZZ_CLAUDE_EFFORT", "").strip().lower()
    if effort:
        if effort not in CLAUDE_EFFORTS:
            raise EngineError(f"YZZ_CLAUDE_EFFORT={effort!r} 无效：可选 {', '.join(CLAUDE_EFFORTS)}")
        args += ["--effort", effort]
    return args


def _claude(engine: str, system: str, user: str) -> tuple[str, dict[str, Any]]:
    cmd = ["claude", "-p", "--model", CLAUDE_ENGINES[engine], *CLAUDE_LEAN, *_claude_guard_args(),
           "--system-prompt", system]
    r = _cli(cmd, user, engine)
    if r.returncode != 0 or not r.stdout.strip():
        raise EngineError(f"{engine} 退出码 {r.returncode}：{r.stderr[-300:].strip()}")
    try:
        d = json.loads(r.stdout)
    except json.JSONDecodeError as exc:
        raise EngineError(f"{engine} 输出不是 JSON：{r.stdout[:200]}") from exc
    d = d[-1] if isinstance(d, list) else d
    if d.get("is_error") or not str(d.get("result", "")).strip():
        raise EngineError(f"{engine} 返回错误或空正文：{str(d.get('result', ''))[:300]}")
    u = d.get("usage") or {}
    usage = {"input_tokens": int(u.get("input_tokens", 0) or 0) + int(u.get("cache_creation_input_tokens", 0) or 0),
             "output_tokens": int(u.get("output_tokens", 0) or 0),
             "cache_read_tokens": int(u.get("cache_read_input_tokens", 0) or 0)}
    return str(d["result"]), usage


def _codex(system: str, user: str, model: str | None = None) -> tuple[str, dict[str, Any]]:
    # 工作目录用新建的空临时目录（-C 与 cwd 都指向它）；read-only 沙箱仍可读全盘，书稿提示词里另须写明不得读本地文件。
    with tempfile.TemporaryDirectory(prefix="codex_") as td:
        out = pathlib.Path(td) / "codex_out.txt"
        work = pathlib.Path(td) / "work"
        work.mkdir()
        cmd = ["codex", "exec", "--skip-git-repo-check", "-s", "read-only", "-o", str(out)]
        if model:
            cmd += ["-m", model]
        if os.environ.get("YZZ_CODEX_EFFORT"):  # 如 medium；不设则用 ~/.codex/config.toml 的默认
            cmd += ["-c", f'model_reasoning_effort="{os.environ["YZZ_CODEX_EFFORT"]}"']
        cmd += ["-C", str(work), "-"]
        r = _cli(cmd, system + "\n\n---\n\n" + user, "codex", cwd=str(work))
        text = out.read_text(encoding="utf8") if out.exists() else ""
    if r.returncode != 0 or not text.strip():
        raise EngineError(f"codex 退出码 {r.returncode}：{r.stderr[-300:].strip()}")
    return text, {"input_tokens": None, "output_tokens": None, "cache_read_tokens": None}


def _cursor(engine: str, system: str, user: str) -> tuple[str, dict[str, Any]]:
    # 书稿文本不可信（可能含注入指令）：只在新建的空临时目录里运行，只读 ask 模式 + 沙箱；
    # 非交互模式必须 --trust，信任的只是这个空目录。输出按不可信文本处理（只当译文/评分解析）。
    cmd = ["cursor-agent", "-p", "--model", CURSOR_ENGINES[engine], "--output-format", "text",
           "--mode", "ask", "--sandbox", "enabled", "--trust"]
    with tempfile.TemporaryDirectory(prefix="cursor_") as td:
        r = _cli(cmd, system + "\n\n---\n\n" + user, engine, cwd=td)
    if r.returncode != 0 or not r.stdout.strip() or "Error:" in r.stdout[:200]:
        raise EngineError(f"{engine} 退出码 {r.returncode}：{(r.stderr or r.stdout)[-300:].strip()}")
    return r.stdout, {"input_tokens": None, "output_tokens": None, "cache_read_tokens": None}


def usage_path(usage_file: str | os.PathLike[str] | None = None) -> pathlib.Path:
    p = usage_file or os.environ.get("LLM_USAGE_TSV") or "~/.cache/yzz-translate/usage.tsv"
    return pathlib.Path(p).expanduser()


def log_usage(engine: str, usage: dict[str, Any], tag: str = "",
              usage_file: str | os.PathLike[str] | None = None) -> None:
    path = usage_path(usage_file)
    path.parent.mkdir(parents=True, exist_ok=True)

    def cell(v: Any) -> str:
        return "-" if v is None else str(v)

    row = [time.strftime("%Y-%m-%d %H:%M:%S"), engine, tag.replace("\t", " "),
           cell(usage.get("input_tokens")), cell(usage.get("output_tokens")),
           cell(usage.get("cache_read_tokens")), f"{usage.get('seconds', 0):.1f}"]
    line = "\t".join(row) + "\n"
    with _USAGE_LOCK:  # 并行 revise/check 同写一个 usage.tsv
        new = not path.exists() or path.stat().st_size == 0
        with open(path, "a", encoding="utf8") as f:
            if new:
                f.write(USAGE_HEADER)
            f.write(line)


def call(engine: str, system: str, user: str, *, max_tokens: int | None = None,
         profile: str = "default", tag: str = "",
         usage_file: str | os.PathLike[str] | None = None, offpeak: bool = True) -> tuple[str, dict[str, Any]]:
    """调用 engine，返回 (正文, usage)。usage 含 input_tokens/output_tokens/cache_read_tokens（命令行引擎为 None）、
    seconds、engine、max_tokens、profile。失败抛 EngineError / BudgetExceeded。

    max_tokens 缺省时按 profile + user 篇幅由 token_economy.out_budget 决定（default=8192）。
    需要旧行为显式传 max_tokens=64000 或 profile=\"long\"。"""
    if engine not in ENGINES:
        raise EngineError(f"未知 engine {engine!r}，可选：{', '.join(ENGINES)}")
    check_budget()
    if max_tokens is None:
        max_tokens = out_budget(profile, user)
    max_tokens = min(int(max_tokens), MAX_TOKENS)
    t0 = time.time()
    if engine in DEEPSEEK_ENGINES and os.environ.get("YZZ_DISABLE_DEEPSEEK"):
        raise EngineError("DeepSeek 已被 YZZ_DISABLE_DEEPSEEK 禁用")
    if engine in DEEPSEEK_ENGINES:
        if offpeak and not os.environ.get("LLM_SKIP_OFFPEAK"):
            wait_s = seconds_to_offpeak()
            if wait_s > MAX_OFFPEAK_WAIT:
                raise EngineError(
                    "DeepSeek 高峰时段（工作日北京时间 09:00–12:00、14:00–18:00）不调用；任务延期到下一个折扣时段")
            wait_offpeak()
        t0 = time.time()
        guard_window = offpeak and not os.environ.get("LLM_SKIP_OFFPEAK")
        text, usage = _deepseek(engine, system, user, max_tokens, check_window=guard_window)
    elif engine in CODEX_ENGINES:
        text, usage = _codex(system, user, CODEX_ENGINES[engine])
    elif engine in CURSOR_ENGINES:
        text, usage = _cursor(engine, system, user)
    else:
        text, usage = _claude(engine, system, user)
    usage = {**usage, "engine": engine, "seconds": time.time() - t0,
             "max_tokens": max_tokens, "profile": profile}
    log_usage(engine, usage, tag, usage_file)
    try:
        record_usage(usage)
    except BudgetExceeded:
        raise
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
