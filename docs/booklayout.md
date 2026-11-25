# booklayout：对齐译文到成书（DOCX/PDF）

`booklayout` 把翻译流水线产出的对齐 JSON 排成书：扉页、摘要、作者、目录、正文、图与图注、检索表、文献、附录、索引。它是确定性脚本，模型只负责提供对齐数据和元数据，不手工拼接 DOCX。

## 安装

```bash
pip install -e .
booklayout --help
```

依赖：`python-docx`（DOCX）、`pymupdf`（页映射和检查）、LibreOffice（只在 `--pdf` 时调用）。

可选 preview 依赖：`pip install 'weasyprint>=62'`（HTML→可选 DRAFT PDF）；Typst 引擎需本机 `typst` 二进制（未装时请用 `--engine html`，HTML 小样不依赖 typst）。

## preview（非交付）与三阶段工作流

成书必须走：**小样排版 → 大模型核验 + 用户核验 → 通过后才正式批量排版/交付**。短说明见 [`docs/preview_workflow.md`](preview_workflow.md)。

| 阶段 | 做什么 | 产物落点 |
|------|--------|----------|
| **A 小样** | `booklayout preview`（`html`\|`typst`，真图，标 **DRAFT**）；按小样改对齐 JSON | 仅 `work/` 临时目录 |
| **B 核验** | 模型：`audit` / `keys-check` / `layout_invariants` + 对照原 PDF 抽查乱码；**用户看小样确认** | 报告/问题单；仍不交付 |
| **C 正式** | 仅当 `booklayout verify` **全绿** 才 `build` 全书 Word/PDF 并拷入交付目录 | 交付目录 |

硬约束：迭代期**禁止**往交付目录刷半成品；小样只在 `work/` 临时目录。`preview` **不算交付**，不替代 `verify` / `build --pdf`。正式成书仍走 DOCX→LibreOffice；`verify` 未绿仍禁止正式 PDF/DOCX。

```bash
# HTML（默认；浏览器打开 index.html）
booklayout preview \
  --aligned aligned.json --figures figures/ \
  --pages 129 --engine html \
  --out work/tmp_preview_p129/

# 可选 Typst（需已安装 typst；失败则改用 html）
booklayout preview \
  --aligned aligned.json --figures figures/ \
  --pages 5-6 --engine typst \
  --out work/tmp_preview_keys/
```

切片写入 `aligned_slice.json`；HTML 用真实 `figures/` crop（经 `source_figure_audit.json`），检索表复用 `split_key_couplet`（中文|拉丁同右栏）。产物含 `DRAFT` 横幅与 `preview_meta.json`（`delivery: false`）。

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

`booklayout build`、`qa`、`check` 都要求该目录存在 `source_figure_audit.json`；路径写错时直接报错退出，不再静默排成无图的书。

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
| `index_entry_fixes` | `[[源索引文字, 改正文字, 依据], ...]`：原书索引的排印错误（错属名、漏字母）。改正后按页核实；被改条目在索引里加 †，书末自动生成 `CORRECTIONS TO THE ORIGINAL` 页，第三项依据可省略 |

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

## 确定性修版（normalize / repair）

对齐数据先过确定性规则，再排版。`normalize` 只处理可判定的结构错误，模型不逐页改写：

```bash
booklayout normalize --aligned aligned.json --out aligned_norm.json \
  --report normalize_report.json
```

规则覆盖：检索表页整体错位、图注重复、缩写表角色与顺序、图版字母残尾、标题与引文粘连、引文混入描述正文、模式种尾段回收、西班牙语作者连接词 `y`、小写段落碎片合并、图注西班牙语来源词、被源书分页切断的正文段（同一章内，前页末段不以句末标点结束、后页首段以小写字母开头，则合并；断词连字符结尾的留给人工），以及两类跨页重复：整节译文吞并后续页（`overflow_duplicate_tail`，只在译文超过原文 1.6 倍时判定，避免把分类描述惯用语误当重复）和正文段落内又嵌入本页条目表与检索表（`embedded_duplicate_list`，要求连续三个前序条目的译文按序出现）。每条改动写入报告，可逐条复核。

