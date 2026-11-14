# 开源项目调研：可借鉴到“分类学感知科学书籍翻译系统”的项目

- 调研日期：2026-11-15（Star 数、最后提交日期均取自当日 `gh repo view` / Hugging Face API，pushedAt 为 UTC 日期）
- 已在既有文档覆盖、本文只更新数字的项目见文末“附：既有覆盖项目数字更新”。
- 标注“未确证”表示仅凭 README/元数据无法确认，需读源码或实测。
- 我们的流水线（对照基准）：Google 免费草稿 → 廉价 LLM 修订 → 自动 QA 守卫（数字、拉丁学名、检索表关键对句、否定词）→ 第二模型语义核对 → 人工队列；分块、断点续跑、缓存。

分组：A 整书/长文翻译流水线；B 免费/开源机器翻译与模型；C 浏览器/阅读器类；D 文档解析；E 质量评估与分类学名称工具；F 术语/翻译记忆工具。每个项目一张小表，末尾给“最值得借鉴（排序）”。

---

## A. 整书/长文 LLM 翻译流水线

### A1. yihong0618/bilingual_book_maker

| 项 | 内容 |
|---|---|
| 仓库 | https://github.com/yihong0618/bilingual_book_maker |
| 星数 / 最后提交 / 许可 | 9,940 / 2026-10-30 / MIT |
| 做什么 | 把 epub/txt/md/srt/pdf 译成双语版；支持 OpenAI/Anthropic 格式端点，也可直接用 Google、DeepL、彩云、腾讯等 MT 引擎（README 的 `--api_format`） |
| 技术/架构 | `--use_context session`：单条追加式历史，8k 处压缩（`--context-compact-at`），依赖提示缓存保持人名一致；`--glossary` 文件（`term → translation` 每行一条，README 称“固定术语必须是你能负责的译法”）；`--glossary-auto` 让模型从自己的交接摘要里学术语（默认关）；`--resume` 手动断点续跑；`--plan` 模式先让 LLM 对 epub 标签分类（译/跳过）并写出 `<book>_plan.json`，覆盖率低于 `--plan-min-coverage`（默认 0.5）即中止；`--parallel-workers` 按章并行；`--batch-api` 走 Anthropic Message Batches 半价；`--retranslate` 按起止字符串局部重译；还提供给 Codex/Claude Code 用的 skill |
| 优点 | 社区最大；MT 引擎与 LLM 引擎同一入口；成本控制（批处理半价、缓存价计费、进度条显示花费）；局部重译与 plan 干跑（`--plan-dry-run`）成熟 |
| 缺点 | README 未见数字/专名/否定等自动 QA 与第二模型核对（未确证，需读源码）；术语表是手写文本、无出处字段；`--resume` 与 `--parallel-workers` 互斥 |
| 可借鉴 | (1) “plan.json 干跑 + 覆盖率守卫”：我们在整书开跑前先产出分块/标签计划并设最低覆盖率闸口，防止整本译错区域；(2) 按起止字符串局部重译，用于人工队列退回后的最小重译；(3) 价格表 + 缓存读价的花费进度条，便于“Google 草稿 + 廉价 LLM”两段成本核算；(4) 批处理 API 半价通道，适合夜间整本跑 |

### A2. hydropix/TranslateBooksWithLLMs（TBL）

| 项 | 内容 |
|---|---|
| 仓库 | https://github.com/hydropix/TranslateBooksWithLLMs |
| 星数 / 最后提交 / 许可 | 2,594 / 2026-11-14 / AGPL-3.0 |
| 做什么 | 桌面/Web 应用，译 EPUB/SRT/DOCX/PDF/TXT；Ollama 本地或 DeepSeek/Gemini/Mistral/OpenAI/OpenRouter 等云端 |
| 技术/架构 | 基于 token 的分块（默认 450 token/块）+ 段间上下文；检查点断点续跑；术语表 `docs/GLOSSARY.md`：只在“块内确实出现该词”时才把 `MANDATORY` 术语块注入系统提示，其余块不耗 token；可 LLM/NER 自动抽取术语；`docs/TERM_FIX.md`：对已译成稿做术语后修，只改含错误译法的句子，其余字节原样写回，支持通配 `Drakbrand*` 和先扫描后改（`--fix-terms-scan` 不调用 LLM）；`--refine` 二次润色；`--text-cleanup` OCR 清理；`docs/JUDGE_RUBRIC_V2.md`：LLM 评审四维分（accuracy/fluency/style/overall）、锚定到专业人译、overall 有硬上限（§4）、评语 ≤200 ASCII 字符，并有按目标语言的模型基准（wiki） |
| 优点 | 术语注入按需、术语后修不重译，工程上最贴近“术语一致性”；基准体系可复用；本地模型免费 |
| 缺点 | PDF 只能重排（reflow），不保留原版面；块很小（450 token），检索表这类跨段结构易被切碎（推断，未实测）；AGPL 许可，直接复制代码会传染 |
| 可借鉴 | (1) 术语按块命中注入（我们的拉丁学名/中文名对照表应同样只注入块内出现项，降低 token 与干扰）；(2) “术语后修”模式：QA 发现某学名译法错误时，用规则表只改命中句，避免整章重译；(3) 评审 rubric 的“硬上限”设计，可改写成我们二次核对模型的评分规则（如数字错误则 overall≤4）；(4) 通配前缀匹配处理词形变化 |

### A3. oomol-lab/epub-translator 与 oomol-lab/pdf-craft

| 项 | 内容 |
|---|---|
| 仓库 | https://github.com/oomol-lab/epub-translator （882★ / 2026-09-18 / MIT）；https://github.com/oomol-lab/pdf-craft （6,677★ / 2026-11-14 / MIT） |
| 做什么 | epub-translator：保留结构的双语 EPUB；pdf-craft：扫描书 PDF → Markdown/EPUB（OCR），并可翻译、把译文写回原 PDF 页面 |
| 技术/架构 | epub-translator 把“翻译”和“XML 结构回填（fill）”分成两次 LLM 调用，可用不同模型与温度（fill 用低温 0.3）；`on_fill_failed` 回调区分可恢复/致命错误，默认最多重试 5 次，致命错误会留在最终 EPUB；`LLM(cache_path=…)` 磁盘缓存；pdf-craft 用 DeepSeek-OCR 兼容服务做 OCR，OCR 与翻译配置相互独立，PCEX 中间文件可复用 |
| 优点 | 结构保真的“两步法”思路；失败事件显式暴露；扫描书 OCR 到 EPUB 的完整链路 |
| 缺点 | 无术语表接口（README 未见，未确证）；译文写回 PDF 需 Ghostscript 和本机字体，README 自称需人工核对版面 |
| 可借鉴 | (1) 把“内容翻译”与“标记/脚注/对句编号还原”拆成两个步骤，并对还原步骤做结构校验——对我们的检索表（对句编号 1(2)、2(1)）和脚注很贴合；(2) 对扫描老专著，pdf-craft 可作为 MinerU 之外的 OCR→EPUB 备选，需实测 19 世纪双栏、拉丁学名斜体的识别率（未确证） |

### A4. neavo/LinguaGacha

