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
| `index_entry_fixes` | `[[源索引文字, 改正文字], ...]`：原书索引的排印错误（错属名、漏字母），改正后才按页核实 |

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

## 检索表页重切（key-align）

检索表页没有标题、引文、条目这些锚点，一行错位就会让整页每对条目都错，而字数覆盖率查不出来（文字没丢，只是串位）。`key-align` 从译文 markdown 的整页文本按源文行末的页码/条目号重切：

```bash
booklayout key-align --aligned aligned.json \
  --translation translation.md --out aligned_key.json --report key_report.jsonl
```

判据：每条源文行以 `(p. N)`、`Author (Year)`、条目号或末词结尾，译文对应位置也应出现同一锚点；行首丢失的 `•` 在上一行锚点之后补找；行尾脚注按脚注号重切，最后一条脚注用后文标题/引文锚点截断，避免吞并下一节。未能重切的页在报告里给 `anchor not found`，不猜。

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
| 一审 结构 | 未译内容块、缺裁剪图、图注无图号、超长标题、缩写表混入正文、全大写正文 | `untranslated_content_blocks > 0` |
| 二审 版式 | PDF 空白页、图注贴图、回退字体、两端对齐造成的超宽词距、文字越出版心、目录/索引页码指错页、检索表目标未右对齐/目标被拆行、图注把一个词拆到下一行 | `wide_spacing`、`overflow_words`、`wrong_page_refs`、`key_layout`、`caption_word_breaks` |
| 三审 文字 | 同页重复段落、引文/条目块混入描述性长文、译文过短、句末截断、附录条目缺源文年份、西班牙语状态语残留 | `role_suspects`、`truncated_endings`、`entry_year_missing`、`spanish_residue` |

三校对应三次确定性关口：一校对齐数据（`normalize` 报告逐条复核）；二校 PDF 版式（`qa` 二审）；三校文字（`qa` 三审）。任一审不为 `ok`，先修数据再重排，不直接改 DOCX/PDF。

一审把"会印进书里的页"上缺译的图注判为内容缺失：构建器遇到空译图注会省略图注、只印图，因此这种图注不能按语言中性块放行。`body_start_page` 之前的前置页、`skip_after_page` 之后和索引章不印，空图注不计。文献引证（`citation`）一般语言中性，原样保留；若引证以大写西班牙语字段名开头（如 `ESPECIE TIPO:`），字段名仍需翻译，一审同样判缺失。

排版本身已固定：正文 10.5 pt 两端对齐，启用 `w:autoHyphenation`、`w:consecutiveHyphenLimit=2`、`w:hyphenationZone=357`，并写入 `w:proofState spelling="clean" grammar="clean"`。LibreOffice 需要 `hyphen-en-us` 词典；缺词典时 PDF 会出现超宽词距，二审会报 `wide_spacing`。二审以 9 pt 为词距上限（10.5 pt 字号、134 mm 版心中约 3.5 个正常空格），超过才判失败；8–9 pt 属正常两端对齐伸缩，不阻断交付。

检索表单独排版：编号/圆点缩进 4 mm，行末用右对齐点线制表位把目标（下一条目号、种名或页码）拉到版心右缘；过长的条目把目标整体移到下一行，仍右对齐，不再把目标留在省略号后面。图注改为左对齐（与原书一致）并禁止自动断词，避免 `Re-drawn` 一类把单词拆到下一行。`qa` 的 `key_layout` 逐行核对检索表目标是否贴右缘、是否出现只有引导点没有目标的行；`caption_word_breaks` 只报短前缀（自动断词）造成的小写续行，`narrow-hooded` 这类原有连字符不算错误。两项都在 `check` 中再次执行。

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

三卷交付后的根因复盘见 `docs/research/2026-11-17/booklayout-delivery-postmortem.md`。结论：`gate.json` 只覆盖 qa/check/key-report；三审文本检查仅针对 `role == "body"`（约 25% 的块），不含 caption/entry/citation 译文，也不含 `zh check`。在 gate 扩展与覆盖率闸口落地前，`ok: true` 不能当作“全书无翻译错误”的证据。

## Release gates, quality receipt, style profile (issues #19, #26, #27, #37)

```bash
# #26 numeric quality gate: metrics JSON + quality_baseline.toml -> receipt
# exit 0 pass / 1 fail / 2 indeterminate; receipt binds manuscript+builder+baseline hashes
python3 -m booklayout quality-gate --metrics m.json --manuscript aligned.json --out receipt.json
python3 -m booklayout verify-receipt --receipt receipt.json --manuscript aligned.json

# #19 one acceptance report (translation review, technical, structure, pilot, visual, quality)
python3 -m booklayout acceptance --aligned aligned.json --translation-review tr.json \
  --technical zh.json --qa qa.json --check check.json --key-report key.json \
  --pilot pilot.json --visual visual.json --receipt receipt.json --command "<build cmd>" --out acceptance.json
# status: release | rejected | incomplete; exit 0 only for release

# gates in the build itself
python3 -m booklayout build ... --pilot pilot.json            # exit 5 unless all pilot items passed
python3 -m booklayout build ... --release-acceptance acceptance.json
#   invalid/stale -> output renamed *.DRAFT.docx, exit 4, report.release_status = "draft"

# #27 style profile and generic blocks
python3 -m booklayout profile > my.json        # default (Vol. 48) profile as a template
python3 -m booklayout build ... --profile my.json --strict-schema
python3 -m booklayout validate-aligned --aligned aligned.json

# #37
python3 -m booklayout kana-check --aligned en_aligned.json --out kana.json   # kana outside ref blocks
```

* Metrics/receipt/stage JSON shapes: docstrings of `booklayout/quality.py` and `booklayout/acceptance.py`.
  Thresholds: `quality_baseline.toml` (all PROVISIONAL, each with evidence link; changes need a `[[history]]` entry).
  The receipt `integrity` hash catches edits and stale files; it is not a signature, so human-review fields
  are only as trustworthy as the named reviewers. Model-named reviewers are rejected.
* `qa` and `check` reports now embed `manuscript_sha256`; acceptance rejects reports built from another manuscript.
* Generic block roles: `table` (rows, colspan, repeated header rows), `list`, `quote`, `box`, `footnote`
  (legacy roles unchanged). `normalize` splits multi-entry `ref` blocks into one block per entry (hanging indent
  is applied by the builder). `booklayout.paragraphs.merge_continuation_paragraphs` merges OCR line-break
  paragraph splits (library function, for use in prep scripts).

多语言一条龙出版命令与新模块见 `docs/publish_pipeline.md`。
