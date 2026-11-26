# 一次结构化、反复低成本重排：顶层设计（2026-11-26）

只读设计，未改代码。上游调研：`docs/research/2026-11-26_structdoc_ocr_layout调研.md`（下称「调研」）；相关规格 `docs/probe_spec.md`（#59–#62）、`docs/ocr_multi_engine_plan.md`、`docs/ocr_tool_survey.md`。
标记：【确证】读码或本会话实跑；【未定】有矛盾或缺数据；【推测】推断未验证。依据一律 `文件:行`（仓库根 `Taxonomy-Aware-Scientific-Book-Translation/`）。

## 0. 目标与总体结构

用户目标：书只结构化一次，之后改译文、改样式都能低成本重排（像 Word 样式）。
设计要点：
1. **单一真源 = aligned.json（扩展为 aligned/2）**，不另起 JSON。StructDoc 维持「派生视图」定位（2026-11-22-structdoc-design.md 原则 1；docstore/structdoc.py:1-4）。
2. **两路入口汇入同一 schema**：原生 PDF 走字体/坐标（nativefonts.py、fontlevels.py），扫描 PDF 走 OCR 版面引擎（PaddleOCR-VL 等）。每块带 `src.origin` 和置信度。
3. **所有块角色都挂 Word 命名样式**，profile 一处定义；`booklayout restyle` 秒级改全书（今天只覆盖标题：builder.py:652-691、cli.py:369-392）。
4. **make 分快速路径与发布路径**：只改样式→restyle；只改译文→跳过 source-check；发布→全闸口。
5. **天然对照实验**：同一本 Rouse et al. 2022 *Annelida* 有原生版（GT）和扫描版（Greg），先用它量化扫描路线的引擎与参数，再定扫描书的默认引擎。

本会话实测的对照书事实【确证，PyMuPDF 实跑】：
| 项 | 原生版 | 扫描版 |
|---|---|---|
| 文件 | `/mnt/p/翻译-译作/Rouse2022_Annelida/原书/Rouse2022_Annelida_专著全本.pdf` | `/mnt/p/翻译-译作/Handbook_Annelida/Greg_Annelida_2022.pdf` |
| 页数 | 621；595×842 pt | 448；595×841 pt；文本层 0 字 |
| producer | PDF-XChange Core API SDK 7.0 | KONICA MINOLTA bizhub C658 |
| 书签 | 89 条，全 level 1，标题是 `oso-9780199692309-chapter-N`（可作章界，不可作标题文字） | 4 条（1-80@1、81-180@94、181-300@210、301-418@1——最后一条页号错），说明扫描件由 4 段拼成 |
| 同一印刷页 | 印刷页 18 = PDF p25（偏移 +7） | 印刷页 18 = PDF p31（偏移 +13）；页图有倾斜、装订阴影、对页透字 |
| 字体（每 6 页抽 1 页） | 正文 DanteMTStd-Regular 10pt（141671 字）；斜体 DanteMTStd-Italic 10；参考文献 SourceSansPro 8.7（含 Italic/Bold）；图注标签 MundoSansStd-Medium 8 + 正文 Dante 9；节标题 DanteMTStd-Bold 14；章标题 Dante 24（Italic 24 为科名）；页眉 Dante 12；索引 Merriweather 8.7 | 无 |
结论：两版同版式同页码（印刷页 18 两边都有 FIGURE 2.7），但**页偏移不固定**（扫描件分 4 段、夹彩色图版 PLATE），对页必须按文字匹配求，不能用常数偏移。原生版字体名直接区分斜体（-Italic），是斜体/粗体 GT 的可靠来源。

## A. 评测协议（原生版作扫描版的 ground truth）

### A.1 样本：20 页分层
来源两本：**Rouse 2022 原生/扫描成对 16 页**（量扫描路线）+ **Handbook 原生卷 4 页**（只量原生路线：双栏、四级编号、检索表；无扫描对照）。
Rouse 2022 是否有二歧检索表【未确证】；若没有，检索表层只由 Handbook 承担。

