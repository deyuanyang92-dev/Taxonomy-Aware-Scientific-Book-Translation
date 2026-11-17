# 计划：400 页半小时 + 省 token + 并行（2026-11-17）

> **总览（后续优化计划正文）：** [`2026-11-17-token-speed-optimization.md`](2026-11-17-token-speed-optimization.md)  
> 本文件保留 PR 级勾选与测量细节；执行以总览硬约束为准。

**目标（用户）：** 翻译一本约 400 页书能在约 30 分钟内跑完机器流水线，同时尽量保质量；内置省 token 方法；多章节可并行；软件更模块化。

**硬约束（用户 2026-11-17 追加，不可破）：**
1. **Google 初译 + 其他模型校正**时，必须走**最低 token**路径；禁止默认全文交给大模型改写/重译。
2. 校正默认顺序：脚本/术语表/规则（0 token）→ 只送风险段或叙述段给模型 → 模型只回 JSON 最小改动（不重写整段）。
3. 提供并文档化 **`--engine none` / 零模型档**：只用 Google + 本地库，完全不调大模型。
4. 任何「Google + 模型」入口若未开 lean/最低 token，CLI 应警告或拒绝（PR-A/C 实现）。
5. **用一次模型，必须能回流一次经验**（见下节「经验闭环」）：模型找出的可规律化错误要进术语异写 / `google_fixes` / 块规则 / 护栏，而不是只改这一本书。不追求「写够 N 个脚本 = 大模型」，追求「每本书后 0-token 覆盖率上升」。
6. **三遍质控最多 1 次大模型**（用户 2026-11-17）：质控①③必须是脚本；质控②至多一次 LLM（lean 改写 **或** risky 核对，禁止再开 verify/第二模型轮）。废除默认「revise+check+verify」三连模型。
7. **极致省 token 且保质量**：不当用法必须改；报告审计「本可 0-token 却送了模型」；护栏/critical 零容忍不因省 token 放松。
8. **`--engine auto` 选最省合适模型**；Opus 等贵模型仅 `--force-engine`；会话用 Opus ≠ 流水线用 Opus。
9. **思考默认关**；DeepSeek 已测开思考不提质只烧 token；其他引擎无小样增益证据不得默认开思考。
10. **分类术语重复红利**：异写表+块分流+回流；重复术语禁止再送模型；送模型字符目标 ≤≈20%。
11. **本地资料库优先**：docstore/名称库/ANNiKEY/yiku/已有译稿；调研见 `docs/research/2026-11-17/local_taxonomic_libraries_for_token_economy.md`。
12. **跨书积累强制功能**：同语言对+领域共享异写库；书末 mine_corrections→审后入库；下一本默认自动加载；禁止每本从头只带本书 glossary。
13. **军师 vs 主力**：Opus 只做框架/规则/难例（军师）；Sonnet/flash 做唯一 LLM 质控轮；学缓存（稳定前缀、cache_control、CLI lean）；见总计划硬约束 13。

**本文件是交付物。** 按 pstack multi-phase-plan：不在此文件获「go」前改业务代码。

原则落地（本会话已读叶技能）：
- **Explain the Number**：基线来自本机 `usage.tsv`，不是估代码。
- **Sequence Verifiable Units**：每个 PR 独立可测，先基线后治疗。
- **Build the Lever**：交付可重跑的 CLI/探针，不靠手工调参。
- **Subtract Before You Add**：先少送模型、再并行、最后才加编排层。
- **Foundational Thinking**：并行单元 = 章/块工作目录隔离，禁止共写同一文件。

---

## 基线（已测，2026-11-17）

材料：`/mnt/p/翻译-译作/Hartmann-Schröder G/_work/translate/*/usage.tsv`（17 份）。

