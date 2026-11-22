# StructDoc：识别后的统一结构化 JSON 层（设计）

日期 2026-11-22。状态：第一切片已实现（schema、构建、校验、CLI），其余为路线。

## 问题

结构化已经存在，但分散：`keys.json`（检索表偶句，`docstore/keys.py`）、`treatments.json`（`booklayout/treatments.py`）、
aligned.json（角色块，`booklayout/profile.py` 的 ROLES）、页面 JSON 的 `extra.names`。各自格式不同、各自校验、各自到排版阶段才汇合，
所以同一类问题（检索表）在每本书的排版阶段重复修。

## 原则（不推翻旧设计）

1. 页面 JSON（docstore pages）仍是主库。StructDoc 是**派生视图**，可由主库和各抽取器完全重建，与 docstore.sqlite 同级处理，不得反向当主库改。
2. aligned.json 保持不变并继续被 booklayout 读取。StructDoc 沿用其 role 词表（它是超集），不另造一套。
3. 依赖方向只向下：structdoc 在 docstore 内，不 import booklayout/translate。
4. 结构只用确定性规则抽取，零模型。校验不过标 `uncertain`，不静默放行。
5. 每个块带出处（来源抽取器、原页、原记录 id），可追溯到页面图像。

## 数据契约 structdoc/1

```json
{"schema": "structdoc/1", "doc": "<资料 key>",
 "blocks": [{"id": "K1-p341-3'", "type": "key_couplet", "page": 341, "order": 17,
             "text": "...", "data": {"key": 1, "lead": "3'", "kind": "...", "terminals": ["..."]},
             "src": {"origin": "keys", "ref": "K1-p341-3'"},
             "status": "ok", "issues": []}],
 "problems": [{"scope": "key:1", "code": "missing_alternate", "detail": "3"}],
 "summary": {"blocks": 0, "by_type": {}, "uncertain": 0}}
```

- type：aligned 的全部 role，加 `key_couplet`、`key_heading`、`treatment`、`figure`。
- order：全书阅读顺序，单调不减；同页内按抽取器给出的版面顺序。
- status：`ok` / `uncertain`（校验有问题）/ `fixed`（经 keys_fix 人工依据修正）。

## 校验（structdoc.validate）

块 id 唯一；type 合法；page 为正整数；order 单调；key_couplet 必带 key、lead；
检索表图检查复用 `docstore.keys.check_couplets`（每个 N 有 N'、每条有终点、跳转号指向存在条目），问题同时写到所属块的 issues。

## 下游消费（路线）

| 下游 | 现状 | 改后 |
|---|---|---|
| 翻译 | `keyblocks.couplet_blocks` 直接读 keys.json | 读 StructDoc 的 key_couplet 块，终点不交模型（逻辑不变） |
| 排版 | aligned.json | `structdoc → aligned` 适配器（切片 2），booklayout 不改 |
| QA | transqa 各自解析文本 | 按块类型取结构，逐块比对 |
| 术语/物种 | 另读文本 | treatment 块直接给 latin/ref/description（切片 3） |

## 切片

1. 【已做】schema + from_keys + from_aligned + validate + `docstore struct build|check` + 测试。
2. structdoc → aligned 适配器；用 Imajima/Vol48 现成数据做往返等价测试（块数、文本、角色不变）。
3. treatments、图/图注绑定并入；译文回收后按块校验。
4. 在 OCR 流水线末端自动生成，并写入 `docs/ocr_eval/LEDGER.tsv` 式的结构准确率账本（检索表偶句查全/查准，对人工金标）。

## 未确证

- 真实书上 keys.json 抽取的偶句准确率：仓库内没有可复现的金标集，切片 4 之前不对外宣称。
- aligned 的 `couplet`/`key` 旧块与 keys.json 偶句如何一一对应，需切片 2 用真实数据核。
