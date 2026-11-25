# 04. 增量排版与极速 PDF 渲染架构设计

## 1. 当前排版与 PDF 产出慢的根因诊断

结合仓库现有结构（`booklayout/normalize.py`、`booklayout/builder.py`、`scripts/publish/build_docx.py`、`scripts/publish/word_render.py`、`scripts/publish/gen_index.py` 等），耗时主要集中在四个串行瓶颈：

1. **全量重跑无缓存**：修改 1 句话或 1 张图，仍需把整本书几百页重新走一遍 `normalize.py` 文本规范化、实体/学名标注（`annotate_names.py`）、索引生成（`gen_index.py`）和整本构建。
2. **Word / LibreOffice 全本渲染极重**：`word_render.py` 启动 Word 或 LibreOffice 对包含数百张高清插图、复杂检索表和大量中英混排斜体的整本 DOCX 进行分页与导出 PDF，单次动辄数分钟，且不支持增量编译。
3. **高分辨率图像反复打包与重采样**：每次生成预览都把几百 MB 的印刷级高 DPI 原图重新嵌入文档，拖慢 I/O 与渲染引擎内存占用。
4. **“交互式微调”与“终稿出版”耦合在同一条重管线上**：微调第 3 章版面时，被迫等待全书目录页码重算、拉丁名/中文名索引重排以及前后 20 个未改动章节的重新排版。

---

## 2. 双轨渲染架构：秒级交互预览 vs 终稿出版发布

将排版出 PDF 拆分为两条清晰轨道，均以 `book_ir/`（文档 03）为唯一输入源：

```text
                       book_ir/units/*.json + build_state.json
                                         │
                 ┌───────────────────────┴───────────────────────┐
                 ▼                                               ▼
   【轨道 A：交互预览模式 (Draft)】                【轨道 B：终稿发布模式 (Release)】
   目标：AI 对话改完 1–3 秒看到 PDF 效果            目标：印刷级精度、严格跨章页码与全书索引
   • 只编译 dirty=true 的 unit                      • 全量一致性校验 + 锁死全局页码
   • 使用低 DPI 缓存预览图（150 DPI）               • 切换 300–600 DPI 原图资产
   • 优先走 Typst 极速引擎 / 单章 PDF 缓存          • 完整生成目录、跨章引用、中拉文索引
   • PyMuPDF (<0.5s) 拼接全本预览 PDF               • 产出出版级 PDF + 可交付 DOCX
```

---

## 3. 四项核心提速机制

### 机制 1：基于内容哈希的单元级增量缓存（`build_state.json`）
将编译粒度从“整本书”缩小为“单个逻辑单元（`unit_id`）”：
- 每个单元的缓存键为：`cache_key = sha256(unit_hash + layout_profile_hash + asset_tier)`。
- 每次执行编译时，对比 `build_state.json`：
  - 未变动的 95% 单元直接命中缓存，**完全跳过 `normalize.py`、排版布局和 PDF 渲染**。
  - 仅对本次通过 JSON Patch 标脏的 1–2 个单元执行重编译。

### 机制 2：单元级 PDF 缓存 + `PyMuPDF` 极速合卷（< 0.5 秒）
每个逻辑单元在 `build/cache/pdf_units/` 下维护自己独立的渲染产物（如 `ch03_sp001_<hash>.pdf`）：
- **单章独立预览（最常用）**：和 AI 对话调整第 3 章时，只需渲染 `ch03.pdf` 并立即刷新预览器，耗时控制在 **0.2–2 秒**。
- **全本预览合卷**：当需要查看整本 PDF 时，用 `PyMuPDF`（`fitz`）按 `toc_tree.json` 顺序把所有已缓存的单元 PDF 直接拼接，并同步写入 PDF 书签树与连续页码水印（Overlay）。对 500 页书籍，纯拼接加页码仅需 **0.3–0.8 秒**。

### 机制 3：引入极速排版后端（强烈推荐 Typst 作为原生 PDF 引擎）
针对当前依赖 `build_docx.py` → `word_render.py` 导出 PDF 过慢的问题，建议实施分层策略：

| 方案 | 单章重编耗时 | 整本 500 页全量编译 | 优势 | 适用场景 |
|---|---|---|---|---|
| **方案 1（推荐）：JSON → Typst → PDF** | **50–300 毫秒** | **2–6 秒** | 原生增量编译、纯命令行无 GUI 依赖、中英混排与拉丁斜体极精准、天然支持分类检索表前导点（Leader）与悬挂缩进 | 交互式 AI 调排版、日常校对、现代出版级 PDF 主力输出 |
| **方案 2（兼容现有 DOCX 链）：JSON → 单章 DOCX → 局部 PDF 缓存** | 2–5 秒 | 首次较慢，后续增量 < 5 秒 | 复用现有 `build_docx.py` 样式代码，无需切换引擎 | 必须交付 Word 源文件给出版社编辑修改的场景 |