| 层 | Rouse 对页数 | 选页规则（对原生页按字体统计自动判，结果人工看缩略图确认） |
|---|---|---|
| 章首页（章名 24pt + 科名斜体） | 2 | 页内有 DanteMTStd 24pt span |
| 双栏正文 + 多级标题（Bold 14 节标题、斜体侧标题） | 4 | 正文 Dante 10 占比 ≥70%，含 Bold 14 或独行 Italic 10 |
| 图 + 长图注 | 3 | 图像面积 ≥30%，含 MundoSansStd "FIGURE" |
| 参考文献 | 2 | SourceSansPro 8.7 占比 ≥60% |
| 术语表（run-in 粗体词条 `abdomen:`） | 1 | DanteMTStd-Bold 10 行首 + 冒号（本会话见于 PDF p339） |
| 索引（多栏、Merriweather） | 1 | Merriweather 占比 ≥60%（见于 p603） |
| 前页/目录 | 1 | 前 15 页内含 Contents |
| 彩色图版 PLATE（只在扫描件里有对应吗未确证） | 2 | 扫描页 OCR 首行 `PLATE`；原生版找不到对页就只评 caption 文字 |
| Handbook 原生：双栏+四级编号标题、检索表、run-in 标签 | 4（Vol3 p13-40 内选 2 页，检索表 2 页） | probe_spec.md §0 已定字体：节标题 DGMetaScience-Bold 12、小节 Bold 9.5 与正文同号 |

固定样本清单写入 `docs/ocr_eval/layout_sample.tsv`（列：book, native_pdf, native_page, scan_pdf, scan_page, printed_page, stratum）。扩页前先问用户（ocr_multi_engine_plan.md §1 第 5 条）。

### A.2 对页（scan_page ↔ native_page）
不能用常数偏移（§0：4 段拼接、夹图版）。做法：
1. 扫描页用 Tesseract eng（本机 /usr/bin/tesseract 5.3.4）出 TSV；sourcecheck.py:122 `ocr_page()` 已有按页 TSV 缓存，直接复用。
2. 原生每页取词集合；对每个扫描页，用「折叠后长度 ≥4 的词」做 Jaccard，取最大者；要求最大值 ≥2 倍第二名，否则记 `ambiguous` 由人看。
3. 再用页脚/页眉印刷页码交叉核对（folio.py 已能读原书页脚，MISTAKES H8）。

### A.3 由原生页生成 GT（`gt/<book>/pNNNN.json`）
- **文字与 run**：PyMuPDF `get_text("dict")` 的 span；斜体/粗体用 `nativefonts.span_style`（nativefonts.py:13，字体名 -Italic/-Bold 加 flags）。行末连字符拼回、连字展开。
- **块**：PyMuPDF block 再按「同字体样式 + 行距 ≤1.5×字号」并段。
- **角色（规则初标，人工终审）**：按本书字体表映射：Dante 24 → heading L1；Dante-Bold 14 → heading L2；独行短句 Dante-Italic 10 → heading L3【规则未定，需人工逐页核】；MundoSans "FIGURE"+后续 Dante 9 → caption；SourceSans 8.7（在 References 节内）→ ref；Merriweather → index；页顶 Dante 12/页码 → furniture（header/footer）；其余 Dante 10 → body。Handbook 用 `fontlevels.analyse`（fontlevels.py:152）+ 编号深度（:80 `number_depth`）给层级。
- **阅读顺序**：按 layout._find_gutter（docstore/layout.py:56）分栏，栏内自上而下；跨栏图注/标题按 y 插入。
- **人工终审**：Sonnet 对照 150 dpi 页图逐块核角色、层级、顺序，改动写 `verified_by`、`changes[]`；GT 文件带 `gt_status: rule|verified`，只用 verified 出正式结论。
- **配准**：扫描页 Tesseract 词框 ↔ 原生词（词序列 difflib 对齐，只取唯一匹配词）→ 最小二乘 + RANSAC 拟合仿射（缩放、旋转、平移）；残差中位数 >3 px（200 dpi）则标 `registration_bad`，该页不计 IoU 类指标，只计文字类指标。原生块框经仿射投影到扫描像素坐标，得扫描页 GT 框。

