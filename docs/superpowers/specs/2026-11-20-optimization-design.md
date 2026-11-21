# 优化设计：OCR、图版、排版与流水线效率（2026-11-20）

版本：2026-11-20。性质：顶层设计，不含实现代码。
输入：`google-suggestion/` 下 4 份建议（`optimization_plan_for_claude_code.md` 繁体短版、`optimization_plan_for_claude_code (1).md` 简体长版、`key_layout_spec.md`、`token-v2-20261120.md`），以及本仓库源码与文档。
证据标记：**已确证**（本仓库文件:行号或已有实测文档）、**未确证**（需本机复测）、**推测**（由读代码推断，未运行）。

---

## 0. 一页结论

1. 用户感到「离开大模型就慢、就差」，主因不在单个函数的 CPU 时间，而在三处结构缺口。
   - **排版靠反复整书重建来发现问题。** 2026-11-17 三卷交付共 4 轮 × 3 卷重建、21 次 build、7 次整书 PDF 转换（`docs/research/2026-11-17/booklayout-delivery-postmortem.md` 第 3 节）。复盘列为 P0 的 `booklayout audit` 至今没有实现：`booklayout/cli.py:1419-1568` 的子命令里没有 `audit`。
   - **OCR 实测最有效的方法不在软件里。** 「争议行裁图交 Haiku→Sonnet 级联」把劣化页 CER 从 5.37% 降到 0.83%（`docs/ocr_hard_scans.md` 第 39–60 行）。但实现脚本放在书目录 `/mnt/p/翻译-译作/日本-imajima/bench/ensemble.py`、`tiers*.py`，不在本仓库。`docstore/proofread.py:126` 只有整页 codex 复核。
   - **扫描书的图版提取没有通路。** `booklayout/pdffigures.py:64-67` 依靠 `page.get_image_info()` 找图，`:108-116` 依靠文本层 `get_text("blocks")` 找图注。扫描书每页只有一张整页图，没有文本层，所以图版和图注都无从定位（**推测**，需用一本扫描书验证）。
2. Google 建议中真正可用的，是一批局部的性能和误报修补，以及图版 CV 的思路。它的「新架构」部分（token-v2 的 ott 八阶段、新建 `docstore/consensus.py`、`key_renderer.py`、Typst 排版、四套检索表新预设）与已有的 docstore、yiku、taxadb、booklayout、keymodel、StyleProfile 重复或冲突，不采纳。
3. Google 给出的所有数字（78.2% CPU、67/100 与 80/100 误报、4.58s→2.95s、47.6% 零 token、2.04%→0.1% 错误率）都来自它的沙箱模拟，**不能当证据**。第 2.6 节列出需要在本机复测的项目。
4. 路线图分 6 个阶段（第 4 节）。第 0 阶段先合并两份检出、建立基线，没有基线就不宣称任何提升。

评估统计（第 2 节，共 55 项）：采纳 15 项，修改后采纳 24 项，不采纳或暂不采纳 8 项（含 A16 交用户定、B4 与 C10 暂缓），已有（重复）6 项，待定 2 项（A6 待本机测，A34 交用户定）。

---

## 1. 现状核对（动笔前已核实）

| 项 | 现状 | 依据 |
|---|---|---|
| `booklayout build` 局部构建 | 没有 `--pages`、`--chapter`、preview | `booklayout/cli.py:1421` 的 build 参数 |
| `gtrans` 网络请求 | 每次请求新建连接（`urllib.request.urlopen`），无 keep-alive | `scripts/gtrans.py:168-170` |
| `gtrans` 缓存写入 | 每条 `put` 单独 `commit`，无批量写；已开 WAL | `scripts/gtrans.py:196`、`:212-218` |
| `gtrans` 后备端点 | clients5 后备**已存在** | `scripts/gtrans.py:61-62` |
| `gtrans` 输出上限 | 写死 16000/32000，未接 `token_economy` | `scripts/gtrans.py:864`、`:895`、`:917` |
| `stage_draft` 复杂度 | `send` 是 list，`s.text in send` 为 O(N²) | `scripts/auto_translate.py:587-592` |
| `log_usage` 并发 | 只有线程锁 `_USAGE_LOCK`，多进程（fast_book 分章并行）不互斥 | `scripts/llm_engines.py:241-256` |
| DeepSeek thinking | 已显式传 `{"thinking": {"type": "disabled"}}` | `scripts/llm_engines.py:108-111` |
| `risk()` 误报修复 | 本目录**已含**：数字用 `core.numbers`、CJK 长度带、`_STOP_GENUS` 形态词停用表；未提交 | `transqa/taxoblocks.py:16`、`:83-104`、`:118-160` |
| 两份检出的差异 | `/root/github` 份有「乱码行不误判日文/单个学名」修复，本目录没有；本目录有 `risk()` 修复，两边相互缺失 | 对两份 `transqa/taxoblocks.py` 做 diff，18 行差异 |
| CJK 术语匹配边界 | `has()` 用 `(?<!\w)…(?!\w)`；Python 的 `\w` 包含汉字，中文定名嵌在词中时判为「缺失」（**推测**会误报 term） | `transqa/taxoblocks.py:126-129` |
| 结构化检索表 | **已有** `booklayout/keymodel.py`（361 行，issue #11、#38）与 `docstore/keys.py`（681 行，按 OCR 行框重建偶句） | 两文件开头的 docstring |
| 版式参数化 | **已有** `booklayout/profile.py` 的 `StyleProfile`（issue #27），默认值复现 Vol.48 版式 | `booklayout/profile.py:1-12` |
| OCR 共识 | **已有** `docstore/consensus.py`（117 行，按行、按字投票） | 文件开头 |
| 三审覆盖面 | 文本检查只取 `role == "body"`，约占块数 25% | `booklayout/cli.py:684`；复盘第 2 节 |
| 未关闭 issue | #2 #13 #25 #26 #27 #34 #37–#43 | `gh issue list`（2026-11-20） |