个别页面仍需人工判定时，用 `repair` 的声明式补丁，按 `block_id` 改角色或译文，保留原有几何信息：

```bash
booklayout repair --aligned aligned.json --patch patches.json --out aligned_fixed.json
```

补丁格式：`{"pages": {"352": [{"block_id": "p352_b11", "role": "body", "translation": "..."}]}}`。条目可带 `level`（标题层级）；页面里未列出的块会被删除，所以重建整页时要把该页全部块按顺序列出。

整页重建会丢掉块的源文（`text`）和坐标，源文规则和拉丁名斜体因此失效。补回用 `backfill-source`，按 `block_id` 从 `source_structure.json` 复制 `text`、`x0/y0/x1/y1`、标题层级；源书没有的合成块会列入报告的 `unmatched_blocks`：

```bash
booklayout backfill-source --aligned aligned_fixed.json \
  --source source_structure.json --out aligned_full.json --report backfill_report.json
```

只改一两个块（改译文、改角色、删块）用 `patch-blocks`，不必重写整页：

```bash
booklayout patch-blocks --aligned aligned.json --patch edits.json --out aligned_edited.json
```

格式：`{"edits": [{"block_id": "p277_b00", "translation": "..."}, {"block_id": "p277_b01", "remove": true}]}`。

乱码/坏段对照原书页修块：先 `extract-blocks` 抽出（源文、坏译文、docstore 页图或 PDF 渲染、OCR），模型改完再用 `patch-blocks` 写回：

```bash
booklayout extract-blocks --aligned aligned.json --doc-key Imajima2001 \
  --block-ids p326_b08,p010_b13 --out-dir garble_packs/
booklayout patch-blocks --aligned aligned.json --patch edits.json
```

## 检索表页重切（key-align）

检索表页没有标题、引文、条目这些锚点，一行错位就会让整页每对条目都错，而字数覆盖率查不出来（文字没丢，只是串位）。`key-align` 从译文 markdown 的整页文本按源文行末的页码/条目号重切：

```bash
booklayout key-align --aligned aligned.json \
  --translation translation.md --out aligned_key.json --report key_report.jsonl
```

判据：每条源文行以 `(p. N)`、`Author (Year)`、条目号或末词结尾，译文对应位置也应出现同一锚点；行首丢失的 `•` 在上一行锚点之后补找；行尾脚注按脚注号重切，最后一条脚注用后文标题/引文锚点截断，避免吞并下一节。未能重切的页在报告里给 `anchor not found`，不猜。

检索表**文字也要排版**：每条须能 `split_key_couplet` → `tabbed`（左栏特征 + 点线 + 右栏目标）。拆不开就只是左对齐散文。越改越差的原因与作业规程见 `docs/keys_layout_lessons.md`；根目录一次性 `tmp_*keys*` 已归档，勿再当正式入口。

## 检索表偶句重建（OCR 行框 → keys.json → apply-keys，issue #38）

日文等无法靠译文对位的检索表，不从译文反推结构，而从原书 OCR 的行框重建：条目号框、正文框、右栏终点框的位置本身就说明了谁是条目号、谁是跳转号或学名。三步，全部是脚本，零 token：

```bash
# 1. 行框 → 偶句（语法 G1–G9 在 docstore/rules/keys.toml；终点缺失、续页、插图版打断等见 docstore/keys.py）
docstore keys extract --cache <行框缓存目录> --last <页数> --out keys_auto.json --fix keys_fix.json
# 2. 偶句描述抽成侧表，翻译（Google 初稿 + DeepSeek 核译，术语表和学名表注入），回收到 keys_<语言>.json
python3 scripts/keys_translate.py prepare keys_auto.json --out-dir keys_tr
python3 scripts/keys_translate.py collect --items keys_tr/items.json --tr keys_tr/<语言>/checked.md --lang <语言> --out keys_tr/keys_<语言>.json
# 3. 用偶句块重建检索表页，审计后排版（审计有缺陷时退出码 1；--allow-defects 放行并写入 keys_apply.json）
booklayout apply-keys --aligned aligned.json --keys keys_auto.json --tr keys_tr/keys_<语言>.json --lang <语言>
```

