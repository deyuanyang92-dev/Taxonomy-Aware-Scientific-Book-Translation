# 省 Token 技能（Cursor 优化档，2026-11-17）

**所有模型调用必须先读本文件。** 实现：`scripts/token_economy.py`、`llm_engines.py`、`book_memory.py`、`auto_translate.py`、`fast_book.py`。  
交付说明：`docs/CURSOR_OPTIMIZATION_2026-11-17.md`。

## 0. 两档（必读）

| 档 | 用途 | verify | 分章 | 可否称「交付」 |
|---|---|---|---|---|
| **试译/草稿**（CLI 默认 `--tier draft`） | 测流程、量产初稿、省钱 | `none`；质控脚本为主 | 建议 `fast_book chapters` | **否** |
| **交付/出版**（`--tier release`） | 正式出书 | **必须异模型**（≠ 译者） | **强制按章**（`--chaptered` 或 `chapters`） | 须过 `delivery_gate` + 排版闸 |

思路全文：`docs/plans/2026-11-17-translation-approach-optimization.md`。  
Lean 默认 kinds 含 `caption`。交付示例：

```bash
python3 scripts/fast_book.py chapters CHDIR -o WORK --tier release \
  --verify-engine codex-sol --engine deepseek-flash -j 4
python3 scripts/delivery_gate.py WORK --tier release \
  --qa final/qa.json --check final/check.json --key-report final/key_report.json
```

## 1. 铁律（试译档默认）

| 优先级 | 做法 |
|---|---|
| 0 | 能脚本就不调模型 |
| 1 | **Lean 默认开**：只改写 `narrative,remarks`；`--no-lean` 才全文改写 |
| 2 | **verify 默认 `none`**（仅试译档）：其余脚本护栏；**交付档禁止以此冒充已审** |
| 3 | 只输出 JSON / 段 ID |
| 4 | 关思考；DeepSeek `cache_control`；按 profile 限 max_tokens |
| 5 | **`--engine auto`** 选最省；Opus 等需 `--force-engine`（军师，不啃正文） |
| 6 | **跨书 memory** 默认加载；书末 `memory_candidates.tsv` → absorb |
| 7 | `YZZ_TOKEN_BUDGET` 超限停机 |

## 2. 推荐命令

```bash
# 估时
python3 scripts/fast_book.py estimate --pages 400 --lean -j 8

# 默认 Lean + 无第二模型 + 跨书 memory
python3 scripts/auto_translate.py run SRC.md -o WORK --sl de --tl en --glossary G.tsv -j 8

# 零模型（只 Google + 表）
python3 scripts/auto_translate.py run SRC.md -o WORK --sl de --tl en --glossary G.tsv --engine none

# 候选入库（下一本更省）
python3 scripts/book_memory.py absorb WORK/memory_candidates.tsv --sl de --tl en
```

## 3. 角色

| 角色 | 模型 | 用途 |
|---|---|---|
| 文书 | 脚本 / Google | 默认主体 |
| 主力 | deepseek-flash / sonnet | 唯一 LLM 质控轮（若需要） |
| 军师 | Opus | 只设计规则/脚本；批量禁用 |

## 4. 调用前检查

- [ ] 这段能否 0 token？
- [ ] lean 是否仍开？verify 是否仍为 none？
- [ ] 是否误用 Opus 而无 `--force-engine`？
- [ ] 是否加载了跨书 memory？
- [ ] 是否设了预算闸？
