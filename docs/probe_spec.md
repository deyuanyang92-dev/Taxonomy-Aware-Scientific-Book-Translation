# docstore probe / 标题分级 / 章界回退 / Handbook 验收 设计说明（issue #59–#62）

2026-11-26 调研（Opus，只读）。本文件是给 Sonnet 并行执行的规格；未经用户同意不扩范围。

## 0. 调研实测（Handbook_Annelida 7 个 PDF，每本抽 2 页，PyMuPDF load_page）

| 文件 | 页数 | 书签 | producer | 抽样页 | 结论 |
|---|---|---|---|---|---|
| Greg_Annelida_2022.pdf | 448 | 4（1-80@1…） | KONICA MINOLTA bizhub C658，title=SKM_C658… | 0 字，整页图 1.06 页面积 | 纯扫描 |
| Vol1 Basal groups… | 484 | 2（Cover003@1、Libro completo@1） | Adobe Acrobat Pro 9.0.0 | 5679 字，双栏 x0=62/309 | 原生，书签不可用 |
| Vol2 / Vol3 / Vol4 | 476/493/500 | 15/28/30，全为 level 1 | iTextSharp 5.0.6 | ≈5000 字，双栏 x0=51或62/298或309 | 原生 |
| 两份中译 | 8 / 2137 | 0 | Microsoft Word 2019 | SimSun/TimesNewRoman 10.6pt | 原生单栏 |

字体实测（Vol4 p151、Vol2 p143、Vol3 p148）：正文 DGMetaSerifScience 9.5pt（衬线）；节标题 `7.13.1.5.2 Sigalionidae…` 为 DGMetaScience-Bold 12pt；
小节标题 Introduction/Morphology/Taxonomy、`Family Trochochaetidae Pettibone, 1963` 为 DGMetaScience-Bold **9.5pt（与正文同号）**；
run-in 标签 Diagnosis:/Remarks:/Type species: 为 DGMetaSerifScience-Bold 9.5pt；页码 `139` 亦为 DGMetaScience-Bold 9.5pt；图注 8pt DGMetaScience。
字体名带子集后缀（Bold5、Regular10、Regul 截断）。⇒ **只按字号分级不够，必须用「族(无衬线/衬线)+粗体+字号」组合**。

现有代码在 Handbook 上的实测问题（已确证，命令见 §5）：
- `booklayout/pdffigures.py:44-48` CAPTION_RE 对 `Fig. 7.11.2.3:` 取得 label=`7`（四级图号被截断）；`audit_manifest` 第 200-201 行会把全章图判为重复 label。
- `booklayout/contents.py:17` `_ENTRY` 要求点引导线，Vol3 目录页（PDF p7）`parse_contents` 得 **0 条**；该页格式为 `7.4\t\nSedentaria…\n 1`（章号、标题、页码分行，无引导线）。
- `scripts/chapter_split.py:159` `if len(bm) >= 2` 在 Vol1 上成立（2 条书签），`_chapters`（:128）按页去重后只剩 1 章，chs 非空 ⇒ **永不回退到目录页**，这是 #61 的直接根因。
- Vol3 书签全是 level 1，但标题自带 `7.7.1` 编号；印刷页 1 = PDF p13（偏移 +12，由书签 `7.4…@13` 与目录 `7.4 … 1` 对照得出）。

## 1. 复用 / 新增清单

直接复用（不复制代码）：
- `docstore/textify.py:19` MIN_CHARS=30；`:21` OCR_LAYER_PRODUCERS；`:74-94` layer_is_ocr(meta, pdf)（整页图 ≥80% 面积）。
- `docstore/classify.py:69` guess(path) → kind/lang/key；`:51` guess_lang(text)。
- `docstore/layout.py:56` _find_gutter(boxes) 与文件头常量 MID_BAND/MIN_SIDE/GUTTER_MIN_FRAC；行框格式 [[4 角点], text, score]。
- `booklayout/nativefonts.py:13` span_style(span) → (italic, bold)（flags 位 + 字体名正则 :9-10）。
- `booklayout/furniture.py:80` detect_furniture(pages)，输入 {"page","height","lines":[{text,y0,y1}]}（文件头 :21）。
- `booklayout/keygraph.py:30` HEADING_RE（检索表标题）；`booklayout/pdffigures.py:108` page_captions(page)。
- `booklayout/headings.py:78` taxon_level(text)（只用于冲突报告，不改它）。
- `scripts/chapter_split.py` 的 toc_offset(:100)、_chapters(:128)、validate_plan。

依赖方向：booklayout 已 import docstore（booklayout/styles.py），docstore 不得在模块顶层 import booklayout。
docstore/probe.py 只在函数内惰性 import booklayout 的纯模块（nativefonts、furniture、keygraph、pdffigures），失败时相应字段为 null。