### A.4 指标（统一由一个评分模块算）
| 指标 | 定义 | 实现 |
|---|---|---|
| 块类型 F1 | 预测块与 GT 块按 IoU≥0.5 一对一匹配（匈牙利），按角色算 P/R/F1，报 macro-F1；另报「文字匹配」口径（块文字 bag_f1≥0.6 即匹配），抵消块粒度差异 | 新写；bag_f1 复用 scripts/bench/ocr_score.py:65 |
| 阅读顺序 | 已匹配块的 Kendall τ；另报「跨栏交错次数」（MISTAKES H12 的病：多栏按行交错） | 新写 |
| 标题层级准确率 | GT 标题中被识别为标题且层级相同的比例；分两栏报：引擎原生输出、经本仓规则（编号深度 + headings.taxon_level，headings.py:78）后 | 新写 |
| CER | 去 furniture 后按 GT 阅读顺序拼接，`ocr_score.cer`（ocr_score.py:59）；同时报 bag_f1，把「顺序错」和「字错」分开 | 复用 |
| 斜体/粗体保留 | GT 斜体词（原生 span）上的词级 P/R/F1。引擎不给斜体时记 n/a，并用 booklayout/styles.py、typo_features.py 从页图量的斜体作对照 | 新写 + 复用 |
| 耗时/成本 | 每页墙钟秒、CPU/GPU、云 API 配额 | 适配器记录 |
结果每引擎每层一行追加 `docs/ocr_eval/LEDGER.tsv`（现有列：date, engine_params, set, metric, result, cost, source），set 写 `Rouse2022 pair n=16 (GT=native verified)`。

### A.5 待比较引擎（本会话 `pip list`/`ls` 确认已装；不做新安装）
| 引擎 | 位置 | 给什么 | 备注 |
|---|---|---|---|
| PaddleOCR-VL-1.6 云 API | docstore/engines/paddle_vl.py:456（缺省模型）；prunedResult 已存 `layout/<key>/pNNNN.json`（:400 save_layout） | 块框、标签、阅读顺序、markdown | 主候选。Rouse 为已出版书，可上云（调研 §4.3 约束） |
| PP-StructureV3 云 API | 同一 API，model 参数；`bench/api_runs/PP-StructureV3`、`bench/api2_PP-StructureV3.log` 已有跑法 | 块 + 表格结构 + 标题 | 仓库无转换器（调研 §4.2） |
| PaddleOCR 3.7 本地（PP-StructureV3 / PP-DocLayoutV3） | `/root/ocr_eval/venv_gpu`（paddlepaddle-gpu 3.3.1）；模型缓存 `~/.paddlex/official_models/` 含 PP-DocLayoutV3、PP-OCRv5/v6 | 同上，离线 | GTX 1660S 6 GB 能否跑全流程【未确证】，先 1 页试 |
| PaddleOCR-VL-1.6 本地 | 模型已缓存 `PaddleOCR-VL-1.6-0.9B` | 同云 API | 官方建议显存 ≥8 GB（ocr_tool_survey.md 候选表），本机 6 GB【未确证】；失败即弃 |
| MinerU 4.2.3 | `/root/ocr_eval/venv_mineru`；HF 缓存 `MinerU2.5-Pro-2605-1.2B` | middle.json para_blocks + title level | 显存【未确证】；VLM 失败退 pipeline 后端 |
| Docling 2.151.1 | `/root/ocr_eval/venv_docling`（带 rapidocr）；HF 缓存 granite-docling-258M | DoclingDocument：section_header/caption/page_header… | 标准管线 + granite 两种都跑 |
| Marker / Surya | `/root/ocr_eval/venv_marker`（marker_single、surya_layout） | 块类型 + section_hierarchy | 许可证有商用门槛（调研 §4.3） |
| Tesseract 5.3.4 eng | /usr/bin/tesseract | 只有行/词 | 文字基线；无块类型，块 F1 记 n/a |
| PP-OCRv6 medium 本地 | venv_gpu | 只有行 | 文字基线 |
不跑：olmOCR（7B，显存不够，调研 §4.3）、kraken（Greg 旧页 CER 0.76/0.62，LEDGER.tsv:173-174）、yomitoku（日文专用）。

适配器统一输出 `engine_page.json`：`{page, engine, params_hash, seconds, blocks:[{bbox_px, label_raw, role, level|null, text, order, italic_spans|null}]}`；标签→role 映射表每引擎一张，VL/StructureV3 复用 vl_to_aligned.py:17-20 的 MAP/SKIP（furniture 映射为 `furniture` 角色，不丢，评分时单列）。

### A.6 判定（不预设阈值，按数据报给用户）
- 输出排名表：CER、块 macro-F1、τ、标题层级、斜体 F1、秒/页；每项标 n。
- 推荐规则：扫描书默认引擎 = 在 CER 不劣于最优者 +0.5 个百分点的引擎中块 macro-F1 最高者；平手取更快者。该规则本身需用户认可后才写进软件缺省【未定】。


## B. aligned.json 升级为单一真源（aligned/2，向后兼容）