`docstore keys check` 按表检查自洽：条目号连续、每个跳转号都落在本表的某个条目、每个条目有终点、每个条目号有备择条目。OCR 本身丢框（终点数字漏掉、横线框漏掉、图号少一位）的残留缺陷，只能对照页面图像人工核对后写进 `keys_fix.json`（`set`/`drop`/`add`，每条必须写 `why`，匹配必须恰好一条，提取器改进后旧补丁失效会报错而不是静默套错位置）。`apply-keys` 每次都从 `keys.json` 重建整页，重复运行结果不变。

## 其他确定性修版规则

- `structured_from_source`：标题/引文/条目块的译文串入邻段时，用源文重建（拉丁名、作者、年份、卷:页与语言无关；只替换西班牙语结构词和连字）。附录页的 `entry` 不在此列，由下一条规则统一处理。
- `appendix_entry_*`：附录异名表的条目只按源文判定。空译文按源文补齐；以括号、方括号、小写词、`suprimida`/`Oficial de` 等开头的块是上一条的折行尾，拼回上一条（译文里已有同样内容则丢弃，防重复）；源文有年份而译文缺年份、且明显更短，判为错配的邻行，用源文重建；译文开头重复了上一条整行时删去该前缀。`? Nereis phasma` 的问号保持正体，只有属种名斜体。状态短语（`grafía posterior incorrecta`、`colocado en la Lista Oficial...`、`Oficial de Nombres de Nivel...` 等）在换行处被切断时也按整句翻译，`Género`/`Especie` 的类群词替换放在状态短语之后，避免打断整句匹配。
- `function_word_join`：跨页拼接造成的虚词重复或错配（`in with`、`in in`）按语法修复。
- `leading_punctuation` / `key_leading_target`：分页切走的标点归位；检索表行首残留的上一行目标（`… (p. 185) •`）删除。

## 三审三校（脚本化）

交付前依次跑三审，全部由脚本判定，不靠目测：

```bash
booklayout qa \
  --aligned aligned.json --figures figures/ \
  --pdf final/book.pdf --metadata metadata.json --out final/qa.json
```

| 审次 | 检查内容 | 失败示例 |
|---|---|---|
| 一审 结构 | 未译内容块、缺裁剪图、图注无图号、超长标题、缩写表混入正文、全大写正文、**严格检索表格式**（必须可拆左栏+右目标、禁并条、禁丢标记、目标合法） | `key_audit.format_ok == false`、`keys-check` 退出码 1 |
| 二审 版式 | PDF 空白页、图注贴图、回退字体、两端对齐造成的超宽词距、文字越出版心、目录/索引页码指错页、检索表目标未右对齐/目标被拆行、图注把一个词拆到下一行 | `wide_spacing`、`overflow_words`、`wrong_page_refs`、`key_layout`、`caption_word_breaks` |
| 三审 文字 | **强制深检**全可印角色（`body/caption/entry/note/heading/citation/key/ref`）；覆盖率不足即失败；短译/过长合并/截断/串角色/U+00A0/行末孤儿连字符/缺年份/西语残留 | `coverage`、`short_translations`、`oversized_translations`、`bad_nbsp`、`orphan_hyphen`、`key_text_outside_key`、`spanish_residue` |

无 PDF 时也可先跑静态审计（检索表 + 各角色文字）：

```bash
booklayout audit --aligned aligned.json --metadata metadata.json --out final/audit.json
```

**正式交付唯一推荐入口（严格，缺一不可）：**

```bash
booklayout verify \
  --aligned aligned.json --figures figures/ --pdf book.pdf \
  --metadata metadata.json --out-dir final/verify/
# 退出码 0 且 verify.json ok=true 才算过关
```