新增：
- `docstore/probe.py`；CLI `docstore probe <pdf...> [--sample 5] [--pages 1,7,150] [--json OUT] [--no-fonts]`，不需要 Store（同 split 的分支写法，docstore/cli.py:832）。
- `booklayout/fontlevels.py`；CLI `booklayout heading-levels <pdf> [--pages 13-40] [--json OUT]`。
- `booklayout/contents.py` 新增 `contents_from_pdf_page(page) -> list[ContentsEntry]`（行几何法），原 parse_contents 不动。

### probe 输出 JSON（字段名固定，每本一个对象，列表输出）
```
{"path","sha256_head"(前 1MiB),"pages","producer","creator","meta_title",
 "kind": "native|scan|ocr-layer|mixed|empty", "kind_reason": str,
 "sampled": [{"page"(1基),"chars","cover_image": bool,"page_kind": "native|scan|ocr-layer|blank",
              "columns": 1|2,"gutter": [x0,x1]|null}],
 "bookmarks": {"count","levels":[int],"distinct_pages","first":[[lv,title,page]x≤3],"usable": bool},
 "fonts": {"body": {"family","size","bold","italic"},"top":[{"font","size","chars"}x≤8],
           "sizes":[[size,chars]],"bold_frac","italic_frac"} | null,
 "layout": {"columns": 1|2|"mixed","header_lines":[str],"footer_lines":[str]},
 "features": {"contents_page": int|null,"key_heading_pages":[int],"caption_pages":[int],"caption_labels":[str]},
 "heading_hint": {"numbered": bool,"styles":[{"family","size","bold","example"}x≤5]},
 "classify": {"kind","lang"},"seconds": float}
```
`--no-fonts` 时 fonts/heading_hint 为 null（scan 本自动为 null）。人读模式每本 1 行：`kind 页数 书签n(usable) 正文字体 栏数 文件名`。

## 2. 判定规则（输入 → 输出）

**页级**（sampled 每页）：chars=len(page.get_text().strip())；cover_image=任一 get_image_info bbox ≥0.8×页面积（同 textify:88-93）。
- chars < MIN_CHARS 且 cover_image → scan；chars < MIN_CHARS 无图 → blank
- chars ≥ MIN_CHARS 且 cover_image → ocr-layer；否则 native

**书级**：producer/creator 命中 OCR_LAYER_PRODUCERS 且有字 → ocr-layer；否则按非 blank 抽样页取多数；
次多数类占比 ≥1/3 → mixed；全 blank → empty。kind_reason 写明命中的规则与计数。不另设阈值。

**抽样页**：默认 k=5，取 [0.1n, 0.9n] 均匀分布 + 用户 `--pages`；只用 doc.load_page(i)，不整本遍历。
目录探测另扫前 min(15,n) 页的纯文本（只查 ^Contents|^目录|^Índice|^Inhalt|^Sommaire 行）。

**分栏**：每页取 get_text("dict") 的 line bbox → 行框格式 → layout._find_gutter；有中缝且两侧各 ≥MIN_SIDE 行 → 2，否则 1。
书级：抽样页一致 → 该值，不一致 → "mixed"。

**页眉页脚**：抽样页 lines（y0/y1/height）喂 detect_furniture(min_repeat=min(3, 抽样数))，输出 phrases 前 3 条，分上下带。

**字体**：span 级 chars 加权；family=去 `ABCDEF+` 子集前缀，去尾部数字（Bold5→Bold）；body=chars 最多的 (family,size)。

**标题字号分级（fontlevels.py，#60）**
- 输入：fitz 页列表；输出 `[{"page","text","level","style":{family,size,bold},"number":"7.4.1"|null,"source":"number|style","conflict":str|null}]` + `ladder:[{family,size,bold,level,count}]`。
- 候选行：整行 1 个样式且 ≠ body 样式，满足 size ≥ body×1.15，或 (bold 且 family 的无衬线/衬线属性与 body 不同)；
  排除：纯数字/罗马数字（页码）、长度 >120、以冒号结尾的 run-in 标签（Diagnosis:）、furniture 行。
- 编号：`^(\d+(?:\.\d+)+)\.?\s+\S` → number，深度=段数；`7.13.1.5.2` 深度 5。
- 样式梯度：候选样式按 (size 降序, bold 先) 排序编 1..n。
- 合并：有编号时 level=编号深度−min_depth+1（source=number）；无编号用样式梯度（source=style）；二者不一致写 conflict。
- 与 taxon_level(text) 不一致也写 conflict（"taxon=1 vs style=3"），不覆盖。

