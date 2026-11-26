# 结构化 JSON + 样式式重排 & OCR 取版面：调研（2026-11-26）

只读调研，未改代码。依据标注 `文件:行`（仓库根 `Taxonomy-Aware-Scientific-Book-Translation/`）。标记：【确证】读码或实跑；【未定】有矛盾或缺数据；【推测】推断，未验证。

## 0. 一句话结论

用户设想的"一次结构化、反复低成本重排"在软件里**已有大半骨架**，但分成两套 JSON，且样式表只覆盖标题：
- 真正驱动排版的是 **aligned.json**（页→块，块带 role/level/text/translation/坐标），不是 StructDoc。
- **StructDoc（structdoc/1）** 是 2026-11-22 设计的统一结构层，目前只是 aligned/keys/treatments 的**派生视图 + 校验器**，排版不直接读它。
- "改样式不重排"：只有**标题 1–4 级**做成了 Word 命名样式，`booklayout restyle` 可秒级改；正文、图注、检索表、文献是**直接格式**，改字号必须整书重 build。
- "改一段译文"：改 aligned.json（`patch-blocks` / `trace set` / 可编辑 HTML 回写）后整书 `make`；有输入哈希缓存，但**没有按章/按块的增量重排**。

## 1. 已有设计：JSON 结构

### 1.1 aligned.json（排版主输入）【确证】
- 结构：`{pages:[{page, chapter, kind, blocks:[{role, level?, text, translation, y0/x0.., block_id, lineage?...}]}]}`（docs/booklayout.md「输入 1」节）。
- role 词表：legacy `heading body caption key ref entry citation index note couplet legend` + 新增 `table list quote box footnote figure_group`（booklayout/profile.py:41-44）。`validate-aligned` 校验（profile.py:168）。
- 页/卷关系：块挂在源 PDF 页下；`chapter` 键把连续页归章；**没有"卷"层**，一卷一个 aligned.json + metadata.json（卷名、页码偏移 folio_offset、页眉等，docs/booklayout.md「书籍元数据」表）。
- 来源：扫描书走 `scripts/vl_to_aligned.py`（PaddleOCR-VL 版面 jsonl → aligned，标签映射见 scripts/vl_to_aligned.py:18-21）；原生/通用走 `docstore export --translate` → md → `booklayout align-md`（booklayout/alignmd.py:1-14，角色按确定性规则只分 heading/caption/key/body）。

### 1.2 样式（StyleProfile）【确证】
- `booklayout/profile.py:48` `StyleProfile`：版心、页边距、正文字体/字号（body_size:62）、页眉页脚、`heading_styles`（profile.py:77，1–4 级各有 size/before/after/align/bold/italic/small_caps/color）、`key_style` tabs|table|couplet（:100）、`footer_style`、`heading_levels` source|taxon、`word_toc` 等。JSON/TOML 文件，`booklayout profile` 导出模板。
- 即"样式表"已经与内容分离——这正是用户想要的 Word 样式思路，**但只做到标题**：
  - 标题段落只引用命名样式 Heading N（builder.py:694-697 `heading()`），样式由 `define_heading_styles`（builder.py:652）从 profile 写入 → 改 profile 一项即全书同级标题统一改。
  - 正文/图注/文献/检索表用 `para()` 直接写字号、缩进、段距（builder.py:617-636），只有 `Normal`（builder.py:421）作底样式。

### 1.3 StructDoc（structdoc/1）【确证】
- 设计：docs/superpowers/specs/2026-11-22-structdoc-design.md；实现 docstore/structdoc.py（SCHEMA:15）。
- 块：`{id, type, page, order, text, data, src:{origin, ref, pi, bi}, status: ok|uncertain|fixed, issues}`；type = aligned role 超集（ROLE_TYPES:18）+ `key_couplet key_heading treatment figure`（EXTRA_TYPES:22）。顶层 `problems`、`summary`、`aligned_meta`。
- 能力：from_aligned/from_keys/from_treatments/from_figures（:75 起）、校验（:194，id 唯一、order 单调、检索表图检查、译文数字/学名/图号）、`to_aligned` 无损回写（:144；Imajima 2009/2001、Vol48 往返逐字相等，见 spec「切片 2」）。CLI `docstore struct build|auto|score`（docstore/cli.py:796-814）。
- 定位：spec 原则 1 明确"派生视图，不得反向当主库"；**不含任何样式字段**，也**没有卷/章层级**（只有 page + order）。
- 用户记得的"之前设计过 JSON"——应即此 StructDoc（2026-11-22）；而实际可排版的 JSON 是更早的 aligned.json。【推测：用户指的是 StructDoc；未向用户确认】