现状【已确证】：排版只读 aligned.json（pages→blocks{role, level, text, translation, block_id, coords}，docs/booklayout.md:26-38）；StructDoc（docstore/structdoc.py:15 SCHEMA=structdoc/1）只是派生视图。profile.validate_aligned（profile.py:170）只查必填字段，未知字段不报错【推测，需读 :170 全文确认】。
原则：**只加可选字段，不改旧字段语义**；缺省时行为与现在一致，旧 aligned.json 不迁移也能排。

### B.1 字段表（块级）
| 字段 | 类型 | 含义 | 由谁写 | 谁读 |
|---|---|---|---|---|
| `role` | str | 不变：heading/body/caption/key/ref/note/entry/index… | 不变 | builder 分派（builder.py:1602-1668） |
| `level` | int\|null | 不变：标题层级 1–4 | 不变 | builder.py:1602-1614 |
| `level_source` | str | `font`/`number`/`taxon`/`engine`/`manual`；冲突时按 manual>number>font>taxon>engine | fontlevels/headings/人工 patch | QA 报冲突（#60 的 8 处冲突即此） |
| `style` | str\|null | 命名段落样式，如 `Body`、`Caption`、`Ref`、`Heading 2`；空则按 role 缺省映射 | ingest 或人工 | builder（C 节） |
| `src.origin` | `native`\|`ocr`\|`manual` | 原文来源 | ingest | source-check 决定是否需 OCR 核对（D 节） |
| `src.engine` | str | 如 `pymupdf-1.24`、`paddleocr-vl-1.6` | ingest | 追溯 |
| `src.page` / `src.bbox` | int / [x0,y0,x1,y1] pt | 原书页与框（native 用 pt，ocr 用 px 并带 `src.dpi`） | ingest | 对页、图位 |
| `src.conf` | float\|null | OCR 置信度；native 为 null | ingest | QA |
| `src.hash` | str | 该块原文 sha1（规范化后） | ingest | 增量失效键（D 节） |
| `font` | {family, size, bold, italic} | 块主导字体（按字符数众数） | native ingest；OCR 引擎能给才写 | fontlevels、评测 |
| `runs` | [{t, i?, b?, sup?, sub?, sc?}] 可选 | 原文 run 级格式 | native ingest | 只作证据与评测，**不驱动排版** |

### B.2 run 格式只保留一个真源
排版已用行内标记驱动 run：builder.add_runs（builder.py:320；sup/sub :330；`*斜体*`/`**粗体**` :349-360）。所以：
- **`text`/`translation` 里的行内 markdown 仍是唯一驱动排版的格式通道**【设计决定】。
- `runs` 只存原文证据。ingest 时由 runs 生成带标记的 `text`（斜体学名 → `*Nereis*`），译文的斜体由翻译闸口按学名保持。
- 不让 builder 同时读 runs 和标记，避免双真源冲突。

### B.3 页级与文件级
- 顶层加 `"schema": "aligned/2"`、`"source": {"pdf", "sha1", "kind": native|scan}`（kind 取自 docstore probe，#59 已实现 docstore/probe.py）。
- 页级加 `printed_page`（folio）、`columns`。
- 无 `schema` 字段视为 aligned/1。

### B.4 示例
```json
{"schema":"aligned/2","source":{"pdf":"Rouse2022_Annelida_专著全本.pdf","kind":"native"},
 "pages":[{"page":25,"printed_page":18,"columns":2,"blocks":[
  {"block_id":"p0025-b03","role":"heading","level":2,"level_source":"font","style":"Heading 2",
   "text":"2.3 Segmentation","translation":"2.3 分节",
   "src":{"origin":"native","engine":"pymupdf","page":25,"bbox":[56,120,290,138],"hash":"9f1c…"},
   "font":{"family":"DanteMTStd","size":14,"bold":true,"italic":false}},
  {"block_id":"p0025-b04","role":"body","style":"Body",
   "text":"In *Capitella teleta* the …","translation":"在 *Capitella teleta* 中……",
   "src":{"origin":"native","page":25,"bbox":[56,142,290,400],"hash":"77ab…"},
   "font":{"family":"DanteMTStd","size":10,"bold":false,"italic":false},
   "runs":[{"t":"In "},{"t":"Capitella teleta","i":true},{"t":" the …"}]}]}]}
```
注：章节号与标题之间一律半角空格，禁用 U+3000。
OCR 块示例只差：`"src":{"origin":"ocr","engine":"paddleocr-vl-1.6","page":31,"bbox":[...],"dpi":200,"conf":0.97}`，无 `runs`，`font` 缺省。

