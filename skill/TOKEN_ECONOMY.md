# 省 Token 技能（DeepSeek / 其他模型共用）

用户 2026-11-17：调度若全文改写 + 多轮重试，token 近似指数上升，不可承受。
**所有模型调用必须先读本文件，再发请求。** 实现见 `scripts/token_economy.py`、`llm_engines.py`。

## 1. 铁律（按优先级）

| 优先级 | 做法 | 何时用 |
|---|---|---|
| 0 | **能脚本就不调模型**（术语规范化、异名录/文献/索引、斜体、种名格式） | 永远 |
| 1 | **Lean 分流**：只改写 `narrative,remarks`；描述/产地/生态用 Google+术语表 | 分类描述文献 |
| 2 | **核对只送风险段**（`--risky-only`） | check 阶段 |
| 3 | **只输出 JSON / 段 ID**，禁止重写整章、禁止解释过程 | check / review / polish |
| 4 | **关思考**（默认；勿设 `YZZ_DEEPSEEK_THINKING=1`） | DeepSeek |
| 5 | **稳定 system + 前缀缓存**（`cache_control`）；术语过大则逐段相关条目 | 全部 DeepSeek |
| 6 | **按任务限 max_tokens**（json=4k，default=8k，revise 按篇幅估） | `llm_engines.call(profile=…)` |
| 7 | **设预算闸** `YZZ_TOKEN_BUDGET=N`，超限停机 | 整书 / 批量 |

## 2. 推荐命令

分类文献（德/保等 → 英，或同类电报体描述）：

```bash
# 快书：Lean + 块并行（冲 400 页≈30 分钟；先 estimate）
python3 scripts/fast_book.py estimate --pages 400 --lean -j 8
python3 scripts/fast_book.py run SRC.md -o WORK --sl de --tl en --glossary G.tsv --lean -j 8
python3 scripts/fast_book.py chapters CH_DIR -o WORK --lean -j 4 --chapter-jobs 4

# 改写 + 核对，Lean（强烈推荐）
python3 scripts/auto_translate.py run SRC.md -o WORK --sl de --tl en \
  --glossary G.tsv --names N.tsv --lean --workers 8 \
  --verify-engine deepseek-flash --allow-same-verify

# 只核对已有译文
python3 scripts/auto_translate.py check SRC.md TGT.md -o WORK --sl de --tl en \
  --glossary G.tsv --lean --workers 8
```

`--lean` 等价于：`--rewrite-kinds narrative,remarks` + `--risky-only`，并把术语表改成逐段相关条目（不整本塞 system）。

英→中直调核译（问题单，本就 JSON）：

```bash
# profile=json 已由 direct_mode 自动传入；另设预算
export YZZ_TOKEN_BUDGET=500000   # 约五十万 billable token 后停
python3 scripts/run_batches.py <书> --mode review --engine deepseek-flash --chapters ch05
```

## 3. 为什么会「指数」涨

实测（Hartmann 17 份 + 1996 单本 usage.tsv）：

1. **全文改写**：描述段占约 66%，本可用 0 token；送模型后输出 ≈ 输入，费用随页数线性，再加重试就陡升。
2. **重试约 25%**：格式/护栏失败再调一次，直接 ×1.25。
3. **多阶段叠乘**：revise × check × verify；check 若不做 risky-only，整页原文+译文再付一遍输入。
4. **开思考**：输出 4–17 倍，且常无正文。
5. **默认 max_tokens=64000**（旧）：不截断时不直接计费，但思考/啰嗦模型会往上填。

Lean 试点（1971，见 `docs/research/2026-11-15/taxo_token_economy.md`）：只改写叙述/讨论 ≈ 12% 字符，描述段与全文模型稿相似度已与两模型互比相当。

## 4. 调用方检查清单

发请求前自问：

- [ ] 这段能否用术语表/规则 0 token 解决？
- [ ] 是否带了 `profile=`（json / revise / translate）？
- [ ] DeepSeek 是否关思考？是否闲时窗口？
- [ ] system 是否稳定（便于缓存）？术语是否只送本段相关？
- [ ] 输出是否要求「只 JSON / 只段 ID」、禁止解说？
- [ ] 是否设置了 `YZZ_TOKEN_BUDGET`？

## 5. 与其它文件的关系

- 流程总览：`SKILL.md` §8、`docs/research/2026-11-15/taxo_token_economy.md`
- 块类型：`transqa/taxoblocks.py`（`narrative` / `remarks` / `description` …）
- 统一入口：`scripts/llm_engines.call(..., profile=...)`
- 用量账本：各书 `usage.tsv` 与 `~/.cache/yzz-translate/usage.tsv`