内部依次跑：`keys-check` → `qa`（必须有 PDF）→ `check --strict` → `key-report` → `gate`。
任一步失败即整单失败。试译可用 `qa --draft` / 不带 `--strict` 的 check，**不得称正式交付**。

另：`delivery_gate.py --tier release` 默认硬拦 `check_failed` 未清空，且必须提供 qa/check/key-report + key-audit（或 aligned）。

### 模型问题 → 脚本闭环（强制）

大模型/核译/人工发现问题后，**不得只改这一本书的 aligned 就完事**。先跑：

```bash
python3 scripts/mine_script_gaps.py \
  --audit final/audit.json --check final/check.json \
  --qa-issues work/en/qa_issues.json \
  --revise-issues work/en/revise_issues.json \
  --aligned final/aligned.json \
  --out-dir final/script_gaps
```

产物：`gaps.json`（归因）、`backlog.md`（P0 漏检 / P1 已检出待修）、`fixtures/`（最小回归样例）。
`uncovered`（模型报了排版类问题、当前检测器却扫不到）退出码为 1：先改 `booklayout`/`transqa` 并补测试，再重建。

三校对应三次确定性关口：一校对齐数据（`normalize` 报告逐条复核 + `audit`/`qa` 一审的 `key_audit`）；二校 PDF 版式（`qa` 二审）；三校文字（`qa` 三审）。
一审把"会印进书里的页"上缺译的图注判为内容缺失：构建器遇到空译图注会省略图注、只印图，因此这种图注不能按语言中性块放行。`body_start_page` 之前的前置页、`skip_after_page` 之后和索引章不印，空图注不计。文献引证（`citation`）一般语言中性，原样保留；若引证以大写西班牙语字段名开头（如 `ESPECIE TIPO:`），字段名仍需翻译，一审同样判缺失。

排版本身已固定：正文 10.5 pt 两端对齐，启用 `w:autoHyphenation`、`w:consecutiveHyphenLimit=2`、`w:hyphenationZone=357`，并写入 `w:proofState spelling="clean" grammar="clean"`。LibreOffice 需要 `hyphen-en-us` 词典；缺词典时 PDF 会出现超宽词距，二审会报 `wide_spacing`。二审以 9 pt 为词距上限（10.5 pt 字号、134 mm 版心中约 3.5 个正常空格），超过才判失败；8–9 pt 属正常两端对齐伸缩，不阻断交付。

检索表排版规则：左栏 + `\t` + 右目标（`split_key_couplet` → `tabbed`，右缘点线制表位）。编号/圆点缩进 4 mm；译文丢点线时用源文末尾目标强制拆栏。过长条目目标整行右移，不把目标粘在省略号后。图注左对齐、禁断词。`qa`/`audit` 拦拆不开的 couplet 与 PDF 未贴右缘；短译文/串行同样失败。

检索表跳转图（`booklayout/keygraph.py`，并入 `keys-check`）：按章/「回到 1」分段，检查悬空跳转、缺对偶（含 `1.`/`—`/`一`/无标记备选与 `19.`/`20.` 顺号对）、欧式 `1(2)` 对偶缺失、跳转成环。`format_ok` = 能否拆栏；`graph_ok` = 跳转图；严格模式 `ok` 二者都要。不编表、不判特征语义。

阶元体例：只有属名、种名、亚种名（含亚属名）斜体；科、亚科、族、总科（-idae/-inae/-ini/-oidea）和目、纲、门等科级以上阶元正体，命名人、年份、`sp./spp./cf./aff.` 也正体。原书把科名排斜体（Vol. 45 p. 7 作者名单），英文版不照搬：`build_genus_set` 不再收科名，`add_runs` 把译者星号圈住的科名和斜体底段落（作者名单页）里的科名改正体，`scripts/italic_check.py` 的 `italic.higher_taxon` 为 `major` 并可用 `--fix` 更正。`booklayout verify` 含 `taxostyle` 步并写入 `italic_audit.json`；`gate --italic-audit` 对 major/critical 硬拦（#33）。细则见 `docs/taxonomic_typography.md`。

