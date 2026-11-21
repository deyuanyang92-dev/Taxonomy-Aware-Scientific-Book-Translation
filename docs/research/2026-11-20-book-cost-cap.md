# 一本书的费用上限与默认零模型（2026-11-20）

用户要求：翻译主体不用大模型（Google 初稿 + 已写好的脚本），模型最多用来核对检索表；一本书最多 ¥2。

## 证据（Imajima 三卷 × 英/中，`work/*/usage.tsv`，按 `token_economy.cost_cny` 折算）
| 卷/语种 | 正文花费 | 其中 revise 全文改写 |
|---|---|---|
| 2001 en / zh | ¥6.26 / ¥5.32 | 约 69%（输出 75 万 token/卷） |
| 2007 en / zh | ¥2.77 / ¥2.53 | 同量级占比 |
| 2009 en / zh | ¥6.18 / ¥5.24 | 同量级占比 |
| 检索表偶句（keys_tr，6 个目录） | ¥0.18–0.31 每目录，合计 ¥1.52 | — |

- 正文合计约 ¥28.3，与 README 的 ¥27.91 相符。
- `work/Imajima2001/en/revise_stats.json`：3428 段里 2459 段（72%）送了模型整段改写；另有 verify（第二模型复核）、check（找错）两遍。
- 根因：翻译路径没有默认费用上限。#42 只给 QA 加了 token 预算；`auto_translate.py` 默认 `--engine auto`，
  `night_batch.sh` 显式 `--engine deepseek-flash --verify-engine deepseek-flash`，一本书走了三遍全文模型。

## 改动
- `scripts/token_economy.py`：`cost_cny / spent_cny / worst_case_cny / reserve_cny / release_cny / budget_cny`。
  上限默认 ¥2（`YZZ_BUDGET_CNY=数字` 改，`off` 关）；汇率 `YZZ_USD_CNY`，默认 7.2。
- `scripts/llm_engines.py:call`：发请求前，已花（该书 usage.tsv，跨续跑累计）+ 在途预留 + 本次最坏情况（输入全按未缓存价、输出打满 max_tokens）超上限则拒绝。
  并行请求共用预留表，失败也释放预留。无人民币单价的引擎（claude/codex/deepseek-v4-pro）预算开启时拒绝。
- `scripts/auto_translate.py`：`--engine` 默认改为 `none`（零模型）。模型必须显式给出。
- 日本-imajima `scripts/night_batch.sh`：正文改为 `--engine none`；`keys_night.sh` 保持（只核检索表，实测 ¥0.18–0.31）。
- 测试：`tests/test_budget_cny.py`（11 项；去掉预算判断后 3 项变红）。

## 已知限制
- 上限按「一个工作目录的 usage.tsv」计：正文目录与 keys_tr 目录各自 ¥2；正文为零模型时，一本书一个语种 ≈ 检索表花费。
- 没有 usage_file 的调用只按默认全局 usage.tsv 记账，预留仍生效，但不跨进程累计。
- 最坏情况按输入未缓存价、输出打满估算，偏保守：余额接近上限时可能提前停，不会超。
