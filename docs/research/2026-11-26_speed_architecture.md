# booklayout 速度与架构调研（2026-11-26，Opus）

范围：原生 PDF 抽取 → 版面/图 → 构建 docx/PDF → 闸口（qa/check/stylecheck/source-check/gate）→ html。Google 翻译除外。
输入：Handbook Vol.1 原书（484 页，原生文本层）；`ingest-native` 全卷重抽后把 text 复制进 translation 模拟译本（只读，未改仓库代码；全部输出在 scratchpad）。
机器：16 核 / 62 GB，WSL2，输出写本地 /tmp（不是 /mnt/p）。注意：WSL 时钟有跳变（个别计时出现负值），数字误差约 ±3 s。

## 1. 实测（全卷 484 源页 → 673 输出页，7182 块，222 图）

| 阶段 | 墙钟 | 说明 / 证据 |
|---|---|---|
| ingest-native 全卷 | 17 s | PyMuPDF，已够快（ingest_native.py:362） |
| figures extract 全卷 | 30 s | 222 图 300 dpi 裁图，串行（pdffigures.py:127,156） |
| make: build1 | 115 s | docx 生成 ≈65 s + LibreOffice 转 PDF 49 s（单独测 49.0 s） |
| make: map-pages | 4.5 s | |
| make: build2 | 123 s | **整本重建 + 再转一次 LibreOffice**，只为填页码（make.py:172） |
| make: key-report | 3.3 s | |
| make: 闸口并行 | 18.5 s | qa 18.5 / check 5.0 / stylecheck <1 |
| make 合计（无 source-check、无 html） | **265 s** | make.json 实测 |
| source-check 40 页 冷 OCR，jobs=4 | 91 s | Tesseract 逐页（sourcecheck.py:122-133） |
| source-check 40 页 热缓存 | 38 s | 其中 output_tokens 28 s（见下） |
| source-check 20 页 热缓存 | 36 s | 固定开销 ≈34 s，与页数几乎无关 |
| html（需 --profile） | 8.3 s | |
| trace.db | 5.1 s | make.py:251 |

外推全卷（未测部分标“外推”）：source-check 冷 OCR ≈ 53 s/40 页 × 4 线程 → 476 页 ≈ **630 s**（外推）；加 output_tokens 28 s、比对约 5 s。
端到端（不含 Google）：ingest 17 + figures 30 + make 265 + source-check ≈ 660 + html 8 + trace 5 ≈ **985 s ≈ 16 min**（外推）。不跑 source-check 也要 ≈ 325 s，**超 5 分钟**。
小样 8 页 make 20 s：每次 build 6 s，主要是 Python 导入 + LibreOffice 启动的固定成本，乘以 2 遍。

## 2. 超过预算的环节与根因（cProfile）

build 单遍 cProfile 119 s（含分析开销），热点：
1. **整本构建两遍 + LibreOffice 两遍**（make.py:164,172；cli.py:244-267）。第二遍只为把 page_map 的页码写进目录/交叉引用，却重做全部 docx 生成和 PDF 转换。buildcache（buildcache.py）因 page_map 改变 docx 键而必然不命中。≈120 s 纯重复。
2. **属名正则每块重建**：builder.py:368-374 每次 add_runs 都 sorted+re.escape 全部属名再 compile。re.escape 调用 1555 万次，19 s；属名数随书增长 → 总成本 ≈ 块数 × 属名数，**超线性**。
3. **python-docx 图片去重二次方**：每插 1 张图对已有全部图片重算 sha1（docx/parts/image.py:77，16290 次 = 181²/2），10.5 s，随图数平方增长。调用点 builder.py:1392,1860。
4. **每段扫描全部样式名**：builder.py:804,810 `"Body" not in [s.name for s in doc.styles]` 每段执行，91 万次 style.name，10 s。
5. python-docx 逐 run 设 bold/italic（_set_bool_prop 18.9 万次，first_child_found_in 13.6 s）：按对象模型插元素，O(子元素) 查找。