### B.5 新入口
- `booklayout ingest-native <pdf> --pages A-B -o aligned.json`：PyMuPDF span → 块（A.3 同一套规则，与评测 GT 生成共用代码）→ fontlevels 给 level → 写 aligned/2。原生书从此不走 OCR。
- `scripts/vl_to_aligned.py` 升级：写 `src.origin=ocr`、`src.engine`、`src.bbox`，并保留 VL 原始 label 到 `src.label`（T6）。
- StructDoc 派生时把 `src.origin` 映射到 structdoc `_block.src.origin`（structdoc.py:32-35 已有该字段）。


## C. 样式表驱动排版（命名段落样式）

### C.1 现状【已确证】
- 只有标题是命名样式：define_heading_styles（builder.py:652-691）按 profile.heading_style 建 1–4 级，heading()（:694-704）只套样式。
- 其余角色在 para()（builder.py:617-636）里直接设字号、缩进、段距、行距：body 10.5、两端对齐、首行 5（:1624-1638）；caption 9.5（:1262-1275）；citation 9.2（:1639-1640）；ref 7.6（:1653-1654）；entry 10.2/9.2（:1656-1662）；key 9.5（:1186/:1212）；keymodel.py:284 直接设 run 字号。
- 所以 `booklayout restyle`（cli.py:369-392）只能改标题（:382 只调 define_heading_styles）。改正文字号必须全量重建。

### C.2 目标
每个 role 对应一个 Word 命名段落样式。段落只引用样式名，不写直接格式（行内斜体/上下标除外）。restyle 改样式定义即可，Word 里用户也能「修改样式」一次改全书。

| 样式名 | 角色 | 现值来源（缺省取现值，保证无回归） |
|---|---|---|
| `Body` | body | builder.py:1624-1638 |
| `Body First` | 节后首段（无首行缩进，若现有逻辑区分）【未确证是否区分】 | 同上 |
| `Caption` | caption、table caption | :1262-1275、:1771 |
| `Note` | note | :1616-1622（profile.note_italic，profile.py:71） |
| `Citation` | citation | :1639-1640 |
| `Ref` | ref | :1653-1654 |
| `Entry` / `Entry Sub` | entry | :1656-1662 |
| `Key` / `Key Couplet` / `Key Table` | key、couplet | :993、:1046、:1120、:1186、:1212；keymodel.py:284 |
| `List Item` / `Quote` / `Box Text` / `Footnote Text` | list/quote/box/footnote | :1774、:1779、:1782、:1793 |
| `Index` | index | :1668、:1915-1983 |
| `Front Matter` / `Contents Title` | 前页 | :1300-1350、:1356 |
| `Heading 1`–`Heading 4` | heading | 已有 |

### C.3 要改的模块与函数
| 文件:行 | 改动 |
|---|---|
| profile.py:48 StyleProfile、:77-82 | 新增 `para_styles: dict[str, dict]`（字段：size, bold, italic, align, first_indent, left_indent, before, after, line, keep_together, keep_with_next, font_east_asia, font_ascii）；缺省值由现常量生成 |
| profile.py:120-128 from_dict、:143-167 validate | 接受 para_styles；校验样式名属已知集合、子字段属允许集合（同 heading_styles 写法） |
| builder.py:414-428 setup | Normal 仍由 body_size；新增调用 `define_styles(doc, profile)` |
| builder.py:652-691 | 抽出 `define_styles()`：先建段落样式，再调原 define_heading_styles；名字保留旧函数作薄包装（cli.py:382 和测试仍可用） |
| builder.py:617-636 para() | 新增参数 `style=`；给了样式就只套样式；仍接受旧参数作覆盖（过渡期），覆盖时 stylecheck 报 warning |
| builder.py:1262、:1616-1668、:1771-1793、:993-1212 | 各调用点改为 `para(..., style="Caption")` 等，删直接字号 |
| keymodel.py:284 | run 字号改为继承段落样式；只保留斜体/粗体 |
| builder.py:612-614 _sz | 缩放改为作用于样式定义（restyle 时整体缩放） |
| cli.py:369-392 cmd_restyle | 调 define_styles（全部样式）；新增 `--style Name.size=10` 形式的命令行覆盖，便于快速试 |
| htmlout.py:23 heading_css、:87、:93 | 由 doc.styles 生成全部段落样式的 CSS，按 par.style.name 套类 |
| stylecheck.py:32 check_docx、runstyle.py:39 | 新增规则：正文段落带直接字号/段距 = warning（防退回直接格式） |

