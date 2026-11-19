# 与开源翻译项目和行业流程的对比

版本 2026-11-10。目的：说清楚本项目从哪些项目学了什么、哪些不采用、哪些是别处没有而我们必须自己做的。

> 说明：以下项目的功能描述来自其公开 README 与论文摘要，均未在本项目中做过同文对比测试。哪一套在分类学文献上更准，需要用第 6 节的基准测试回答。

---

## 1. 对比对象

| 类别 | 项目 / 标准 | 一句话 |
|---|---|---|
| 反思式翻译 | [andrewyng/translation-agent](https://github.com/andrewyng/translation-agent) | 译 → 自评 → 改；术语表放进提示词 |
| 长书分块并行 | [deusyu/translate-book](https://github.com/deusyu/translate-book) | 分块 + manifest 哈希 + 全局术语表 + 续译状态；多代理并行 |
| 逐段忠实 | [asadeisa/book-translator](https://github.com/asadeisa/book-translator) | 段落编号、不合并不删、`check all` / `review all` |
| 多角色审校 | [senshinji/claude-translation-skill](https://github.com/senshinji/claude-translation-skill)（本仓库所用 translation-quality-codex 的来源） | 术语员 / 译者 / 独立审校 / 修订；问题按严重度分级 |
| PDF 版面保留 | [PDFMathTranslate](https://github.com/PDFMathTranslate/PDFMathTranslate)、[BabelDOC](https://github.com/funstory-ai/BabelDOC) | 解析版面 → 翻译 → 原位回填，出双语 PDF |
| 成品审计 | [vittta/translate-paper-zh](https://github.com/vittta/translate-paper-zh) | 原文清单、区域回填、覆盖与字体审计 |
| 文档解析 | [opendatalab/MinerU](https://github.com/opendatalab/MinerU) | 复杂 PDF、扫描件转结构化文本 |
| 分类学文献结构化 | [plazi/GoldenGATE-Imagine](https://github.com/plazi/GoldenGATE-Imagine) | 标注 taxonomic treatment、名称、标本记录（不翻译） |
| 研究方法 | MAPS（He et al., TACL 2024）；TransAgents；术语约束多代理翻译（ACL 2026 Industry） | 先抽关键词/主题/示例再译；模拟翻译公司分工；分析-翻译-译后编辑-审阅 |
| 行业标准 | ISO 17100:2015（翻译服务）、ISO 18587:2017（机器翻译译后编辑）、MQM 错误分类 | 译者 + 独立审校两人原则；译后编辑流程；错误类型与严重度 |
| 传统 CAT 工具 | OmegaT、Trados 等；TMX（翻译记忆）、TBX（术语库交换格式） | 翻译记忆、术语库、段对齐，是人工翻译行业几十年的基础设施 |

---

## 2. 逐项对比

| 能力 | translation-agent | translate-book | book-translator | claude-translation-skill | PDFMathTranslate / BabelDOC | CAT 工具 | **本项目** |
|---|---|---|---|---|---|---|---|
| 长书分块、续译 | — | ✔ | ✔ | — | 部分 | ✔ | ✔（借 translate-book） |
| 段落编号、逐段对应 | — | 部分 | ✔ | ✔ | — | ✔ | ✔（段号挂问题、验证、对照） |
| 术语表注入 | ✔（手写） | ✔（抽样生成） | ✔ | ✔（带置信度） | — | ✔ | ✔ |
| **术语有出处与依据等级** | — | — | — | 部分（来源 + 置信度） | — | 人工录入 | **✔ 书名 + 页码 / 名词委条目号；依据次序裁定** |
| **同一英文按类群分义项** | — | — | — | — | — | 少见 | **✔（operculum、uncini 按科不同）** |
| 独立审校 | 同模型自评 | — | 双语审阅 | 同模型多角色 | — | 人工 | **✔ 必须换模型；主会话裁定** |
| 审校分级 | — | — | — | ✔ | — | — | ✔ MQM + 分类学专项 |
| **外部审查意见的裁定** | — | — | — | — | — | — | **✔ 用字类意见先查志书计数** |
| 数字、专名自动核对 | — | 部分 | ✔ | 清单 | — | QA 插件 | ✔ + 学名、引文、图号 |
| **分类学专用验证** | — | — | — | — | — | — | **✔ 学名、命名人年份、计数、检索表（待写）、异名** |
| **学目标语领域写法** | — | — | — | — | — | — | **✔ 从志书归纳「具/无 + 阿拉伯数字」等表述** |
| **错误回流成自动检查** | — | 术语反馈重译 | — | — | — | — | **✔ 陷阱表 → 回归检查** |
| 版面保留 | — | — | — | — | ✔ | — | ✘（文字与图分离，重新排版） |
| 出版排版 | — | Word/EPUB/PDF | Word/PDF/EPUB | — | 双语 PDF | — | ✔ Word/PDF/A、插图浮动、目录量页、参考文献、索引 |
| **从资料建结构化数据** | — | — | — | — | — | — | **✔ 物种记述 / 名称用法 / 名录（work/treatment/name_usage）** |
| 与模型无关 | ✔ | ✔ | ✔ | Claude 为主 | 多服务 | — | ✔ 命令行 + 文件交接 |

---

## 3. 采纳了什么

| 来源 | 采纳的做法 | 在本项目中的位置 |
|---|---|---|
| translation-agent | 「译后反思再改」 | 改成**异模型**译审（同模型自评盲点相同） |
| MAPS | 译前给关键词、主题、示例 | 「志书例句检索」：为形态段落取 2–3 段同类原文描述作示范 |
| translate-book | 分块、哈希、续译状态；术语变了只重译受影响分块 | `term_impact.py`：改译名前列出受影响章与上下文 |
| book-translator / claude-translation-skill | 段号、正反两遍核对、数字专名清单、严重度分级 | 核译提示词、`--max-block-chars 1200` 段号 |
| translate-paper-zh | 成品审计 | 目录页码、图注位置、空白页、插图数、`zh check` |
| ISO 17100 / 18587 | 译者与审校分离；样章试译；终审 | 模块 M3 试译样章、M5 异模型译审、M8 裁定 |
| MQM | 错误类型与严重度 | 问题单 type / severity；另加分类学专项 |
| CAT 工具 | 术语库、段对齐、翻译记忆 | yiku（术语）、段对齐；计划导出 TBX 便于与 CAT 工具互通 |
| GoldenGATE（思路） | 识别 treatment 结构 | 分类数据层的记述切分（标本采集地 / 形态特征 / 地理分布 / 讨论） |

## 4. 不采用什么，为什么

| 做法 | 原因 |
|---|---|
| PDF 原位回填（PDFMathTranslate、BabelDOC） | 老扫描专著图版多、双栏、历史字体，原位回填不可靠；我们把图抽出、记录位置，译文重新排版后放回 |
| 抽样生成全书术语表（translate-book 默认） | 抽样会漏科名和形态术语；改为逐章术语表 + 缺口清单 |
| 以模型置信度代替出处 | 置信度不是证据；每个术语须有书名页码或名词委条目 |
| 同一模型多角色互审 | 共享同样的知识盲点；译审必须换模型 |
| BLEU、模型自评分 | 不能反映分类学错误；用人工标注的基准测试 |

## 5. 别处没有、必须自己做的

1. **出处与依据次序**：用户核定 > 正式记述该类群的志书 > 近海1988 > 名录 > 名词委（志书没有时）> 专题论文 > 暂定（WoRMS 派生、词源）。区分「正式记述」与「顺带列名」（卷9 表2 的「节节虫科」教训）。
2. **按类群分义项**：同一英文术语在不同科可有不同定名，术语库带类群范围。
3. **学目标语领域写法**：从中国志书归纳形态描述惯例，用计数核实，再写进规则（如卷33「具1」628 次、「1对」428 次 vs「一对」7 次）。
4. **裁定须查证**：外部审查的用字意见先查志书实际用法（「背外侧」在志书 0 次，故驳回）。
5. **分类学验证**：学名、命名人年份、计数、引文、图号；检索表编号与跳转（待写）。
6. **分类数据层**：同一批资料同时产出译名、写法规范和结构化物种记述、名录。
7. **陷阱表回归**：每个错误变成一条自动检查。

## 6. 基准测试（计划）

选一篇 15–30 页、含物种描述、比较表、二歧检索表、图注的分类学论文，由分类学家给出标准答案。每次改流程后重跑，按 7 项打分：全文覆盖、术语一致、分类学准确（计数 / 性状状态 / 比较关系）、检索表正确、学名保真、可追溯、成品质量。不用 BLEU 和模型自评。必要时用同一篇文献跑 translate-book、translation-agent 作对照。

---

## 7. 2026-11-15 增补：主流商用 MT / CAT、更多开源项目、Google 提速

> 本节是一次完整调研的结论，**下次需要对比时先读本节和 `docs/research/2026-11-15/` 原始报告，不要重做**；只在下表「复查时机」到期或出现新产品时增补。
> 原始报告（逐条带出处 URL、星数、日期，未核实者标「未确证」）：`commercial_mt.md`（15 个商用产品）、`opensource_projects.md`（约 40 个 GitHub 项目）、`google_speed.md`（免费端点提速与实测）、`codex_astra_review.md`（gpt-6-astra 对本系统的审查与 P0/P1/P2 方案）。

### 7.1 商用机器翻译与 CAT/QA（摘要）

| 产品 | 术语控制 | 翻译记忆/自适应 | QA | 保/俄/日/拉丁 | 对我们最有用的一点 |
|---|---|---|---|---|---|
| DeepL | 术语表（不保证命中）；context 只当语境 | TM（阈值 75） | 段级质量问题（type/severity/span） | 拉丁无术语表/TM | 段级问题单格式 |
| Google Cloud | v3 术语表；Adaptive（取最相似 5 对）；LLM 模型 | Adaptive 数据集 | — | TLLM 无拉丁 | 检索式 few-shot |
| Azure / Amazon | 动态词典 / 自定义术语（**官方说不保证**） | Custom Translator / Active Custom | — | 无拉丁 | 术语一律自己回检 |
| Lara（ModernMT） | 术语表 > TM > 模型 | 自适应 TM | — | — | ModernMT **2026-12-31 停服** |
| 百度 / 有道 / 腾讯 | 术语干预（"调优"非替换） | — | — | 有道支持拉丁 | 腾讯 TranSmart **2026-11-24 关闭** |
| Trados / memoQ / Xbench / Verifika | 禁用词表、关键词表 | TM、上下文匹配 101/102% | 数字（按语言格式）、标签、一致性、目标=源、空译、重复词 | — | 确定性 QA 清单 |
| Phrase / Smartcat | — | TM 优先 → 引擎路由 → QA | 质量分（QPS/TQS）阈值路由人工 | Phrase 不支持保加利亚源 | 阈值路由人工队列 |

结论：**没有一家保证术语/学名命中**，拉丁语支持普遍缺失，供应商有停服风险——学名保护、术语回检和异模型核对必须在我们自己这一侧完成。

### 7.2 开源项目（本节新增，§1 已有的不重复）

| 项目（星数，2026-11） | 机制 | 采纳情况 |
|---|---|---|
| yihong0618/bilingual_book_maker（~9.9k） | plan.json 干跑 + 覆盖率守卫；局部重译；批处理半价 | 覆盖守卫已做（transqa.coverage）；干跑计划 P1 |
| hydropix/TranslateBooksWithLLMs（~2.6k，AGPL） | 块内命中的术语才注入；术语后修只改命中句 | 只送相关术语已做（auto_translate.relevant）；定点后修 P1（只借思路，不复制 AGPL 代码） |
| FolioLoom | 源文账本、零遗漏发布闸门、术语波次冻结 | 发布阻断部分已做（check_failed、human_review_queue）；状态账本 P0 待做 |
| sukamenev/booktrans | 先侦察再译、盲编、双文核对 | 异模型全文复核已做 |
| gnames/gnfinder + gnparser | 学名发现与解析 | P1：接入 transqa.taxonomy 作学名第二来源 |
| Unbabel/COMET、google-research/metricx、GEMBA-MQM | 质量估计 | P2：只作人工队列排序信号，不作通过标准 |
| ssut/py-googletrans、deep-translator、translators | Google 免费端点封装 | 无真批量；我们自写 urllib 客户端 |
| kiss-translator、Traduzir-paginas-web、LDDC | translateHtml 数组批量 | 需 Google 挂件内置 key，权限策略未放行，**待用户决定** |
| immersive-translate | 只发布 Release，**非开源** | — |

### 7.3 Google 免费端点提速（实测，保→英，每组 150 段）

| 方案 | 段/分钟 | 处理 |
|---|---|---|
| gtrans 原实现（逐段、每段停 1–2 s、顺序） | ~20 | 已淘汰 |
| gtx 逐段，4 线程 + 0.5 s 间隔 | 237 | — |
| **gtx 逐段，8 线程无间隔，429/5xx 全体冷却** | **320** | **已采用**：`gtrans.Google.prefetch()`，auto_translate 复用同一客户端 |
| gtx 拼段（多段一请求） | 21（大量 429） | 不采用 |
| translateHtml 数组批量 | 调研单样本约 4400 | 未启用（见上） |

注意：同机 Python `requests` 库对 gtx 返回 429，`urllib`/`curl` 正常（原因未确证）；本项目只用 urllib。缓存键含语言对（英→中沿用旧键）。

### 7.4 本次已落地（2026-11-15，668 项测试通过）

| 做法 | 来源 | 位置 |
|---|---|---|
| 共用 QA 层：通用检查（覆盖/页序/漏段、数字双向含数词与千分位、异常文字、残留原文、否定风险、禁用词）+ 分类学插件（学名按次数与顺序、括号命名人、检索表图、图版号）；问题带 critical/major/minor/info | CAT QA、DeepL 问题格式、architecture.md §5、astra 审查 | `transqa/`、`tests/test_transqa.py` |
| 审查发现的 5 个漏检探针成为回归用例 | astra 审查 | `tests/test_transqa.py` |
| 异模型全文复核 + 覆盖回执；第二模型独有发现进人工队列；找错与复核同模型即拒绝 | booktrans、ISO 17100 双人原则 | `scripts/auto_translate.py` stage_check |
| critical 改动（学名、数字、有/无、检索表）不自动落实，写 `human_review_queue.csv` | Phrase/Smartcat 阈值路由、MQM | 同上 |
| 闸口：任何类型都不得丢数字和斜体学名；有拒绝行退出码 1 | memoQ 数字检查、astra 审查 | `scripts/apply_issues.py` |
| DeepSeek 每次重试前重查夜间窗口 | 用户规定、astra 审查 | `scripts/llm_engines.py` |
| Google 并发预取、全体冷却、统一客户端 | 实测 | `scripts/gtrans.py`、`scripts/auto_translate.py` |

### 7.4b 第二轮（同日）：成本函数视角的四项改动

依据：外部建议「少送字、少重送、少返工；输出单价是输入数倍，最贵的是让译文被生成第二遍；prompt 按稳定性分层」，经本项目数据核对后采纳。

| 改动 | 位置 | 实测（Marinov 9 页基准页，deepseek-flash 关思考） |
|---|---|---|
| 块类型判定：异名录、文献、索引不送 Google、不送模型，按转写表与缩写表确定性处理；处理后仍残留原文的才退回模型 | `transqa/blocks.py`；`auto_translate.stage_draft/stage_revise` | 全书异名录 147 块（6.9% 字符）走确定性处理，退回模型 2 块；基准页里只有 3 块 |
| 段 ID 协议：送模型的每段带 `⟦p103_s2⟧`，须逐 ID 返回；缺、多、重复 ID 都算失败并重试；按模板原样拼回页标记、图版行 | `transqa/segments.split_template/render`；`auto_translate.parse_segments` | 101 段 ID 全部对齐，无 ID 残留 |
| 稳定前缀：system = 规则 + 全书术语表 + 转写表（整本书字节不变）；每段只送待改写的段 | `auto_translate.stable_prefix` | 第 2、3 段缓存命中 8,576 token；**总费用与旧基准相当**（旧基准提示词碰巧也把全表放在开头）；相对原 auto 档「逐段筛术语放 user 开头」主要收益是全书一致性而非省钱 |
| 报告指标：每页输入/输出 token、缓存命中率、返工率、确定性处理段数、送 Google 段数；订阅额度标「未计价」而不是 0 | `auto_translate.report` | 基准：每页输入 6,706（含缓存）/输出 1,171；缓存命中率 54%；返工率 1/3 |

质量：transqa 阻断项旧稿 2 条（漏数字 76、学名 Grubca），新稿 1 条（Grubca 为原文转录的 OCR 误读，模型改成了正确的 Grubea）。
核对结论：输出与输入费用相当（基准 $0.0044 vs $0.0043），所以**不让模型重写整段来做核对**：找错与复核只输出 JSON 判定与回执。
外部建议里「剥离非译内容可砍 40–60%」在 Marinov 实测只有约 14–17%（检索表、图注含描述，照常翻译）；「缓存折扣 75–90%」在 DeepSeek 实为约 98%（$0.003 vs $0.15/M）。
「脚本卡关代替全量双向审校」**不采纳**：p.249「两条横向纤毛环」、「цифта=对」这类意义错误脚本看不见。

### 7.5 不采纳及理由（避免反复讨论）

| 做法 | 理由 |
|---|---|
| TM 相似度 ≥75% 直接复用、跳过核对 | 一个数字或否定词即可改变诊断；模糊匹配只作 few-shot 范例 |
| 只核对脚本或第一模型标出的疑点 | 两者都漏的错误发现不了；全文异模型复核保留 |
| 只比较规范化学名集合 | 丢失重复、位置、括号命名人；比较带次数与顺序 |
| 全量数字、地名换占位符 | 遮蔽数量关系；只锁定不可变实体（学名等，P1） |
| COMET/MetricX/QE 分高即通过 | 对分类学与小语种未验证；只作排序信号 |
| 让模型自动学术语 | 放大未核实译法；术语仍以 yiku（有出处）为准 |
| 抓取、硬编码或轮换 Google 挂件 key、代理、指纹伪装 | 未获授权；不做规避 |

### 7.6 待做（按 astra 审查优先级）

- **P0**：段落状态机与租约续跑（从 `direct_mode.py` 提炼 `claim/commit`，按完整依赖指纹失效）；`run_batches`/`gtrans` 也改用 transqa。
- **P1**：块类型判定扩到标本记录（采集号、产地）、图注独立通道；yiku 多语言（词形、方向、领域范围）；已批准译文的检索式 few-shot；学名占位锁定 + gnparser；干跑计划与覆盖阈值；报告区分字符、token、订阅额度、未知用量。
- **P2**：QE 排序信号；商用 MT 适配器（只在语言覆盖与试译通过后接入）；按语言对与文本类型分层的基准，开发集与锁定测试集分离。

### 7.7 复查时机

商用产品价格与停服信息每 6 个月复查一次（下次 2027-05）；Google 免费端点在出现连续 429 或速度明显下降时复测；开源项目在立项新语种或新文档类型时增补。