---

## 2. 任务 A：逐项评估 Google 建议

结论分四类：**采纳**（照做）、**修改后采纳**（方向对，做法要改）、**不采纳**、**已有**（仓库已实现，属重复造轮子）。

### 2.1 短版 T1：局部构建与预览

| # | 建议 | 结论 | 理由与依据 |
|---|---|---|---|
| A1 | `build --pages/--chapter` 只构建部分源页 | **采纳** | 现无此参数（`cli.py:1421`）。它直接对应复盘 P1「1 页样张 preflight」。约束：局部构建与整书构建必须用同一个 `build()`（`builder.py:1202`），只是输入块的子集，保证样式一致。 |
| A2 | `preview` 子命令输出 HTML（<50ms，带 `--watch`） | **不采纳** | 另写一套 HTML 渲染器会与 DOCX 版式漂移，用户看到的预览不等于交付物，违反「排版视觉样式不得变动」的约束。预览应是 A1 的局部 DOCX→PDF。 |
| A3 | 局部 DOCX 经 LibreOffice 转 PDF（约 1.5s） | **修改后采纳** | 并入 A1，复用 `cli.py:191-201` 的 soffice 调用。1.5s 是 Google 的数字，需本机复测。 |

### 2.2 短版 T2：`add_runs` 性能

| # | 建议 | 结论 | 理由与依据 |
|---|---|---|---|
| A4 | 属名正则按集合缓存 | **采纳** | `builder.py:265-272` 每次调用都对 `genera` 排序并重新 `re.compile` 一个大的选择式正则。按 `frozenset(genera)` 缓存，输出逐字节不变，属纯性能改动。 |
| A5 | 默认格式不写 rPr，继承 Normal 样式 | **修改后采纳** | 可能有收益，但会改变 DOCX 的 XML 结构。Word 与 LibreOffice 对「继承」与「显式」的解析未必一致（CJK 字体回退尤其敏感）。必须以「渲染后 PDF 逐页像素对比无差异」作为验收，否则回退。 |
| A6 | 「add_runs 占 78.2% CPU」 | **未确证** | Google 沙箱数据。先用 `cProfile` 在一本真书上测热点（第 4 节 P1），再决定 A5 值不值得做。按复盘，耗时大头是重建轮数，不是单次 build 的 CPU。 |

### 2.3 短版 T3：`risk()` 误报

| # | 建议 | 结论 | 理由与依据 |
|---|---|---|---|
| A7 | 数字比较改用 `core.numbers()` | **已有** | `taxoblocks.py:16` 已导入，`:137` 已使用（本目录，未提交）。要做的是提交，并与 `/root/github` 份合并。 |
| A8 | 按语种设长度比，短句跳过 | **修改后采纳** | 机制已有（`taxoblocks.py:94-104`，CJK 带 0.15–0.90，30 字符以下不判）。Google 的 (0.18, 0.70)、(0.55, 1.70) 没有来源，不照搬。阈值应由已核译文的实测分布标定，这正是 issue #40（ja→en 61% 误报）的范围。 |
| A9 | CJK 术语匹配去掉 `\w` 边界 | **采纳** | `taxoblocks.py:126-129`：中文定名在译文里常是复合词的一部分，`(?<!\w)` 会使其匹配失败。修法限定在 tl 为 CJK 时用子串匹配；`transqa/terms.py` 的 `normalize` 一并检查。配回归测试。 |
| A10 | `_EPITHET` 形态学首词停用表 | **已有** | `taxoblocks.py:83-89` 的 `_STOP_GENUS` 已覆盖 Dorsal/Ventral 等。 |
| A11 | 月份名白名单（Januar→N月） | **修改后采纳** | 长版称加入后德→英误报 80/100 降到 0/100（**未确证**）。应先用本机德文书复测误报构成，再把月份等写进 `transqa/languages.py` 的语种表，不写死在 `risk()` 里。 |

### 2.4 短版 T4：LLM 调用量

