---
name: yzz-translate
description: 英文专业书译成中文的通用流水线，任何领域、任何模型（Claude、Codex、DeepSeek）都可执行。核心是术语：先从 yiku 术语库注入有出处的定名，库里没有的去权威资料定向查，再查不到的分类阶元依 WoRMS 和词源拟「暂定」译名；然后由一个模型初译、另一个模型逐句核译，最后由脚本闸口替换并检查一致性。按领域加载规则包（分类学/多毛类、进化生物学/物种概念/思想史，可新增）。也负责从经典译作和名家论著学术语与译风。用户提到翻译专著/教材/Handbook/Rouse/Mayr、英译中、学译法、译风、参考译作、核译、校对或润色译文、术语对照、科名中文名、译名统一时使用。排版插图不在此技能内。
---

# yzz-translate · 英译中专业翻译

**目标是译准。** 普通句子任何模型都能译好，所以本技能的重点是术语，其次是忠实。排版和插图留到定稿后另做。

- 脚本目录：`S=~/.claude/skills/yzz-translate/scripts`。
- Codex 端的 `~/.codex/skills/yzz-translate` 是同一目录的软链接。
- 工作区总入口：`/mnt/p/翻译-译作/AGENTS.md`；总方案：`/mnt/p/翻译-译作/方案.md`。
- 2026-11-09 改版前的文件备份在 `_backup_20261109/`。

## 1. 文件分层（按注入顺序）
| 层 | 文件 | 作用 | 谁读 |
|---|---|---|---|
| 通用硬规则 | [RULES.md](RULES.md) | 忠实、术语、引证、格式；任何领域都适用，违反即错 | 译者、核译者 |
| 领域包 | `domains/<领域>.md` | 该领域的术语依据、领域用字、专名惯例 | 译者、核译者 |
| 译风 | [STYLE.md](STYLE.md) | 从经典译作提炼的中文表达习惯 | 译者、核译者 |
| 术语库 | yiku（技能 `yiku`） | 生成每章术语表、检查术语一致性 | 脚本调用 |
| 术语依据 | [TERMS.md](TERMS.md) | 来源优先级、本地资料路径 | 查证者、裁定者 |
| 提示词 | [PROMPTS.md](PROMPTS.md) | 初译、核译、查证三个模板 | 调度者 |

现有领域包：`分类学`（多毛类、环节动物）、`进化生物学`（物种概念、思想史）。遇到新领域时，复制 `domains/_模板.md` 新建。

## 2. 角色（按能力分工，不看厂商）
| 角色 | 做什么 | 用谁 |
|---|---|---|
| 执行者 | 抽取、初译、核译、查找缺口 | 任何模型，token 不限（Codex、DeepSeek、Claude 子代理） |
| 闸口 | 核验出处、替换、一致性检查 | 脚本，不用模型 |
| 裁定者 | 处理冲突表、质疑清单、暂定清单，并做抽查 | 用户，或最强模型的主会话 |

- 初译和核译**必须由不同的模型**来做，避免同一个模型的盲点被自己放过。
- 执行者不得再派生子任务。每完成一节就写盘。

## 3. 工程结构（每本书一个目录）
```
<书>/src_en/chNN.txt         英文原文，按章分文件
<书>/译文/chNN_<中文名>.md     译文
<书>/核译/issues/bNN.jsonl    核译问题清单（只列问题，不改译文）
<书>/核译/uncertain_terms.tsv  暂定术语，含词源暂定
<书>/核译/质疑清单.tsv          对经典译法的质疑
<书>/核译/抽查.tsv             抽查记录
<书>/核译/核译对照报告.md
```

## 4. 流程（按顺序执行，每步都能断点续做）
0. **定领域**：确认本书的 yiku 领域名，下文记作 `<D>`；确认 `domains/<D>.md` 已存在。
1. **切章**：运行 `python3 $S/extract.py <pdf> <起页> <止页> > src_en/chNN.txt`。扫描本用 `python3 $S/ocr_rapid.py <pdf> <outdir>`，不要用 tesseract。
   **原书页码标记**（分类学书必做，种名「每页首现拉丁名」规则依赖它）：原文里每个原书页的起点单独一行 `<!-- p.13 -->`（印刷页码）。从资料库取页用 `docstore export <key> --marked --pages <PDF页范围>`（页码偏移要先登记，没登记写 `pdfNN`）；自己清洗 OCR 拼接 src_en 时用 `direct_mode.with_page_markers`。初译提示词要求译者原样保留，直调模式下丢失或不一致的块不算完成。