| 项 | 内容 |
|---|---|
| 仓库 | https://github.com/neavo/LinguaGacha |
| 星数 / 最后提交 / 许可 | 2,699 / 2026-11-14 / 许可字段为空（README 注明商用需联系作者授权，视为非标准许可） |
| 做什么 | 面向字幕、电子书、游戏文本的“AGENT 式”翻译器（README 自称 Harness） |
| 技术/架构 | 自动生成术语表保证专名全书统一；“文本保护”（规则保护不应被翻译的片段，见 wiki TextPreserve）；“语义化智能审校”：只指出问题，由 agent 修正润色；校对页（Proofreading）；文本替换（后处理规则）|
| 优点 | 术语表 + 文本保护 + 审校三件套齐全，且面向非技术用户 |
| 缺点 | 文档主要在 wiki，README 不含算法细节，实现细节未确证；商用授权限制 |
| 可借鉴 | “文本保护 = 正则白名单占位”与我们的 Latin 名/数字保护同构：翻译前把学名、命名人+年份、数字量纲替换为占位符，译后还原并校验占位符数量一致 |

### A5. sukamenev/booktrans

| 项 | 内容 |
|---|---|
| 仓库 | https://github.com/sukamenev/booktrans |
| 星数 / 最后提交 / 许可 | 55 / 2026-11-08 / MIT |
| 做什么 | 整本书一次跑完（epub/fb2/html/pdf/md/txt → epub/fb2/html/md/txt/LaTeX/pdf），Claude Code/Codex/Antigravity 或 API 驱动 |
| 技术/架构 | 十遍流水线：markup（对样式普查，让模型判断各 class 是标题/正文/垃圾，结果写 `work/structure.json` 可手改）→ scouting（先通读全书，记录人名/术语/性别/称谓）→ headings（所有标题一次翻译以保证一致）→ translation（约 2600 词/块，带情节摘要、上一块尾部、累计术语）→ editing（“不看原文”的润色）→ verification（把编辑的疑点连同原文交给核对者：确属作者错误则加脚注、翻译错误则改、无据则驳回；默认全文逐对核对遗漏、意思反转、数字和量纲错、弱化内容）→ footnotes → index → assembly → checks（完整性、数字、长度、残留原文、脚注引用、术语）。拒绝截断或错位回复，自动重试/换模型；`--like` 用前几本书的工作目录沿用已接受的译名；`--only qa` 干跑看标题数/段落数/去除量 |
| 优点 | 与我们的流水线目标几乎同构（草稿 → 修订 → 不同视角核对 → 校验）；编辑“盲看原文”再由核对者“同看两边”的分工；术语注册表分“共享框架 + 不设上限的实体表”，请求时只带相关行 |
| 缺点 | 面向小说（叙述者声音、称谓表），分类学专著用不上的部分多；星数少、项目新，稳定性未确证；单人开发 |
| 可借鉴 | (1) 先“通读侦察”再翻译：为每本专著先扫出学名、术语、命名人、缩写、检索表结构，生成术语注册表（正好对接 yiku 术语库）；(2) “编辑盲看原文、核对者看双文”的两级分工，降低第二模型的成本——只有编辑标出的疑点和脚本检出的数字/学名异常才送核对；(3) `--only qa` 的开跑前样式普查；(4) 拒绝截断/错位回复的闸口；(5) 重命名后只重核受影响块的“术语改动传播”机制 |

### A6. daanaagua/FolioLoom

| 项 | 内容 |
|---|---|
| 仓库 | https://github.com/daanaagua/FolioLoom |
| 星数 / 最后提交 / 许可 | 70 / 2026-10-13 / MIT |
| 做什么 | 长篇小说“连续性感知”翻译引擎（TypeScript 核心 + Electron 桌面 + Python 输入适配），SQLite 状态库 |
| 技术/架构 | 源文件“无损账本”（哈希与位置映射）、新导入保留“源范围证书”，可核对每个原文段是否都被译到；每个并行波次冻结术语锚点；术语和实体别名带证据入库；导入术语 JSON/YAML/CSV/XLSX 带字段映射与冲突处理；全书运行中可改术语，改动在下一个耐久波次边界生效；同一实体可按原文块范围使用不同译名；术语追溯修订（retrofit）支持预览、可回滚、并作为严格导出的闸门；确定性检查 + 一次有界本地修复（遗漏、残留、结构错误）；EPUB 以原书为模板导出，结构槽位或内部链接无效则拒绝发布；`book doctor` 不调模型做覆盖/分块/异常检查；`book review scan/run/status` 免费风险扫描 + 单独预算的只读语义比对 |
| 优点 | “可审计”工程化程度最高：账本、哈希、波次、回滚、严格导出 |
| 缺点 | 仅 Windows 桌面包；面向小说；Node 24+ 依赖较重；项目新（未确证长期维护） |
| 可借鉴 | (1) 源覆盖账本：每个源段落哈希 + 译文映射，导出前检查“零遗漏”；(2) 术语按波次冻结，避免并行块之间漂移；(3) 同一实体按范围用不同译名——对分类学很重要（同一拉丁名在不同修订里有不同有效名/中文名）；(4) 导出闸门：存在未决 QA 项则拒绝生成最终稿 |

### A7. YutongWang1216/DocMTAgent（DelTA，ICLR 2025）

| 项 | 内容 |
|---|---|
| 仓库 | https://github.com/YutongWang1216/DocMTAgent ；论文 arXiv:2410.08143 |
| 星数 / 最后提交 / 许可 | 65 / 2025-02-10 / Apache-2.0 |
| 做什么 | 文档级翻译代理，四层记忆：专名记录（首次译法，之后复用）、双语摘要、长时记忆（宽跨度上下文句，检索相关句）、短时记忆（窄跨度，作示例） |
| 技术/架构 | 在线逐句翻译，提示词中拼入四类记忆；提供 LTCR-1 术语一致性指标脚本（`eval_consistency/`）；骨干可用 GPT 或 Qwen |
| 优点 | 有论文和指标背书；“专名记录 + 摘要 + 检索”是长文一致性的最小充分集 |
| 缺点 | 面向句级流式翻译，非整书工程；自 2025-02 起无提交；骨干模型较旧（未确证新模型表现） |
| 可借鉴 | LTCR-1（术语一致性率）可直接作为我们“同一学名译法全书一致性”的评估指标；专名记录对应我们的“首现定名 + 全书复用” |

### A8. BigDawnGhost/wenyi

| 项 | 内容 |
|---|---|
| 仓库 | https://github.com/BigDawnGhost/wenyi |
| 星数 / 最后提交 / 许可 | 2,921 / 2026-11-14 / GPL-3.0 |
| 做什么 | 桌面/Web 长文翻译（小说、社科专著）；MinerU 为 PDF 默认输入，可选 BabelDOC 桥保版面 |
| 技术/架构 | 章节摘要 + 全书梗概 + 滚动上下文；翻译中抽取专名/术语，冲突译法被提出来待人裁定并回灌后续批次；可选润色与“证据驱动的全书审校”（shadow fixing，会多轮全书审查，token 开销大）；按操作选模型；断点续跑；EPUB 译文写回原 XHTML 模板 |
| 优点 | “冲突译法浮出、人裁定、回灌”闭环；与 MinerU/BabelDOC 链路已打通，和我们既有调研重叠度高 |
| 缺点 | GPL-3.0；README 自述全书审校显著增加 token；细节需读源码（未确证） |
| 可借鉴 | 术语冲突队列：同一源词出现≥2 种译法时自动进人工队列，裁定后回灌；可直接并入我们的“人工队列”设计 |