| 观察 | 数 | 含义 |
|---|---|---|
| 1996 一书 wall | **421 min**，1438 次调用，4.77 M token | 当前「全文改写」路线远超 30 min |
| 同批中等书 | 约 30–60 min / 约 0.3–1.0 M token | 仍偏贵 |
| revise 占比 | 1996：635 revise / 396 check / 407 verify | **墙钟与输出 token 主因是 revise** |
| auto revise | `stage_revise` **按块串行** | check 已有 `--workers`，revise 没有 |
| run_batches 直调 | 章与章 **for 循环串行**；章内 `-j` 并行 | 多章并行未做 |
| 分类块组成（1971 试点 `src_de.md`） | description 52%，narrative+remarks **16%** | lean 只改写叙述/讨论可砍约 5/6 模型改写量 |
| 试点质量（已有研究 `taxo_token_economy.md`） | Google+术语表 vs 模型改写相似度 ≈ 两模型互比 | 描述段可 0 token 规范化 |

### 400 页 timing 模型（推断；探针要在 PR-C 实跑校准）

假设 DeepSeek flash 关思考、已在折扣窗口内（不含 wait_offpeak）、块大小 3 页 → ≈133 块：

| 路线 | revise | check | 合计粗估 |
|---|---|---|---|
| 现状：全文改写 + 串行 revise | ≈27 min | ≈4 min @j=4 | **≫30 min**（再加 verify） |
| 并行 revise j=8 + 全文 | ≈3 min | ≈4 min | 仍可能超（输出贵、重试） |
| **lean（16% 改写）+ 并行 + risky-only check** | ≈0.5 min | ≈1 min | **约 10–15 min**（含 Google 初稿与 verify） |

**硬限制（不修则 30 min 无解）：**
1. DeepSeek 默认只在北京时间 00:30–08:30；窗外 `wait_offpeak` 会直接让墙钟爆炸（或 defer）。
2. 「可发表定稿」≠「机器流水线完成」：critical 项进 `human_review_queue.csv`，人审不进 30 min 预算。
3. 高并发会撞 API 限流；需背压与可恢复重试，不能盲加 `-j`。

---

## 零模型 / 最低 token 校正路线（建议默认）

实测依据：`docs/research/2026-11-15/taxo_token_economy.md`（1971 试点）。

| 档 | 做法 | Token | 质量（分类描述为主的书） |
|---|---|---|---|
| **0 · 零模型（推荐先跑）** | Google → `transqa.terms.normalize` 术语异写 → `skill/google_fixes.tsv` → 异名录/文献/索引确定性处理 → `taxoformat` 斜体 → 护栏脚本 | **0** | 与模型改写稿相似度已接近两模型互比；错几乎都是术语，补进异写表即可积累 |
| **1 · 最低 token（硬约束默认）** | 档 0 + 只改写 `narrative,remarks` + `check --risky-only`（JSON 最小改动）+ 可选窄任务 `judge` | 约为全文改写的 **10–20%** | 叙述段靠模型，描述段靠库 |
| **2 · 全文模型（禁止默认）** | 每段送模型改写/重译 | 贵且慢 | 仅 `--full` 显式打开 |

**不用大模型时怎么保证越来越准（建议）：**
1. 每本书跑完后 `mine_corrections`（或等价）从终稿挖替换 → 审后写入术语异写。
2. 固定错译进 `skill/google_fixes.tsv`。
3. 风险句用脚本标（数字/否定/学名/长度比/术语缺失），人工只看风险页，不调模型。
4. 攒够句对后再考虑本地 OPUS-MT 微调（仍 0 API token）。

### 经验闭环（用模型时同步优化脚本）

```
Google 初稿
  → 0-token 规则/术语
  →（仅缺口）大模型 JSON 小改
  → mine_corrections / 护栏误报分析
  → 写入：术语异写 | google_fixes | taxoblocks 标签 | 风险信号
  → 下一本 0-token 比例更高、送模型更少
```

**要写多少脚本才能等效大模型？**

| 层次 | 脚本能否替代 | 说明 |
|---|---|---|
| 术语、词形、Google 固有错 | **能，且应替代** | 杠杆在这里；异写表越厚，送模型越少 |
| 异名录/文献/索引/斜体/数字护栏 | **能** | 已有确定性脚本，不应再交模型 |
| 电报体物种描述 | **大部分能** | 试点：Google+库 ≈ 模型改写 |
| 叙述、讨论、论证语气 | **不能靠堆脚本等效** | 需要理解；长期也只需对「风险句」调用模型 |
| 「写 N 个脚本 = 一个大模型」 | **伪命题** | 不是数量问题，是**闭环**：每类重复错误变成一条规则；目标是分类书 80–90% 页 0-token，剩下 10–20% 才用模型 |