1a. **切分检查**（草稿前必做，分类学书必做）：`python3 $S/split_check.py src_en/body.txt src_en/captions.txt`（或 `run_batches.py <书> --mode split --chapters body,captions`，报告写 `核译/split_check.txt`）。列出混进正文流的图注残段（段内 ≥3 个「缩写, 词;」对、Scale bar、「Fig. N.」起首）、前段以连字号结尾而后段小写起首的断词、以连字号结尾的图注、只有「Fig. N.」没有说明文字的图注；有可疑段退出码 1。逐条人工核对：图注残段移入 captions.txt，断词合并，再开始草稿，否则核译会报「漏译」并把图注残段插进正文。
2. **术语先行**（在初译之前完成）：
   1. 运行 `yiku table src_en/chNN.txt --domain <D> [--scope <类群>] [--fallback <领域>]`，得到本章术语表。表分 **HARD**（必用：学名与本领域已核译名一致者）和 **SOFT**（多译名/多义项/候选/跨领域〔回退〕，附出处页码、层级、定义语境和中文用例，由译者按本书义项取舍）。`--fallback` 缺省：分类学书回退到进化生物学，其他领域不回退。
   2. 找出缺口：本章出现、但术语库里没有的术语。用提示词 C，按 TERMS.md 和领域包列出的权威资料逐个定向查，每条都要写书名和页码。
   3. 仍然查不到的：如果是分类阶元名，按第 5 节拟「暂定」译名；其他术语直接标「暂定」，并保留英文。
3. **初译**：运行 `python3 $S/run_batches.py <书> --mode translate --chapters chNN --engine <模型A> --domain <D>`。脚本会把 RULES、领域包、STYLE 和本章术语表注入提示词。
4. **核译**：先运行 `python3 $S/plan_batches.py <书>`，再运行 `run_batches.py <书> --mode review --engine <模型B> --domain <D>`。
   **直调模式**（不经智能体，按块直接调模型，产物按块写盘、断点续跑）：`--engine deepseek-flash|deepseek-v4-pro|claude-sonnet|claude-opus`，要 `--chapters`。推荐分配：初译 `claude-sonnet`，核译 `deepseek-flash`。初译输出在 `核译/direct/<章>/out/`，合并为 `译文/<章>_直译初译.md`；核译问题单合并为 `核译/issues/<章>_direct.jsonl`，再过 `apply_issues.py --dry`。引擎封装见 `scripts/llm_engines.py`，用量记在 `核译/usage.tsv`。续跑时每块产物旁的 `.meta.json`（引擎、系统提示词与术语表的 sha256；核译另含所核译文）必须与当前设置一致，不一致报错停下，确要重做加 `--force`。核译输出必须是 JSONL 问题单或单独一行 `NO_ISSUES`，其余格式该块记为失败、不写完成文件。
   - **保真检查**（直调初译自动做，`--no-fidelity` 关闭；弱模型只管起草，格式规则交给脚本）：`fidelity_check.py --en 块.txt --zh 块.md [--fix] [--seen seen.json]`，确定性、不调模型。查拉丁名（英文里的属名/双名必须出现在中文里，缺的附英文原句；`--fix` 只在中文里已有 yiku 中文名时于其首现后补「（*Latin*）」）、惯译人名（`skill/person_names.tsv` 可增补；`--fix` 改中文并去掉名前缩写，引证与参考文献不动）、带单位数字和年份（只报告）、yiku 已核术语首现补「（English）」（各块共享首现状态）；日志 `核译/direct/<章>/fidelity/cNN.txt`。标题补英文用 `heading_bilingual.py --en body.txt --zh 译文.md [--fix]`（Title Case，默认只报告）。
   - 核译者只出 JSONL 问题清单，不改译文。
   - 先试点 1 批，裁定者抽查合格后再全面铺开，并发 3–4 个。
