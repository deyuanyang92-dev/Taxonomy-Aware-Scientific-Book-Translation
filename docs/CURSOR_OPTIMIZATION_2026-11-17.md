# Cursor 优化交付说明（2026-11-17）

**标记：** 本轮由 **Cursor** 按用户硬约束与 `docs/plans/2026-11-17-token-speed-optimization.md` 落地，供你本地测试效果。  
**跟踪 issue：** [#32](https://github.com/deyuanyang92-dev/Taxonomy-Aware-Scientific-Book-Translation/issues/32)（相关 #28/#26/#25/#4/#29/#31/#20/#30 已注释约束）。  
**思路比对（分章 / 三审三校 / 文风）：** `docs/plans/2026-11-17-translation-approach-optimization.md` —— CLI 默认 = **试译档**；正式交付须异模型审 + 分章 + 排版三审，勿把 lean/verify=none 当出版合格。

## 改了什么（相对旧默认）

| 项 | 旧 | 现（Cursor） |
|---|---|---|
| Lean 分流 | 可选 `--lean` | **默认开**（`--no-lean` 才全文改写） |
| 第二模型 verify | 默认 `codex-sol` | **默认 `none`**（质控至多 1 次 LLM） |
| max_tokens | 常 64000 | profile：json=4k / default=8k / revise 按篇幅 |
| DeepSeek 缓存 | 弱 | system **cache_control** |
| 思考 | 可误开 | **默认关** |
| Opus 等贵模型 | 可当批处理 | **需 `--force-engine`** |
| 跨书经验 | 每本从头 glossary | **自动加载** `~/.cache/yzz-translate/memory/{sl}-{tl}/…`；书末写出 `memory_candidates.tsv` |
| 快书 | 含 verify 估时 | `fast_book` 默认无 verify 轮 |

## 请你这样测（小样）

```bash
cd /root/github/Taxonomy-Aware-Scientific-Book-Translation

# 1) 估时（不花钱）
python3 scripts/fast_book.py estimate --pages 40 --lean -j 4

# 2) 零模型档（应无 DeepSeek 调用）
python3 scripts/auto_translate.py run SRC.md -o /tmp/yzz_t0 --sl de --tl en \
  --glossary G.tsv --engine none --stop-after revise

# 3) Lean 默认（可加 --engine none 先只看 Google+表）
python3 scripts/auto_translate.py run SRC.md -o /tmp/yzz_t1 --sl de --tl en \
  --glossary G.tsv --workers 4 --stop-after revise

# 4) 跨书：看合并表与候选
ls /tmp/yzz_t1/_merged_glossary.tsv /tmp/yzz_t1/memory_candidates.tsv
# 审核 candidates 的 approve=y 后：
python3 scripts/book_memory.py absorb /tmp/yzz_t1/memory_candidates.tsv --sl de --tl en

# 5) 预算闸（可选）
export YZZ_TOKEN_BUDGET=50000
```

看 `WORK/usage.tsv`：默认路径不应出现第二引擎；`--engine none` 应无 LLM 行。

## 相关文件

- `scripts/token_economy.py` / `llm_engines.py` / `book_memory.py` / `auto_translate.py` / `fast_book.py`
- `skill/TOKEN_ECONOMY.md`
- 计划：`docs/plans/2026-11-17-token-speed-optimization.md`

## 本机自测（Cursor，2026-11-17）

```
PYTHONPATH=scripts python3 -m pytest -q \
  tests/test_token_economy.py tests/test_book_memory.py \
  tests/test_llm_engines.py tests/test_fast_book.py tests/test_auto_translate.py
# → 72 passed

python3 scripts/fast_book.py estimate --pages 40 --lean -j 4
# → verify=off(默认)；Cursor 优化档；合计约 0.8 分钟
```

## 关联 GitHub issues（本轮注释/约束）

| Issue | 与省 token 关系 |
|---|---|
| #28 corpus driver | 新驱动须继承 lean / verify=none / memory |
| #26 quality gate | 交付闸用脚本基线，禁止再叠 LLM 轮 |
| #25 semantic QA | 至多 1 次 LLM；其余校准+脚本分拣 |
| #4 / #29 / #31 Google | 0-token 初译稳定性；与 LLM 省钱互补 |
| #20 / #30 斜体 | 继续走 taxoformat 脚本（0 token） |

## 未在本轮做完的（仍按计划）

- 名称库/ANNiKEY 自动拼进 glossary 的一键 CLI（可先手工 `--glossary`）
- 动物志 registered→text_done 批量入库（资料侧）
- PR-E 抽检闸数值基线（issue #26）
