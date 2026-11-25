# 01. OCR 预检与物理分块调度设计

## 1. 设计目标与核心原则

本模块解决的核心矛盾是：**既希望在后续环节按“章节/条目”清晰整理 JSON，又希望 OCR 阶段并行高效、显存可控、支持只跑部分章节以节省算力**。

核心架构红线：
1. **物理调度与逻辑切分彻底解耦**：OCR 阶段永远按“物理页”为最小落盘与缓存单元，绝不直接按 PDF 书签或目录硬切源 PDF。
2. **书签/目录只做前置范围过滤与后置边界先验**：有书签时可用来勾选“只识别哪几章”，但实际下发给 OCR 的物理页队列会自动扩展缓冲页（Buffer），避免因页码偏移或半页起章导致文本截断。
3. **单页结果永久复用**：页级 OCR 结果在本地按页持久化缓存；后续扩大识别范围或调整切分规则时，命中缓存的页直接跳过 OCR，零重复计算。

---

## 2. 阶段划分与仓库模块映射

| 阶段 | 职责 | 归属现有模块 | 核心产出 |
|---|---|---|---|
| **Stage 0：预检与范围规划** | 检测文档类型（是否有书签、是否有印刷目录、总页数、空白/纯图版页），根据用户需求生成待识别页码集合与前后 Buffer | 扩展 `docstore/cli.py`（建议新增轻量 `docstore/plan.py`），复用 `booklayout/contents.py` 的目录解析逻辑 | `ocr_plan.json` |
| **Stage 1：统一物理 OCR 池** | 固定批次（如 16–32 页）并发调度多引擎 OCR、版面分析、块分类、置信度质检与拉丁文纠错，单页原子落盘 | 完全归口 `docstore/`：`store.py`、`engines/ppocr_worker.py`、`rapidocr.py`、`tesseract.py`、`layout.py`、`classify.py`、`qc.py`、`consensus.py`、`latinfix.py` | `pages/pXXXX.json`（或存入 `docstore/store.py`） |

---

## 3. Stage 0：多场景预检与 Buffer 策略

用户在启动 OCR 前，支持 4 种任务范围模式：

1. **全本模式（Full）**：默认将全部非空白物理页入队。可先执行低分辨率快速版面检测，标记纯空白页或纯图版页。
2. **书签选章模式（Bookmark Slice）**：
   - 使用 `PyMuPDF` 读取 `doc.get_toc()`。
   - 用户勾选目标章节（如第 3 章，书签显示为 50–82 页）。
   - 系统自动在区间两端各扩展 2 页 Buffer，实际生成 `[48..84]` 的物理页队列，彻底消除书签偏移 1–2 页或半页起章的风险。
3. **目录抽样选章模式（TOC Slice）**：
   - 针对无书签但有印刷目录的扫描书，先仅对前 15–25 页执行轻量 OCR 读取目录表，并每隔 50 页抽样识别 1 页页脚页码，估算印刷页码与 PDF 物理页码的偏移量。
   - 用户选定目标章节后，按估算区间前后各扩展 5 页 Buffer 入队。
4. **手动页段试跑模式（Range）**：用户直接指定起止物理页（如 `45-80`），用于快速调试新书版式或验证翻译效果。

### `ocr_plan.json` 数据契约

```json
{
  "book_id": "imajima_2003",
  "pdf_sha256": "e3b0c442...",
  "total_pages": 412,
  "detected_profile": "scanned_with_bookmarks",
  "selection_mode": "bookmark_slice",
  "buffer_pages": 2,
  "target_pages": [48, 49, 50, 51, 52],
  "prior_anchors": [
    {
      "source": "pdf_bookmark",
      "level": 1,
      "title": "Family Nereididae",
      "approx_page": 50
    }
  ]
}
```

---

## 4. Stage 1：物理页 OCR 调度与元数据标准

### 4.1 调度原则（与翻译批处理严格隔离）
- **`docstore/` 只管 Page Batch**：按固定页数打包分发给 worker（如 `ppocr_worker.py`），负载均衡不受章节长短影响；某页触发 `docstore/qc.py` 低置信度告警或共识校验（`consensus.py`）时，仅针对单页重跑。
- **天然断点续传**：调度器启动前比对 `ocr_plan.json` 与 `docstore/store.py` 已有页记录，已通过质检的页自动跳过。

### 4.2 页级中间结果必含元数据
为了支撑 Stage 2（逻辑切分）实现极低 Token 甚至 0 Token 精准分章，OCR 阶段**绝不能只输出纯文本**，每页必须保留块级结构特征：

```json
{
  "page": 50,
  "width": 1654,
  "height": 2339,
  "page_type": "body",
  "printed_page_num": "36",
  "qc_status": "pass",
  "blocks": [
    {
      "block_idx": 0,
      "bbox": [180, 95, 1470, 140],
      "font_size_est": 10.2,
      "layout_type": "header",
      "text": "IMAJIMA: POLYCHAETA FROM JAPAN",
      "confidence": 0.98
    },
    {
      "block_idx": 1,
      "bbox": [320, 210, 1330, 275],
      "font_size_est": 18.5,
      "layout_type": "title",
      "text": "Family NEREIDIDAE Johnston, 1865",
      "confidence": 0.99
    }
  ]
}
```

关键字段说明：
- `layout_type`：至少区分 `title`、`text`、`header`、`footer`、`figure`、`caption`、`table`、`key`（联动 `docstore/layout.py`、`classify.py`、`keyblocks.py`）。
- `font_size_est` 与 `bbox`：用于计算全书正文字号中位数、识别居中大字标题、判断缩进层级（对分类检索表尤其关键）。
- `printed_page_num`：从页眉/页脚抽取的印刷页码，用于 Stage 2 校准目录页偏移。

---

## 5. 工作区目录契约（Stage 0–1）

```text
work/<book_id>/
├── manifest.json          # 书籍全局元数据、PDF 哈希、引擎配置
├── ocr_plan.json          # Stage 0 产出：物理页任务队列与先验锚点
└── ocr_pages/             # Stage 1 产出：单页物理缓存（永不因拆章而切碎）
    ├── p0001.json
    └── ...
```