4a. **覆盖核对**（可选，长章或重点章）：借用工作区技能 translation-quality-codex 的分块脚本，为本章原文编段号，核译时逐段对照，保证不漏段：
   `python3 /mnt/p/翻译-译作/.claude/skills/translation-quality-codex/scripts/prepare_translation_job.py src_en/chNN.txt --out-dir 核译/blocks/chNN --max-block-chars 1200`（默认块太大：Codex 一次跑 82 个文件只分了 412 块）
   只用它的段号与审校方法（正反两遍、数字专名、结构计数、严重度/置信度分级）；**不用**它的术语表置信度（没有出处）、不用它的同模型复核代替异模型核译、不用它的排版脚本（排版用 build_docx.py + Word）。
4b. **专业表述核译**（分类学书必做）：形态描述、图注、术语表释义按 `domains/分类学.md` 第 5 节核对志书写法（具/无+阿拉伯数字+量词、电报式短句、长于/短于、或有或无、方位词）。核译者在 issues 里用 type「表述」。
4c. **外部审查意见**（Codex 等第二模型）：按 `domains/分类学.md` 第 7 节裁定——忠实度问题对照原文；用字问题先查志书计数与例句再定；逐条写裁定记录；发现一类问题就全书扫同类。
5. **过闸口**：
   - `apply_issues.py <书> 核译/issues/bNN.jsonl`：只在恰好匹配 1 次时替换；丢失英文或数字的改动自动拒绝。
   - `yiku check src zh --domain <D> [--decisions 核译/term_decisions.jsonl]`：HARD 严格检查；SOFT 按术语决策日志检查（同英文+义项必须同译名，不同义项可不同但须登记），没有日志时只给「提示」。
   - 术语决策：直调初译在译文后输出「### 术语决策」JSONL，脚本按块存 `核译/direct/<章>/decisions/` 并合并为 `核译/term_decisions.jsonl`；`yiku decide validate`（格式）→ `yiku decide review`（列出须主会话裁定的：多译名、无出处、zh 不在候选）→ `yiku decide apply --book <书>`（写回：候选，来源 `决策_<书>`；只有 `--verified` 才记已核）。
   - 种名格式（分类学书）：`run_batches.py <书> --mode species --chapters body,captions [--names 种名.tsv]`（不调模型，闸口之后、终稿核译之前跑；`--dry` 只报告）。有中文名的种按原书页规范：每页首现「中文名（*Genus species*）」，同页再现只写中文，换页再写拉丁名；图注每条算一个单元；没有中文名的种不动。名单取 yiku 的 HARD 种名，再叠加 `--names` TSV（拉丁名、中文名）。先备份 `*.bak-species` 再写回。单文件用 `species_format.py`。补拉丁名前核对 `src_en/` 对应原书页：该拉丁名（OCR 近似写法也算）不在原文那一页就不补；后接科属目…后缀或落在更长类群名里的、中文名后已带拉丁名的、已在括号里的、通名（沙蚕 ↔ sand worm）一律不动；拉丁名后的 `[OCR?]` 保留。页码标记把一句话切成两段时，先 `join_page_breaks.py <译文>`（默认只报告，`--fix` 并段、标记移到合并段之后）再跑本步。
   - 引文与图号对照（终稿后必做）：`python3 $S/cite_diff.py --en src_en/body.txt --en src_en/captions.txt --zh 译文/body_直译初译.md --zh 译文/captions_直译初译.md --out 核译/cite_diff.tsv`（或 `run_batches.py <书> --mode cite --chapters body,captions`，自动读 `核译/cite_noise.tsv`、`核译/cite_alias.tsv`）。比较 (第一作者, 年份) 和图号的多重集，已归一 and/与/和、et al./等、1980a,b、全角括号、OCR 断词；打印真差异数，有真差异退出码 1：译文多出的引文＝疑似增补/幻觉，缺失＝漏译，年份或第二作者不同＝改错。「变体?」只提示、不计入。逐条对原文裁定后，确属 OCR 或排版噪声的写进 `cite_noise.tsv`（次数须与当前一致），不得直接放过。
   - 中文通读（定稿前必做，在终稿核译及其闸口之后）：`run_batches.py <书> --mode polish --chapters body,captions`（默认 `deepseek-flash`，只在闲时跑；`--engine` 可换）。只给模型中文、不给原文，规则运行时读 STYLE.md 第 6 节；交回 type=润色 的 old→new 问题单，写盘前自动核验引证/年份/图号/斜体拉丁名/数字单位/〔译注〕/页码标记/HARD 术语不变，不过关的进 `核译/direct/<章>/rejected_polish.jsonl`；过了指纹的条目再过语义核验（每块一次请求，英文原文 + 编号 (old,new) 对发给 `--polish-check-engine`，默认 `deepseek-flash`，可与润色模型不同；查否定/谁主张什么/量词/限定语/因果，没有明确回 ok 的一律拒绝）；通过的 `核译/issues/<章>_polish.jsonl` 再过 `apply_issues.py`。顺序：final → apply_issues → **polish → apply_issues → cite → species → yiku check**。
   - `drift_check.py <书>`：检查科名漂移。
   - `qa.py <书>`：检查残留英文、标点、空格和 U+3000。