| # | 建议 | 结论 | 理由与依据 |
|---|---|---|---|
| A12 | 跨页打包 ⟦pN_sM⟧，每包 3000–4000 字符 | **修改后采纳** | 能减少请求数与重复的系统提示词。前提是段号在回填时一一对应，`apply_issues` 闸口（old 必须恰好匹配一次）不能被绕过。先在 1 章上对比请求数、token 与解析失败率。 |
| A13 | lean 模式默认 `--verify-mode judge`，`edits=[]` 时跳过第二模型 | **修改后采纳** | `judge` 已实现（`auto_translate.py:953`、`:1200`，默认 `review`）。改默认值会降低异模型审校强度，与 `docs/design.md` 第 7 节「异模型译审」原则相抵。须先用 `scripts/bench/qa_seed.py` 注入已知错误，比较两种模式的检出率，检出率不降才改默认。 |
| A14 | fast_book 分层异模型复核（否定风险页、检索表页、critical） | **采纳** | 与「贵的模型只做判断」一致，接在现有 `risk()` 信号上，不新增判定逻辑。 |
| A15 | lean 默认 `--no-entities` | **修改后采纳** | 需复测实体抽取的命中价值（`auto_translate.py:604`、`:1183`）；作为 lean 档的默认值可接受，全量档不改。 |
| A16 | gtrans 默认 `--llm-mode edits` | **不采纳（交用户定）** | `gtrans.py:16-20` 说明 rewrite 是有意选择的默认（名家译风整段改写，加意义核对）。edits 便宜但译风差。见开放问题 Q3。 |
| A17 | gtrans 的 `max_tokens` 接 `token_economy.out_budget("json")` | **采纳** | 写死值见 `gtrans.py:864/895/917`；`token_economy.py` 是仓库规定的预算入口（CLAUDE.md）。 |
| A18 | 送 Google 前先做 `terms.normalize` | **已有** | `term_presub`（提交 d02d063）已在 `auto_translate.py:584` 前置替换。 |

### 2.5 短版 T5–T7：网络、缓存、并发、分类学规则

| # | 建议 | 结论 | 理由与依据 |
|---|---|---|---|
| A19 | gtrans 用线程局部 `HTTPSConnection`，gzip，断线重连 | **采纳** | `gtrans.py:168-170` 每请求新建 TLS 连接。收益需本机测（每千请求耗时）。 |
| A20 | `PRAGMA synchronous=NORMAL` | **采纳** | 已开 WAL（`gtrans.py:196`）；WAL 下 NORMAL 是标准搭配，断电最多丢最近事务，缓存可重算。 |
| A21 | `missing_keys` 用 500 键一批的 `SELECT … IN` | **采纳** | `prefetch`（`gtrans.py:353`）逐条 `get`。 |
| A22 | `put_many`，每 30–50 条或 2 秒提交 | **采纳** | `gtrans.py:212-218` 每条提交一次。 |
| A23 | HARD 术语并入 prefetch | **修改后采纳** | 需先确认 HARD 术语单独请求的数量是否显著；不显著则不做。 |
| A24 | 双端点 | **已有** | `gtrans.py:61-62`。 |
| A25 | `stage_draft` 用 set | **采纳** | `auto_translate.py:587-592`。一行改动，输出不变。 |
| A26 | `log_usage` 加 flock / msvcrt | **采纳** | 线程锁不跨进程（`llm_engines.py:253`），fast_book 多进程会交错写。Linux 用 `fcntl.flock`；Windows 端（publish 工具在 Windows 上用 `-X utf8` 运行）用 `msvcrt.locking`。 |
| A27 | DeepSeek 客户端单例，thinking 显式传参不改 `os.environ` | **修改后采纳** | thinking 已显式（`llm_engines.py:108-111`）；只需核查是否仍有改 `os.environ` 的路径，有则改为参数。 |
| A28 | `_ask_json` 区分 JSON 解析错与 429/5xx，后者指数退避 | **采纳** | 即 issue #39（引擎错误被吞成 parse_failed）；`auto_translate.py:786-810`。 |
| A29 | `apply_edits` 按页字典处理 | **修改后采纳** | 先测是否是热点（`auto_translate.py:459`）；不是则不改。 |
| A30 | fast_book 分章汇总 report/usage/review_queue，拆分预算 | **采纳** | 对应 issue #2、#42；`fast_book.py:140-170` 现只并行，不汇总。 |
| A31 | `latin_names` 支持三名法、cf./aff. | **修改后采纳** | Google 定位错了：`transqa/taxonomy.py:30-37` 的 `latin_names` 提取的是斜体串，不是按二名法正则。三名法与 cf./aff. 的问题在 `taxoblocks.py:77` 的 `_EPITHET`，应在那里修，并配测试。 |
| A32 | `key_edges`/`key_structure` 兼容无粗体 `1(2)`、`1a/1b` | **修改后采纳** | 不在正则上继续打补丁；把 `transqa/taxonomy.py:39` 与 `auto_translate.py:231` 改为调用 `booklayout/keymodel.py` 的 `parse_key_text`，检索表只保留一套解析。 |
| A33 | 注入上一页末段与上级分类标题作只读 CONTEXT | **采纳** | 跨页断句是已知问题（issue #37）。须计入 token 预算，并在 1 章上测 token 增量。 |

### 2.6 长版补充：语言路由、OCR 四层共识、TaxonTreatment、检索表 JSON

