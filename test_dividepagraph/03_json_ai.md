# 03. 中心化 JSON 内容库与 AI 对话式局部更新设计

## 1. 为什么必须引入中心化 JSON 内容库？

当前在和 AI 对话调整译文或排版细节（例如：“把第 128 页的 *Namalycastis* 改成斜体”、“把图 4 移到本节末尾”、“把某句译文润色得更贴合动物志风格”）时，存在三大痛点：
1. **改动成本失衡**：改一个词却要重跑全书正则清洗（`booklayout/normalize.py`）、全书排版构建（`builder.py` / `build_docx.py`）和整本 PDF 导出。
2. **补丁容易丢失**：如果直接用脚本去改最终产物（如修改 DOCX XML），下一次重新编译整本书时人工/AI 调整会被覆盖；或者需要在源码与成品之间维护复杂的双向同步。
3. **AI 误伤上下文**：直接让 AI 编辑几万字的整章 Markdown，容易出现漏行、拉丁学名斜体丢失、编号错位等回归问题。

**解决方案**：确立 **Canonical Book JSON Store（中心化块级 JSON 内容库）** 为全仓库的**唯一真相源（Single Source of Truth, SSOT）**。所有翻译产出、人工校对、术语替换和 AI 对话微调，全部以**原子 JSON Patch** 的形式精准作用于单个 `block_id`，随后仅触发受影响章节的增量渲染。

---

## 2. Canonical Book IR 数据模型

每本书按逻辑单元拆分为独立的 JSON 文件，存储在 `work/<book_id>/book_ir/` 中：

```text
work/<book_id>/book_ir/
├── book_meta.json         # 书名、作者、全局样式配置（profile）、术语表版本
├── toc_tree.json          # 由 chapter_manifest.json 同步而来的逻辑单元顺序树
├── assets_index.json      # 图片、表格、参考文献的全局索引与文件哈希
├── units/                 # 按逻辑单元拆分的 JSON（增量更新的最小编译粒度）
│   ├── ch01.json
│   ├── ch03_key01.json
│   └── ch03_sp001.json
├── patches/               # AI/人工对话产生的所有增量补丁日志（可追溯、可回滚）
│   ├── 20261121_1510_p001.json
│   └── 20261121_1514_p002.json
└── build_state.json       # 每个 unit 的内容哈希、脏标记（dirty）与产物缓存索引
```

### 单个 Unit JSON 示例（`units/ch03_sp001.json`）

每个块都拥有**全局稳定且不可变的 `block_id`**，以及独立的语义结构与局部样式覆盖字段：

```json
{
  "unit_id": "ch03_sp001",
  "node_type": "taxon_entry",
  "title_src": "Namalycastis abiuma (Grube, 1872)",
  "title_zh": "阿比乌玛微须沙蚕",
  "unit_hash": "a8f31c9e...",
  "blocks": [
    {
      "block_id": "ch03_sp001:b001",
      "kind": "taxon_heading",
      "source_ref": { "pages": [54], "ocr_blocks": [[54, 0]] },
      "src": "Namalycastis abiuma (Grube, 1872)",
      "zh": "阿比乌玛微须沙蚕 *Namalycastis abiuma* (Grube, 1872)",
      "style_override": { "space_before_pt": 12, "keep_with_next": true },
      "locked": false,
      "content_hash": "31d0ab..."
    },
    {
      "block_id": "ch03_sp001:b002",
      "kind": "synonymy",
      "source_ref": { "pages": [54], "ocr_blocks": [[54, 1], [54, 2]] },
      "src": "Lycastis abiuma Grube, 1872: 47.",
      "zh": "Lycastis abiuma Grube, 1872: 47.",
      "style_override": { "hanging_indent_pt": 18, "font_size_pt": 9.5 },
      "locked": true,
      "content_hash": "9c21fe..."
    },
    {
      "block_id": "ch03_sp001:b005",
      "kind": "figure_ref",
      "asset_id": "fig_014",
      "caption_zh": "图 14 阿比乌玛微须沙蚕（A. 体前端背面观；B. 中体节疣足）",
      "placement": "here_or_top",
      "style_override": { "width_ratio": 0.85 },
      "content_hash": "77ea02..."
    }
  ]
}
```