6. **抽查**：每批随机抽 20 条，由裁定者判断对错。
   - 错误率超过 5%：退回重做，并把原因写进 RULES、领域包或 STYLE。
   - 结果记入 `核译/抽查.tsv`。
7. **全书统一**：所有批次结束后，运行 `unify.py <书> terms/统一替换.tsv`。只用带边界的正则；替换后抽样检查上下文。
8. **交付**：提交核译对照报告和三份清单（暂定、质疑、冲突），由用户裁定后写回 yiku。

## 5. 没有可靠中文资料的分类阶元（用户 2026-11-09 授权）
按 TERMS.md 列出的中文来源都查不到时，按下面的顺序拟译名。
1. **WoRMS**：用 `oworms api` 或 `oworms run <Taxon>` 查以下四项：
   - 有效名，以及是否为异名。如果是异名，先找它的有效名有没有中文名。
   - 阶元。
   - 上级类群。
   - 原始描述，以及物种页上的 Etymology 注释。
2. **派生**：上级或下级阶元已有权威中文名的，直接派生，例如「豆缨虫亚科 → 豆缨虫科」「刺女虫科 → 刺女虫属」。规则见 TERMS.md。
3. **词源**：先看原始描述里的 Etymology 段；没有的，再拆解拉丁或希腊词根，意译成中文，并沿用中文命名惯例（如「××虫属」「××虫科」）。词根含义要写出依据，例如所用词典或原始文献的页码。
4. **标注**：
   - 正文写「暂定中文名（*Latin*）」。
   - 在 `uncertain_terms.tsv` 登记一行：`Latin  暂定名  依据类型（WoRMS派生/词源）  词根解释  出处`。
   - 用户裁定前，不入库为定名。

## 6. 学习新的参考书
用户加入新的「英文原著 + 中译本」或名家中文论著时，按 `/mnt/p/翻译-译作/一些经典译作/AGENTS.md` 的通用 5 步处理：
1. 用 `yiku pair`（对照书）或 `yiku paren`（中文论著）抽取。
2. 脚本核验。
3. 入库。
4. 定名。

能推广的表达规则提炼进 STYLE.md；领域用字写进对应的领域包。

## 7. 铁律
- 推测语气不得译成断言：apparently、may、suggests 分别对应「看来」「可能」「提示」，不对应「显然」。
- 没有依据，不拟科、属、种的中文名。第 5 节的 WoRMS 和词源依据算作依据，但拟出的译名必须标「暂定」。
- 经典译法照用。有怀疑时只写进质疑清单，不改译文。
- 数字、学名、引证原样保留。原文来自 OCR：疑似排印/OCR 问题不得注〔原书…〕，标 `[OCR?]` 留给人工（RULES 第 3 节）；经页图或第二来源确证的原书笔误，订正后注〔原文作 …〕；核实不了的只注〔原书如此〕。
- 不删除、不覆盖已有译文。一切改动都要经过 issues 文件和 `apply_issues.py` 闸口。
- 禁用 U+3000。交付 .docx 或 .pdf 前，运行 `python3 /mnt/p/yzz-分类工作流/yzz.py zh check`。