### A9. purecodework/bookllm 与 xunbu/docutranslate

| 项 | 内容 |
|---|---|
| 仓库 | https://github.com/purecodework/bookllm （44★ / 2026-10-11 / MIT）；https://github.com/xunbu/docutranslate （1,373★ / 2026-11-01 / MPL-2.0） |
| 做什么 | bookllm：自托管，术语抽取 + 审校 + 润色三段式，“Sidekick”第二模型专做审校/润色，按页术语上下文，PDF 含 OCR；docutranslate：多格式（pdf/docx/xlsx/md/epub/srt/json）本地文件翻译，术语表可自动生成，PDF 先经 MinerU（在线或本地）转 Markdown，有 MCP、REST、异步接口 |
| 优点 | bookllm 的“主模型 + 副模型”分工与我们的“修订模型 + 核对模型”同构；docutranslate 提供 MCP/REST 便于接入 |
| 缺点 | docutranslate 译 PDF 会丢版面（README 明说）；两者星数低或功能较通用，细节未确证 |
| 可借鉴 | 术语抽取作为独立前置阶段，产物为可编辑文件而不是隐式提示；docutranslate 的“JSONPath 指定要译的字段”可用于我们的结构化中间格式（段落 JSON）只译指定字段 |

---

## B. 免费/开源机器翻译与开源 MT 大模型

### B1. LibreTranslate、Argos Translate、LTEngine、CTranslate2

| 项 | 内容 |
|---|---|
| 仓库 | https://github.com/LibreTranslate/LibreTranslate （17,703★ / 2026-11-14 / AGPL-3.0）；https://github.com/argosopentech/argos-translate （6,654★ / 2026-11-14 / MIT）；https://github.com/LibreTranslate/LTEngine （214★ / 2026-10-14 / AGPL-3.0）；https://github.com/OpenNMT/CTranslate2 （4,749★ / 2026-11-10 / MIT） |
| 做什么 | LibreTranslate：自托管、可离线的机器翻译 REST API，引擎是 Argos Translate；Argos：基于 OpenNMT 的离线 Python 库，模型是 `.argosmodel` 包，没有直接语对时自动经英语等中间语言“枢轴”翻译；LTEngine：Rust 编写、兼容 LibreTranslate API，改由本地 llama.cpp 跑 Gemma3 1B/4B/12B/27B（27B 约 18G 显存）；CTranslate2：高效 Transformer 推理引擎，Argos 的底层 |
| 技术/架构 | 小型 Transformer（Argos）→ 句子切分 + 逐句翻译；LTEngine 把 LLM 封装成与 LibreTranslate 相同的 API |
| 优点 | 完全离线、可私有部署、无调用配额；API 兼容使“Google 草稿”这一层可无缝换成本地后端；LTEngine 允许用同一接口换 TranslateGemma/Hy-MT GGUF（需验证，未确证） |
| 缺点 | Argos 语种覆盖远少于 NLLB 的 200 种（README 语言表具体数量未完整核对，未确证）、质量低于 Google/NLLB 级别（推断，未实测），且以句子为单位、不懂学名；AGPL 对内部使用影响不大但对再分发有约束 |
| 可借鉴 | (1) 把草稿层抽象成“LibreTranslate 兼容 HTTP 接口”，Google 免费端点失效或被限流时可降级到本地 LTEngine/Argos，不改流水线；(2) Argos 的“枢轴语言”思路用于源语言冷门（如俄、德、拉丁文旧著）而目标语言为中文的场景：X→英→中，但需在枢轴处做学名保护，否则两次翻译会放大学名损伤 |

### B2. ssut/py-googletrans、nidhaloff/deep-translator、UlionTse/translators（免费草稿层的三种封装）

| 项目 | 星数 / 最后提交 / 许可 | 说明 |
|---|---|---|
| ssut/py-googletrans https://github.com/ssut/py-googletrans | 4,300 / 2026-08-08 / MIT | 非官方 Google 网页接口封装，v4.0.0（2024-12-13）起；支持批量、异步、HTTP/2、代理、自定义服务 URL；README 自述“单段上限 15k 字符”、“不保证稳定”、“若出现 HTTP 5xx 多半是 IP 被封”，并建议要稳定就用官方 API |
| nidhaloff/deep-translator https://github.com/nidhaloff/deep-translator | 2,053 / 2024-07-23 / Apache-2.0 | 统一封装 Google/DeepL/Microsoft/MyMemory/Linguee/Pons/Yandex 等；支持代理；最后提交较久，维护状态存疑 |
| UlionTse/translators https://github.com/UlionTse/translators | 2,694 / 2026-01-26 / GPL-3.0 | 封装 20 余家服务（README 表列 Niutrans、MyMemory、Alibaba、Lara、Baidu、ModernMt、VolcEngine、Google、Bing、DeepL、Yandex、Argos 等），标注支持语言数；GPL-3.0 对内嵌分发有约束 |

- 共同点：都是“网页端点 / 免费额度”封装，随对方改版随时失效，且可能违反服务条款（未逐一核对，未确证）。
- 可借鉴：(1) 我们已用 Google 免费草稿，建议做“多后端回落链”：Google → Bing/Alibaba（经 UlionTse 封装）→ 本地 LTEngine/Hy-MT；(2) 草稿层必须带“单段 ≤15k 字符 + 指数退避 + 缓存”，googletrans 的 15k 限制和封 IP 风险应写进分块参数；(3) 因草稿不可信，把它只当“预翻译”：QA 守卫对草稿阶段的数字/学名破坏要在 LLM 修订前就记录，便于归因。

### B3. 开源 MT 专用大模型（2025–2026）

