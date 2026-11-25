"""模型调用的省 token 规则：任务档位、输出上限、预算闸、Lean 默认。

依据（Hartmann 17 份 usage.tsv，2026-11-17）：
  - 全文改写占大头（1996 一本 revise 输出 170 万 token）；描述段用 Google+术语表即可
  - 重试约 25%；check 输入大、输出小 → 只送风险段
  - 开思考输出约 4–17 倍；默认关闭
  - DeepSeek 前缀缓存便宜（cache 价约 input 的 1/50），稳定 system 必须显式 cache_control

用法：
  from token_economy import out_budget, apply_lean, check_budget, record_usage
  max_tokens = out_budget("json")           # check / verify / judge
  max_tokens = out_budget("revise", user)   # 按待改写篇幅估
  apply_lean(argparse_namespace)            # --lean → rewrite_kinds + risky_only
"""
from __future__ import annotations

import os
import threading
from typing import Any

# 分类文献 Lean：叙述/讨论/图注送模型；描述/产地/生态走 Google + 术语表（0 token）
# caption 纳入：Marinov 实测图注 Google 可用率最低
LEAN_REWRITE_KINDS = "narrative,remarks,caption"
LEAN_STABLE_LIMIT = 20_000  # Lean 下术语表不整本塞 system，逐段只送相关条目

# 任务 → 输出 token 上限。None = 按 user 篇幅动态估，再封顶。
PROFILES: dict[str, int | None] = {
    "json": 4096,        # check / verify / judge / polish 问题单
    "revise": None,      # 改写：约等于待改写段长度
    "translate": None,   # 初译：约等于原文长度
    "default": 8192,     # 未声明任务时的安全默认（旧默认 64000 易被长思考/啰嗦填满）
    "long": 64000,       # 显式长输出逃逸阀
}

_ABS_CEILING = 64000
_lock = threading.Lock()
_spent = 0  # 本进程累计 billable ≈ input + output（缓存读另计，见 record_usage）


class BudgetExceeded(RuntimeError):
    """累计用量超过 YZZ_TOKEN_BUDGET 时抛出，避免指数级烧钱后才发现。"""


def estimate_tokens(text: str) -> int:
    """粗估：拉丁字母约 4 字符/token，CJK 约 1.5 字符/token。偏保守（略高）。"""
    if not text:
        return 0
    cjk = sum(1 for c in text if "\u4e00" <= c <= "\u9fff" or "\u3040" <= c <= "\u30ff")
    other = max(0, len(text) - cjk)
    return max(1, int(cjk / 1.5 + other / 4) + 1)


def out_budget(profile: str = "default", user: str = "", *, ceiling: int = _ABS_CEILING) -> int:
    """按任务档位给出 max_tokens。revise/translate 按 user 估，并加 30% 余量。"""
    if profile not in PROFILES:
        raise ValueError(f"未知 profile {profile!r}，可选：{', '.join(PROFILES)}")
    fixed = PROFILES[profile]
    if fixed is not None:
        return min(fixed, ceiling)
    est = estimate_tokens(user)
    return min(ceiling, max(2048, int(est * 1.3) + 512))


def system_blocks(system: str, *, cache: bool = True) -> str | list[dict[str, Any]]:
    """DeepSeek Anthropic 兼容端点：稳定 system 加 ephemeral 缓存标记，后续块几乎只付 cache 价。"""
    if not cache or not system:
        return system
    return [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]


def apply_lean(a: Any) -> Any:
    """给 argparse.Namespace 打开 Lean：块分流 + 风险段核对。已显式设置的字段不覆盖。"""
    if not getattr(a, "lean", False):
        return a
    if not getattr(a, "rewrite_kinds", ""):
        a.rewrite_kinds = LEAN_REWRITE_KINDS
    if not getattr(a, "risky_only", False):
        a.risky_only = True
    return a


_budget_override: int | None = None  # 进程内覆盖值（set_budget）；优先于环境变量


def set_budget(limit: int | None) -> None:
    """设置进程内预算上限（覆盖 YZZ_TOKEN_BUDGET）；None 清除覆盖，回到环境变量。"""
    global _budget_override
    _budget_override = limit


def budget_limit() -> int | None:
    if _budget_override is not None:
        return _budget_override
    raw = os.environ.get("YZZ_TOKEN_BUDGET", "").strip()
    if not raw:
        return None
    return int(raw)


def spent() -> int:
    with _lock:
        return _spent


def reset_spent(value: int = 0) -> None:
    global _spent
    with _lock:
        _spent = value


def billable(usage: dict[str, Any]) -> int:
    """计费近似：非缓存 input + output；cache_read 单独很便宜，按 1/50 折算进预算。"""
    def n(k: str) -> int:
        v = usage.get(k)
        try:
            return int(v or 0)
        except (TypeError, ValueError):
            return 0

    return n("input_tokens") + n("output_tokens") + n("cache_read_tokens") // 50


def record_usage(usage: dict[str, Any]) -> int:
    """累加本进程用量；若设了 YZZ_TOKEN_BUDGET 且超限则抛 BudgetExceeded。返回本次 billable。"""
    global _spent
    add = billable(usage)
    limit = budget_limit()
    with _lock:
        _spent += add
        total = _spent
    if limit is not None and total > limit:
        raise BudgetExceeded(
            f"token 预算已超：累计约 {total} > YZZ_TOKEN_BUDGET={limit}；"
            f"本次 +{add}（input={usage.get('input_tokens')} out={usage.get('output_tokens')} "
            f"cache={usage.get('cache_read_tokens')}）。停机，避免继续指数消耗。"
        )
    return add