闸口：
6. **source-check 对原生 PDF 仍做 Tesseract OCR**（sourcecheck.py:122-133，300 dpi pdftoppm + tesseract 每页一进程）。原生 PDF 有精确文本层，OCR 是多余且引入噪声的工作；全卷冷跑 ≈ 10 min。
7. **source-check 读输出 PDF 每页一个 pdftotext 进程**（sourcecheck.py:211-225，673 次 subprocess = 28 s），且无论 --pages 多小都读整本输出 → 20 页检查也要 34 s。
8. **qa 对同一 PDF 反复抽文本**：7405 次 page.get_text（673 页 ≈ 11 遍），22 s / 31 s；各检查各自 fitz.open（cli.py:649,735,1084,1164；folio.py:70；taxonlist.py:128,160；iczn.py:17；frontmatter.py:36；runstyle.py:23）。
9. 每阶段一个子进程（make.py:20 `_bl`）：每次重新导入（0.75 s）+ 重新解析 8 MB aligned JSON；10 余次，约 10–15 s。

正确性问题（顺带发现，会阻断无人值守）：
- make.py:190 `--translated` 时写死 `--lang spa --dict-lang es`：英文原书被当西班牙语 OCR/查词。
- make.py:217 `--html` 未给 `--profile` 时把空列表传给 `html`，而 html 要求 --profile → exit 2（实测报错 “the following arguments are required: --profile”）。sample.py 不传 profile。
- `figures extract` 有审计问题时 exit 1（全卷实测 ok=False），sample.py:61 只能靠“manifest 存在”放行。

## 3. 改法（按收益排序，估算为全卷）

| # | 改法 | 位置 | 省时（估） |
|---|---|---|---|
| A | 原生 PDF 的 source-check 不 OCR：直接用 PyMuPDF 取原书词（带坐标），只对扫描本走 Tesseract；判别用 ingest 时已知的 engine 字段 | sourcecheck.py:694-706,122 | 630 s → ≈5 s |
| B | output_tokens 改为一次 fitz.open 逐页 get_text，且只取 --pages 对应的输出页 | sourcecheck.py:211 | 28 s → ≈2 s |
| C | 去掉 build2 整本重建：build1 用占位页码（定宽），map-pages 后只改写 docx XML 中目录/交叉引用文本（或 Word/LO 字段更新）；页码定宽则版面不变，可直接在 PDF 层用 PyMuPDF 改写数字，免第二次 LibreOffice | make.py:170-172；builder.py fill_heading_contents/remap_refs | ≈120 s |
| D | builder 热点：属名正则按 frozenset 缓存一次；样式存在性缓存布尔；图片 sha1 建 dict（包装 package.get_or_add_image_part）；run 属性改直接写 rPr XML | builder.py:368-374,804,810,1392,1860,321 | docx 65 s → ≈20 s/遍 |
| E | qa/check 共享一次 PDF 抽取（每页 dict + words 只算一次，传给各检查） | cli.py:645,731,1053,1108,1351；folio/taxonlist/iczn/runstyle | qa 18.5 → ≈5 s |
| F | 阶段在同进程内调用，aligned 只解析一次；ingest 与 figures 并行（互不依赖）；figures 裁图用进程池 | make.py:20；sample.py:55-63 | 15–30 s |
| G（长期） | 直接排 PDF（Typst 或 PyMuPDF Story）代替 docx→LibreOffice；docx 作为可选导出 | cli.py:244 | 再省 ≈50–100 s（未测） |

改后估算（A–F，不含 G）：并行(ingest 17 ∥ figures 30)=30 + build 20+49 + map 5 + 页码回填 ≈5 + key-report 3 + 闸口并行 ≈10 + html 8 + trace 5 ≈ **≈135 s**，满足 5 分钟；做 G 后 ≈ 60–90 s（推测）。
建议同时加速度回归测试：全卷各阶段写入 make.json，任一阶段 >60 s 或总计 >300 s 在 make 里报 WARN，CI 用 50 页样本卡阈值（防再退化）。

## 4. 从“规划流程”到“无人值守跑通”缺什么