| 模型 | 来源 / 日期 | 许可 | 要点 | 与我们系统的关系 |
|---|---|---|---|---|
| Hy-MT2（1.8B / 7B / 30B-A3B） | https://github.com/Tencent-Hunyuan/Hy-MT2 （1,760★ / 2026-08-26）；HF 发布 2026-05（模型卡见 tencent/Hy-MT2-7B） | HF 模型卡写 Apache-2.0；GitHub 许可字段为“other”，二者不一致，以仓库 LICENSE 为准（未确证） | 33 种语言；提示词模板内置：术语（`参考下面的翻译：{src} 翻译成 {tgt}`）、风格、个性化偏好、分隔符（“保留等量分隔符，不得遗漏、转义或翻译”）、结构化数据（锁定 JSON/XML 结构，只译可见文本）、背景信息；发布 IFMTBench（指令遵循翻译基准）；7B 与 30B-A3B 自称在快思考模式下优于 DeepSeek-V4-Pro、Kimi K2.6（厂商自述，未独立复核）；1.8B 提供 1.25bit 量化（440MB） | 术语/分隔符/结构化模板可直接复用于我们的修订提示；1.8B/7B 可作“本地廉价第二模型”核对者 |
| HY-MT1.5（1.8B / 7B）与 Hunyuan-MT-7B / Chimera | https://github.com/Tencent-Hunyuan/HY-MT （842★ / 2026-06-01）；https://github.com/Tencent-Hunyuan/Hunyuan-MT （728★ / 2025-12-30） | other（腾讯社区许可，地域限制条款未核对，未确证） | WMT25 31 个语向中 30 个第一（官方自述）；Chimera 是“集成模型”：给 6 个候选译文，综合出一个更好的（提示模板见 README）；1.5 版新增术语干预、上下文翻译、格式化翻译（`<source>…</source>` 标签） | Chimera 思路 = 多个廉价候选（Google 草稿 + LLM 修订 + 本地 MT）合并，可作“第二模型核对”的替代形态：不是判对错，而是合成 |
| TranslateGemma（4B / 12B / 27B） | Google，2026-01-12 发布，技术报告 arXiv:2601.09012；HF 页面需登录协议（未能读取模型卡全文） | Gemma 许可（受限访问，需同意条款） | 基于 Gemma 3，55 个核心语向（WMT24++），27B MetricX 4.04→3.09；12B 超过 Gemma 3 27B 基线；报告指出日→英退化主要来自命名实体误译（据搜索结果转述，未读原文） | “命名实体误译是 MT 模型的已知弱点”的外部证据，支持我们必须对学名/人名做外部守卫 |
| Seed-X（7B：Instruct / PPO / RM） | https://github.com/ByteDance-Seed/Seed-X-7B （171★ / 2025-08-18）；arXiv:2507.13618 | OpenMDW（README 徽章） | 7B Mistral 架构；含奖励模型 Seed-X-RM-7B 可给译文打分；PPO 模型提示末尾必须加语言标签如 `<de>`；公开 challenge set（含人工参考译文，覆盖生物医学、科技等领域） | RM 可作为开源的无参考质量打分器候选，需实测对分类学文本是否可用（未确证） |
| Index-Translate / Omni（2B / 9B / 35BA3B） | https://github.com/bilibili/Index-Translate （2,042★ / 2026-11-12 / Apache-2.0） | Apache-2.0 | README 给出 FLORES/WMT24++ COMET22 与 WMT26 Judge 分数、指令遵循（IFMTBench）评测；Omni 版含图像翻译与语音；README 内 arXiv 编号疑似有误，未核对 | 新近开源，可作为候选本地修订模型；评测数据为厂商自报 |
| Qwen-MT | 阿里云 Model Studio API（help.aliyun.com 的 Qwen-MT API 页），无开源权重（未确证） | 商用 API | `translation_options` 含术语干预、翻译记忆（`tm_list` 的 source/target 句对，模型模仿其风格）、领域提示 | API 形态的“术语 + 翻译记忆注入”可作为我们提示词设计的参照：把已确认的句对（检索表对句）作为 few-shot 记忆 |
| Tower+ / TowerInstruct（Unbabel） | HF：Unbabel/Tower-Plus-2B/9B/72B（2025-06）；TowerInstruct-7B-v0.2（2024-02）；9B 卡 8192 上下文，22 种语言 | CC-BY-NC（9B 卡头标 cc-by-nc-sa-4.0，正文写 CC-BY-NC-4.0，二者不一致） | 翻译 + 通用指令混合训练，含 CPT、IT、WPO；同厂 COMET/xCOMET/M-Prometheus（评审模型）形成训练—评估闭环 | 非商用许可，仅可研究使用；其“翻译与评估同源”的设计值得参考 |
| NLLB-200 | HF：facebook/nllb-200-3.3B（下载量 288,737，2022-07 创建）；代码在已归档的 facebookresearch/fairseq（32,206★，2025-09-30 归档） | CC-BY-NC-4.0 | 200 种语言，句子级；模型卡明确“研究模型，不用于生产，不适合医学/法律等领域文本，不用于文档翻译” | 覆盖冷门语言（如 Faroese 等）时可作草稿后备；不宜用于专著级长文 |
| MADLAD-400（3B/7B/10B MT） | HF：google/madlad400-10b-mt（2023-11 创建，2024-04 更新） | Apache-2.0 | 450+ 语言；T5 系 | 许可友好，可作为冷门语言草稿后备（质量未实测，未确证） |
| SeamlessM4T v2 | https://github.com/facebookresearch/seamless_communication （11,907★ / 2026-09-08 / 许可字段 other） | 模型 CC-BY-NC-4.0（HF 页面） | 约 100 种语言，含文本到文本（T2TT）、语音；对书籍文本无特别优势 | 本任务用不上语音；仅作冷门语言文本后备 |

- 对我们的整体判断（推断，非实测）：开源 7B 级 MT 模型已能作为“本地廉价修订/核对者”，其价值不在绝对质量，而在 (a) 内置术语/分隔符/格式模板；(b) 可离线、无配额；(c) 可与云端 LLM 形成“异源核对”。分类学术语（学名、命名人、检索表句式）都不在其训练重点，必须靠外部守卫，实测前不应采信厂商基准。

---

## C. 浏览器/阅读器类（沉浸式翻译的开源对应物）

### C1. fishjar/kiss-translator

| 项 | 内容 |
|---|---|
| 仓库 | https://github.com/fishjar/kiss-translator |
| 星数 / 最后提交 / 许可 | 13,338 / 2026-11-14 / GPL-3.0 |
| 做什么 | 双语对照网页翻译扩展 + 油猴脚本；内置 Google/Microsoft/Baidu/Tencent/Volcengine/DeepL 与 OpenAI/Gemini/Claude/Ollama/DeepSeek 等；插件机制可对接任意非标准 API |
| 技术/架构 | 按“文本翻译/词典/字幕断句/OCR/语音”分能力配置服务；批量聚合翻译、流式、上下文记忆对话；“个人专业术语库”和术语库调试工具；规则订阅（可视元素选取器，kiss-rules 社区规则库）；本地 AI（WebGPU/WASM，模型中心）；PDF 深度解析（版面检测、OCR、表格/公式、分阶段翻译与缓存，只导出 Markdown/HTML/ZIP，不还原 PDF 排版）；系统提示词模板管理 |
| 优点 | 服务可插拔、提示词模板可管理、术语库带调试工具；规则订阅机制成熟 |
| 缺点 | 本质是网页阅读辅助，无整书断点/全书一致性机制；GPL-3.0 |
| 可借鉴 | (1) 把“Google 草稿 / LLM 修订 / 本地模型”都实现为统一“服务插件”接口，每个服务声明自己具备的能力（文本、批量、流式、术语）；(2) 术语库调试工具：给一句话，显示哪些术语条目命中、注入后的最终提示词，便于排查术语为何未生效 |

### C2. mengxi-ream/read-frog