**最佳实践**：日常写作、翻译校对与 AI 对话微调全部走 **JSON → Typst → PDF**（毫秒级反馈）；仅在交付出版社需要 `.docx` 时，从同一份 `book_ir/` 一键调用 `build_docx.py` 导出最终 Word 文件。

### 机制 4：图像资产分级与重操作延迟（Defer Heavy Passes）
1. **双轨图片缓存**：在 `scripts/publish/extract_figs.py` 抽图阶段，同步生成一份轻量预览图（如 150 DPI WebP/JPEG，置于 `assets/preview/`）与原图（`assets/print/`）。Draft 模式永远引用 `preview/`，文件体积缩小 80%–90%，排版引擎加载速度大幅提升。
2. **前置规范化只做一次**：把 `booklayout/normalize.py`（84 KB）与学名/属名标注（`annotate_genera.py`、`annotate_names.py`）前移到“入库 `book_ir/` 时按单元执行并缓存”，而不是每次导出 PDF 重复跑全书扫描。
3. **全局索引与交叉引用延迟到 Release**：Draft 模式下跳过全书索引重算（`gen_index.py`）和全局图号重排，或者仅沿用上次快照；只有在执行 `publish --release` 时跑一次完整终稿锁定。

---

## 4. AI 对话触发极速更新的端到端流程

以下展示一次典型的“和 AI 对话调整排版”从指令到看到新 PDF 的完整耗时拆解：

```text
1. 用户指令："第 3 章阿比乌玛微须沙蚕那张图太宽了，缩到 75%，顺便把该段里 'parapodia' 改译为 '疣足'"
       │
       ▼ (~0.05s)  bookir query 精准召回 ch03_sp001:b003 与 ch03_sp001:b005
2. AI 输出 20 行原子 JSON Patch（不重写整章）
       │
       ▼ (~0.05s)  apply_patch 校验斜体/术语 -> 更新 units/ch03_sp001.json -> 标脏 ch03_sp001
3. 增量编译器检测到仅 1 个 unit 变脏
       │
       ▼ (~0.2s, Typst) 或 (~2.5s, 单章 DOCX->PDF) 重新渲染 ch03_sp001.pdf
4. 自动打开局部预览 / 0.4s 内用 PyMuPDF 刷新整本 preview.pdf
       │
       ▼ 总耗时：约 0.5–3 秒（原全本重排需 2–5 分钟）
```

---

## 5. 渐进式落地路线图（对齐现有仓库）

建议分 4 个里程碑平滑演进，每阶段均可独立验收，不中断当前出书流程：

| 阶段 | 改造重点 | 涉及模块 | 预期收益 |
|---|---|---|---|
| **Phase 1：建立 JSON IR 与脏缓存** | 定义 `book_ir/units/*.json` 与 `build_state.json`，把 `booklayout/normalize.py` 改为按单元增量缓存 | `booklayout/normalize.py`、`scripts/chapter_manifest.py` | 消除重复全书文本清洗，局部改动准备阶段降到毫秒级 |
| **Phase 2：单元级 PDF 缓存 + `PyMuPDF` 拼接** | 让现有 `build_docx.py` / `word_render.py` 支持 `--unit <id>` 单章渲染，并用 `PyMuPDF` 拼出整本预览 | `scripts/publish/build_docx.py`、`word_render.py`、`publish_book.py` | 无需换排版引擎，立即把单处修改出 PDF 从分钟级压到数秒级 |
| **Phase 3：接入 AI Patch 协议与资产分级** | 实现 `bookir query`、`apply_patch`（整合单块 `italic_check` / `transqa`）与 150 DPI 预览图缓存 | `scripts/apply_issues.py`、`scripts/publish/patch_release.py`、`extract_figs.py` | AI 对话直接精准改块、零误伤、可回滚、永不丢补丁 |
| **Phase 4：引入 Typst 极速 PDF 后端** | 新增 `booklayout/typst_render.py`，直接将 `book_ir/units/*.json` 映射为 Typst 模板（支持分类志缩进与检索表前导点） | `booklayout/` 新增轻量渲染后端 | 单章渲染进入百毫秒级，500 页全本终稿编译压到 5 秒内 |