**章界回退（#61，改 chapter_split.py）**：书签 usable 判定 = 去重起始页数 ≥2 且 >50% 起始页 ≠ 首页；否则回退：
contents_from_pdf_page（行几何：右侧页码行 = 行末 token 是数字且 x1 ≥ 栏右界−15pt；向上合并无页码行为标题；行首 `\d+(\.\d+)*` 为章号，level=段数−1）
→ toc_offset 求偏移 → plan.chapters[].source = "bookmarks|contents|headings|single"，plan 写 "chapter_source"。

## 3. 任务拆分（T1–T4 可并行；T5 依赖 T1–T4）

| 任务 | 只改/建文件 | 签名 | 验收 |
|---|---|---|---|
| T1 docstore probe (#59) | 建 docstore/probe.py、tests/test_docstore_probe.py；改 docstore/cli.py | `probe_pdf(path: Path, sample: int = 5, pages: list[int] \| None = None, fonts: bool = True) -> dict`；`page_kind(page) -> dict`；`book_kind(meta: dict, sampled: list[dict]) -> tuple[str, str]`；`cmd_probe(a)` | `python3 -m pytest -q tests/test_docstore_probe.py tests/test_docstore.py` |
| T2 标题分级 (#60) | 建 booklayout/fontlevels.py、tests/test_booklayout_fontlevels.py；改 booklayout/cli.py（加 heading-levels） | `body_style(pages) -> dict`；`heading_candidates(page, body) -> list[dict]`；`number_depth(text) -> tuple[str, int] \| None`；`assign_levels(cands) -> dict`（含 ladder、conflicts） | `python3 -m pytest -q tests/test_booklayout_fontlevels.py tests/test_booklayout.py` |
| T3 四级图号 (#62 子项) | 改 booklayout/pdffigures.py（仅 CAPTION_RE）；建 tests/test_booklayout_pdffigures_multilevel.py | label 改为 `[0-9]+(?:\.[0-9]+)*[A-Za-z]?(?:\s*[-–,]\s*[0-9]+(?:\.[0-9]+)*[A-Za-z]?)*[’'′]?`，末尾冒号不入 label | `python3 -m pytest -q tests/test_booklayout_pdffigures.py tests/test_booklayout_pdffigures_multilevel.py` |
| T4 章界回退 (#61) | 改 scripts/chapter_split.py、booklayout/contents.py；建 tests/test_chapter_split_fallback.py | `bookmarks_usable(bm, first) -> bool`；`contents_from_pdf(pdf: Path, scan: int = 15) -> list[tuple[str, int, int]]`（标题,印刷页,level）；`contents_from_pdf_page(page) -> list[ContentsEntry]` | `python3 -m pytest -q tests/test_chapter_split.py tests/test_chapter_split_fallback.py tests/test_booklayout_contents.py` |
| T5 Handbook 验收 (#62) | 建 tests/test_handbook_acceptance.py（skipif 文件缺失；env HANDBOOK_DIR） | 只读；结果用 `gh issue comment 62` 发表，不写盘 | 见 §4 只读验收命令 |

所有任务完成后：`ruff check docstore booklayout scripts/chapter_split.py`、`mypy docstore/probe.py booklayout/fontlevels.py`、全量 `python3 -m pytest -q`。
T1/T2 不改 headings.py、nativefonts.py、textify.py、layout.py（只 import）。
git status 中已有他人改动的文件（如 scripts/apply_issues.py、tests/test_apply_issues.py）任何任务都不得触碰。

## 4. 小测方案（不依赖大文件、不联网）

各测试用 PyMuPDF 在 tmp_path 合成（写法同 tests/test_booklayout_pdffigures.py:_make_pdf；reportlab 4.4.10 已装，非必需）：
1. 原生 1 页：insert_text 若干行（≥30 字）→ kind=native，columns=1。
2. 纯图片 1 页：Pixmap 填色后 insert_image 覆盖全页、无文字 → scan。
3. 图片+隐形文字 1 页：全页图 + insert_text(render_mode=3) → ocr-layer；另测 producer 置 "ABBYY FineReader" 的原生页 → ocr-layer。
4. 双栏 2 页：左右两栏各 ≥5 行（x=50 与 x=310），页眉 "Handbook of Zoology" 与页码 → columns=2，header_lines 含该页眉。
5. 带书签：set_toc([[1,"Cover",1],[1,"Libro completo",1]]) → usable=False；正常 3 章书签 → usable=True。
6. fontlevels：同页用 "helv"(无衬线) 粗体 12pt 写 `7.4.1 Fabriciidae`、粗体 9.5pt 写 `Introduction`、"tiro" 9.5pt 正文、粗体 `Diagnosis:` run-in、页码 `139` → 前两行为候选（level 3 编号、样式级），后两者排除；
   `Family Sabellidae` 样式与 taxon_level 不一致时 conflict 非空。
7. 目录页：按 Handbook 格式分行写 `7.4` / `Sedentaria: Spionida` / `1`（右对齐），contents_from_pdf_page ≥2 条且 level 正确。

只读 Handbook 抽样验收（T5，≤30 页）：
```
cd /mnt/p/翻译-译作/Taxonomy-Aware-Scientific-Book-Translation
python3 -m docstore.cli probe /mnt/p/翻译-译作/Handbook_Annelida/*.pdf --sample 3          # 7 本×3 页
python3 -m booklayout.cli heading-levels "/mnt/p/翻译-译作/Handbook_Annelida/Handbook of Zoology-Annelida-Volume3.pdf" --pages 13-40
HANDBOOK_DIR=/mnt/p/翻译-译作/Handbook_Annelida python3 -m pytest -q tests/test_handbook_acceptance.py
```
期望：Greg=scan；四卷=native、columns=2；Vol1 bookmarks.usable=false；Vol3 目录 p7 ≥10 条、偏移 +12；p296 caption label=7.11.2.3。
耗时预估：本次热缓存实测每本 0.1–1.2 s；冷读 /mnt/p（9P）此前 7 本×3 页约 116 s。上限按 ≤3 分钟计。

## 5. 风险与未确证项

| # | 内容 | 状态 | 依据 |
|---|---|---|---|
| R1 | 四卷标题大多与正文同号 9.5pt，只靠字号分级会漏 | 已确证 | §0 字体实测 Vol2 p143、Vol3 p148、Vol4 p151 |
| R2 | CAPTION_RE 截断四级图号 | 已确证 | 本次 `CAPTION_RE.match("Fig. 7.11.2.3: …").group("label")` = "7" |
| R3 | contents.parse_contents 对 Handbook 目录 0 条 | 已确证 | Vol3 load_page(6) 实测 entries=0、leftover=161 |
| R4 | chapter_split 书签 2 条同页时不回退 | 已确证 | scripts/chapter_split.py:159 与 :128-131 去重逻辑 |
| R5 | 改 CAPTION_RE 影响 Fauna Iberica 等旧书的 label | 未定 | 新正则对 "Fig. 12"、"Figs. 3-5" 应不变，需回归 tests/test_booklayout_pdffigures.py |
| R6 | 无衬线/衬线判定靠字体名（含 Sans/Serif/Arial/Helvetica/Times…）对其他出版社是否通用 | 推测 | 仅在 DGMeta*、Word 输出上见过；fitz flags 位 4(serif) 可作第二证据，未实测 |
| R7 | 隐形文字（render_mode=3）的 OCR 层能被 get_text 读出 | 推测 | PyMuPDF 通常提取 invisible text；T1 测试 3 将确证 |
| R8 | 116 s 主要是 /mnt/p 冷读，非 PyMuPDF 计算 | 推测 | 同 7 本本次 0.1–1.2 s/本（热缓存）；未测冷读 |
| R9 | probe 内惰性 import booklayout 被视为违反「docstore 不依赖 booklayout」约定 | 未定 | docstore/structdoc.py:4 只对该模块声明；需用户确认，或把 features 字段移到 booklayout |
| R10 | Vol1 目录页位置与格式与 Vol3 相同 | 未定 | 只实测了 Vol3 p7 |
| R11 | furniture 在双栏页的带宽 0.1 适用 | 未定 | 未在 Handbook 上跑 detect_furniture，T5 验收 |

## 6. 可贴给 /goal 的目标

```
在 /mnt/p/翻译-译作/Taxonomy-Aware-Scientific-Book-Translation 按 docs/probe_spec.md 完成 T1–T5（issue #59–#62）。
T1–T4 各派一个 Sonnet 并行，只改各自表内文件；T5 等 T1–T4 全绿后做。不得碰 git status 里他人已改的文件。
完成判据：
1) python3 -m pytest -q tests/test_docstore_probe.py tests/test_booklayout_fontlevels.py tests/test_booklayout_pdffigures_multilevel.py tests/test_chapter_split_fallback.py 全过；
2) 全量 python3 -m pytest -q 无新增失败；ruff check、mypy 新文件无报错；
3) docstore probe /mnt/p/翻译-译作/Handbook_Annelida/*.pdf --sample 3：Greg=scan，四卷=native 且 columns=2，Vol1 bookmarks.usable=false；
4) Vol3 heading-levels --pages 13-40 给出 7.x 编号层级与样式梯度，冲突单独列出；
5) Handbook 验收结果（通过/失败逐项）以 gh issue comment 62 发表，失败项另开 issue；
6) 每个 issue 写明用了哪些现有函数、新增哪些文件与测试。用户确认前不 push。
```