| 项 | 内容 |
|---|---|
| 仓库 | https://github.com/mengxi-ream/read-frog |
| 星数 / 最后提交 / 许可 | 10,428 / 2026-11-14 / GPL-3.0（另有“商业许可授予”章节，细则未读） |
| 做什么 | 自称“沉浸式翻译的开源替代”；网页/划词/字幕翻译 + 生词本（FSRS 间隔复习）；20+ 个 AI 提供商 |
| 技术/架构 | “上下文感知翻译”：抽取页面标题与精简 Markdown 作为上下文喂给模型，使术语按领域翻译；“批量请求”：多个翻译请求合并成一次 API 调用，自称最多省 70% 成本（厂商自述，未复核），含指数退避重试，批失败自动回落逐条请求；自定义 AI 动作（自定义提示词 + 结构化输出字段） |
| 优点 | 批量合并 + 自动回落的成本/鲁棒性设计清晰 |
| 缺点 | 为语言学习设计，无书籍级结构；上下文只是页面级摘要 |
| 可借鉴 | “批失败 → 自动降级为逐条”的回落策略：我们在合并多段做一次修订请求时，一旦发现输出段数与输入不一致（错位），回落为逐段重发，并记录该批以便统计错位率 |

### C3. immersive-translate/immersive-translate

| 项 | 内容 |
|---|---|
| 仓库 | https://github.com/immersive-translate/immersive-translate |
| 星数 / 最后提交 | 19,797 / 2026-11-13 |
| 说明 | 该仓库只发布 Release 与收集 Issue，README 明确“沉浸式翻译并非开源软件，本仓库不包含源代码”，旧版开源项目 old-immersive-translate 已于 2023-01-17 归档（README 原文）。功能自述：网页/PDF（保留版面）/EPUB/字幕/图片翻译，“部分服务支持术语库、领域设置和上下文翻译”。 |
| 可借鉴 | 无可复用代码；仅作产品对照。开源替代首选 kiss-translator、read-frog（见上） |

### C4. windingwind/zotero-pdf-translate

| 项 | 内容 |
|---|---|
| 仓库 | https://github.com/windingwind/zotero-pdf-translate |
| 星数 / 最后提交 / 许可 | 12,291 / 2026-11-13 / AGPL-3.0 |
| 做什么 | Zotero 插件：翻译 PDF、EPub、网页、条目标题/摘要、批注、笔记；20+ 翻译服务，默认 Google，含 Bing、Microsoft、GPT 及兼容端点 |
| 技术/架构 | 划词翻译自动写入批注；批注可修改后“更新批注”；独立翻译窗口可并排比较多个服务的译文；单词走词典服务 |
| 优点 | “并排比较多引擎译文”和“把译文写入批注、可修改”的交互，天然适合人工复核 |
| 缺点 | 句/段级交互，不是整书流水线 |
| 可借鉴 | 人工队列界面：同一原句并排显示 Google 草稿、LLM 修订、第二模型意见，人只需点选或改写；改写结果回写为译文并同时入术语/翻译记忆 |

---

## D. 文档解析（PDF → 结构化文本）

### D1. docling-project/docling

| 项 | 内容 |
|---|---|
| 仓库 | https://github.com/docling-project/docling |
| 星数 / 最后提交 / 许可 | 70,574 / 2026-11-14 / MIT |
| 做什么 | 多格式解析（PDF、DOCX、PPTX、XLSX、HTML、EPUB、LaTeX、图片等）；PDF 版面、阅读顺序、表格结构、代码、公式；统一的 DoclingDocument 表示；导出 Markdown/HTML/DocTags/无损 JSON；本地可离线；MCP 服务器与 docling-serve API；VLM 支持（GraniteDocling）；README 的“即将推出”含元数据抽取（标题、作者、参考文献、语言） |
| 优点 | 无损 JSON（保留元素类型与位置）便于“只译文本字段、其余原样回填”；MIT 许可最宽松；生态集成多 |
| 缺点 | 对 19 世纪双栏/老字体扫描书的表现未见公开评测（未确证）；据 Marker 自家基准（OmniParseBench，厂商自测）docling 综合分 67.5，低于 Marker balanced 的 80.5 |
| 可借鉴 | 以 DoclingDocument 式“带类型的元素树”作为我们的内部中间格式：段落、标题、脚注、表格、图注各有类型，QA 守卫按类型施加规则（检索表对句、学名行、脚注不混入正文） |

### D2. datalab-to/marker

| 项 | 内容 |
|---|---|
| 仓库 | https://github.com/datalab-to/marker |
| 星数 / 最后提交 / 许可 | 40,910 / 2026-11-14 / 代码 Apache-2.0，模型权重 modified OpenRAIL-M（README：研究、个人、资金或营收低于 500 万美元的初创免费，其余需商用授权） |
| 做什么 | PDF/图片/Office → Markdown/JSON/chunks/HTML；去页眉页脚；表格、公式（行内公式转 LaTeX）、代码、引用 |
| 技术/架构 | 四种模式：`no_ocr`（仅用文字层 + ONNX 版面，CPU 57 页/秒）、`fast`（CPU/MPS）、`balanced`（GPU 默认：干净拉丁文页走 CPU，公式、复杂表格、CJK/非拉丁、扫描页路由到 Surya 2.5 VLM）、`vllm`（每页 VLM）；`--use_llm` 混合模式用 Gemini/Claude/OpenAI 兼容端点合并跨页表格、修表格与公式；`--force_ocr` 处理文字层损坏的 PDF |
| 优点 | 按页难度路由的思路；文字层损坏时强制 OCR；README 自带基准 |
| 缺点 | 基准为厂商自测（OmniParseBench 为 datalab 自建，未独立复核）；权重有商用门槛；README 声称 balanced/vllm 超过 MinerU 2.5-Pro，需自行用旧专著样张验证 |
| 可借鉴 | (1) “按页路由”：数字原生页走低成本通道，扫描/公式/多栏页才走重型模型，降低整书解析成本；(2) 文字层坏时 `force_ocr` 的开关逻辑，对老书扫描 PDF 很常见（OCR 层本身带错字）；(3) 与 MinerU 做小样本对照（5–10 页老专著含检索表、拉丁学名斜体、双栏脚注），再定主力解析器 |

---

## E. 质量评估与分类学名称工具（QA 守卫相关）

### E1. Unbabel/COMET（含 xCOMET、CometKiwi）

| 项 | 内容 |
|---|---|
| 仓库 | https://github.com/Unbabel/COMET |
| 星数 / 最后提交 / 许可 | 790 / 2026-04-21 / 代码 Apache-2.0；模型各自许可 |
| 做什么 | 神经机器翻译评估框架：有参考（wmt22-comet-da，Apache-2.0）、无参考（wmt22-cometkiwi-da，CC-BY-NC-SA-4.0）、可解释（XCOMET-XL/XXL，CC-BY-NC-SA-4.0，门控下载）：除总分外输出错误片段并按 MQM 标为轻微/严重/关键（`--to_json`）；DocCOMET 支持文档级上下文（`--enable-context`）；`comet-mbr` 做最小贝叶斯风险重排 |
| 优点 | 无参考评分可直接给“草稿 vs 修订”打分；xCOMET 的错误片段可定位到词；成熟、论文多 |
| 缺点 | 基于 XLM-R，README 明说“语言覆盖外的语对结果不可靠”；训练数据是新闻/通用域，对学名、检索表句式、否定词是否敏感未确证（需自建小测试集）；NC 许可限制商用；句级为主 |
| 可借鉴 | 作为“数字/学名/否定守卫”之外的统计型第二意见：对每段 (原文, 译文) 打 QE 分，低于阈值进人工队列；先在已有人工审校的 Travisia/Marphysa 段落上标定阈值，再上线；xCOMET 的错误片段可高亮在人工队列界面 |