原书索引偶尔排错：属名写错（`arietina, Apomatus` 实际是 *Ditrupa arietina*）、漏字母（`cristaventalis` 实际是 *cristaventralis*）、大小写变体（`(LEICHONINI)` 实际是 Leiochonini）。这类条目用元数据 `index_entry_fixes` 声明改正，索引按改正后的名字重映射页码并接受 `qa` 核对；改正后重复的行只印一次。原书正文的连字（`ﬂ`）由 `match_text` 做 NFKC 折叠，斜体标记 `*...*` 在页映射前去掉，否则带斜体的条目会漏掉块页码。

附录排得比西班牙文原书密，`map-pages` 不能用「源书一页对成品一页」推算附录页码：它以印刷的 APPENDIX 标题为下界，逐页用该页译文匹配成品 PDF，匹配不到才回退估算。源书一页常跨成品两页，索引里按源页换算的页码可能落在名字出现之前；`map-pages` 同时记录每个块自己的起始页（`block:<block_id>`），索引重映射时先在该源页的块里找到条目名，用块页码，找不到才用页起始页。索引固定排在全书最后，所以目录里索引条目也放在最后，与正文印刷顺序一致，即使源书把 Annex 之类排在索引之后。

章标题默认另起一页（`heading_in_flow: false`）。元数据里把 `heading_in_flow` 设为 `true` 会让章标题接在目录或上一章末尾，只适用于内部校样，不用于出版稿。源书章节交界页常先有上一章的尾段，再出现新章标题；构建器把新章标题插在该页源标题的位置，尾段仍归上一章，不把尾段排到新章标题之下。卷首页目录由 `map-pages` 的结果自动生成，源书前置页里的目录页（`body_start_page` 之前）不重复排版。

## 速度

一次成书只需三遍命令：`build`（第一遍）→ `map-pages` → `build`（第二遍）。三本 450–640 源页的书，第一遍约 60–110 秒，第二遍相近；不要每改一行就重排全书。先用 `normalize`/`repair` 改对齐 JSON，再重排；版式问题用 `qa` 定位到具体页，不要逐页翻 PDF。

## 验收与低能力模型操作

低能力模型只执行命令，不改 `booklayout` 代码：

1. 先跑 `booklayout check`，把 `untranslated_blocks`、`missing_crops` 原样报告。卷首有前置页时 `check` 必须带 `--metadata`：不带时 `body_start_page` 退回 1，源书目录页会被误判为正文长标题。带 `--source <source_structure.json>` 时逐页比较源文与译文字数：会印出的页若保留下来的译文不足源文的四分之一，判为整页缺译（对齐脚本可能把整页压成一个块，数据本身看不出缺口）。
2. 只有 `ok: true` 才能宣布排版完成；`yzz.py zh check` 仍须另外运行。`check` 同时核对 PDF 是否真的嵌入了图：图目录有审计记录而 PDF 一张图都没有时判失败（`--figures` 指错目录、排版时静默跳过全部插图都会在这里暴露）。
3. 两遍排版后，`map-pages` 的 `entries` 应覆盖正文起止页；目录和索引页码用抽查页核对。
4. 失败时保留 `build_report.json`、`check.json` 和命令原文，不手工改 DOCX/PDF。

## 退出码

- `0`：成功，或 `check` 无问题。
- `1`：`check` 发现问题。
- 其他非零：参数、输入文件、LibreOffice 转换失败。

## 交付复盘（2026-11-17）

三卷交付后的根因复盘见 `docs/research/2026-11-17/booklayout-delivery-postmortem.md`。已落地：三审覆盖 `body/caption/entry/note`；短译文与截断计入失败；`key_audit` 在对齐 JSON 上静态拦检索表；`gate` 硬读这些字段。`zh check` 仍须另外运行；`ok: true` 仍不覆盖语义对错，只证明排版可控缺陷已清。