现在需人工介入的点（证据）：
1. 命令要人手串：sample/make 只覆盖“已对齐 JSON 之后”，全卷没有单命令（sample.py 只限页段，且固定 --glossary/无 profile）。
2. 失败只给报告不给动作：gate 失败后生成 review.html 等人裁定（make.py:222-228），accepted.json 由人维护；qa/check 的已知问题类（无图号图注、孤立分图字母、段落边界不确定 69 处、页眉混入正文）没有自动修复器挂接，尽管 cli 已有 repair/patch-blocks。
3. 退出码不分类：make 只有 0/1/2（make.py:169,269），无法区分“需人判断”“工具坏了”“配置错”。
4. 上节三处正确性 bug（spa 写死、html 缺 profile、figures exit 1）会让无人值守中途停。
5. source-check 慢（10 min）导致每次试跑都超时，被迫手工跳过 → 人工判断“这次跑不跑”。

`booklayout run` 设计：
- 输入一个 `book.toml`：source_pdf、pages、sl/tl、profile、metadata、glossary、figure 参数。缺省值自动探测（原生/扫描、语言、页眉）。
- 阶段 DAG（ingest ∥ figures → translate → normalize/repair → build → paginate → gates ∥ → html/trace），同进程执行；每阶段输入内容哈希做缓存，状态写 `<out>/run.status.json`（阶段、耗时、计数），供进度汇报。
- 自动修复回路：gate 问题按类映射到确定性修复器（repair、key-breaks、promote_captions、furniture 剔除、段落拼接、页眉块删除），修一轮重跑受影响闸口，最多 2 轮；修复写日志与 patch 文件，可回滚。不调用模型。
- 明确退出码：0 PASS；10 DRAFT（仅缺译文核定/release acceptance）；20 需人裁定（输出 review.html 与问题清单，列出每项为何不能自动修）；30 工具/环境失败（阶段名 + stderr 尾）；40 配置错误；50 超时预算（任一阶段超 budget）。
- 时间预算：每阶段 budget（默认全卷 60 s），超时报 WARN 并写入 status；总预算 300 s。

## 5. 未测 / 未确证
- G（直排 PDF）实际耗时；source-check jobs=16 冷跑；/mnt/p（9p 盘）上的 I/O 额外开销（仓库与工程都在 /mnt/p，可能更慢）；Vol41 67 s 样本未复测。
- C 方案中定宽占位页码能否保证版面不变，需小样验证（目录页码位数变化会改换行）。

## 6. Implemented 2026-11-26 (measured on whole Vol1, 484 pp, --no-translate)

Command: `python3 -m booklayout run <pdf> --out <dir> [--pages a-b] [--no-translate] [--no-source-check] [--no-html]`
Exit: 0 pass / 10 only untranslated blocks left / 20 needs human / 30 tool failure / 40 config error. Status: `<out>/run.status.json`.

| Fix | State | Evidence |
|---|---|---|
| A native-text source-check (per page, edge bands dropped, OCR only for pages without text layer) | done | source-check 714 s -> 23.6 s; items 479 -> 355 (OCR noise gone) |
| B single fitz open in output_tokens | done | sourcecheck.py |
| C second full rebuild | done for books whose build never reads the page map (builder counts reads, make.py skips map-pages+build2 when 0) | Vol1: build2 124 s -> 0 s. Books with contents/index still do build2 (untimed here). |
| D builder hotspots: genus regex cache, style-name scan cache, python-docx image sha1 cache | done | build1 129 s -> 97 s |
| E qa shared PDF extraction, F same-process stages, G direct PDF typesetting | not done | gates now 30.6 s, not worth it yet |

Whole Vol1 run (no Google): ingest 24 s + figures 36 s + translate-copy 8 s + make 131 s (build 97, gates 31, html 9) = **175 s**, every stage < 5 min. Google translation not included.
Tests: tests/test_booklayout_run.py, tests/test_booklayout_unattended.py. Full suite: 5 failures, same 5 as before the work (keys_layout, chapter_split, structdoc, usage_monitor x2).

Open: output-PDF text "loss" (350 blocks) from the earlier crude probe is noise for the one block checked (Bartolomaeus 1997 present on output p.232); not proven for the rest. Remaining 355 source-check items need review.