### E2. google-research/metricx（MetricX-23/24）

| 项 | 内容 |
|---|---|
| 仓库 | https://github.com/google-research/metricx |
| 星数 / 最后提交 / 许可 | 154 / 2026-07-02 / Apache-2.0（HF 上 metricx-24-hybrid-xl/xxl-v2p6 亦为 Apache-2.0） |
| 做什么 | 译文质量回归模型，输出 0–25 的 MQM 式错误分（越低越好）；MetricX-24 为混合模型，同一模型既可有参考也可无参考（QE）；提供 Large/XL/XXL 及 bfloat16 版（显存省 50%） |
| 技术/架构 | mT5 系；训练含 DA 与 MQM 数据及“过译/欠译”合成负例，并加入多句长段完美译文以降低对长译文的偏见（README 说明） |
| 优点 | 许可友好（Apache-2.0）；欠译/漏译敏感，正好对应“漏句”风险；Google 自家 TranslateGemma 报告用 MetricX 评测（见 B3） |
| 缺点 | 句/短段级；同样对分类学文本未验证（未确证）；XXL 需较大显存 |
| 可借鉴 | 许可上比 xCOMET 更适合进入我们开源流水线；用 MetricX-24 hybrid QE 作为“漏译/欠译”粗筛，与脚本级“数字、学名”守卫互补 |

### E3. MicrosoftTranslator/GEMBA 与 google-research/mt-metrics-eval、mjpost/sacrebleu

| 项目 | 星数 / 最后提交 / 许可 | 说明与借鉴 |
|---|---|---|
| GEMBA https://github.com/MicrosoftTranslator/GEMBA | 158 / 2025-12-15 / CC-BY-SA-4.0 | GEMBA-MQM、GEMBA-DA：用 GPT 类模型按 MQM 类别给译文标错并打分，命令行输入两个对齐文件。借鉴：“第二模型核对”的提示词可直接采用 MQM 分类（遗漏、加译、意思反转、数字、专名、术语），输出可统计 |
| mt-metrics-eval https://github.com/google-research/mt-metrics-eval | 140 / 2026-04-23 / Apache-2.0 | WMT 度量元评估工具与人工 MQM 数据入口。借鉴：当我们自建“分类学测试集”时，用它的元评估流程检验各指标与人工判断的相关性 |
| sacrebleu https://github.com/mjpost/sacrebleu | 1,265 / 2026-08-20 / Apache-2.0 | BLEU/chrF/TER 标准化计算。借鉴：只用于回归测试（同一章前后版本的变化），不作质量判据 |

### E4. gnames/gnfinder、gnames/gnparser、nleguillarme/taxonerd（拉丁学名守卫的现成部件）

| 项目 | 星数 / 最后提交 / 许可 | 说明 |
|---|---|---|
| GNfinder https://github.com/gnames/gnfinder | 55 / 2026-11-10 / MIT | 在任意文本中快速发现学名（词典 + NLP，宣称单机每小时 1500 万页，厂商自述）；输出 CSV/TSV/JSON，含名称偏移量；可自动检测语言并调整贝叶斯算法（目前英、德）；可对多个生物数据库核验名称，并展开缩写属名（保留 `verbatim` 与 `abbrName`）；识别 `sp. nov.`、`comb. nov.` 等命名学注记；可抽取 PDF/DOCX/HTML 文本（部分格式默认经远程 Apache Tika 服务转换，可用 `--no-tika` 强制本地；名称核验需联网，文本片段会发往外部服务，处理未公开稿件时需关闭核验，README 原文） |
| GNparser https://github.com/gnames/gnparser | 57 / 2026-10-09 / MIT | 把学名拆成语义成分（属、种、亚种、命名人、年份）并归一为 canonical form，用于异名与变体的比对 |
| TaxoNERD https://github.com/nleguillarme/taxonerd | 48 / 2026-11-02 / MIT | 面向生物多样性文献的分类单元实体识别（spaCy，md 与 biobert 两种架构）；识别学名、俗名、缩写；可链接到 NCBI/GBIF/TAXREF，也可自定义分类系统（论文：Methods Ecol Evol 13:625，doi:10.1111/2041-210X.13778） |

- 可借鉴（具体）：学名守卫不必自己写正则：(1) 对原文和译文分别跑 GNfinder，得到名称集合与偏移；(2) 用 GNparser 归一后做集合比较，译文中“缺失/新增/被改写”的学名一律进人工队列；(3) 缩写属名（如 *P. dumerilii*）由 GNfinder 展开后再比对，减少误报；(4) 命名人与年份（如 “Audouin & Milne Edwards, 1833”）由 GNparser 的成分拆分单独校验，防止译成中文后丢年份；(5) GNfinder 的语言模型只覆盖英/德，其他源语言（法、俄、拉丁）需手工放宽，未确证对旧专著 OCR 噪声的容错。

---

## F. 术语库 / 翻译记忆 / CAT 类

| 项目 | 星数 / 最后提交 / 许可 | 说明 | 可借鉴 |
|---|---|---|---|
| Supervertaler/Supervertaler-Workbench https://github.com/Supervertaler/Supervertaler-Workbench | 62 / 2026-11-10 / MIT | 开源 CAT 工作台：多 LLM（GPT、Claude、Gemini、Mistral、Ollama）+ 翻译记忆（模糊匹配，TMX 导入导出）+ 术语表（项目/背景术语表高亮，“禁用术语”标记）+ 统一检索（TM、术语、MT、网页）；对接 memoQ、Trados 等 | “禁用术语（forbidden term）”：为学名及常见误译维护黑名单，QA 守卫命中即报；TMX 作为与人工 CAT 工具交换的格式 |
| hint-lab/deeptrans-studio https://github.com/hint-lab/deeptrans-studio | 174 / 2026-07-26 / MIT | 多智能体翻译工作台；术语抽取、项目词典、翻译记忆（pgvector 向量检索 + PGroonga 中日韩关键词检索）、TMX/CSV/XLSX 导入导出、批量评估；论文 CSCW '26 Demo：把专家干预转为团队共享知识；README 同时引用 ACL '26 BabelDOC 论文（Qi 等，aclanthology.org/2026.acl-demo.25，已在 README 中给出，未读原文） | 人工队列的每次修改自动沉淀为术语/记忆条目（向量检索 + 关键词检索双通道），下一章自动命中 |
| translate5/translate5 https://github.com/translate5/translate5 | 55 / 2026-11-11 / 许可字段 other | 开放的语言智能平台；README 称 2026 年夏起不再在 GitHub 公开源码 | 仅作产品对照；不要依赖其仓库 |
| translated/lara-mcp https://github.com/translated/lara-mcp | 100 / 2026-11-06 | Lara Translate 的官方 MCP 服务器：语言检测、上下文翻译、翻译记忆、术语表；Lara 为商业服务（T-LM） | 参考其“术语表/翻译记忆作为 MCP 工具暴露”的接口设计；服务本身不开源 |
| bfsujason/bertalign https://github.com/bfsujason/bertalign | 167 / 2026-11-10 / GPL-3.0 | 多语句子对齐：sentence-transformers 向量 + 两步动态规划（先 1-1，再多对多），支持 25 种语言（含中、英、法、德、俄） | 用来把已有中文译本（经典译作）与英文原著对齐成句对，批量学术语（yiku 流程）；也可对齐“草稿—修订—人工终稿”追踪改动。注意 GPL-3.0 |
| bitextor/bitextor https://github.com/bitextor/bitextor | 301 / 2024-11-11 | 从多语网站生成翻译记忆 | 与本任务关系弱，不推荐 |