| # | 建议 | 结论 | 理由与依据 |
|---|---|---|---|
| A34 | 非英语源默认先译英文，加 `--then-zh` 才译中文 | **交用户定** | 是产品取向问题：英文枢纽便于用 Google 与英文术语库，但多一层误差。见开放问题 Q2。 |
| A35 | OCR L1：Tesseract 与 Surya/PP-OCR 异源逐行共识 | **不采纳** | 本机实测：3–4 引擎逐行投票几乎无收益（`docs/ocr_hard_scans.md` 第 41–49 行）；Rapid+Tesseract 共识在动物志33 抽样无增益（`docs/ocr_design.md` 第 30 行）。共识模块已存在（`docstore/consensus.py`），提议「新建 consensus.py」属重复。 |
| A36 | OCR L2：书内高频实体共识（混淆加权编辑距离 ≤2） | **修改后采纳** | 做进已有的 `docstore/latinfix.py`、`docstore/lexicon.py`、`docstore/rules/latin_confusions.toml`，产物进 docstore 的 alternates，不另写 `_audit/consensus_*.jsonl` 库。 |
| A37 | OCR L3：新建 `docstore/taxofix.py`，接 WoRMS、gnverifier、Crossref、BHL | **修改后采纳** | WoRMS 只经 oworms 调用（`docs/design.md` 第 184 行）。外部名库只产生「建议」进待核队列，不自动改 OCR 文本；历史名不替换为现代名（原文不可侵犯，`design.md` 第 28 行）。 |
| A38 | OCR L4：逐行裁图，Haiku 两遍一致即采纳，不一致升 Sonnet | **已有（但在仓库外）** | 方法已在本机实测有效（`ocr_hard_scans.md` 第 39–60 行），脚本在 `/mnt/p/翻译-译作/日本-imajima/bench/`。要做的是收编进 `docstore/proofread.py`，见阶段 P2。 |
| A39 | TaxonTreatment 结构，补德文标签，taxadb 多语言前置 | **修改后采纳** | 物种记述的唯一主库是 taxadb（`AGENTS.md`「单一主库」）。`transqa/rules/taxo_labels.toml:10-12` 已有 Bemerkungen、Gattung 等德文标签，只补缺项。「47.6% 区块零 token」需本机复测。 |
| A40 | 新建 `booklayout/key_renderer.py` 与 `transqa/key_qa.py`，取代 builder 的 `key_para/tabbed/LEADER_RE` | **修改后采纳** | 结构化模型已有（`keymodel.py`、`docstore/keys.py`）。拓扑 QA（偶句成对、可达、无环、目标存在）写进 `keymodel.py`；渲染仍用 `builder.py:473` `tabbed` 与 `:532` `key_para`，视觉不变。 |

### 2.7 `key_layout_spec.md`

| # | 建议 | 结论 | 理由与依据 |
|---|---|---|---|
| B1 | 4 套检索表预设，默认 `bracketed_hanging` | **不采纳为默认** | 现行版式（Fauna Ibérica 式 `tabbed`）是用户已确认的视觉样式，按 UI 冻结规则不得更改。可作为 `StyleProfile`（`profile.py`）的可选 profile，只在用户明确选择时启用。 |
| B2 | 5 条铁律中的「项对不拆页」（keep_with_next）、「目标原子化」 | **修改后采纳** | 属于结构正确性，不是视觉风格，但会改变分页。先作为 `booklayout audit` 的检查项报告违例数，用户确认后再作为构建行为开启（开放问题 Q4）。 |
| B3 | JSON 契约 | **修改后采纳** | 以 `keymodel.py` 的现有字段为准，只补 `target_type`、`source_page` 等缺失字段，不另立一套。 |
| B4 | `learn-style`：纠斜后取中位数，VLM 判定性风格，产出 `book_style.yaml` | **暂不采纳** | 输出物即 `StyleProfile`；对新书有价值，但当前瓶颈不在此。放入后续 backlog。 |
| B5 | `key_qa`：防退化断言（无降级为普通段落的检索行、无残留文本点线） | **采纳** | 直接针对复盘中的「检索表内联、短引导点」类缺陷，作为 `booklayout audit` 的检查项。 |

### 2.8 `token-v2-20261120.md`（ott 八阶段架构）