### 1.4 其他相关结构
- `booklayout/keymodel.py`：检索表结构模型（编号、备择、终点、跨页），`render_key` 排版（docs/publish_pipeline.md「新模块」）。
- `booklayout/structure.py`：只做跨页段落边界不确定性报告（structure.py:1-8），与"文档结构 JSON"无关，名字易误解。
- `booklayout/fontlevels.py`（issue #60）：原生 PDF 按字体族/粗体/字号阶梯 + "7.4.1" 编号判标题层级，CLI `booklayout heading-levels`（fontlevels.py:152-198）；`nativefonts.py` 读 span 斜体/粗体/字号；`styles.py`/`typo_features.py` 从扫描页图量 x-height、笔画粗细、倾角（粗/斜体线索）。这三者**输出独立 JSON，未写回 aligned/StructDoc**。

### 1.5 与"Word 样式式排版"的差距
| 能力 | Word 样式思路 | 现状 |
|---|---|---|
| 内容与样式分离 | 段落只挂样式名 | 标题是；正文/图注/检索表/文献否（直接格式） |
| 改一个样式全书生效、不重排 | 改样式定义即可 | 仅标题：`booklayout restyle`（cli.py:2036, cmd_restyle:369）；其他需整书 build |
| 字符样式（学名斜体、科名正体） | 字符样式 | builder 按规则在 run 上直接设斜体（_roman_family_group 等），无命名字符样式 |
| 结构层级（卷/章/节/科/属/种） | 大纲级别 | aligned 只有 page/chapter/level；Heading1–4 带 outline level（docs/booklayout.md「make」节）；无卷层 |
| 原文排版属性（字号/粗斜体/栏） | — | 量得到（fontlevels/nativefonts/styles），没进主 JSON |
| 单一结构 JSON | 一份 | aligned + StructDoc + keys.json + treatments.json 并存；StructDoc 未成排版入口 |

注意：Handbook_Annelida 当前排版**不走 booklayout**，用工程内自带的 md→docx `build_docx.py`（Rouse 底本，见 Handbook_Annelida/CLAUDE.md），所以上述能力目前都没用到 Handbook 上。【确证：Handbook CLAUDE.md「数据流」节】

## 2. 实现程度

### 2.1 两条入口能否产出结构 JSON
| 路线 | 产出 | 状态 |
|---|---|---|
| 扫描 PDF → PaddleOCR-VL 版面 → aligned | `scripts/vl_to_aligned.py`（VL 标签 text/paragraph_title/doc_title/figure_title/reference_content/content… 映射为 body/heading/caption/ref/index，:18-21；页眉页脚页码丢弃 SKIP:22） | **已实现**，Fauna Ibérica Vol.21/25/41 实用。但是 scripts/ 下脚本而非 CLI 子命令；标题层级要靠 profile `heading_levels: taxon` 从文字推断（booklayout/headings.py） |
| 扫描 PDF → PP-OCR 行框 → keys → StructDoc | `docstore struct auto`（structauto.py:24-50） | **半实现**：只抽检索表，金标账本 `docs/ocr_eval/STRUCT_LEDGER.tsv` 无数据行（spec 切片 4） |
| 原生 PDF → 结构 JSON | `docstore text` 只存**纯文本**（docstore/textify.py:207-218 `get_text()`，无块/字体）→ `docstore export --translate` → md → `booklayout align-md`（角色只 heading/caption/key/body，alignmd.py:9-12） | **半实现**：字体/字号/粗斜体能读（nativefonts.py、fontlevels.py `heading-levels`、docstore/probe.py），但**没有一条命令把原生 PDF 的块+字体+层级直接写成 aligned/StructDoc**。issue #60（标题按字体分级）、#61（无书签时章节切分回退）、#62（Handbook 双栏原生 PDF 验收）均 OPEN |
| Handbook 实际用法 | 工程自带 `handbook_prep.py`（坐标"先纵后横"抽文本）→ md → 工程内 `build_docx.py` | 与仓库 booklayout 两套，结构信息停在 md 标题 `#` 层级（mdheadings.py 专门审计这种漂移） |