---

## G. 其他已发现、但本次未细读（仅元数据，未确证细节）

| 项目 | 星数 / 最后提交 | 备注 |
|---|---|---|
| binary-husky/gpt_academic https://github.com/binary-husky/gpt_academic | 71,662 / 2026-01-25 | 学术 LLM 交互界面，含 arXiv 论文翻译插件；近 10 个月无提交；与整书流水线关系有限 |
| Mengqi-Lei/texglot https://github.com/Mengqi-Lei/texglot | 124 / 2026-11-14 | 译 arXiv/LaTeX 工程并保留公式、引用（仅读描述） |
| jesselau76/ebook-GPT-translator https://github.com/jesselau76/ebook-GPT-translator | 1,738 / 2026-03-15 | 较早的 epub 翻译脚本 |
| equalang/equalang-skill https://github.com/equalang/equalang-skill | 94 / 2026-11-03 | 面向 agent 的翻译 skill（PDF/DOCX/PPTX/XLSX/EPUB 等），仅读描述 |
| NingK1ng/book-translation-workflow、skitniknikita/book-translation-agent | 8 / 6 | Codex 技能，逐章翻译加 DeepSeek 复核/研究优先；星数极低，仅作思路参考 |
| ckanner/jta https://github.com/ckanner/jta | 133 / 2025-11-12 | JSON 翻译，“agentic reflection”（译后自我反思再改） |
| LibreTranslate/LTEngine | 见 B1 | LLM 版本地 MT API |

---

## H. 总表（星数与最后提交，2026-11-15 取值）

| 分组 | 项目 | 星数 | 最后提交 | 许可 | 备注 |
|---|---|---:|---|---|---|
| A | yihong0618/bilingual_book_maker | 9,940 | 2026-10-30 | MIT | |
| A | hydropix/TranslateBooksWithLLMs | 2,594 | 2026-11-14 | AGPL-3.0 | |
| A | oomol-lab/epub-translator | 882 | 2026-09-18 | MIT | |
| A | oomol-lab/pdf-craft | 6,677 | 2026-11-14 | MIT | |
| A | neavo/LinguaGacha | 2,699 | 2026-11-14 | 空（商用需授权） | |
| A | sukamenev/booktrans | 55 | 2026-11-08 | MIT | 新项目 |
| A | daanaagua/FolioLoom | 70 | 2026-10-13 | MIT | 新项目 |
| A | YutongWang1216/DocMTAgent（DelTA） | 65 | 2025-02-10 | Apache-2.0 | 论文 ICLR 2025 |
| A | BigDawnGhost/wenyi | 2,921 | 2026-11-14 | GPL-3.0 | |
| A | purecodework/bookllm | 44 | 2026-10-11 | MIT | |
| A | xunbu/docutranslate | 1,373 | 2026-11-01 | MPL-2.0 | |
| B | LibreTranslate/LibreTranslate | 17,703 | 2026-11-14 | AGPL-3.0 | |
| B | argosopentech/argos-translate | 6,654 | 2026-11-14 | MIT | |
| B | LibreTranslate/LTEngine | 214 | 2026-10-14 | AGPL-3.0 | |
| B | OpenNMT/CTranslate2 | 4,749 | 2026-11-10 | MIT | |
| B | ssut/py-googletrans | 4,300 | 2026-08-08 | MIT | 最新 Release v4.0.0（2024-12-13） |
| B | nidhaloff/deep-translator | 2,053 | 2024-07-23 | Apache-2.0 | 久未提交 |
| B | UlionTse/translators | 2,694 | 2026-01-26 | GPL-3.0 | |
| B | Tencent-Hunyuan/Hy-MT2 | 1,760 | 2026-08-26 | other（HF 卡为 Apache-2.0） | 许可不一致 |
| B | Tencent-Hunyuan/HY-MT（1.5） | 842 | 2026-06-01 | other | |
| B | Tencent-Hunyuan/Hunyuan-MT | 728 | 2025-12-30 | other | |
| B | ByteDance-Seed/Seed-X-7B | 171 | 2025-08-18 | OpenMDW | |
| B | bilibili/Index-Translate | 2,042 | 2026-11-12 | Apache-2.0 | |
| B | facebookresearch/seamless_communication | 11,907 | 2026-09-08 | other（模型 CC-BY-NC） | |
| B | facebookresearch/fairseq（NLLB 代码所在） | 32,206 | 2025-09-30 | MIT | 已归档 |
| B | HF：facebook/nllb-200-3.3B | HF 下载 288,737 | 2023-02-11 | CC-BY-NC-4.0 | 非 GitHub |
| B | HF：google/madlad400-10b-mt | HF 下载 4,127 | 2024-04-12 | Apache-2.0 | |
| B | HF：google/translategemma-12b-it | HF 下载 6,350 | 2026-01-28 | Gemma（受限） | 创建 2026-01-12 |
| B | HF：Unbabel/Tower-Plus-9B | HF 下载 18,765 | 2025-06-25 | CC-BY-NC（见 B3） | |
| C | fishjar/kiss-translator | 13,338 | 2026-11-14 | GPL-3.0 | |
| C | mengxi-ream/read-frog | 10,428 | 2026-11-14 | GPL-3.0 | |
| C | immersive-translate/immersive-translate | 19,797 | 2026-11-13 | 闭源（仅发布页） | |
| C | windingwind/zotero-pdf-translate | 12,291 | 2026-11-13 | AGPL-3.0 | |
| D | docling-project/docling | 70,574 | 2026-11-14 | MIT | |
| D | datalab-to/marker | 40,910 | 2026-11-14 | Apache-2.0（权重 OpenRAIL-M 改） | |
| E | Unbabel/COMET | 790 | 2026-04-21 | Apache-2.0（模型各异） | |
| E | google-research/metricx | 154 | 2026-07-02 | Apache-2.0 | |
| E | MicrosoftTranslator/GEMBA | 158 | 2025-12-15 | CC-BY-SA-4.0 | |
| E | google-research/mt-metrics-eval | 140 | 2026-04-23 | Apache-2.0 | |
| E | gnames/gnfinder | 55 | 2026-11-10 | MIT | |
| E | gnames/gnparser | 57 | 2026-10-09 | MIT | |
| E | nleguillarme/taxonerd | 48 | 2026-11-02 | MIT | |
| F | Supervertaler/Supervertaler-Workbench | 62 | 2026-11-10 | MIT | |
| F | hint-lab/deeptrans-studio | 174 | 2026-07-26 | MIT | |
| F | bfsujason/bertalign | 167 | 2026-11-10 | GPL-3.0 | |

