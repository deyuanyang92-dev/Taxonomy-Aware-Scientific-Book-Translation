# booklayout：对齐译文到成书（DOCX/PDF）

`booklayout` 把翻译流水线产出的对齐 JSON 排成书：扉页、摘要、作者、目录、正文、图与图注、检索表、文献、附录、索引。它是确定性脚本，模型只负责提供对齐数据和元数据，不手工拼接 DOCX。

## 安装

```bash
pip install -e .
booklayout --help
```

依赖：`python-docx`（DOCX）、`pymupdf`（页映射和检查）、LibreOffice（只在 `--pdf` 时调用）。

## 输入

### 1. 对齐 JSON（`--aligned`）

```json
{
  "pages": [
    {
      "page": 14,
      "chapter": "Introduction",
      "kind": "chapter",
      "blocks": [
        {"role": "heading", "level": 1, "translation": "Introduction", "y0": 80},
        {"role": "body", "translation": "Translated paragraph.", "y0": 120}
      ]
    }
  ]
}
```

- `page`：源 PDF 页码（1 起）。
- `chapter`：章节键；同一键的连续页归为一章。
- `kind`：`chapter`、`appendix`、`index` 等；附录条目用 `appendix`。
- `blocks[].role`：`heading`、`body`、`caption`、`key`、`ref`、`entry`、`citation`、`index`。
- `blocks[].translation`：英文译文；`text` 仅用于提取拉丁名，不排版。
- `y0`：块在源页上的纵坐标，用于判断图注是否位于图上方。

### 2. 图目录（`--figures`）

目录内必须有 `source_figure_audit.json`，其 `figures` 每项至少含：

```json
{"source_pdf_page": 17, "source_label": "1", "crop": "source_figure_crops/fig_source_p017_01.png"}
```

`crop` 相对图目录。缺少裁剪图会在 `check` 中报出。

### 3. 译文 Markdown（`--translation`，可选）

只在 `metadata.abstract_page` 存在时读取，用 `<!-- PDF p.N -->` 分页标记取摘要原文。正文排版不读这个文件。

### 4. 书籍元数据（`--metadata`，可选）

JSON 字段（全部可省略）：

| 字段 | 用途 |
|---|---|
| `title`, `volume`, `subtitle`, `edition`, `publisher`, `notes` | 扉页 |
| `running_left`, `running_right` | 页眉左右文字 |
| `contents_title`, `index_title` | 目录、索引标题 |
| `abstract_page`, `abstract_cut` | 摘要所在源页；`abstract_cut` 用于截断重复段 |
| `include_front_matter` | 是否排摘要、作者、贡献者页 |
| `authors`, `contributions` | `[[姓名, 单位/章节], ...]` |
| `authors_title`, `contributions_title`, `license_note` | 前置页标题与许可说明 |
| `chapter_titles` | `{章节键: 目录显示名}` |
| `body_start_page` | 正文起始源页 |
| `folio_offset` | 源书印刷页码 = 源 PDF 页 − `folio_offset` |
| `skip_after_page` | 该源页及以后不排正文（封底、系列页） |
| `index_chapter` | 索引章节键；正文阶段跳过，由索引渲染器统一输出 |
| `index_intro_prefix` | 索引引言起始文字 |
| `skip_headings` | 章节首页要丢弃的标题前缀（如重复标题） |
| `entry_prefixes` | 附录条目开头要删的正则列表 |

示例见 `tests/test_booklayout.py`；Vol. 48 的完整元数据在工程目录，不随仓库分发。

## 两遍排版（页码正确）

目录和索引里的页码来自第一遍 PDF，必须跑两遍：

```bash
# 第一遍：无页码映射
booklayout build \
  --aligned aligned.json --figures figures/ \
  --translation reviewed.md --metadata metadata.json \
  --out pass1/book.docx --pdf

# 建立源书印刷页 -> 成品 PDF 页的映射
booklayout map-pages \
  --pdf pass1/book.pdf --aligned aligned.json \
  --metadata metadata.json --out page_map.json

# 第二遍：写入目录和索引页码
booklayout build \
  --aligned aligned.json --figures figures/ \
  --translation reviewed.md --metadata metadata.json \
  --map page_map.json \
  --out final/book.docx --pdf --report final/build_report.json

# 结构检查；有未译块、缺图或 PDF 回退字体时退出码为 1
booklayout check \
  --aligned aligned.json --figures figures/ \
  --pdf final/book.pdf --out final/check.json
```

## 验收与低能力模型操作

低能力模型只执行命令，不改 `booklayout` 代码：

1. 先跑 `booklayout check`，把 `untranslated_blocks`、`missing_crops` 原样报告。
2. 只有 `ok: true` 才能宣布排版完成；`yzz.py zh check` 仍须另外运行。
3. 两遍排版后，`map-pages` 的 `entries` 应覆盖正文起止页；目录和索引页码用抽查页核对。
4. 失败时保留 `build_report.json`、`check.json` 和命令原文，不手工改 DOCX/PDF。

## 退出码

- `0`：成功，或 `check` 无问题。
- `1`：`check` 发现问题。
- 其他非零：参数、输入文件、LibreOffice 转换失败。
