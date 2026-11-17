# 分类学书籍：如何译得更准、更高效

版本 2026-11-17（Cursor 汇总）。依据：`workflow.md`、`comparison.md`、`taxo_token_economy.md`、`budget_tiers.md`、省 token / 交付档定案。

**口诀：** 术语有出处 → Google+表扛描述 → 模型只啃叙述/风险 → 脚本守证据 → 异模型审意义 → 每书回流。

---

## 1. 「准」是什么（验收标准）

| 维度 | 合格标准 |
|---|---|
| 术语 | 每个定名有出处（书名+页码或名词委）；同书同义项不漂移 |
| 证据 | 学名、命名人年份、数字、否定、检索表跳转与原文一致；错只加注不径改 |
| 结构 | 段不丢、页标记齐、图注/检索表角色不错位 |
| 写法 | 描述用志书电报体（具/无+阿拉伯数字…），不为「通顺」加信息 |
| 审校 | 交付档：异模型双语审；critical 人审；排版三审脚本过闸 |

不追求散文「优雅」；叙述/总论才做名家式通读（`polish`）。

---

## 2. 更准：固定做法（按优先级）

1. **先术语后成句**  
   逐章 `yiku table` → 缺口按领域依据次序查证 → HARD 必用、SOFT 看义项。禁止模型临时造名当定名。

2. **块分流，勿全文当小说译**  
   | 块 | 主路径 | 为何 |
   |---|---|---|
   | 描述 / 产地 / 生态 / 异名 / 文献 | Google + 术语异写（0 token） | 电报体；错几乎都在术语 |
   | 叙述 / 讨论 / 图注 | Lean 送模型改写 | 完整句、易意义漂移 |
   | 检索表 | 结构脚本 + 必要时模型 | 编号/跳转比文采重要 |

3. **证据用脚本，不用语感**  
   `transqa`（数字、学名、残留、覆盖）→ `taxon_validate` → italic/taxoformat → critical 进 `human_review_queue`。

4. **交付才上异模型审**  
   试译可 `verify=none`；出版必须 `--tier release` + 异模型 `--verify-engine` + 分章。同模型自评不算审。

5. **样章闸**  
   1–2 章全流程，抽查错误率 >5% 不铺开全书。

6. **错误回流**  
   每类错写进陷阱表 / 异写 / 规则，并回答「下次哪一步自动拦住」。

---

## 3. 更高效：固定做法（省时间与 token）

1. **Google 初译永远先跑**（并发缓存）；不要一上来全书 LLM。  
2. **Lean 默认开**（`narrative,remarks,caption`）；描述不上模型。  
3. **跨书 memory**：异写审核后 `book_memory absorb`，下一本同语种更省。  
4. **按章并行**：`fast_book chapters`；章之间不抢同一文件。  
5. **闲时 DeepSeek、关思考、system 缓存**；贵模型（Opus 等）只设计规则，批量要 `--force-engine`。  
6. **两档分清**  
   - 试译：`--tier draft`（省）  
   - 交付：`--tier release` + `delivery_gate` + `booklayout qa`  

实测取向（德/保分类文献）：约 **80%+ 字符可不调模型**；送模型字符目标 **≤约 20%**。

---

## 4. 推荐命令（最短路径）

```bash
# 试译 / 量产草稿（真·0 LLM token：必须 --engine none）
# 注意：默认 --engine auto 仍会对叙述/图注调模型，会费 token！
python3 scripts/auto_translate.py run SRC.md -o WORK --sl de --tl en \
  --glossary G.tsv --engine none --tier draft --chaptered

python3 scripts/fast_book.py chapters CHDIR -o WORK --sl de --tl en \
  --glossary G.tsv --engine none --tier draft -j 4

# 交付（准）
python3 scripts/fast_book.py chapters CHDIR -o WORK --sl de --tl en \
  --glossary G.tsv --tier release --verify-engine codex-sol \
  --engine deepseek-flash -j 4
python3 scripts/delivery_gate.py WORK --tier release \
  --qa final/qa.json --check final/check.json --key-report final/key_report.json

# 跨书变省
python3 scripts/book_memory.py absorb WORK/memory_candidates.tsv --sl de --tl en
```

---

## 5. 常见错法（禁止）

- 全书默认 DeepSeek/Opus 改写两遍、三遍  
- 用模型自信度或 BLEU 代替出处与分类学核对  
- TM 模糊匹配直接当定稿  
- 为流畅改数字、学名、有/无  
- 把 `verify=none` 的草稿标成已交付  

---

## 6. 相关文件

- 工作流模块：`docs/workflow.md`  
- 与主流对比：`docs/comparison.md`  
- 省 token 实测：`docs/research/2026-11-15/taxo_token_economy.md`  
- 试译/交付：`skill/TOKEN_ECONOMY.md`、`docs/CURSOR_OPTIMIZATION_2026-11-17.md`  