| # | 建议 | 结论 | 理由与依据 |
|---|---|---|---|
| C1 | 整体换成 ott 八阶段，新建 `ontology/`、`profiles/`、`src/`、`workspace/` | **不采纳** | 替换 docstore、yiku、taxadb、booklayout，违反「单一主库」与「不得另建库」（`AGENTS.md`）。 |
| C2 | Typst 模板排版 | **不采纳** | 交付物是 Word/DOCX，并须通过 `yzz.py zh check` 与 `ms check`（全局规则）。换引擎即换视觉样式。 |
| C3 | 按 CropBox 渲染合层页，不用 `get_images` 拆图 | **已有** | `pdffigures.py` 开头已说明按显示矩形裁剪的理由。 |
| C4 | 图版纯 CV：字高指纹 H_char、RLSA、四类劈分、图注锚定、保留 A–N 标号、墨迹框 IoU、表格与整页图版分流 | **修改后采纳** | 这是扫描书图版提取缺口（第 3.3 节）的正确方向。做进 `booklayout/pdffigures.py` 作为「扫描页」分支，图注位置取自 docstore 的 OCR 行框，而不是文本层。 |
| C5 | `review_plates.html` 人工拖框，写 `manual_overrides.json` | **修改后采纳** | 人工修正落在书的 work 目录，由 `pdffigures` 读取；页面只读本地文件，不建新库。 |
| C6 | preflight：去书脊阴影、Lab 去霉斑、双阈值抑透字 | **修改后采纳** | 本机实测：全页增强会让劣化页变差（0.137→0.252），二值化对模糊页有害（`ocr_hard_scans.md` 第 13–24 行）。只能沿用现有「自适应、置信度不降才采用」的框架逐项加，每项须在 34 页测试集上不降。 |
| C7 | 哨兵掩码（学名、数字、引文送翻译前替换为占位符） | **修改后采纳** | 与 `term_presub`、`fidelity_check` 功能重叠；只对 Google 初译通道试点，测占位符被打乱的比例。 |
| C8 | 5 道 QC 门：ENTITY_LOST、TERM_MISMATCH、KEY_GRAPH_ERR、UNIT_ANOMALY、RESIDUAL_SRC | **修改后采纳** | 前三项已有对应（`fidelity_check`、`yiku check`、`taxonomy.key_edges`）。UNIT_ANOMALY（如 mm/µm 量级异常，只加注 `[sic]` 不改）与 RESIDUAL_SRC（`taxoblocks.py:81` 只有德语残留表）是真缺口，加进 `transqa`。 |
| C9 | mine-terms：N-gram 挖术语候选 | **修改后采纳** | 产物只进 yiku 的「候选」（`design.md` 第 73 行），不自建词表。 |
| C10 | 15 页 Sonnet 探针生成 `book_profile.yaml` | **暂不采纳** | 与 B4 同类，放入 backlog。 |

### 2.9 必须在本机复测的 Google 数字

| 数字 | 来源 | 复测方法 |
|---|---|---|
| `add_runs` 占 78.2% CPU | 短版 T2 | 对一本真书的 aligned JSON 跑 `cProfile`，取前 10 热点 |
| 650 页 DOCX 4.58s→2.95s；5 页 PDF 1.39s | 长版 | `time booklayout build`，同一输入跑 3 次取中位数 |
| 德→英误报 67/100、80/100、月份白名单后 0/100 | 短版、长版 | 用已核译文抽 100 段跑 `risk()`，人工判真假报警 |
| 英→中误报 100/100 | 短版 | 同上，用 Rouse 已核章节 |
| 47.6% 区块零 token | 长版 | 在 Hartmann-Schröder 1996 或同类书上跑 `taxadb split`，统计可直接模板化的区块比例 |
| 词袋错误率 2.04%→<0.6%→<0.1% | 长版 OCR | 必须先有人工金标准（第 3.1 节），否则无法测 |
| HTML 预览 <50ms、局部 PDF 约 1.5s | 短版 T1 | A1 完成后计时 |

---

## 3. 任务 B：Google 没有覆盖的缺口

### 3.1 没有人工金标准，OCR 的所有「精度」都无法验证

`docs/ocr_design.md` 第 11 行：278 页 `ocr_verified` 中 277 页是 glm 转录，CER 实为「与 glm 的一致率」。第 5 节设计的 30 页人工金标准尚未完成（**未确证**是否已开始；文档中没有完成记录）。任何 OCR 改动在此之前只能说「与 glm 更一致」，不能说「更准」。这是所有 OCR 优化的前置条件。

### 3.2 已验证有效的 OCR 方法游离在仓库之外

争议行（server 与 mobile 两种读法不同且置信度 <0.97）裁图后交 Haiku，再按条件升 Sonnet：劣化页 5.37%→0.83%，没有一页被改坏，费用约 $0.0001–0.0014/行（`ocr_hard_scans.md` 第 41–60 行）。但脚本在书目录 `日本-imajima/bench/`。后果是：别的书用不上，没有测试，`docstore` 的版本记录（`--by`、alternates、history）也没有记录它的产出。这是 OCR 质量上收益最大、成本最低的一步。

### 3.3 扫描书的图版提取没有通路

`pdffigures.py` 只处理「PDF 内嵌多张图」的出版社 PDF：用 `get_image_info` 找图块（`:64-67`），用文本层找图注（`:108-116`）。扫描书每页是一张整页图，没有文本层，因此图块就是整页，图注找不到（**推测**，需用一本扫描书跑 `booklayout figures extract` 验证）。`scripts/publish/extract_figs.py` 同样依赖文本层的「FIGURE x.y:」。补法是 C4：以 docstore 已有的 OCR 行框为图注锚点，用 CV 在整页图内切分图版。

### 3.4 排版的瓶颈是「发现问题的方式」，不是单次构建速度

单次 build 为 60–110 秒（`docs/booklayout.md`「速度」节），尚可接受。真正的代价是缺陷要等整书 PDF 出来才能发现，一类缺陷触发一轮重建（复盘第 3 节第 1–2 条）。复盘 P0 的三项至今没有落地：

1. `booklayout audit`：从 aligned JSON 一次静态算出全书缺陷计数（检索表内联、拆行、短引导点，图注间距，重复段，截断句，源语言残留，覆盖率）。
2. `gate` 串联 `zh check` 与图注审计，并要求按角色声明的检查覆盖率达到 100%（现在只查 body，约 25%，`cli.py:684`）。
3. 构建输入入 work 目录，`build_report.json` 记录输入 SHA256 与命令行，拒绝 `/tmp` 输入。