## 8. 低成本流程：gtrans.py（Google 免费初译 → 脚本修正 → DeepSeek flash 不开思考一次核对润色 → 报警段才开思考）
`python3 scripts/gtrans.py <英文.txt> -o <输出目录> [--domain 进化生物学] [--llm-mode rewrite|edits] [--rewrite-engine E] [--think-escalate] [--no-llm] [--dry]`。适合试读、预览和不求定稿的篇幅；整书定稿仍走第 4 节的初译 + 异模型核译。
1. 输入：空行分段；`<!-- p.N -->` 页码标记、标题、图注（`Fig.` 开头）各自成单元，标记不送 Google；被页码标记切开的半句话先合并，标记移到合并段之后。
2. Google 免费初译（gtx 端点，每段一个请求，>4500 字符按句子边界切块，间隔 1–2 秒，429/5xx 指数退避）；结果缓存在 `~/.cache/yzz-translate/gtrans_cache.sqlite`（键 sha1(原文)），重跑零请求。
3. 脚本修正（不调模型）：
   - `skill/google_fixes.tsv`（错 / 对 / 说明 / 触发词）：Google 固有错译，如 显着→显著、兄弟物种→同胞种、脑电波→灵感（brain waves）、本质主义→本质论；有触发词的只在英文里出现该词时才替换。新增错译直接加一行。
   - `yiku table` 的 HARD 术语：把 Google 对该术语单独翻译的结果换成 yiku 定名（SOFT 不自动替换）。
   - 一致性警告：同一英文术语出现 ≥2 次而译文有多种译法。
   - `fidelity_check --fix`（拉丁名、人名、数字、术语首现括注）、`heading_bilingual`、`cite_diff`（只报告）。
4. 默认 `--llm-mode rewrite`：每单元让名家译者（`STYLE.md` §6 入 system，引擎缺省 deepseek-flash 关思考，`--rewrite-engine` 可换）整段改写；改写稿过 `polish_guard`（引证、年份、数字单位、拉丁名、页码标记、HARD 术语、段数不变）才采用，否则保留初稿；采用后再做一次意义核对（flash 关思考，只报意思不一致的句子并给最小修正，修正过同一护栏；返回格式错误则保留改写稿并在 report.md 标注），`--think-escalate` 对仍有未修意义警告的单元开思考再核一次。2 段试验（Mayr）显示整段改写的可读性远高于逐条改，但可能意义漂移，故必须配意义核对。旧模式 `--llm-mode edits`：DeepSeek flash 不开思考，每单元（≤1500 英文词）一次，只回 JSON 改动。改动要求 old 恰好出现一次并通过 `polish_guard`（引证、年份、数字、拉丁名、页码标记、HARD 术语不变），否则拒绝并记入 report.md 与 edits.jsonl。这道护栏也意味着模型改不了数字、年份、学名，这类问题只能由脚本修或人工处理。
5. `--think-escalate`：第一轮之后仍有一致性警告或保真问题的单元，才开思考再跑一次（实测开思考的输出约为不开的 10 倍以上）。单个大写词的拉丁名报警多是地名（Patagonia），只记录，不触发升级。
6. 输出：`zh.md`（带页码标记）、`report.md`（逐单元：Google 字符、采纳与拒绝的改动、警告、DeepSeek token、是否开思考）、`edits.jsonl`；每次调用同时追加到 llm_engines 的 usage.tsv。
7. 规则：DeepSeek 只在北京时间 22:00–08:00 调用（`deepseek_offpeak`），除非用户授权才可设 `LLM_SKIP_OFFPEAK=1`；先用 `--dry` 看请求数和估算 token，再跑。Google 译文只是初译，术语和意思仍须按第 7 节铁律核对。