### 2.2 JSON → docx/pdf/html 渲染
- `booklayout build` 读 aligned.json + profile + metadata + 图目录 → DOCX，`--pdf` 经 LibreOffice；`make` 一条命令串 build→map-pages→build(→build3)→qa/check/stylecheck/source-check 并行→gate→HTML（booklayout/make.py:31-137）。【确证】
- `booklayout html`：由成品 DOCX 转 HTML，CSS 由同一 profile 生成（htmlout.py:126、cli.py:2044）。
- `edit-html` / `apply-html-edits`：浏览器改粗/斜/换行写回 aligned；**字体、字号只记录不回写**（booklayout/editor.py:5-11）。
- StructDoc **不直接渲染**：需 `to_aligned`（structdoc.py:144）转回 aligned 再 build。

### 2.3 局部修改能否局部重排
| 修改 | 做法 | 是否整书重跑 |
|---|---|---|
| 标题某级字号/段距/对齐 | 改 profile.heading_styles → `booklayout restyle --docx --profile --out [--pdf] [--html]` | **否**（只改 DOCX 样式表；实测见 §3）。但目录/索引静态页码可能随之过期（推测：标题变大→分页变→需重跑 map-pages；Word TOC 域可"更新域"） |
| 正文/图注/检索表/文献字号、缩进 | 改 profile 对应字段 → build | **是**（这些是直接格式，builder.py:617-636） |
| 改一段译文 | `patch-blocks` / `trace set`（docs/booklayout.md「追踪库」节）/ edit-html 回写 → `make` | **是**：任何 aligned 变化使 buildcache 键失效（buildcache.py:56-66），整书重排 |
| 改一个字（不重排） | `scripts/publish/patch_release.py` 对 docx/pdf 定点替换（docs/architecture.md §6） | 否，但绕过数据源，aligned 不同步 |
| 按章增量重排 | — | **未实现** |

### 2.4 测试覆盖（实跑）【确证】
`python3 -m pytest -q` 相关 13 个文件（alignmd、cache、editor、fontlevels、profile、structure、docstore_probe、structauto、structdoc、styles、styles_attach、typo_features、vl_to_aligned）：**97 passed, 1 failed，15 s**。
- 失败：`tests/test_docstore_structdoc.py:200 test_figure_no_order_flags_outlier_with_hint`——测试期望 `figure_no_order` 问题码，代码中不存在（全仓 grep 只在测试里）。测试由提交 27df090 加入，实现未同提交，**测试先于代码，应报 issue**。
- restyle 有测试（tests/test_booklayout_fauna_features.py 中引用）；"改样式后目录页码是否仍正确"无测试。【确证 grep；后者未见】

## 3. 效率

### 3.1 实测数字【确证：yanjie/排版成品/*.make.json】
Fauna Ibérica Vol.21 全书（西文 PDF 529 页、中文 473 页，DOCX 约 97 MB）`booklayout make`：
| 版本 | 总时长 | 每次 build | map-pages | 并行闸口 |
|---|---|---|---|---|
| ES | 1183.6 s | 57.2 / 60.9 / 67.1 s（3 次） | 9.2 s | 977.0 s |
| EN | 753 s | 约 59 s ×3 | — | 549 s |
| ZH | 882 s | 约 59 s ×3 | — | 652 s |
| ES p1-150 | 748 s | — | — | — |

（来源：Fauna_Iberica_Vol21_ES_full.make.json 的 seconds 字段；各次均 ok:false/DRAFT，闸口未过，不影响计时。）

### 3.2 restyle 实测【确证：本会话 scratchpad 实跑】
ZH 全书 DRAFT.docx（97 MB），只把 profile 中二级标题字号 12→14：`booklayout restyle` 写 DOCX **3.47 s**（墙钟 4.39 s，内存 253 MB），未转 PDF。转 PDF 还要 LibreOffice，按 buildcache.py 文件头 Vol48 基线（470 页 PDF 43 s）推，约 40–60 s【推测】。

### 3.3 缓存【确证：booklayout/buildcache.py、cli.py:323-355】
- DOCX 键 = aligned + profile + metadata + 图目录 + 代码指纹的哈希；PDF 键 = DOCX 的 sha256。完全没变时秒级命中。
- 任一输入变化（哪怕改一个字）→ DOCX、PDF 全量重建；改仓库代码也全部失效（code_fingerprint 哈希全部 booklayout 源码）。
- 无按章/按块增量。

