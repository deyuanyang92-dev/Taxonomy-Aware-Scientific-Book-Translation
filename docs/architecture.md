# 组件架构与接口（v1，2026-11-10）

取代此前「脚本串联」的做法。原则：**每个组件只做一件事、有唯一主库、有自己的命令行与测试；组件之间只通过下文约定的接口交接，不引用彼此内部代码；书和领域的差异全部放配置，不写进代码。**

```
             ┌──────────── 用户、Claude、Codex、其他技能（yzz-compilation / yzz-review / yzz-zootaxa）
             ▼
 ┌─────────────────────┐   ┌──────────────┐   ┌──────────────┐
 │ docstore 本地资料库 │◄──│ taxadb 分类库 │   │ termbase 术语 │（yiku）
 │ 资料登记·文本·检索  │   │ 记述·名称·名录│   │ 定名·出处·等级│
 └─────────▲───────────┘   └──────▲───────┘   └──────▲───────┘
           │ 读页面/检索           │ 读记述            │ 查术语
 ┌─────────┴───────────────────────┴──────────────────┴───────┐
 │ translate 翻译与审校（每本书 book.toml）                      │
 │ 分段对齐 · 术语注入 · 初译 · 异模型核译 · 问题单 · 闸口        │
 └───────────┬──────────────────────────────┬─────────────────┘
             ▼                              ▼
     ┌──────────────┐              ┌──────────────┐
     │ qa 验证       │              │ publish 出版  │
     │ 通用 + 领域插件│              │ md → docx/pdf │
     └──────────────┘              └──────────────┘
```

依赖方向只向下：docstore、termbase 不知道上层存在；删掉 translate，资料库照样能用。

---

## 1. docstore 本地资料库（第一优先，独立产品）

**定位**：用户把任何 PDF（志书、名录、专著、论文、译本、原著）放进来，就能随时检索、取原文、引页码。服务翻译，也服务物种汇编、写新种稿、审稿、日常查资料。

**主库**：`<库根>/`（默认 `/mnt/p/翻译-译作/参考资料/_资料库/`，可用 `--root` 或环境变量 `DOCSTORE_ROOT` 覆盖）
```
_资料库/
  registry.tsv            资料登记（唯一进度来源）
  docstore.sqlite         页文本 + 全文索引（FTS5，trigram；可由 pages/ 完全重建：docstore rebuild）
  pages/<key>/pNNNN.json  逐页证据：主版本（文本、方法、引擎、producer、时间、dpi、质量、核对等级）+ alternates + history
  imports.tsv             收编记录（detect 用它判断「已导入」）
  quality/<key>.tsv       抽查单
  images/<key>/           按需渲染的页图缓存（可删）
```

**资料登记字段**：key、path、sha256、pages、kind（志书/名录/专著/学位论文/译本/英文原著/中文论著/论文）、lang、pair（对照书）、domain、tier（依据等级）、title、authors、year、page_offset（印刷页 − PDF 页）、status、note、added_by、added_at。原件不在本机而只有页文本的资料，status 记「原件缺失」，sha256 为空。

**页面核对等级**：`text_layer`（原生文本层）＞ `ocr_verified`（逐页核过）＞ `ocr_sampled`（抽查过）＞ `ocr_raw`（机器初识）＞ `blank`。PDF 自带的 OCR 文本层（producer 为 Paper Capture、ABBYY 等）不算原生文本层，记 `ocr_raw` 并以 300 dpi 重识。

**页面 json**：顶层是主版本；同一页的其他版本放 `alternates`，一律保留不丢；`verify` 校正记入 `history`（by、时间、前后等级、confirmed fixes、diff）。主版本取核对等级最高者，同级 300 dpi > 200 dpi > 其他，再同级则先到者。