---

## I. 最值得借鉴（排序）

排序依据：对我们“分类学感知、老专著、任意源到任意目标语言”的流水线，哪些做法能补当前缺口，且工程代价低、许可风险小。

| 序 | 来源 | 借鉴什么（具体） | 落到我们流水线的位置 | 代价 / 许可注意 |
|---:|---|---|---|---|
| 1 | sukamenev/booktrans | ① 翻译前“通读侦察”：扫全书得到学名、术语、命名人、缩写、检索表位置，写入可手改的注册表；② 编辑遍“不看原文”、核对遍“同看两边”，只把编辑疑点与脚本异常送核对者；③ 拒绝截断/错位的模型回复；④ `--only qa` 开跑前干跑普查；⑤ 重命名后只重核受影响块 | 分块之前加侦察遍；第二模型核对改为“只核疑点 + 抽样”，省钱；闸口加“段数不一致即重发” | 低；MIT |
| 2 | daanaagua/FolioLoom | ① 源文“无损账本”（段哈希 + 译文映射）+ 导出前“零遗漏”检查；② 并行波次冻结术语锚点；③ 同一实体按源块范围用不同译名；④ 术语追溯修订可预览、可回滚；⑤ 有未决项则拒绝导出 | 导出闸门；术语注册表支持“范围”字段（同一拉丁名在不同修订/章节的有效名不同）；断点续跑状态用 SQLite 而非散文件 | 中；MIT；整套引擎太重，只借设计 |
| 3 | hydropix/TranslateBooksWithLLMs | ① 术语仅在块内出现时才注入提示；② “术语后修”：错误译法规则表（含通配）+ 先扫描后改，只改命中句；③ LLM 评审 rubric 含“硬上限”；④ 按目标语言的模型基准 | 术语注入层；QA 发现系统性误译时的低成本补救；第二模型评分规则 | 低；AGPL-3.0，只借设计不抄码 |
| 4 | gnames/gnfinder + gnparser（+ TaxoNERD 备选） | 对原文与译文分别抽学名，GNparser 归一后比对集合；缩写属名展开；命名人和年份成分单独校验；`sp. nov.` 等注记识别 | 自动 QA 的“拉丁学名守卫”直接用现成工具，替代自写正则 | 低；MIT；注意 Tika 与核验会联网，未公开稿件要关；语言模型仅英/德 |
| 5 | google-research/metricx（MetricX-24 hybrid）与 Unbabel/COMET（xCOMET）、GEMBA-MQM | 无参考 QE 分数作粗筛，xCOMET 错误片段作高亮；GEMBA 的 MQM 类目作核对提示词模板 | 第二模型核对前的低成本筛；人工队列优先级排序 | 中；MetricX 为 Apache-2.0，xCOMET/CometKiwi 为 CC-BY-NC-SA（非商用）；须先在我方已审校段落上标定，勿直接信厂商基准 |
| 6 | Tencent Hy-MT2 / HY-MT1.5（含 Chimera 集成思路） | 内置的术语、分隔符、结构化数据、背景信息提示模板；多候选合并（Chimera）作为“修订 + 核对”的另一种形态；本地小模型作离线廉价第二模型 | 修订提示词模板；离线后备 | 中；许可信息不一致（HF 卡 Apache-2.0，GitHub 为 other），采用前读 LICENSE；厂商基准未复核 |
| 7 | yihong0618/bilingual_book_maker | plan.json 干跑 + 覆盖率守卫；按起止字符串局部重译；价格表 + 缓存读价的花费进度条；批处理 API 半价通道；session 上下文压缩 | 开跑前计划；人工退回后的最小重译；成本核算 | 低；MIT |
| 8 | YutongWang1216/DocMTAgent（DelTA） | 专名记录 + 双语摘要 + 长/短期记忆四层结构；LTCR-1 术语一致性指标 | 用 LTCR-1 度量“同一学名全书译法一致率”，作为回归测试指标 | 低；Apache-2.0；代码较旧，只借指标与结构 |
| 9 | BigDawnGhost/wenyi 与 hint-lab/deeptrans-studio | 术语冲突（同一源词≥2 种译法）自动进人工队列，裁定后回灌后续批次；人工修改沉淀为术语/记忆（向量 + 关键词双通道检索） | 人工队列的反馈闭环；翻译记忆 | 中；wenyi 为 GPL-3.0，只借设计 |
| 10 | oomol-lab/epub-translator（及 pdf-craft） | “翻译”与“标记结构回填”拆成两次调用，回填用低温度并做结构校验，失败事件显式暴露 | 检索表对句编号、脚注编号、斜体学名标记的还原步骤 | 低；MIT |

### 采用前的共性提醒

1. 星数高不等于适合：bilingual_book_maker、TBL、kiss-translator 面向通用读者，分类学特有问题（学名、检索表对句、命名人与年份、异名链）都没有现成实现，需要我们自己做或借 GNfinder/GNparser。
2. 厂商基准（Marker 的 OmniParseBench、Hy-MT2/Index-Translate/Seed-X 的榜单、read-frog 的“省 70%”、GNfinder 的吞吐）均为自报，本调研未复核，一律视为“未确证”，需在我们自己的老专著样张上实测。
3. 许可：AGPL/GPL（TBL、LibreTranslate、wenyi、read-frog、kiss-translator、bertalign、translators、zotero-pdf-translate）只借设计不抄代码；NC 许可（NLLB、Seamless、Tower、xCOMET、CometKiwi）限非商用；Marker 模型权重有商用门槛。
4. 本调研未做的事：未运行任何项目；未读源码（除 README/文档/HF 模型卡）；未检查各项目 issue 区的已知缺陷。书籍级项目是否真的能处理 19 世纪双栏脚注书，没有证据，需要抽样试跑。

---

## 附：既有覆盖项目数字更新（仅更新，不重述）

| 项目 | 星数 | 最后提交（pushedAt，UTC） | 备注 |
|---|---:|---|---|
| andrewyng/translation-agent | 5,815 | 2024-08-04 | 超过 2 年无提交 |
| deusyu/translate-book | 2,410 | 2026-11-07 | |
| asadeisa/book-translator | 1 | 2026-10-09 | |
| senshinji/claude-translation-skill | 38 | 2026-03-12 | |
| Byaidu/PDFMathTranslate | 38,419 | 2026-11-14 | AGPL-3.0；README 标 EMNLP 2025 Demo |
| funstory-ai/BabelDOC | 9,872 | 2026-11-07 | AGPL-3.0；ACL 2026 Demo 论文（见 deeptrans-studio README 引用） |
| opendatalab/MinerU | 83,667 | 2026-11-13 | 许可字段 other |
| plazi/GoldenGATE-Imagine | 6 | 2016-11-29 | 近 10 年无提交 |