### 3.4 瓶颈
1. **闸口**：占总时长 75–83%（977/1184、549/753、652/882）。其中 source-check 用 Tesseract 重 OCR 原扫描页比对（docs/publish_pipeline.md；Vol25 p1-50 带/不带 source-check：约 80 s / 13 s）。改译文后其实不必重跑原文 OCR 比对，但 make 没有"只改译文/只改样式"的快速路径。【确证数字；"不必重跑"为推测】
2. **三次整书 build**：页码映射要两遍（目录静态页码），检索表再一遍；每遍约 60 s，其中 LibreOffice 转 PDF 约占 70%（buildcache.py 文件头）。
3. 结论：**改样式（仅标题）高效（秒级）；改一段译文后要正式成品，一本 500 页书约 12–20 分钟**。日常校对可只 `build`（约 1 分钟）+ 看 PDF，发布前再 `make`。

## 4. 取版面（格式）的办法

### 4.1 原生 PDF：不用 OCR【确证】
原生 PDF 自带字体、字号、粗/斜体、坐标。PyMuPDF 的 span 就是最准的"格式"来源，软件已在用（booklayout/nativefonts.py、fontlevels.py、docstore/probe.py）。缺的只是"汇入主 JSON"这一步（§2.1）。
Handbook 实测的局限：节和小节标题字体相同（DGMetaScience-Bold 9.5pt），只靠字体分不出层级，要再结合编号"7.4.1"和书签（本会话前段 `booklayout heading-levels` Vol3 p13-40 实测）。所以原生 PDF 判层级要用三条线索：字体、编号、书签。

### 4.2 扫描 PDF：现用引擎【确证：读码与仓库文档】
| 引擎 | 能给的格式 | 软件里的状态 |
|---|---|---|
| PaddleOCR-VL（AI Studio 云 API，缺省 VL-1.6） | 每页 `prunedResult`：块框、块标签（paragraph_title/doc_title/text/figure_title/reference_content/header/footer/number…）、阅读顺序；另有 markdown（标题带 #） | docstore/engines/paddle_vl.py:345-363 已把 prunedResult 存到 `<库>/layout/<key>/pNNNN.json`（save_layout:400）；`scripts/vl_to_aligned.py` 把 VL jsonl 转 aligned。两者是否已打通（vl_to_aligned 能否直接读 layout/<key>/）【未定，未实跑】 |
| PP-StructureV3（同一 API，model=PP-StructureV3） | 版面块 + 表格结构 + 标题 | API 支持（docs/ocr_eval/paddle_aistudio_api_official.md §1 model 参数）；仓库无专门转换【确证 grep 无 PP-StructureV3 转换器】 |
| PP-OCRv5 / RapidOCR / Tesseract | 只有行框+文字，没有块类型 | 主力文字引擎（docs/ocr_tool_survey.md） |
| 云 API 实测 | 扫描 3 页 131 s；30 页 112 s；合成 250 页成功；扫描 105 页（76 MB）曾 500 失败 | docs/ocr_eval/paddle_aistudio_api_probe.md T1–T11 |

用户记得"pp api 能取格式"——对：VL/StructureV3 给的是**块类型 + 位置 + 阅读顺序**，可判标题、正文、图注、页眉；但**不给字号、字体、粗斜体**，标题级别也只有 doc_title/paragraph_title 两档【确证 vl_to_aligned.py:18-21 MAP 只认这两档；VL 是否另给层级字段 未确证】。粗/斜体在软件里另由 booklayout/styles.py、typo_features.py 从页图量。

