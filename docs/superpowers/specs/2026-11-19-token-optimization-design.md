# 省 token 优化：设计与取舍（2026-11-19）

## 起因

早期翻译消耗大量 token 和费用，Claude 与 DeepSeek 两边都贵。用户要求先优化软件，再继续翻译；之后的测试一律限额或用小样本。

## 费用从哪来（已测）

| 来源 | 证据 | 结论 |
|---|---|---|
| Claude Code 会话 | `token_habits.py`：Opus 约占 71%；18 个超长会话占 93%；最长一个 7869 次调用 | 最大头，靠使用规范解决，不靠改代码 |
| 流水线调用（usage.tsv） | Hartmann 17 份约 4.8M token；1996 一本 revise 输出 170 万 | 已有 Lean、预算闸、引擎闸（Cursor 2026-11-17 起） |

“每次重读上下文”大多是缓存读，不等于花费同量的钱。

## 本次改动（均为 0 token 的确定性改动，测试用假引擎）

1. **`transqa/taxoblocks.risk()` 去误报**。risk() 决定哪些段落送模型核对，误报越多送得越多。
   - 数字：改用 `transqa.core.numbers`，小数逗号等于小数点，千分位写法统一。原先 `1,5`/`1.5`、`1.200`/`1,200` 都报 `number`。
   - 长度：按语言对取区间。EN→ZH 用 0.15–0.90，ZH→EN 取其倒数，同文字体系仍用 0.6–1.6。原先 EN→ZH 几乎每页都报 `length`。源文和译文都短于 30 字符不按比例判，空译文仍报。
   - 学名：句首的方位形容词（Dorsal、Ventral 等）不当作属名。
   - 区间依据：Rouse 2022 ch05–09 整章字数比 0.44–0.50（含保留的拉丁名，偏高），纯叙述句估计 0.22–0.25。**页级分布未测，属未确证**；区间故意取宽，只挡整段缺失、重复、未翻译，细小漏译仍由 term/number/negation 抓。
2. **`scripts/llm_engines.py` 的 `claude -p`**：加 `--no-session-persistence`；单次预算默认 `--max-budget-usd 1`（`YZZ_CLAUDE_MAX_USD` 可改，`off` 关闭）；`YZZ_CLAUDE_EFFORT` 可选指定思考档位。此 CLI 的 `--help` 没有 `--max-turns`，因工具全关本来就只有一轮，所以没加。已用 1 次真实 sonnet 调用（584 入 / 4 出）确认参数被接受。

## 使用规范（最大头，改习惯而不是改代码）

- 一个任务一个会话；会话超过约 300 次调用或换主题就写进度、`/clear`。
- 长会话不用 Opus。Opus 只用于一次性的决策备忘或疑难裁定，用完即停。
- 全局 `effortLevel` 现为 `xhigh`，建议日常降为 `medium`，需要时再临时调高。**这是用户的全局设置，未改动，等用户决定。**
- 批量初译/核译走 `run_batches.py`，先 `--dry`，再试点 1 批；不用会话手工逐段翻译。

## 暂不做（先量后做）

Google 建议中下列几条数字来自沙箱模拟的 Google 服务，本机未实测，不盲收：gtrans 连接池/批量缓存、usage.tsv 多进程加锁、`add_runs` 瘦身、booklayout 局部页预览、taxonomy 三名法、OCR 共识、`TaxonTreatment` 结构。各自先在本机小样上量出收益，再决定。Cursor 的 pstack P0–P4 等用户说 go 再做。

## 目标与非目标

- 目标：减少无谓送模型的段落，给模型调用加硬上限，规范会话使用。
- 非目标：不改界面、不改译文、不动任何书稿与资料库数据；不跑真实全书翻译。

## 遗留

- 本机两份检出（`/mnt/p/...` 与 `/root/github/...`）仍分叉；本次改动只在 `/root/github` 份，`/mnt/p` 份的未提交 risk() 改动不同，尚未合并。
- `/mnt/p` 份有未跟踪的 `scripts/usage_monitor.py` 与 `tests/test_usage_monitor.py`（半成品），两个用例失败；非本次改动引起，未触碰。
