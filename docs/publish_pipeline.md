# 多语言译本出版流水线（issue #13、#7、#11、#38）

一条受支持的命令把「导出 → 翻译 → 抽图 → 对齐 → 检索表核对 → 排版 → 三审 → 闸口」串起来，每步的命令行、退出码、耗时、版本和输入 sha256 写进 `WORK/publish_run.json`。

```bash
python3 scripts/publish_book.py run --key Vol48 --pdf book.pdf --work work/vol48 --sl es --tl en --pages 1-5 --dry   # 先看命令
python3 scripts/publish_book.py run --key Vol48 --pdf book.pdf --work work/vol48 --sl es --tl en                      # 全跑
python3 scripts/publish_book.py run --source-md src.md --translation-md tgt.md --pdf book.pdf --work work/x          # 已有译文：跳过导出/翻译
```

| 阶段 | 命令 | 产物 |
|---|---|---|
| export | `docstore export KEY --translate --strict` | `src.md`（`<!-- PDF p.N -->` 页标记） |
| translate | `scripts/auto_translate.py run`（语言对 `--sl/--tl`） | `tgt.md` |
| figures | `booklayout figures extract` | `figures/figures_manifest.json`、`source_figure_audit.json`、`source_figure_crops/` |
| align | `booklayout align-md` | `aligned.json`、`align_report.json`（页内段数不齐的页显式列出，不猜配对） |
| keycheck | `booklayout key-model` | `key_model.json`（来源端图检查 + 译文逐支对齐 + 翻译单元） |
| build | `booklayout build`；有 PDF 时 `map-pages` 后 `build --map` 两遍 | `book.docx`、`book.pdf` |
| qa | `booklayout qa` / `check` / `key-report` | `qa.json`、`check.json`、`key_report.json` |
| gate | `booklayout gate` | `gate.json`；不过则退出码 1，`publish_run.json` 里 `releasable=false` |

`--no-pdf`（无 LibreOffice）只出 DOCX，闸口不运行，结果标为草稿。`--only`/`--skip` 选阶段。翻译阶段调用模型（费用、DeepSeek 忙时等待），先 `--dry`，再 `--pages` 小样。

## 新模块

- `booklayout/pdffigures.py`（#7）：按 PDF 里图像的**显示矩形**从整页渲染裁图（保留黑底等页面合成），清单含页、bbox、xref、像素、sha256、标签、图注文字与 bbox；同图出现在 ≥3 页判为页面装饰（徽标）；审计：未配对图/图注、重复标签、缺失/多余标签（`--expected-labels`）、低分辨率、图注邻接（复用 `figures.audit_placement`）。`booklayout figures map` 把图按图号配到译文图注块，找不到或有歧义的列入 `unresolved`。`--vector` 可选，聚类矢量图。
- `booklayout/keymodel.py`（#11、#38）：检索表结构化模型（编号、备择、正文、终点、页、跨页），来源端图检查，译文逐支对齐（缺/重/终点改/顺序），译文单元（终点逐字回填），`render_key` 用 `builder.tabbed` 排成名称栏 + 点线 + 右对齐终点，成对不分页。`booklayout key-model` 为 CLI。
- `docstore/keyblocks.py`（#38）：`docstore keys blocks|plan`；偶句翻译单元、译文回收校验（缺/多/重、终点、数字、学名、名称表）、缺陷 → `keys_fix.json` 骨架（`why` 留空，人对照页面图像填后才被 `extract --fix` 接受）。
- `scripts/keys_report.py`：多卷前后对比报告（自洽数、缺陷数、残留页与条目）。`--imajima` 用本机 PP-OCR 缓存的三卷。
- `booklayout/alignmd.py`：页标记 Markdown 原文 + 译文 → aligned JSON（确定性角色规则）。

## 已知限制

- 真实 Vol.48 的 PDF 与译文不在本机，未做真实书验证；合成 fixture 覆盖结构，视觉验收（PDF 渲染看检索表与图位）仍需人工。
- `align-md` 的角色规则是通用基线；参考文献、条目、索引等需 `booklayout normalize` / `patch-blocks` 继续精修。
- `parse_key_text` 要求一支一行；单行扁平页要先拆行。