### C.4 验收
- 回归：同一 aligned.json，改前改后 PDF 逐页文字相同、页数相同、每页 bbox 差 ≤1 pt（用 `pdftotext -bbox` 比较）。现值缺省保证这一点；做不到即视为回归。
- restyle 生效：`booklayout restyle in.docx --profile p.json --style Body.size=11 -o out.docx` 后，抽 3 个正文段 `p.style.name=="Body"` 且 `paragraph_format`/run 无直接字号。
- `pytest tests -k "builder or restyle or stylecheck or htmlout or profile"` 全过。

## D. 增量重排（make 快速通道）

### D.1 现状【已确证】
- make（make.py:31）固定走：build1（:66）→ map-pages（:72）→ build2（:74）→ key-report（:75）→ 必要时 build3（:76-78）→ 并行 qa/check/stylecheck/source-check（:80-99）→ gate（:102）→ review/html（:114-120）→ trace（:125-129）。argparse（:144-159）没有快速通道开关。
- buildcache 键 = 全部输入哈希 + code_fingerprint（buildcache.py:33-39 哈希全部 booklayout/*.py；:52-62 input_key）。改一个字或改任一 .py 都整本失效。
- 实测耗时：Vol21 闸口占 75–83%（ES 全程 1183.6 s，其中闸口 977 s）；docs/booklayout.md:388 记 Vol25 p1-50 含 source-check 80 s、不含 13 s。source-check 是对原书逐页 Tesseract TSV（sourcecheck.py:122，有 pNNNN.tsv 缓存）再 difflib 比对。
- 各闸口在 977 s 内的分摊【未确证】，T5 先量。

### D.2 判定表（改了什么 → 跑什么）
| 改动 | 判定依据 | 跑 | 跳过 | 命令 |
|---|---|---|---|---|
| 只改样式（profile 的 heading/para_styles） | aligned.json 的 src.hash 与 translation 哈希都没变；profile 哈希变 | restyle →（可选）PDF → stylecheck | build、map-pages、source-check、qa | `booklayout restyle in.docx --profile p.json --pdf` |
| 只改样式且影响分页（字号/段距/行距） | 同上，且改的是尺寸类字段 | restyle → PDF → 重量目录页码 → 目录回填 | source-check、qa 文字类 | `booklayout make … --fast=style` |
| 只改译文（translation、patch-blocks，cli.py:1636） | src.hash 全部不变 | build1→map→build2→key-report→qa/check/stylecheck→gate | source-check（原文没变，结论不会变） | `booklayout make … --fast` |
| 原文变（src.hash 变、新增/删块、重 OCR） | 任一 src.hash 变 | 全量；source-check 只跑变了的页 | — | `booklayout make …` |
| 代码变 | 见 D.3 分模块指纹 | 受影响步骤 | 不受影响步骤 | 自动 |
| 发版 | 用户指定 | 全量，不用任何缓存 | — | `booklayout make … --release` |
规则：`--fast` 只是请求，make 先按上表自判；判出原文变了就自动降为全量并打印原因。gate 报告写明哪些闸口被跳过、跳过依据（哈希值），不得把「跳过」写成「通过」。

### D.3 缓存失效规则
1. **source-check 按页缓存**：键 = (原书页 sha1、该页所有块 src.hash、sourcecheck.py 指纹、Tesseract 版本+参数)。命中即复用上次 verdict（sourcecheck.py:622）。只改译文时整页命中。
2. **code_fingerprint 分模块**：把 buildcache.py:33-39 的单一指纹拆成 `builder_fp`（builder/keymodel/profile/htmlout）、`check_fp`（qa/stylecheck/runstyle）、`source_fp`（sourcecheck）。改 qa 代码不使 DOCX 缓存失效。
3. **按章失效**：块带章 id（来自 manifest 或 contents）；章哈希 = 本章块 (src.hash, translation, style) 的哈希。只有变了的章重跑 qa/check。整本 DOCX 仍一次生成（章间页码连续，见 F）。
4. **分章构建**（每章单独 DOCX 再合并）是第二阶段【推测可行】，前提是能保证页码连续与目录回填；本期不做。

### D.4 验收命令
- `booklayout make <book> --fast` 在只改 1 个 translation 的 Vol25 p1-50 上：耗时 ≤ 不含 source-check 的基线（13 s 量级，docs/booklayout.md:388）× 1.2；gate 报告含 `source-check: skipped (src unchanged, hash=…)`。
- 同一数据改 1 个 src 字：`--fast` 自动降级为全量，source-check 只跑 1 页。
- `booklayout restyle … --style Body.size=11 --pdf` 在 Vol21 DOCX 上 ≤ 现 restyle 3.47 s + PDF 转换时间。
- `pytest tests -k "make or buildcache or sourcecheck"` 全过；新增测试覆盖 D.2 每一行判定。

## E. Sonnet 任务（每个任务只改、只提交自己的文件；工作区有他人未提交改动，提交用 `git add <具体文件>`，禁止 `git add -A`；禁止再开子代理；每完成一步写盘）

| # | 任务 | 改哪些文件 | 测试 | 验收命令 | 不得碰 | 依赖 / 并行 | issue |
|---|---|---|---|---|---|---|---|
| T1 | 评测框架：样本表、对页、原生→GT、仿射配准、评分（A 节） | 新 scripts/bench/layout_pair.py、layout_gt.py、layout_score.py、adapters/*.py；docs/ocr_eval/layout_sample.tsv；追加 LEDGER.tsv | tests/test_bench_layout_score.py（合成块算 F1/τ/层级/斜体 F1，手算对照） | `python3 scripts/bench/layout_score.py --sample docs/ocr_eval/layout_sample.tsv --engine tesseract` 出 16 行结果 | booklayout/、docstore/ 源码；ocr_score.py 只 import 不改 | 无；与 T2、T3、T5 并行 | 新开 issue「版面评测：原生版作扫描 GT」 |
| T1b | 跑引擎（A.5 表），每引擎先 1 页试，再 16 页 | 只写 bench 输出目录与 LEDGER.tsv | — | 排名表写入 docs/ocr_eval/layout_result.md | 不新装包；6 GB 显存跑不动就记录并跳过 | T1 后 | 同上 |
| T2 | `booklayout ingest-native` → aligned/2（B 节） | 新 booklayout/ingest_native.py；cli.py 只加子命令注册；profile.py:170 validate_aligned 接受新字段 | tests/test_booklayout_ingest_native.py（合成 PDF + Handbook Vol3 p13-14 真页 smoke） | `booklayout ingest-native Vol3.pdf --pages 13-40 -o /tmp/a.json` 后 `booklayout build` 成功；标题层级与 fontlevels 输出一致 | builder.py | 无；与 T1、T3 并行（与 T1 共用 GT 规则：T2 先出函数，T1 import） | #60、#62 |
| T3 | 命名段落样式（C 节 C.3 除 cli/htmlout 外各行） | profile.py、builder.py、keymodel.py | 改前后同一 aligned PDF 文字/页数/bbox 回归（C.4）；新增 tests/test_booklayout_para_styles.py | `pytest tests -k "builder or profile or keymodel"`；C.4 回归脚本 | cli.py、htmlout.py、make.py | 无；与 T1、T2、T5 并行 | #27 |
| T4 | restyle 扩展 + HTML 样式 + stylecheck 防直接格式 | cli.py:369-392、:2036；htmlout.py；stylecheck.py；runstyle.py | tests/test_booklayout_restyle.py | `booklayout restyle … --style Body.size=11 --pdf`（C.4） | builder.py（T3 的） | T3 后 | #27 |
| T5 | make `--fast`、分模块指纹、source-check 按页缓存、先量闸口分摊 | make.py、buildcache.py、sourcecheck.py | tests/test_booklayout_make_fast.py（D.2 每行一个用例） | D.4 前三条 | builder.py、profile.py | 无；与 T1–T3 并行 | 新开 issue「make 增量快速通道」 |
| T6 | VL / PP-StructureV3 结果 → aligned/2（src.origin=ocr、label、bbox、层级） | scripts/vl_to_aligned.py；新 scripts/structv3_to_aligned.py | tests/test_vl_to_aligned.py（用 layout/<key>/pNNNN.json 现成样例） | Greg 16 页转出后用 T1 评分，标题层级不低于直接 VL 输出 | docstore/engines/paddle_vl.py | T1 后（要评分器） | 新开 issue 或并入 #27 |
| T7 | Handbook Vol3 试点：ingest-native → build → restyle → make --fast 端到端 | 只写 Handbook 排版目录下试排产物与记录 | tests/test_handbook_acceptance.py 加 1 例 | 端到端命令全成功；与现 `排版/试排_第一卷` 版式对照表 | 译文 md（Handbook CLAUDE.md 硬约束）；不覆盖现有成品 | T2、T3、T4、T5 后 | #62 |

先报 issue：T1（版面评测）、T5（make 快速通道）两个新 issue 先开；T2 评论到 #60/#62，T3/T4 评论到 #27，T6 视评测结果再开。按用户规则「缺功能先报 issue」（KNOWLEDGE 2026-11-26），开 issue 前先给用户过目。
并行批次：第 1 批 T1、T2、T3、T5 四个同时；第 2 批 T1b、T4、T6；第 3 批 T7。
每个任务交付：改动文件清单、测试结果、验收命令输出摘要（≤200 字）、commit hash（只含本任务文件）。

## F. 风险与未确证

| # | 项 | 状态 | 依据 / 下一步 |
|---|---|---|---|
| F1 | Rouse 原生 PDF（producer PDF-XChange，书签 oso-…）与 Greg 扫描件是否同一印次 | 已确证同版式同页码（印刷页 18 两边都有 FIGURE 2.7，§0）；全书逐页一致【未确证】 | T1 对页时 Jaccard 低于阈值的页单列 |
| F2 | 扫描件 4 段拼接、夹彩色 PLATE，页偏移不固定 | 已确证（书签 301-418@1 页号错，§0） | A.2 文字对页 |
| F3 | VL 云 API 是否输出标题层级字段 | 未确证；vl_to_aligned.py:17-20 只映射 paragraph_title/doc_title 两层 | T6 读 layout/<key>/pNNNN.json 原字段 |
| F4 | 闸口 977 s 内各项分摊（source-check vs qa vs stylecheck） | 未确证 | T5 第一步计时；--fast 收益取决于此 |
| F5 | 跳过 source-check 的前提是 src.hash 可信 | 推测成立；旧 aligned/1 无 src.hash | 无 hash 时 --fast 不跳过 source-check |
| F6 | 改样式后分页变，目录页码失效 | 已确证机制（目录两遍编译，Handbook CLAUDE.md；collect_toc_pages.py） | D.2 第 2 行强制重量目录 |
| F7 | 分章构建的页码连续 | 推测可行，未验证 | 本期不做（D.3-4） |
| F8 | 本地 VL/MinerU 在 GTX 1660S 6 GB 能否跑 | 未确证 | T1b 每引擎 1 页试，失败即记录跳过 |
| F9 | 直接格式改命名样式会出视觉回归 | 风险中 | C.4 bbox 回归；缺省值取现常量 |
| F10 | tests/test_docstore_structdoc.py:200 已失败（figure_no_order 未实现） | 已确证（调研时 pytest） | 与本设计无关，不在本期修；各任务以「改前基线」比较 |
| F11 | 全量 pytest 有 5 个既有失败 | 已确证存在，基线未在改动前验证（KNOWLEDGE 2026-11-26） | 各任务开工先跑并存基线 |
| F12 | Handbook 节与小节同字体（DGMetaScience-Bold 9.5），只靠字体分不出层级 | 已确证（#60 实测，8 处冲突） | B.1 level_source 优先级 + 编号深度（fontlevels.py:80） |
| F13 | 斜体 GT 只能来自原生 span；扫描路线的斜体只能从页图量 | 已确证机制（nativefonts.py:13；styles.py 文件头） | A.4 斜体指标对扫描引擎多为 n/a |
| F14 | Rouse 2022 有无二歧检索表 | 未确证 | A.1 检索表层由 Handbook 承担 |
| F15 | profile.validate_aligned（profile.py:170）对未知字段的行为 | 未确证（未读全文） | T2 先读后改 |

## 结论摘要
1. 原生 PDF 书：用 `ingest-native` 直接出 aligned/2，不走 OCR；标题层级 = 字号/字体 + 编号深度 + 人工 patch。
2. 扫描书：引擎由 A 节实测排名决定，不预设；目前 PaddleOCR-VL 是唯一已接入的版面引擎。
3. 快排版：命名段落样式 + restyle（秒级）解决「改格式」；make --fast（跳过 source-check、分模块指纹、按页缓存）解决「改译文」。
4. 本文件只是设计，未改任何代码。