PR-A/C 应带上回流钩子：`report.md` 列出「本跑次可入库的候选异写/规则」；无候选则不算完整 fast path。

## 产品抉择（需操作者拍板，审查门控）

| ID | 问题 | 建议默认 |
|---|---|---|
| Q1 | 30 min 目标是「机器流水线出可抽检稿」还是「可直接交付出版」？ | **可抽检稿**；出版另计人审 |
| Q2 | 分类学书是否默认 `--lean`（只改写 narrative,remarks）？ | **是**（已升为硬约束）；非分类叙述书用 `--full` |
| Q3 | 白天是否允许 `LLM_SKIP_OFFPEAK=1` 换全价换速度？ | **否**默认；`--fast-day` 显式打开并计价 |
| Q4 | 默认档是 0（零模型）还是 1（最低 token 模型）？ | **先 0 出稿 + 护栏；质量不够再开 1** |

---

## 变更总览与依赖图

```
trunk
  ├─ PR-A  省 token 调用层（独立）
  ├─ PR-B  并行 revise + 多章并行（独立；与 A 可并行开发）
  └─ PR-C  一书编排器 fast path（依赖 A+B）
        └─ PR-D  模块收敛 / 删重复（依赖 C 实跑通过）
              └─ PR-E  质量抽检预算与报告闸（依赖 C；交互变更 → 审查门控）
```

落地顺序：A → B → C →（操作者确认 Q1–Q3）→ D → E。  
A 与 B 可从 trunk 分叉并行合入。

---

## PR-A · 省 token 调用层（独立）

- [ ] 依赖：无（trunk）
- [ ] 可碰文件：
  - `scripts/llm_engines.py`
  - `scripts/token_economy.py`（新建）
  - `scripts/auto_translate.py`（`--lean` / profile / max_tokens）
  - `tests/test_llm_engines.py`、`tests/test_token_economy.py`、相关 auto 测试
  - `skill/TOKEN_ECONOMY.md`、`skill/SKILL.md`（短链）
- [ ] 一处变更：所有模型调用经统一省 token 配置（关思考默认、任务档 max_tokens、DeepSeek `cache_control`、预算硬顶、`--lean` 默认；`--engine none|auto`；选模梯队；Opus 需 `--force-engine`；Google+模型路径未 lean 则警告/拒绝；**默认关闭第二模型 verify**，质控至多 1 次 LLM）
- [ ] 可见结果：默认路径不送描述段给模型；`--engine none` 时 usage.tsv 无新 LLM 行；`--lean` 试点 `sent_to_model` ≤ 叙述+讨论；json/check 档 max_tokens ≤ 4096；默认 `run`/`check` 的 usage 里**不会出现两个不同 LLM 引擎**（无 verify 轮）；`auto` 不选 opus；thinking 默认关闭可测
- [ ] 验证
  - [ ] unit：`pytest -q tests/test_llm_engines.py tests/test_token_economy.py tests/test_auto_translate.py`
  - [ ] live：对 `pilot1971` 跑 `auto_translate.py run ... --lean --stop-after revise`，看 `revise_stats` 的 `sent_to_model` / `google_kept`
  - [ ] perf：指标 = `sent_to_model` 段数与 `usage.tsv` 输出 token 合计；trunk 基线 = 同书无 `--lean` 的 revise 输出 token；失败线 = lean 输出 token 未降到全文的 30% 以下（分类试点）

---

## PR-B · 并行：块级 revise + 章级并行（独立）

- [ ] 依赖：无（建议合入后与 A 再叠 C）
- [ ] 可碰文件：
  - `scripts/auto_translate.py`（`stage_revise` ThreadPool；每块只写 `revise/cNNN.json`）
  - `scripts/run_batches.py` / `scripts/direct_mode.py`（多章并行；每章已有独立 `核译/direct/<章>/`）
  - 对应测试
