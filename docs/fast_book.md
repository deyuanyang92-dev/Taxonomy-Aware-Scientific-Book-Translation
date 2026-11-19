# 快书调度：400 页 ≈ 30 分钟

用户目标（2026-11-17）：一本约 400 页的分类学书，半小时内译完，且质量可接受、token 可负担。

## 墙钟怎么够

| 阶段 | 不做并行 | Lean + `-j 8`（估） |
|---|---|---|
| Google 初稿 | ~5–8 分钟 | ~5 分钟（已 8 路 prefetch） |
| 改写 | 全文改写数小时 + 烧 token | 只改写 ~12% 叙述/讨论；块并行 → ~数分钟 |
| 意义核对 | 全文再送一遍 | `--risky-only` ~20% 页；块并行 → ~数分钟 |
| 合计 | 不可接受 | **estimate 显示 ≤30 分钟**（已有机读原文、术语表、可跳过闲时窗） |

```bash
python3 scripts/fast_book.py estimate --pages 400 --lean -j 8
```

## 质量不砍什么

- 术语表 HARD / 本地规范化（0 token）
- 护栏：数字、学名、检索表、页标记
- 异模型或同模型二审（`--allow-same-verify` 仅在预算政策允许时）
- critical 仍进人工队列

砍的是：描述段的「模型整段改写」（用 Google+术语表，试点相似度已够）。

## 并行接缝

1. **块**：`auto_translate --workers N`，revise/check 各块写 `revise/cNNN.json` / `check/cNNN.json`，主线程按序合并。
2. **章**：`fast_book.py chapters`，每章 `WORK/chapters/<名>/`，进程池并行（无共享写）。
3. **usage.tsv**：`llm_engines` 写锁，避免并行交错坏行。

## 前提与风险

- 原文已文本化并切成带 `<!-- PDF p.N -->` 的 md；OCR 不计入 30 分钟。
- 默认 `LLM_SKIP_OFFPEAK=1`（`--respect-offpeak` 可关）。白天折扣外会按原价计费。
- DeepSeek 限流时墙钟变长；降 `-j` 或错峰。
- 多章并行时术语一致性靠**共享术语表文件**（只读），不靠运行时互相学习。

## 命令

见 `scripts/fast_book.py --help` 与 `skill/TOKEN_ECONOMY.md`。