复盘 P1 还提出：key-breaks 改为从 aligned 数据静态计算（`cli.py:1225` 已有 `_key_breaks_from_lines`，需确认是否已脱离 pass1 PDF），从而把三遍构建减为两遍。

### 3.5 检索表结构在 OCR 拼行时丢失

`docstore/keys.py` 开头说明：`engines/ppocr.py` 的 `rows_to_text` 把行框拼成连续文字时，条目号、点线和右栏终点丢失，这是 issue #35、#36 的根因。上游修复（#38）已有模块，但下游的 `transqa/taxonomy.key_edges`、`auto_translate.key_structure` 仍在拼好的文字上用正则重新猜结构（见 A32）。检索表应全程只有一个结构化表示。

### 3.6 两份检出互相缺改动

本目录与 `/root/github` 份各有对方没有的提交或未提交改动（CLAUDE.md「容易踩的坑」；`taxoblocks.py` 实测 18 行差异）。PATH 上的 `docstore`、`booklayout` 命令跑的是 `/root/github` 份。在合并之前，任何优化都有可能只落在一份里，测出来的效果和实际运行的代码也可能不是同一份。

### 3.7 DPI 与预处理按语种而异，现在没有按书配置

中文页 300 dpi 明显优于 200 dpi（`ocr_design.md` 第 13、第 110 行），日文页却是 200 dpi 更好（`ocr_hard_scans.md` 第 34 行）。现在由环境变量和默认值决定，应记进 docstore 的登记行（每本书的 OCR 参数），让重跑可复现。

---

## 4. 任务 C：分阶段路线图（按收益/成本排序）

通用规则（每阶段都适用）：

- 每项先报 GitHub issue，写明复现材料、基线数字与验收标准，再动手。
- 代码改动配测试；新增与改动代码过 `ruff check` 和 `mypy`；`python3 -m pytest -q tests yiku/tests` 全过。
- 不覆盖用户数据。OCR 新结果作为 docstore 的新版本并存；译文修改只经问题单与 `apply_issues` 闸口。
- 排版只改性能与结构，不改视觉样式。凡触及 builder 输出，验收都包括「同一输入的 PDF 逐页像素对比无差异」。
- 先 1 章或 1 页小样，再全量。

### P0 合并检出、建立基线（收益：前置条件；成本：低）

- **目标**：只有一份权威代码；后续每项改进都有可比较的前后数字。
- **内容**：
  1. 合并两份检出（本目录未提交的 `risk()` 修复、质检流水线三方合并；`/root/github` 的乱码行修复与 `qa-three-review` 分支），然后再跑 `scripts/sync_skill.sh`。
  2. 写一个基线脚本，输出 JSON：同一本书 build 耗时与 `cProfile` 前 10 热点；`gtrans` 每千请求耗时与缓存命中率；`risk()` 在 100 段已核译文上的报警率（分 de→en、en→zh、ja→en）；每章 LLM 请求数与 token（取自 `usage.tsv`）。
- **验收**：两份检出 `git diff` 为空（或只剩登记过的差异）；基线 JSON 存入 `docs/bench/2026-11-20-baseline.json`，命令写进文档，可重跑。
- **涉及文件**：`transqa/taxoblocks.py`、`scripts/auto_translate.py`、`scripts/token_economy.py`、`scripts/bench/bench.py`。
- **风险**：合并冲突覆盖了一方的改动。对策：合并前把两边的 diff 各存一份，合并后逐项核对。
- **依赖**：无。**工作量**：1–2 天。

### P1 零风险性能修补（收益：中；成本：很低）

- **目标**：去掉已确证的低效代码，输出不变。
- **内容**：A4（属名正则缓存）、A25（`stage_draft` 用 set）、A19–A22（gtrans 长连接、`synchronous=NORMAL`、批量查缓存、批量提交）、A26（`log_usage` 跨进程锁）、A17（gtrans 预算接 `token_economy`）、A28（`_ask_json` 错误分类，关闭 #39）。
- **验收**：
  - build 输出的 DOCX 与改动前在 XML 层逐字节相同；PDF 逐页像素相同。
  - `gtrans` 对同一批 1000 段的总耗时下降（目标值在拿到 P0 基线后设定），译文逐字相同。
  - 新增测试：两个进程并发写 `usage.tsv` 1000 行，无交错、无丢行；`_ask_json` 在 429 时退避重试、在 JSON 坏时报 parse_failed、在引擎异常时报 engine_error。
- **涉及文件**：`booklayout/builder.py`、`scripts/auto_translate.py`、`scripts/gtrans.py`、`scripts/llm_engines.py`。
- **风险**：长连接在 Google 端被重置。对策：断线自动重建连接，并保留现有的退避与后备端点。
- **依赖**：P0。**工作量**：2 天。

### P2 OCR 争议行复核入库（收益：大；成本：中）