def check_budget() -> None:
    """调用前预检：已超预算则直接拒绝发请求。"""
    limit = budget_limit()
    if limit is not None and spent() > limit:
        raise BudgetExceeded(f"token 预算已超：累计约 {spent()} > YZZ_TOKEN_BUDGET={limit}")


# 贵模型：批量翻译/校正禁止默认使用（军师/架构才允许 --force-engine）
EXPENSIVE_ENGINES = frozenset({"claude-opus", "deepseek-v4-pro", "codex-astra"})


def guard_engine(engine: str, *, force: bool = False) -> str:
    """拒绝默认贵模型；force=True 才放行。none/auto 原样返回。"""
    if engine in ("none", "auto", ""):
        return engine
    if engine in EXPENSIVE_ENGINES and not force:
        raise SystemExit(
            f"引擎 {engine} 属贵模型（军师档），批量翻译/校正默认禁用；"
            f"确需使用请加 --force-engine。主力请用 deepseek-flash / claude-sonnet / auto。"
        )
    return engine


def guard_tier(tier: str, *, verify_engine: str, chaptered: bool) -> str:
    """试译档放行；交付档必须异模型 verify + 分章。
    见 docs/plans/2026-11-17-translation-approach-optimization.md（仅 /root/github 份）。"""
    t = (tier or "draft").strip().lower()
    if t in ("draft", "试译", ""):
        return "draft"
    if t not in ("release", "交付", "publish"):
        raise SystemExit(f"未知 --tier {tier!r}，可选 draft / release")
    problems: list[str] = []
    if verify_engine in ("none", ""):
        problems.append("release 须设异模型 --verify-engine（不可为 none）")
    if not chaptered:
        problems.append("release 须按章（fast_book chapters，或加 --chaptered）")
    if problems:
        raise SystemExit("交付档（--tier release）未满足：\n- " + "\n- ".join(problems))
    return "release"


# ───────── 人民币预算闸：一本书（一个工作目录的 usage.tsv）默认最多 ¥2 ─────────
# 依据：2026-11-20 用户定「一本书最多 2 块」；Imajima 三卷×英/中实测每个语种版本 ¥2.5–6.2，
# 其中全文改写（revise）约占 69%，见 docs/research/2026-11-20-book-cost-cap.md。
DS_PRICE = {'in': 0.15, 'cache': 0.003, 'out': 0.6}   # deepseek-flash 闲时 USD/1M（官方定价页 2026-11-14）
PRICED_ENGINES = frozenset({'deepseek-flash'})        # 只有这个有人民币单价；其余引擎无法核算，预算开启时拒绝
DEFAULT_BUDGET_CNY = 2.0

_cny_lock = threading.Lock()
_reserved: dict[str, float] = {}


def usd_cny() -> float:
    return float(os.environ.get('YZZ_USD_CNY', '7.2'))


def budget_cny() -> float | None:
    """每本书的人民币上限。YZZ_BUDGET_CNY=数字 改上限；off 关闭（返回 None）。默认 ¥2。"""
    raw = os.environ.get('YZZ_BUDGET_CNY', '').strip().lower()
    if not raw:
        return DEFAULT_BUDGET_CNY
    if raw in ('off', 'none', 'unlimited'):
        return None
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f'YZZ_BUDGET_CNY={raw!r} 不是数字，也不是 off') from exc


def cost_cny(engine: str, input_tokens: Any, output_tokens: Any, cache_tokens: Any) -> float | None:
    """按官方价折算人民币；无单价的引擎返回 None。"""
    if engine not in PRICED_ENGINES:
        return None

    def n(v: Any) -> int:
        try:
            return int(v or 0)
        except (TypeError, ValueError):
            return 0

    usd = (n(input_tokens) * DS_PRICE['in'] + n(cache_tokens) * DS_PRICE['cache']
           + n(output_tokens) * DS_PRICE['out']) / 1e6
    return usd * usd_cny()


def spent_cny(usage_file: Any) -> float:
    """该书 usage.tsv 里已花的人民币（跨多次续跑累计）。文件不存在为 0。"""
    from pathlib import Path
    p = Path(str(usage_file))
    if not p.exists():
        return 0.0
    total = 0.0
    for line in p.read_text(encoding='utf-8').splitlines()[1:]:
        f = line.split('\t')
        if len(f) < 6:
            continue
        total += cost_cny(f[1], f[3], f[4], f[5]) or 0.0
    return total


def worst_case_cny(engine: str, system: str, user: str, max_tokens: int) -> float | None:
    """这一次请求的花费上界：输入全按未缓存价、输出打满 max_tokens。"""
    return cost_cny(engine, estimate_tokens(system) + estimate_tokens(user), max_tokens, 0)


def reserve_cny(usage_file: Any, amount: float, cap: float) -> None:
    """发请求前预留最坏花费；已花 + 在途预留 + 本次最坏 > cap 则拒绝。并行请求共用一个预留表。"""
    key = str(usage_file)
    with _cny_lock:
        used = spent_cny(key) + _reserved.get(key, 0.0)
        if used + amount > cap:
            raise BudgetExceeded(
                f'预算闸：这本书已花 ¥{used:.3f}，本次最坏还要 ¥{amount:.3f}，会超过上限 ¥{cap:g}'
                f'（YZZ_BUDGET_CNY）。不发请求。')
        _reserved[key] = _reserved.get(key, 0.0) + amount


def release_cny(usage_file: Any, amount: float) -> None:
    key = str(usage_file)
    with _cny_lock:
        _reserved[key] = max(0.0, _reserved.get(key, 0.0) - amount)