- [ ] 一处变更：独立块/章可并发，共享状态只读（术语表、system）；写路径按块/章隔离
- [ ] 可见结果：`--workers 8` 时 revise 墙钟显著低于串行；多章 `-j` 同时写不同章目录且无交叉损坏
- [ ] 验证
  - [ ] unit：并发顺序合并、缓存命中、失败块不拖死他块
  - [ ] live：同一 8 页样例串行 vs `-j 4` 各跑一遍，产物文本一致（允许 JSON 字段顺序差）
  - [ ] perf：指标 = revise 墙钟秒；基线 = 串行同输入；失败线 = j=4 墙钟 > 串行的 50%（限流除外，需在日志标明 429）

---

## PR-C · 一书 fast path 编排器（依赖 A+B）

- [ ] 依赖：PR-A、PR-B 已合入
- [ ] 可碰文件：
  - `scripts/fast_book.py`（新建，薄编排；或扩展 `auto_translate.py`/`run_batches.py` 的 `run-book` 子命令——实现时选更小的那个）
  - `docs/workflow.md` 一小节
  - 探针脚本 `scripts/bench/book_timing_probe.py`（新建）
- [ ] 一处变更：一条命令跑「Google → lean revise → risky check → taxoformat → report」，并先打印 ETA/预算；支持按章列表并行
- [ ] 可见结果：对约 40 页样章，`--dry` 给出调用次数与 ETA；实跑墙钟有记录；400 页外推 ETA ≤ 30 min（在折扣窗口内、j≥4、lean 开）
- [ ] 验证
  - [ ] unit：dry 估算与 chunk 公式一致
  - [ ] live：40 页样章端到端出 `report.md` + `checked.md`
  - [ ] perf：指标 = 墙钟分钟与 M token；基线 = 同书旧 `auto_translate.py run` 无 lean/无并行 revise；失败线 = 样章未达到「旧路线墙钟的 1/3」或 token 未降到 1/2

---

## PR-D · 模块收敛（依赖 C）

- [ ] 依赖：PR-C live 通过
- [ ] 可碰文件：把 `gtrans.py` / `auto_translate.py` / `direct_mode.py` 里重复的 call+usage+prompt 拼装收到 `token_economy`/`llm_engines`；删掉死参数与重复 system 拼装
- [ ] 一处变更：调用面只剩一个入口 + 任务档；调用方不再手写 max_tokens=64000
- [ ] 可见结果：`rg "max_tokens=64000"` 仅剩 long profile；直接模式 system 可选用 compact 档
- [ ] 验证
  - [ ] unit：全量 `pytest -q tests yiku/tests`
  - [ ] live：PR-C 同一 40 页样章仍能跑通
  - [ ] perf：同 PR-C 探针，回归失败线 = 墙钟或 token 相对 PR-C 变差 >10%

---

## PR-E · 质量抽检预算（依赖 C；审查门控）

- [ ] 依赖：PR-C；**合并前需操作者过目**（改「什么叫够好」）
- [ ] 可碰文件：`scripts/audit_sample` 相关、`report.md` 模板、`skill/TOKEN_ECONOMY.md` 质量门槛
- [ ] 一处变更：fast path 强制抽 N 页盲评清单 + 确定性护栏全过，否则退出码非 0
- [ ] 可见结果：未过护栏不能宣称「30 min 完成」；critical 队列单独计数
- [ ] 验证
  - [ ] unit：护栏失败 → 非 0
  - [ ] live：故意抽坏一页，流水线失败
  - [ ] perf：抽检本身 ≤ 总墙钟 10%

---

## 明确不做（本轮）

- 不重写翻译引擎，不换新模型供应商框架。
- 不把人审 critical 塞进 30 min。
- 不默认白天跳过 DeepSeek 折扣（除非 Q3 显式开）。
- 不为并行引入共享可写全局缓存文件（先隔离，见 Separate Before Serializing）。

---

## 仍未证明

- 400 页实书在本机 API 限流下 j=8 是否仍稳定（只有样章外推）。
- lean 在「非分类、叙述为主」书上的质量（试点是多毛类德文）。
- ~~verify 强模型全文复核~~：已裁定为**默认关闭**（质控至多 1 次 LLM）；若显式开第二模型则必须走 `--full` 并计入超限。

---

## 操作者下一步

回复 **go**（可附带 Q1–Q3 选项）后，从 PR-A 开干。  
若只要「先省钱不求 30 min」，只批 **go A**。  
若只要并行，只批 **go B**。