### 4.3 其他办法（网络检索 2026-11-26；未在本机测试，均【未定】）
| 工具 | 输出的结构 | 层级/样式 | 备注与来源 |
|---|---|---|---|
| MinerU 2.5（开源） | middle.json：para_blocks，类型 text/title/list/index/image/table…；title 带 level | 有 title_leveling（2–6 级），只在整份文档时运行 | github.com/opendatalab/MinerU docs/en/reference/output_files.md；OmniDocBench Overall 90.67（docs/ocr_eval/survey_notes.md 引 sota2，2026-11-11）。本机 6 GB 显存能否跑：未确证 |
| Docling（IBM，开源） | DoclingDocument JSON 树：section_header、text、caption、table、page_header… | 默认所有标题同级；可开 heading hierarchy 阶段，用书签、编号（1.1、A.2）、字体推层级 | docling-project.github.io/docling/usage/heading_levels/。原生 PDF 不需 OCR，扫描可接 OCR。思路与 §4.1 三线索一致，值得对照 |
| Marker（Datalab） | JSON 树，块类型 SectionHeader/Text/Caption…，每块带 section_hierarchy | 有 h1/h2… 层级 | github.com/datalab-to/marker README；权重为 modified OpenRAIL-M，商用有门槛（survey_notes.md）；OmniDocBench 71.3（较低） |
| Surya | 版面检测 + 阅读顺序 + OCR | 块类型，无字体 | Marker 的底层；同上许可 |
| LayoutParser / DocLayout-YOLO | 只做版面块检测（框+类别） | 无层级、无文字 | 需自配 OCR；作组件用 |
| olmOCR（Ai2） | 输出 markdown 线性文本 | markdown 标题 | 约 7B，本机显存不够（survey_notes.md）；OmniDocBench 81.79 |
| Azure Document Intelligence Layout | paragraphs 带 role（title/sectionHeading/pageHeader/pageFooter/footnote…），可出 markdown | 只有 title/sectionHeading 两档，无多级 | learn.microsoft.com …/prebuilt/layout；约 $1.5/千页起（survey_notes.md，未确证实时价） |
| Google Document AI Layout Parser | 块 + 标题层级 chunk | 有层级 | 云；未细查 |
| Adobe PDF Extract API | structuredData.json：elements 按阅读顺序，路径含 H1/H2/H3、P、Figure、Table | 有标题层级；`includeStyling` 可出字体、字号、粗斜体（但只取首字符字体） | developer.adobe.com/document-services/apis/pdf-extract/；对原生 PDF 最接近"Word 样式"，云端收费 |
| ABBYY FineReader | 导出 docx 保留样式；FineReader Engine/XML 有块与字体 | 有样式 | 德文实测内嵌 FR11 层错误率 53%（docs/ocr_tool_survey.md），老版本不可靠 |

约束：仓库设计规定未发表资料默认不上传云 API（docs/ocr_eval/survey_notes.md 末节），Azure/Google/Adobe 只能用于已出版、可公开的书。

### 4.4 判断
- 原生书（Handbook 四卷）：最准的格式就在 PDF 里，不需要任何 OCR 或云 API。【确证】
- 扫描书：PaddleOCR-VL 已够给块类型；标题多级、粗斜体仍要靠规则（编号、分类阶元词）+ 页图量测补。MinerU、Docling 能给更多层级，值得在 1 本扫描书 20 页上与 VL 对比一次再决定【推测】。

## 5. 建议（按优先级；先用已有功能）

1. **把原生 PDF 的字体与层级并入 aligned**（新命令，例如 `booklayout native-aligned` 或扩展 `align-md`）：每块带 role、level、原字号、粗斜体；层级用 字体+编号+书签 三线索（复用 fontlevels.py、probe.py、contents.py）。Handbook 立刻受益，也是走 booklayout 的前提。→ **先在 #60/#61 下评论或新开 issue**。
2. **正文/图注/检索表/文献改成 Word 命名样式**（Body、Caption、Key、Ref…），profile 改一项、`restyle` 秒级全书生效，补齐用户要的"像 Word 一样改样式"。builder.py:617-636 的 para() 是改动点。→ **需 issue**（可挂 #27）。改后加测试：restyle 前后正文字号变化、目录页码仍对。
3. **make 加快速路径**：只改译文/样式时跳过 source-check（原文 OCR 比对，占时最多），只跑 build→map-pages→build→qa；发布前再全闸口。可省约 75% 时间（§3.4）。→ **需 issue**。
4. **Handbook 迁到 booklayout**（#62 验收）：在 1 做完后，用 Handbook 第一卷试排，对比现 build_docx.py 成品。不做之前，§1–3 的能力用不到 Handbook。→ 已有 #62；动排版前按 Handbook 规定先请用户确认。
5. **扫描书对比试验**（可选）：同一扫描书 20 页跑 PaddleOCR-VL / PP-StructureV3 / MinerU / Docling，比较标题层级与块类型，结果记 docs/ocr_eval/LEDGER.tsv。→ 先列入 ocr_tool_survey.md 候选表，不必 issue。

另：`tests/test_docstore_structdoc.py:200` 测试先于实现（figure_no_order 未实现），**应报 issue**。
StructDoc 不建议改成排版入口：它已定位为派生视图（spec 原则 1），把层级和样式类加进 aligned 更直接【推测，供用户裁定】。