- **目标**：把已实测有效的「争议行→Haiku→Sonnet 级联」做成 docstore 的正式功能，并补人工金标准。
- **内容**：
  1. 把 `日本-imajima/bench/ensemble.py`、`tiers*.py` 的方法收编为 `docstore proofread --lines`：双引擎读法不一致且置信度低于阈值的行才裁图；每页一次请求；结果写为新的 alternate 版本，带 `--by`；保留「候选与任一 OCR 读法相似度 ≥60 才采用」的护栏。
  2. 按 `ocr_design.md` 第 5 节完成约 30 页人工金标准（用户校对，或用户抽核模型校对结果）。
  3. A36：书内高频学名一致性纠错并入 `latinfix.py`，只出建议。
  4. 按书记录 DPI 与预处理参数（第 3.7 节）。
- **验收**：在 34 页测试集（`ocr_hard_scans.md`）上复现劣化页 CER ≤1.0%、清晰页不升高；在人工金标准上报告真实 CER（首次）；每页费用与耗时写入报告；没有被改坏的页（相似度护栏统计）。
- **涉及文件**：`docstore/proofread.py`、`docstore/engines/ppocr.py`、`docstore/latinfix.py`、`docstore/rules/*.toml`、`docstore/cli.py`。
- **风险**：模型调用费用；`claude` 可执行文件自动更新时短暂缺失（`ocr_hard_scans.md` 第 60 行）。对策：每书先估算争议行数与费用，超过上限停下请示；调用加重试。
- **依赖**：P0。人工金标准需要用户时间（开放问题 Q1）。**工作量**：4–6 天（不含人工校对）。

### P3 排版一次查全：`booklayout audit` 与 gate 扩展（收益：大；成本：中）

- **目标**：缺陷在 aligned JSON 层一次全部报出，不再靠反复重建整书来发现；增加局部构建，用于看样张。
- **内容**：
  1. `booklayout audit`（复盘 P0）：检查项包括检索表内联、拆行、短引导点、无降级为普通段落的检索行（B5）、项对跨页风险（B2，只报告）、图注间距与断词、重复段、截断句、源语言残留、各角色覆盖率。
  2. `gate` 串联 `audit`、`zh check` 和图注审计，按角色声明的覆盖率须达到 100%。
  3. 构建输入可追溯：`build_report.json` 记录输入 SHA256 与命令行，拒绝 `/tmp` 输入。
  4. A1+A3：`build --pages/--chapter`，局部 DOCX→PDF，复用同一个 `build()`。
  5. 检索表拓扑 QA 并入 `keymodel.py`（A40）；`key_edges` 与 `key_structure` 改用 `keymodel` 解析（A32）。
- **验收**：在上次三卷交付的 aligned JSON 上，`audit` 能一次报出复盘第 1–2 节列出的全部缺陷类别（逐条对照）；局部构建 5 页的输出与整书构建中对应页像素一致；下一本书交付的整书重建轮数 ≤2（复盘中为 4）。
- **涉及文件**：`booklayout/cli.py`、`booklayout/quality.py`、`booklayout/acceptance.py`、`booklayout/keymodel.py`、`transqa/taxonomy.py`、`scripts/auto_translate.py`。
- **风险**：`audit` 误报过多而被忽略。对策：每个检查项先在三卷数据上标定，误报率写进文档。
- **依赖**：P0。**工作量**：5–7 天。

### P4 扫描书图版提取（收益：大；成本：中到高）

- **目标**：扫描书也能自动切出图版，并与图注一一对应；无法确定的情况交人工拖框，不靠大模型。
- **内容**：
  1. `pdffigures` 增加扫描页分支：整页图内用字高指纹、RLSA 区分文字区与图区，图注以 docstore OCR 行框中匹配图注标签的行作锚点；分出整页图版、表格与普通插图；保留图内 A–N 分图标号。
  2. 无法确定的页写入 `review_plates.html`（只读本地文件），人工修正保存到书 work 目录下的 `manual_overrides.json`，由 `pdffigures` 读取。
  3. 产物仍为 `figures_manifest.json` 与 `source_figure_audit.json`，`booklayout build` 无需改动。
- **验收**：先用一本扫描书人工标注 30 页图版框作为参照；自动切图与参照框 IoU ≥0.85 的比例（目标值在试点后设定）；图注配对正确率；需人工修正的页占比。
- **涉及文件**：`booklayout/pdffigures.py`、`booklayout/figures.py`；读 `docstore` 页面行框（只读）。
- **风险**：版式差异大的老书规则不通用。对策：参数进书的 profile，不写死；先跑 1 本，再推广。
- **依赖**：P0；建议在 P2 之后，因为图注锚点依赖 OCR 质量。**工作量**：7–10 天。

### P5 翻译通道降本与误报标定（收益：中；成本：中）

- **目标**：在审校检出率不降的前提下，减少模型请求与 token。
- **内容**：
  1. `risk()` 误报标定（A8、A9、A11，关闭 #40）：用已核译文求各语种对的长度比分布与报警构成。
  2. A31：`_EPITHET` 支持三名法与 cf./aff./s.l./s.str.。
  3. A12 跨页打包、A33 前页上下文、A14 分层复核、A15 lean 档默认关实体抽取。
  4. A13（judge 默认）只在 `qa_seed` 检出率不降时才改。
  5. C8：`transqa` 增加单位量级异常与通用源语言残留检查。
  6. A30：fast_book 分章汇总与预算拆分（#2、#42）。