**命令**（全局参数 `--root`、`--by`）
| 命令 | 作用 |
|---|---|
| `docstore add <文件或目录>…` | 登记 PDF（按 sha256 去重；改名只更新 path；同路径内容变即新 key），初判 kind/lang/domain，note 标「初判，待确认」。跳过 `_资料库 _本地知识库 知识库 参考库 _work` 等派生目录 |
| `docstore text [<key>…\|--pending] [--workers N] [--dpi 300] [--engines rapidocr,tesseract] [--vlm deepseek-flash] [--limit N]` | 文本化：每页可抽字符 ≥30 直取文本层；否则双引擎 OCR（RapidOCR + Tesseract）做行/字共识，再按 `docstore/rules/ocr_fix.toml` 做规则纠错；已有记录的页跳过（断点续跑） |
| `docstore consensus <key> [--pages 1-50]` | 对已存在的 OCR 版本重算共识（不重跑 OCR），把重算结果写为新版本，旧版本保留在 alternates |
| `docstore quality <key>` | 列低置信、少字、乱码（私用区/替换符）、缺字□ 页，生成 `quality/<key>.tsv` 抽查单 |
| `docstore qc <key> [--apply] [--redo] [--pages] [--limit]` / `docstore qc --calibrate` | 自动质控：风险分分流（pass/redo/human），jsonl 断点续跑；`--apply` 可将 ocr_raw 升为 ocr_sampled；`--redo` 追加高 dpi OCR；阈值 `docstore/rules/qc.toml`，标定 `docs/ocr_qc_calibration.json` |
| `docstore verify <key> <页> --fix <file> [--level ocr_verified\|ocr_sampled]` | 写入校正：file 为全文 txt，或 json `{"text": …}` / `{"replace": {"误": "正"}}`；旧版本进 alternates，改动进 history |
| `docstore search "<词>" [--key K] [--kind 志书] [--domain D] [--level L]` | 全文检索（≥3 字走 FTS5 trigram，1–2 字走 LIKE），返回 key、PDF 页、印刷页、核对等级、producer、片段 |
| `docstore page <key> <页> [--image] [--json]` | 取一页文本（显示 producer、引擎、其他版本、校正记录），或渲染页图 |
| `docstore cite <key> <页>` | 规范引注（作者. 年份. 书名. 印刷页（PDF 页）. [docstore:key]） |
| `docstore export <key> --txt\|--md [-o 文件]` | 导出全文 |
| `docstore status` | 每份资料的页数、已文本化页数、各核对等级页数、各 producer 页数 |
| `docstore rebuild` | 由 registry.tsv 与 pages/*.json 重建 sqlite |
| `docstore detect <目录>` | 扫描库外疑似页面库，报告格式、对应资料（sha256 / 目录名 / 页数）、是否已导入 |
| `docstore import <目录> --adapter codex_kb\|sqlite_pages\|json_pages\|txt_pages [--map M] [--key K --offset N --dpi D] [--producer P]` | 收编库外页面库，只读来源 |
| `docstore attach <key> <pdf> [--check]` | 给已登记资料（如「原件缺失」）绑定原件：补 path、sha256、pages，status 改回 registered；`--check` 抽页比对 PDF 与已有页文本核页码偏移。不复制、不移动原件；找原件要搜 `/mnt/n` 与 `/mnt/p` 两个盘 |
| `docstore pair <keyA> <keyB>`、`docstore set <key> 字段=值…`、`docstore rename <旧> <新>` | 设对照书、改登记字段、改 key |

**库接口（Python）**：`open_store(root)`、`store.search(q, **filters)`、`store.page(key, n)`、`store.pages(key)`、`store.doc(key)`。其他组件和技能只用这几个函数。

### 多模型协作

- **producer 留痕**：每个页面版本记录 `producer`（模型或工具名：codex、claude-opus、claude-haiku、rapidocr、claude-script…）、`engine`（如 RapidOCR 300dpi）、`time`；每次 verify 记录 `by` 与时间。命令行 `--by <名称>`，缺省取 `DOCSTORE_AGENT`，再缺省为 `unknown`（写入命令会打印提醒）。`status` 与 `page` 显示 producer。
- **并发写入**：每页写入持文件锁、读-合并-原子写；不同来源的版本并存于 alternates，不覆盖；sqlite 只是索引，坏了可 `rebuild`。
- **收编流程**：别的模型在库外自建了页面数据时，`docstore detect <目录>` → 看清格式与对应资料 → `docstore import <目录> --adapter <名>`（目录名对不上 key 时写 `--map`：`dir key offset dpi`）→ `docstore status` 核对。收编记入 `imports.tsv`，之后 detect 显示「已导入」。不要另建库。

**迁移（2026-11-10 已完成）**：三处旧页文本——`参考资料/_本地知识库/`（adapter codex_kb；`confirmed_fixes / approved_pages` 转成 `ocr_verified` 并记入 history）、`一些经典译作/知识库/知识库.sqlite`（sqlite_pages）与 `参考库/*/OCR`（json_pages）、`Rouse2022_Annelida/术语库/OCR/`（txt_pages，200 dpi）与 `_本地知识库/分类数据层/ocr300/动物志33`（txt_pages，300 dpi）——按原件 sha256 并到同一 key。只搬数据、不重做 OCR；旧目录只新增「已迁移至_资料库.md」说明，其余不动。迁移报告见 `_资料库/迁移报告.md`。

---

## 2. termbase 术语库（yiku）

**主库**：`yiku.db`。skill 的 `terms/*.tsv` 改为 `yiku export` 生成的只读视图。

**接口**：`yiku lookup / table / check / import / review / export`（已有）；新增 `yiku from-docstore <key>`：对 docstore 中的资料做 `paren`（中文论著）或 `pair`（对照书），产出候选。
**不做**：不存页文本（只存 key + 页码，回 docstore 取原文）。

---

## 3. taxadb 分类数据库

**主库**：`taxa.sqlite`（`<库根>/taxa.sqlite`，即 `/mnt/p/翻译-译作/参考资料/_资料库/taxa.sqlite`），表 `work / treatment / name_usage / field_check`，字段与 yzz-compilation 的 work.csv / treatment.csv / name_usage.csv 对齐。可用 `TAXADB_PATH` 覆盖（测试用）。

**输入**：docstore 的页面（只读 `open_store / pages / page / doc`，不改页文本）；分卷切分规则在 `taxadb/rules/*.toml`（标题格式、小标题词、页眉噪声、图注剥离、清单比对、规范化）。

**命令**（全局 `--db --root --by`，写入者缺省取 `TAXADB_AGENT` / `DOCSTORE_AGENT`）：
| 命令 | 作用 |
|---|---|
| `taxadb split <key> --rules <规则.toml> [--dry]` | 切分一卷：标题 → treatment，异名列表 → name_usage，写入 taxa.sqlite；重切保留 field_check 已核值 |
| `taxadb verify <key> [--reference tsv] [--sample N] [-o 待核.tsv]` | 列关键字段（学名、命名人年份、中文名、页码、地理分布）待看原页核对的记录；`--sample` 固定种子随机抽查 |
| `taxadb check <核对.jsonl> [--key]` | 导入看原页核对结果（`{treatment_id, field, db_value, page_value, ok, pdf_page, note}`）；ok=0 的 page_value 写回 treatment；5 个关键字段全核后 verify_status=「关键字段已核」 |
| `taxadb export [--family X] [--work K] --format tsv\|csv\|json` | 导出名录 |
| `taxadb status` | 每份 work：书中种数 / 切分数 / 已核数 / 带疑点数 |
| `taxadb worms` | （计划）经 oworms 对照有效名 |

**规则**（`taxadb/rules/动物志.toml`，按卷33 实际版式）：种标题 `(编号)中文名 学名 命名人,年份（图N）`；编号可独立成行；小标题 `标本采集地/形态特征/生殖和发育/地理分布/讨论`（OCR 变体 fuzzy 匹配）；图注只剥「图 N」开头的短段；页眉按页首 N 行剥；两个数字间的「一」等按 OCR 对范围号「—」的误识规范化为「—」（只改写入副本，不改 docstore 页文本）；主 300 dpi 版本与低 dpi 版本合并补漏（只补插入，替换保留主版本）。

**验收（卷33 试点，2026-11-10）**：切分 203 种 = 书中所列种数（英文摘要 p474「203 species」，总论表 2 编号 (1)–(203)；清单页 OCR 漏 (144)(186) 两行，正文按编号连续接受）；随机抽 20 种关键字段逐字对原页核对（`taxadb/验证/pilot33_v2.jsonl`），11 处 OCR 疑误已修正并留痕，抽查后 20 条错误 0；OCR 疑误清单 `taxadb/验证/ocr_疑误.tsv`（docstore 页文本不动）。

**约束**：用于名录和描述的记录，学名、命名人、年份、数字须为「关键字段已核」。

---

## 4. translate 翻译与审校

**每本书一个 `book.toml`**：书目、领域、类群范围、原文与译文目录、页码范围（参考文献、索引、图版）、模型分配。现在写死在脚本里的值全部移到这里。
**命令**：`translate align | terms | examples | draft | review | issues | apply | status | next`。
**依赖**：docstore（原书页、志书例句）、termbase（术语表）、taxadb（可选，取物种记述作参照）。
**主库**：`<书>/核译/`（段对齐、问题单、裁定、变更日志）、`<书>/状态.json`。

**已实现的脚本（`scripts/`，以仓库为准，`scripts/sync_skill.sh` 同步到技能目录）**：

| 脚本 | 作用 |
|---|---|
| `llm_engines.py` | 直接调模型的统一入口 `call(engine, system, user) -> (正文, usage)`。engine：`deepseek-flash`、`deepseek-v4-pro`（anthropic SDK 流式，base_url 指向 DeepSeek 的 Anthropic 兼容端点，`max_tokens=64000`，调用前 `wait_offpeak()`，连接错误重试 3 次，正文为空且输出达上限报「推理耗尽」）、`claude-sonnet`、`claude-opus`（`claude -p --tools ""`，stdin 送入）、`codex`（`codex exec -s read-only -o`）。凭证取 `DEEPSEEK_API_KEY` 或 `DEEPSEEK_ENV_FILE`，不入库。每次调用向 usage.tsv（`LLM_USAGE_TSV`）追加时间、engine、token、耗时 |
| `deepseek_offpeak.py` | DeepSeek 忙时守卫：忙时不发请求，等到闲时 |
| `run_batches.py` | 批次调度。智能体模式（`--engine codex\|claude`，模型自己读写文件）；直调模式（`--engine deepseek-flash\|deepseek-v4-pro\|claude-sonnet\|claude-opus`，由 `direct_mode.py` 切块约 9000 字符、每块注入 `yiku table` 术语表、经 `llm_engines` 调用，产物按块写盘、断点续跑，合并时去掉每块「### 待定术语」并汇总，核译输出 JSONL 问题单交 `apply_issues.py` 闸口）。推荐分配：初译 `claude-sonnet`，核译 `deepseek-flash` |
| `split_figures.py` | 从按章抽出的英文原文分离图注/表注，输出 `正文.txt`（接回被图注打断的句子、去连字符断行）与 `图注.txt`，分块翻译前先跑 |
| `termonline_lookup.py` | 名词委（termonline.cn）逐词查询；缓存路径 `TERMONLINE_CACHE`，缺省 `~/.cache/termonline/cache.json` |
| `bench/bench.py` | 模型比测：多 engine 翻译样段、自动评分（术语落实、数字、学名、汉字比）、盲评目录与汇总；结论见 `docs/model_bench.md` |
| `sync_skill.sh` | 把 `skill/*.md`、`skill/domains/`、`scripts/` 复制到 `~/.claude/skills/yzz-translate/`，复制前比对并打印差异 |

## 5. qa 验证

通用检查：数字、引文、图号、结构计数、残留英文、全角空格。
领域插件：`qa.taxonomy`（学名、命名人年份、检索表编号与跳转、陷阱表回归）。插件接口：`check(src_segments, tgt_segments, config) -> issues`。

## 6. publish 出版

输入：译文 md + `book.toml` + 图库。输出：docx / PDF / 传播版。
步骤：标注（类群中文名、暂定名、英文括注，按规则与 termbase 生成）→ 排版 → 插图浮动 → 量页 → 目录、参考文献、索引 → 检查。
渲染后端可选：Windows Word（默认，版式最好）或 LibreOffice（无 Word 时）。前言、联系方式等放 `book.toml` 指向的文件。

**成品修订工具（`scripts/publish/`）**
- `patch_release.py 书.docx|书.pdf 替换表.tsv`：按「旧→新」定点替换，不必重排整本。docx 遍历 `word/` 下全部 XML，按文本节点替换，跨 run 拆开的文字也能命中并单独计数，0 次报「未命中」。PDF 只在新旧字数相同、都是全角字、且新字字形确在同一嵌入字体程序里（核对 `loca`，不信 ToUnicode）时用 PyMuPDF 原地改字形编码；其余提示「请用 word_render 由改后 docx 重渲染」。
- `share_pdf.sh 正式版.pdf`：Ghostscript 生成传播版（图像 120 dpi、JPEG 质量 72，字体全嵌入子集化；Rouse 55 MB → 12 MB）。
- Windows 上调用 `collect_pages.py`、`word_render.py` 一律加 `-X utf8`，否则打印生僻字（如 𧍒）会因 GBK 崩溃。

---

## 7. 重构顺序与验收

| 步 | 内容 | 验收 |
|---|---|---|
| 1 | **docstore**：实现命令与库接口；迁入现有三处页文本；登记用户新加的书 | `docstore search` 能检到所有已入库资料；迁移前后页文本逐页一致；新书完成文本化 |
| 2 | termbase：`terms/*.tsv` 改为导出视图；`from-docstore` | 脚本不再直接读 tsv |
| 3 | translate + `book.toml`：把 Rouse 的写死值移到配置 | 用配置重排 Rouse，与当前成品逐字一致 |
| 4 | qa 拆出通用与分类学插件；陷阱表回归 | 已知 9 个陷阱均能自动检出 |
| 5 | publish 配置化；LibreOffice 后端 | 同上逐字一致；无 Word 也能出 PDF |
| 6 | taxadb 改读 docstore；卷33 修切分规则后推广 | 试点 20 条关键字段错误率达标（✅ 2026-11-10：切分 203=书中 203，抽查 20 条修正后错误 0） |

每步一个提交、配测试；不新建任何「临时的第 N 个库」。