关键设计点：
- **行内格式结构化或轻量化约束**：学名斜体、加粗等在 `zh` 字段中使用受控行内标记（如 `*Namalycastis abiuma*`）或显式 `spans` 数组，避免在排版阶段再做脆弱的全文正则猜斜体。
- **`locked: true` 保护锁**：对于已通过人工定稿、同物异名录或参考文献块，加锁后防止批量润色或全局术语替换脚本误改。
- **`style_override` 局部微调槽位**：AI 对话调整字号、段距、图宽、换页符（`page_break_before: true`）或图版浮动位置时，直接写入该块的 `style_override`，不污染全局模板。

---

## 3. AI 对话式局部更新协议（Patch Protocol）

当你和 AI 对话提出修改指令时，AI **不需要读取或重写整章全文**，只需经过“定位 → 生成微补丁 → 局部校验 → 标脏”四步闭环：

### 3.1 轻量索引定位（毫秒级检索）
提供一个本地查询 CLI（例如 `bookir query --text "Namalycastis" --page 54` 或 `--fig fig_014`），快速返回命中的 1–3 个 `block_id` 及其前后各 1 个邻居块给 AI，极度节省上下文 Token。

### 3.2 原子 Patch 格式（`patches/20261121_1510_p001.json`）

```json
{
  "patch_id": "20261121_1510_p001",
  "reason": "按用户对话指令修正种名斜体并缩小图 14 宽度至 75%",
  "author": "ai_dialogue",
  "operations": [
    {
      "op": "update_field",
      "unit_id": "ch03_sp001",
      "block_id": "ch03_sp001:b001",
      "field": "zh",
      "old_hash": "31d0ab...",
      "value": "阿比乌玛微须沙蚕 *Namalycastis abiuma* (Grube, 1872)"
    },
    {
      "op": "merge_style_override",
      "unit_id": "ch03_sp001",
      "block_id": "ch03_sp001:b005",
      "value": { "width_ratio": 0.75, "placement": "section_end" }
    }
  ]
}
```

支持的标准原子操作类型：
- `update_field`：修改单块文本（`zh` / `caption_zh` / `title_zh`），附带 `old_hash` 乐观锁防止误覆写。
- `merge_style_override`：修改局部排版属性（缩进、段距、图宽、强制分页、字号微调）。
- `reorder_block` / `move_figure`：在单元内移动图注或段落顺序。
- `split_block` / `merge_blocks`：拆分或合并段落。
- `update_key_couplet`：专门修改检索表某一条耦联项（`docstore/keys.py` / `booklayout/keymodel.py` 结构），保证编号与跳转指向完整。

### 3.3 单块级瞬时守卫（Fast Guard）与状态更新
执行 `apply_patch` 时，无需跑全书检查，仅对被修改的块触发毫秒级单块守卫：
1. 调用 `scripts/italic_check.py` 与 `transqa/zh_typo.py` 的单块校验函数，确认未破坏拉丁学名斜体和标点规范。
2. 联动 `yiku/` 术语库校验，若用户本次修改明确更改了某个物种或形态学术语译法，可选自动沉淀回 `yiku/` 并提示是否同步扫描其他单元。
3. 重新计算该块与所属 `unit_id` 的 `unit_hash`，在 `build_state.json` 中**仅将 `ch03_sp001` 标记为 `dirty: true`**。
4. 自动记录反向操作快照，支持一键 `patch revert <patch_id>` 回滚。

---

## 4. 与现有仓库脚本的桥接方案

为避免破坏现有工作流，将仓库里已有的补丁/审校脚本统一收口到 JSON 内容库之上：
- `scripts/apply_issues.py` 与 `scripts/apply_review_queue.py`：改为生成标准 Patch 文件并调用统一 `apply_patch` 入口，不再直接文本替换散落的 Markdown。
- `scripts/publish/patch_release.py`：定位从“直接热修最终发布文件”升级为“优先同步写入 `book_ir/patches/`，再触发受影响单元的增量重编译”，彻底杜绝“热修过的地方下次重新出书又还原”的问题。