- **验收**：`risk()` 在已核译文上的报警率降到阈值以下（目标值由 P0 基线定）；`qa_seed` 注入错误的检出率不低于基线；每章 token 与请求数相对 P0 基线下降，并报告下降幅度。
- **涉及文件**：`transqa/taxoblocks.py`、`transqa/languages.py`、`transqa/core.py`、`scripts/auto_translate.py`、`scripts/fast_book.py`、`scripts/gtrans.py`。
- **风险**：降本削弱审校。对策：以 `qa_seed` 检出率作为硬闸口。
- **依赖**：P0、P1。**工作量**：5–7 天。

### 不进入本轮路线图（backlog）

A5（rPr 继承，等 P0 证明 `add_runs` 确为热点）、B1 和 B4（检索表新预设、learn-style）、C6（新的图像预处理）、C7（哨兵掩码）、C10（探针生成 book_profile）、A39 的全量 TaxonTreatment 分流。

### 排序依据

| 阶段 | 收益 | 成本 | 说明 |
|---|---|---|---|
| P0 | 前置 | 低 | 没有它，其余都无法验收 |
| P1 | 中 | 很低 | 已确证的低效，改动小、输出不变 |
| P3 | 大 | 中 | 直接消除复盘中的重建轮数 |
| P2 | 大 | 中 | 方法已实测，主要是收编 |
| P4 | 大 | 中到高 | 新能力，需要试点 |
| P5 | 中 | 中 | 依赖基线标定 |

建议执行顺序：P0 → P1 → P3 与 P2 并行 → P4 → P5。

---

## 5. 任务 D：需要用户拍板的问题

**Q1 人工金标准由谁做？**
OCR 改进的「真实精度」只能靠约 30 页人工校对来测（`ocr_design.md` 第 5 节）。
- 选项：(a) 用户亲自校对；(b) 模型校对，用户抽核 20%；(c) 暂不做，只报告与 glm 的一致率。
- **推荐 (b)**：用户投入约为 (a) 的五分之一，同时仍有人工把关；报告中注明是抽核金标准。

**Q2 非英语源书默认先译英文，还是直接译中文？**（A34）
- 选项：(a) 默认译英文，`--then-zh` 再译中文；(b) 直接译中文；(c) 按书配置。
- **推荐 (c)**，默认值为 (b)：中文译本是主要产出，多一层枢纽就多一层误差；德、日文书需要英文版时再按书打开。

**Q3 gtrans 的模型阶段默认用 rewrite 还是 edits？**（A16）
- rewrite 是名家译风的整段改写加意义核对，较贵；edits 只出 JSON 改动，便宜但译风差。
- **推荐保持 rewrite 为默认**，lean 档改用 edits，并在报告中写明所用档位。

**Q4 检索表「项对不拆页」是否作为构建行为开启？**（B2）
- 它不改字体、缩进和点线，但会改变分页，个别页底会多出空白。
- **推荐**：先由 `audit` 报告违例数；用户看过一卷的违例样页后再决定是否开启。

**Q5 争议行模型复核的费用上限是多少？**（P2）
- 实测费用约 $0.0001（Haiku）至 $0.0014（Sonnet）每行；劣化书约一半行是争议行。另有记忆规则「一本书费用上限 ¥2，正文零模型」。
- **推荐**：OCR 复核另设预算，每本书上限 ¥5，只跑劣化页；超出时停下请示。若坚持 ¥2 总上限，就只对学名行和检索表行做复核。

---

## 附：本文引用的主要文件

- Google 建议：`google-suggestion/optimization_plan_for_claude_code.md`、`optimization_plan_for_claude_code (1).md`、`key_layout_spec.md`、`token-v2-20261120.md`
- 设计文档：`docs/design.md`、`docs/architecture.md`、`docs/workflow.md`、`docs/plan_minimal_translation.md`、`docs/ocr_design.md`、`docs/ocr_hard_scans.md`、`docs/ocr_eval/metrics_summary.json`、`docs/booklayout.md`、`docs/publish_pipeline.md`、`docs/research/2026-11-17/booklayout-delivery-postmortem.md`
- 源码：`booklayout/{cli,builder,pdffigures,figures,keymodel,profile,quality}.py`、`transqa/{taxoblocks,taxonomy,core}.py`、`transqa/rules/taxo_labels.toml`、`scripts/{gtrans,auto_translate,llm_engines,fast_book}.py`、`docstore/{consensus,proofread,keys,latinfix}.py`
- 仓库外：`/mnt/p/翻译-译作/日本-imajima/bench/{ensemble,tiers,tiers_hcas,tiers_hs}.py`

---

## 6. 用户决定（2026-11-20）

| 问题 | 决定 |
|---|---|
| Q1 金标准 | 先出小样，由用户批复；也支持模型复核。小样用 Sonnet 制备，DeepSeek 或 Codex 复核，通过后再大规模运行。 |
| Q2 非英语源书 | 先译英文，再按需译中文（与第 5 节推荐不同，以用户为准）。 |
| Q3 gtrans 模型阶段 | 默认 edits（只出差量 JSON），不整段重写。rewrite 仅在显式指定时使用。 |
| Q4 检索表项对不拆页 | 先不开启；只由 audit 报告违例数。 |
| Q5 OCR 复核费用 | 可配置，不写死；默认沿用每本书 ¥2，可用参数覆盖，超出时停下请示。 |
