# 商用 MT 与 CAT/QA 产品调研（2026-11 状态）

调研日期：2026-11-15。只用官方文档/官方页面；每条主张附 URL；官方页面查不到或只在第三方转述的，标"未确证"。
目标场景：分类学旧专著（俄/保/德/法/日/拉丁 → 英/中）的"分类学感知"书籍翻译；管线 = Google 免费初稿 → 廉价 LLM 修订 → 自动 QA 闸口（数字/拉丁学名/检索表要点/否定）→ 第二模型核意 → 人工队列。

状态标注：**已确证** = 官方页面原文；**未确证** = 无官方出处或页面无法渲染；**推测** = 本人推断。

---

## 1. DeepL（API / 术语表 / 文档翻译 / Write / context）

### 1.1 总表

| 维度 | 结论 | 出处 |
|---|---|---|
| 语言（保/俄/日/拉丁） | **API 语言表（官方文档页，经 headless Chrome 渲染，2026-11-15）**：**BG 保加利亚语、JA 日语、RU 俄语**均支持 Translation + Glossaries + Tag Handling + Translation Memory + Style Rules & Custom Instructions（JA 另有 Text Improvement）；**LA 拉丁语：只有 Translation + Tag Handling，没有 Glossaries、Translation Memory、Style Rules & Custom Instructions**；ZH/ZH-HANS/ZH-HANT 作目标语言均支持术语表、TM、风格规则（ZH-HANS/HANT 仅作目标）；EN 变体 EN-US/EN-GB 仅作目标。**含义：拉丁语作源文时，DeepL 的全部定制手段（术语表/TM/指令）均不可用，只能裸翻** | https://developers.deepl.com/docs/getting-started/supported-languages （JS 渲染表）；应用端语言表（含 Latin）：https://support.deepl.com/hc/en-us/articles/360019925219-Languages-included-in-DeepL |
| 术语机制 | 术语表（glossary）：按语言对的词/短语映射，文档称"智能屈折（flex）以适配格、性、时态"；可一次传最多 5 个 `glossary_ids`；v3 为多语言术语表（一个术语表含多个 dictionary，每个单向）。**这是"引导"不是硬约束**，官方未承诺 100% 命中（未确证有硬保证） | https://developers.deepl.com/docs/customize/managing-glossaries ；https://developers.deepl.com/api-reference/translate |
| 术语表限额 | 单条源/目标/名称 ≤1024 UTF-8 字节；单术语表 ≤10 MiB；账户 ≤1000 个术语表；重复源键返回 400；Thai 不可建术语表；按根语言（`EN` 通用于 EN-US/EN-GB）；不带 `source_lang` 时可自动检测，但文档翻译带术语表必须给 `source_lang`；CSV/TSV 格式 | https://developers.deepl.com/api-reference/glossaries ；https://developers.deepl.com/docs/customize/managing-glossaries |
| Developer 免费档的术语表 | 仅 1 个术语表、≤1000 条（页面内嵌 JSON）；Growth 档 ≤2000 个术语表、每个 ≤200000 条（页面渲染文本同样写 "1 glossary" / "2,000 glossaries"） | https://www.deepl.com/en/pro-api（页面内嵌套餐 JSON，`packageId: api-developer / api-growth`；国家码 DE，欧元计价） |
| 翻译记忆（TM） | 2026 版 API 有 TM：`translation_memory_id` + `translation_memory_threshold`（默认 75，<50 按 50 处理）；模糊匹配命中则**直接复用库中译文**；TM 只能经 TMX **导入/导出**（后台作业，轮询 job），**不支持编辑已有 TM**；TM 必须覆盖该语言对否则 404；TM 初始需经 DeepL UI 上传（教程写法） | https://developers.deepl.com/docs/customize/using-translation-memories ；https://developers.deepl.com/api-reference/openapi.yaml （TranslationMemories 标签） |
| 风格/指令 | `custom_instructions`：≤10 条、每条 ≤300 字符，自然语言，逐句/逐段应用，**不是整篇编辑**；可存在 style rule list 里用 `style_id` 引用；`style_profile_id` 把术语表+风格规则+TM 打包，**不能与单项参数同用**（否则 400） | https://developers.deepl.com/docs/customize/custom-instructions ；https://developers.deepl.com/api-reference/translate |
| `context` 参数 | 给歧义词/短文本提供前后文；**context 字符不计费**；官方明确说**不是** LLM 指令通道（"Always translate X as Y" 不可靠）；术语规则要走术语表 | https://developers.deepl.com/docs/learning-how-tos/examples-and-guides/how-to-use-context-parameter ；https://developers.deepl.com/api-reference/translate |
| `model_type` | `quality_optimized` / `prefer_quality_optimized` / `latency_optimized`；官方称"next-generation language model"属付费档，Spanish-LatAm 仅限 next-gen | https://developers.deepl.com/api-reference/translate ；https://support.deepl.com/hc/en-us/articles/360021200939-DeepL-API-plans |
| 文档/格式 | 文档翻译：docx/doc、pptx、xlsx/xlsm、**pdf**、txt、html、idml、mif、xml、json、yaml、properties、strings、md、dita、xliff（1.2/2.0/2.1）、srt、vtt、scorm、resx、odt、rtf、图片。付费档：docx/pptx/pdf 100 MB / 500 万字符；免费 10 MB / 50 万字符；文档类格式每份最低计 5 万字符 | https://developers.deepl.com/docs/resources/usage-limits |
| 文本 API 标记 | `tag_handling=xml/html`（v2 默认），`ignore_tags`、`non_splitting_tags`、`splitting_tags`、`outline_detection`；标签不计费 | https://developers.deepl.com/api-reference/translate |
| QA | **文档质量评估（Quality Evaluation，beta，仅限选定客户）**：对每个段落给 0-100 分 `segment_score`，问题类型含 Accuracy（Addition/Omission/Mistranslation/Over-/Under-translation/Untranslated）、Fluency（标点/拼写/语法/语域/**Inconsistency**/编码）、Style、Miscellaneous；严重度 Critical/Major/Minor；返回 source/target 字符区间；回报每段**实际命中的术语表词对**；报告保留 24 小时；**支持语言对仅 DE/EN/ES/FR/IT/JA/KO/ZH 的若干组合，不含俄语、保加利亚语** | https://developers.deepl.com/api-reference/quality-evaluations/poll ；https://developers.deepl.com/docs/best-practices/document-translations |
| 润色 | DeepL Write API：改写/纠错，`writing_style`、`tone`；Write 目标语言仅 de/en/en-GB/en-US/es/fr/it/ja/ko/pt/pt-BR/pt-PT/zh/zh-Hans，**无俄/保** | https://developers.deepl.com/api-reference/openapi.yaml （`TargetLanguageWrite` 枚举） |
| 价格 | **Developer（免费）**：一次性 **100 万字符**额度（用完不重置），1 个 API key、**1 个术语表**、1 个风格规则列表；**Free（50 万/月）与 Pro 已停售**。**Growth**：页面（headless Chrome 渲染，地区=Hong Kong，USD）标价 **$26/月（按年付）+ 按量**，含 **1200 万字符/年**；月用量上限 5000 万字符；**超出部分 $27.50 / 百万字符**；2,000 个术语表、10 个 API key、"No data training"、CAT 工具集成。同一页面内嵌 JSON（德国站，EUR）显示：基础费 €29.75/月（年付 €285.60）、按量 **€22 / 百万字符**——**价格随地区/币种而异，购买前以所在地区结算页为准**。Enterprise：定制承诺。第三方文章的 "$5.49 + $25/百万" 为旧 Pro 价，与官方当前页面不符，不采用。 | 方案描述：https://support.deepl.com/hc/en-us/articles/360021200939-DeepL-API-plans ；价格：https://www.deepl.com/en/pro-api （渲染文本 + 内嵌 JSON `packageId: api-growth / api-developer`） |
| 计费口径 | 按**源文本 Unicode 码点**计；context 与 HTML/XML 标签不计；源=目标语言也计费 | https://developers.deepl.com/docs/resources/usage-limits ；https://developers.deepl.com/docs/best-practices/estimating-character-usage |
| 限流 | 单请求体 ≤128 KiB；header ≤16 KiB；**无固定 QPS**，服务动态调整；429/529 指数退避+jitter，尊重 `Retry-After`；456 = 额度用完，不重试；Growth 月用量上限 5000 万字符 | https://developers.deepl.com/docs/resources/usage-limits ；https://developers.deepl.com/docs/best-practices/error-handling ；https://support.deepl.com/hc/en-us/articles/360021200939-DeepL-API-plans |
| 数据留存 | 官方方案页：Growth/Pro"文本翻译后立即删除"、Growth 含 "No data training"；Developer（免费）档不含 "No data training"（渲染页面写 "Everything in Developer, plus: No data training"），内嵌 JSON 中 `enhancedDataSecurity:false`——**推测**：免费档的文本可能被用于改进模型，涉及未出版手稿/私人译稿时应避免用免费档（未确证） | https://support.deepl.com/hc/en-us/articles/360021200939-DeepL-API-plans ；https://www.deepl.com/en/pro-api |

### 1.2 对本系统最值得借鉴（DeepL）

1. **TM 的"阈值 + 导入/导出 TMX + 单独的 job 轮询"设计**：我们的"已校对段落"回流库可采用同样的接口形态——`threshold`（默认 75、下限 50）+ 命中即直接复用，而不是再发给 LLM。具体：校对通过的段落以 TMX 形式落盘，下一章先做 50-100% 模糊匹配，命中≥75% 的段直接复用并跳过 LLM；命中 50-75% 的作为 few-shot 示例注入 LLM 提示词。
2. **段落级质量评估报告的字段设计**：`segment_score(0-100)` + `type/sub_type/severity` + 源/目标字符区间 + **`applied_glossary_term_pairs`（每段实际命中的术语对）**。我们的 QA 闸口输出可直接沿用此 schema（Accuracy.Omission / Accuracy.Mistranslation / Fluency.Inconsistency / Untranslated），每条 QA 失败带 span，供人工队列精确定位；新增"本段命中的拉丁学名/术语表条目"字段，使"术语是否被遵守"可审计。
3. **`context` 不是指令通道 vs. 术语表是规则通道的明确分工**：DeepL 自己承认把"总是把 X 译成 Y"塞进 context 不可靠。我们的提示词设计同理：术语/学名保护走结构化表（占位符 + 回检），LLM 提示词只给语境（前后各 1-2 段、章节标题、分类阶元路径），避免把硬规则放进自然语言指令里。

---

## 2. Google Cloud Translation（Basic v2 / Advanced v3 / 术语表 / Adaptive / 文档 / TLLM）

注：官方文档已迁到 `docs.cloud.google.com/translate/...`（旧 `cloud.google.com/translate/docs` 301 跳转）。页脚"Last updated 2026-11-10 UTC"见 https://docs.cloud.google.com/translate/docs/supported-formats 。

### 2.1 模型与语言

| 模型 | 模型 ID | 要点 | 出处 |
|---|---|---|---|
| NMT | `general/nmt` | 最快；Basic v2 + Advanced v3 均可用；支持文本 `text/plain`、`text/html` | https://docs.cloud.google.com/translate/docs/advanced/compare-models |
| Translation LLM（TLLM） | `general/translation-llm` | "Gemini 驱动、为翻译微调"，官方称延迟约为 Gemini 2.0 Flash 的一半；**仅 `text/plain`**；一次最多 1024 个字符串；Basic 里需传完整 resource name | https://docs.cloud.google.com/translate/docs/advanced/compare-models ；https://docs.cloud.google.com/translate/docs/translation-llm ；https://docs.cloud.google.com/translate/docs/supported-formats |
| Adaptive 机翻 | `general/translation-llm-adaptive` | 在 TLLM 上做"实时轻量定制"（few-shot） | 同 compare-models |
| 定制 TLLM / 定制 NMT | `translation-llm-custom/{id}` 等 | 用平行语料微调/训练；按小时计训练费 | 同 compare-models；https://docs.cloud.google.com/translate/pricing |

| 语言 | NMT | TLLM / Adaptive | 出处 |
|---|---|---|---|
| 保加利亚语 `bg` | 是 | 是（Official Support） | https://docs.cloud.google.com/translate/docs/languages |
| 俄语 `ru` | 是 | 是 | 同上 |
| 日语 `ja` | 是 | 是 | 同上 |
| **拉丁语 `la`** | **是** | **页面 TLLM 列表中未见 Latin → 无官方支持（按列表判断）** | 同上（NMT 列表 "Latin / la"；TLLM 列表不含 Latin） |

说明：Latin 在 TLLM 列表中不存在是我对页面文本的检索结果（全页仅 NMT 段出现 "Latin"），应视为"已确证列表中没有"；至于 TLLM 是否仍能容忍拉丁语输入，页面未说，**未确证**。

### 2.2 术语 / TM / 自适应

| 维度 | 结论 | 出处 |
|---|---|---|
| 术语表（Advanced only） | 单向 glossary（一个语言对）或"等价术语集"（多语言 CSV）；TSV/CSV/**TMX 1.4**；总大小 ≤10,485,760 UTF-8 字节、单词条 <1024 字节（超长忽略）；默认**区分大小写**，请求时可整体忽略大小写；词条宜为单词或短语（通常 <5 词）；**stopwords**：词条与停用词表（the/of/to…）精确相同时被忽略；glossary 必须放在 `us-central1`（示例代码注释）；创建术语表本身不收费，按翻译字符计费 | https://docs.cloud.google.com/translate/docs/advanced/glossary ；https://docs.cloud.google.com/translate/docs/advanced/stopwords ；https://docs.cloud.google.com/translate/docs/advanced/translating-text-v3 |
| 术语表 × TLLM | 术语表页与 TLLM 页**均未说明二者是否可组合**；Basic API 明确不支持术语表（"use Advanced for glossaries"）→ **TLLM+glossary：未确证** | https://docs.cloud.google.com/translate/docs/advanced/translating-text-v3 |
| Adaptive Translation | 请求里直接给 `referenceSentencePairs`（**最多 5 对**，全部使用），或指定数据集：从数据集中**自动选出最相似的 5 句**做 few-shot；数据集用 TSV/TMX，≥5 对、API ≤30,000 对（控制台 ≤10,000）、单对 ≤512 字符；一次只能一个目标语言；输入 plain/HTML（HTML 标签不翻译）；**限速 1 QPS/项目**；控制台可调 temperature、示例数并与 NMT 并排对比 | https://docs.cloud.google.com/translate/docs/advanced/adaptive-translation |
| 定制模型 | 定制 NMT/TLLM：训练费 $45/小时，单次训练封顶 $300；定制 NMT 文本价 $80/百万字符（分档递减） | https://docs.cloud.google.com/translate/pricing |

### 2.3 文档翻译、QA、价格、限速

| 维度 | 结论 | 出处 |
|---|---|---|
| 文档翻译 | Advanced only：DOC/DOCX、PDF（可输出 PDF 或 DOCX）、PPT/PPTX、XLS/XLSX；**原生 PDF** 保留超链接/字号/颜色；**扫描 PDF 有排版损失**、表格/多栏/带图例的图有损失；同一 PDF 中混合扫描与原生内容时**扫描部分不翻译**；DOCX 文本框内文字不翻译；在线：文件 ≤20 MB，原生 PDF ≤300 页（需 `isTranslateNativePdfOnly=true`）、开 `enableShadowRemovalNativePdf` 则 ≤20 页、扫描 PDF ≤20 页；官方建议"有 DOCX/PPTX 就先翻译再转 PDF" | https://docs.cloud.google.com/translate/docs/advanced/translate-documents |
| QA | **无内置质量评估/QA 检查**（文档中只有模型评估工具：BLEU 等，用于定制模型评测）。本项为"未在文档中找到"，非"确证不存在" | https://docs.cloud.google.com/translate/docs/advanced/compare-models （"Model evaluation"导航项）；**未确证** |
| 价格（USD，标准档） | NMT 文本：**前 50 万字符/月免费（以 $10 月度抵扣实现，Basic+Advanced 共享，不结转，不适用于格式化文档翻译）**，超出 **$20/百万字符**；文档翻译（DOCX/PPT/PDF）**$0.08/页**；定制模型文档 $0.25/页；**TLLM 文本 $10/百万输入 + $10/百万输出字符**；**Adaptive $25/百万输入 + $25/百万输出**；定制 TLLM $10+$10；批量/文档按"源字符 × 目标语言数"计；语言检测不另计费；折扣档（1/3 年 Savings Plan）另列 | https://docs.cloud.google.com/translate/pricing |
| 限速/配额 | 通用模型 6,000,000 字符/分钟/项目；日配额默认不限；定制模型 100,000 字符/分钟；文档翻译 2,400 页/分钟；**TLLM 无内容配额**；Advanced 单请求最多 30K 码点（推荐 ≤5K），Basic ≤100K 字节；超配额返回 403（`Daily Limit Exceeded` / `User Rate Limit Exceeded`） | https://docs.cloud.google.com/translate/quotas |

### 2.4 对本系统最值得借鉴（Google）

1. **Adaptive "自动选最相似 5 对"的检索式 few-shot**：我们现在是"Google 免费初稿 → 廉价 LLM 修订"，可在 LLM 修订步骤复刻：以本书已校对的双语句对库（TMX/TSV）为数据集，对每个待修订段做 n-gram / 嵌入检索取最相似 3-5 对，作为 few-shot 示例注入 DeepSeek/Codex 提示词。**5 对**与 **≥5 对起步、≤512 字符/对** 这些数字可直接作为首版参数（来源：adaptive-translation 页）。分类学书里重复的描述句式（"Body elongate, ... segments ..."）收益最大。
2. **词条精确匹配 + stopwords 忽略 + 大小写开关**：Google 术语表明确"词条只有与停用词**完全相同**才忽略"、默认大小写敏感。我们的拉丁学名/术语锁定表应同样做三件事：①默认大小写敏感（学名首字母大写规则本身是语义）；②短语条目 <5 词；③设"拒收清单"，防止把 `the`、`of`、单字母缩写（如属名缩写 `P.`）当术语入库。
3. **扫描 PDF 与原生 PDF 分流 + "混合页扫描部分不翻译"的告警**：Google 文档里写明混合内容中扫描部分被跳过。我们的 OCR→翻译管线应在入口对每页判定"原生文字层 / 扫描"，对"混合页"显式打标并进入人工队列，避免静默漏翻（老专著常见：文字层 OCR 与插图中的拉丁标注混合）。

---

## 3. Microsoft Azure Translator（Foundry Tools 内；Custom Translator / 动态词典 / 文档翻译 / Adaptive custom translation）

### 3.1 总表

| 维度 | 结论 | 出处 |
|---|---|---|
| API 版本 | **2026-06-06 GA，相对 v3.0 有破坏性变更**（请求数组 `inputs`、响应数组 `value`）；新增：可选 NMT 或 **LLM 部署（示例 GPT-5.1，需 Microsoft Foundry 资源）**、**Adaptive custom translation**、LLM 的语气（正式/非正式/中性）与性别控制 | https://learn.microsoft.com/en-us/azure/ai-services/translator/text-translation/overview |
| 语言 | 保加利亚语、俄语、日语均在 NMT 语言表中；**拉丁语（Latin 语言）不在表中**——页面里的 "Latin / Latn" 是**文字系统（script）**，用于音译，不是语言 `la`（对页面文本逐行检索得出）。LLM 路径的语言覆盖：页面未单列，**未确证** | https://learn.microsoft.com/en-us/azure/ai-services/translator/language-support |
| 术语（文本 API） | **动态词典**：`<mstrans:dictionary translation="…">短语</mstrans:dictionary>` 标记；**官方明说"仅对复合名词（专名、产品名）安全"**；要求 From/To 之一为英语，且必须显式给 `From`（不能自动检测）；词条多时官方建议改用 Custom Translator；另有 `translate="no"`/`notranslate`（仅 HTML 模式）与"不把该串送去翻译" | https://learn.microsoft.com/en-us/azure/ai-services/translator/dynamic-dictionary ；https://learn.microsoft.com/en-us/azure/ai-services/translator/text-translation/how-to/prevent-translation |
| 术语（Custom Translator） | 可在 Custom Translator 中用**词典"以 100% 概率规定某短语译法"**，无训练语料时可只用词典训练模型 | 同 prevent-translation；https://learn.microsoft.com/en-us/azure/ai-services/translator/custom-translator/overview |
| 术语（文档翻译） | 词汇表（glossary）：仅**一对一**源→目标语言；TSV 优先，也支持 CSV/XLIFF；可用"源=目标"做不翻译；放在 Blob 存储，请求里给 `glossaryUrl`+`format`；批量 ≤10 MB，同步 ≤1 MB | https://learn.microsoft.com/en-us/azure/ai-services/translator/document-translation/how-to-guides/create-use-glossaries ；https://learn.microsoft.com/en-us/azure/ai-services/translator/service-limits |
| 记忆/自适应 | **AdaptCT**：在 LLM 之上，上传 **5–10,000** 对预对齐句对（**每段 ≤250 字符**，源或目标超 250 即拒收；全无效则上传失败；`Get Import Job Status` 可查出问题段），导入 TMX/TSV，**数分钟**建好"自适应数据集索引"；**推理时按请求检索相似句段**引导术语/语境/风格；或在请求里直接给**最多 5 条**参考译文；API v1.0 为预览，playground 在 Foundry NextGen 为 GA | https://learn.microsoft.com/en-us/azure/ai-services/translator/custom-translator/azure-ai-foundry/concepts/adaptive-custom-translation ；text-translation/overview（"up to five reference translations"） |
| Custom Translator（NMT 定制） | 通常需 ≥10,000 对平行句；训练可能长达约 48 小时；更新需重训重部署；可上传 ALIGN/PDF/LCL/HTML/XLF/TMX/XLIFF/TXT/DOCX/XLSX，也接受"文档级平行"（自动句对齐）；官方称正确数据下 BLEU 常 +5–10 | https://learn.microsoft.com/en-us/azure/ai-services/translator/custom-translator/overview ；adaptive-custom-translation 页对照表 |
| 文档翻译 | 异步批量（需 Blob + SAS/托管标识）与同步单文件；格式含 PDF（**扫描件用 OCR 并保留版面**）、DOC/DOCX、PPT/PPTX、XLS/XLSX、ODT/ODP/ODS、RTF、HTML、MHTML、Markdown、XLIFF、TSV/CSV、TXT、MSG、图片（jpeg/png/bmp/webp，按图计费，预览）；不支持加密/受限文档；**混合语言句子可能翻不完整**；批量：单文档 ≤40 MB、≤1000 文件、总量 ≤250 MB、≤10 目标语言；同步：≤10 MB、1 文件、1 目标语言 | https://learn.microsoft.com/en-us/azure/ai-services/translator/document-translation/overview ；https://learn.microsoft.com/en-us/azure/ai-services/translator/service-limits |
| QA | **未在文档中找到内置质量评估/QA 检查**（只有 BLEU 评测、TMX 回灌）。**未确证** | 上述页面 |
| 价格（USD，eastus，官方零售价 API） | S1 标准文本 **$10 / 百万字符**；S1 文档 **$15 / 百万字符**；S1 定制翻译 **$40 / 百万字符**；定制训练 **$10 / 百万字符（源+目标）**，单次训练封顶 **$300**；定制模型托管 **$10 / 月 / 模型 / 区域**；Free：**每月 200 万字符**（标准翻译与定制训练合计）；另有 250M/1000M/4000M 承诺档。**LLM 路径按 Azure OpenAI 的输入/输出 token 计费，不是字符** | https://prices.azure.com/api/retail/prices （2026-11-15 实查，`productName=Translator Text`，serviceName=Foundry Tools）；https://azure.microsoft.com/en-us/pricing/details/cognitive-services/translator/ （页面价格由 JS 渲染，文本抓取显示 "$-"，故价格取自零售价 API）；LLM 计费：text-translation/overview |
| 限速 | 每请求 ≤50,000 字符（跨所有目标语言合计）、数组 ≤1000 项（LLM：≤50 项、每项 ≤5,000 字符）；**按小时配额**：F0 200 万字符/时，S1 4000 万/时，S2/C2 4000 万/时，S3/C3 1.2 亿/时，S4/C4 2 亿/时；需均匀消耗（约 F0 33,300 字符/分钟）；**不限并发**；定制模型 3,600 字符/秒/模型；最大延迟 15 秒（标准）/120 秒（定制）；同步文档 600 万字符/分钟 | https://learn.microsoft.com/en-us/azure/ai-services/translator/service-limits |

### 3.2 对本系统最值得借鉴（Azure）

1. **"动态词典只对复合名词安全"这条官方限制**：它直接说明"行内标记强制译法"对**拉丁学名/专名**是可靠的，对普通术语（动词、形容词、屈折词）不可靠。我们的实现：学名、模式产地、人名、标本库缩写（BMNH/AMNH/ZIN 等）→ **占位符锁定**（翻译前替换为 `⟦T0007⟧`，翻译后回填并回检）；普通形态术语（如 "parapodium"、"chaeta"）→ 术语表 + LLM 提示词，并交 QA 闸口检查。两条通道分开，不混用。
2. **AdaptCT 的"句段 ≤250 字符、5 对起步、导入作业状态可查错误段"**：我们的双语句对库入库时做同样的**入库校验**：超长段拒收并给出具体段号、全无效则整批失败；这样可防止低质量/错位句对污染 few-shot 检索。
3. **Custom Translator vs. AdaptCT 的决策表（≥10,000 对 + 48 小时重训 vs. 5 对 + 数分钟）**：对我们（单本书、数千句、持续校对）明确选"检索式 few-shot"而非"微调"；微调留给整套丛书（≥1 万对、术语稳定）时再考虑。

---

## 4. Amazon Translate（自定义术语 / Active Custom Translation / 批量与实时文档）

### 4.1 总表

| 维度 | 结论 | 出处 |
|---|---|---|
| 语言 | 官方称 75 种语言；保加利亚语、日语、俄语在支持表中；**语言表里没有拉丁语**（对页面文本检索：仅 Bulgarian/Japanese/Russian 命中，无 Latin） | 价格页："across 75 languages"：https://aws.amazon.com/translate/pricing/ ；语言表：https://docs.aws.amazon.com/translate/latest/dg/what-is-languages.html |
| 术语机制 | 自定义术语（custom terminology）：上传术语文件，源文本命中则用术语译文。**官方明说"不保证每次都使用目标术语"**——依据源/目标词在上下文中的含义决定是否采用；可"大小写不敏感匹配"；另有 HTML `translate="no"` 不翻译标记（实时 API 与批量作业均可用，须为 HTML 元素） | https://docs.aws.amazon.com/translate/latest/dg/how-custom-terminology.html ；https://docs.aws.amazon.com/translate/latest/dg/customizing-translations-tags.html |
| 术语限额 | 文件 ≤20 MB；每账户每区域 ≤100 个术语文件；每文件 ≤30 个目标语言；**单个术语源/目标长度 ≤200 字节**；每次请求最多挂 **1 个**术语文件；ImportTerminology 5 TPS | https://docs.aws.amazon.com/translate/latest/dg/what-is-limits.html |
| 记忆/自适应 | **Active Custom Translation（ACT）**：在**批量翻译作业**中附带"平行数据"（parallel data，源语言一个 + 一或多个目标语言，CSV 等格式），运行时让输出贴合其风格、语气、用词，**无需训练定制模型**；更新平行数据即可调整；**仅批量作业**，且仅在 us-east-1 / us-west-2 / eu-west-1 可用；限额：每账户每区域 ≤1000 个平行数据资源、输入文件 ≤5 GB、**单段 ≤1000 字节**、一个资源只能 1 个源语言、同时只能 1 个创建/更新操作 | https://docs.aws.amazon.com/translate/latest/dg/customizing-translations-parallel-data.html ；https://docs.aws.amazon.com/translate/latest/dg/customizing-translations-parallel-data-input-files.html ；https://docs.aws.amazon.com/translate/latest/dg/what-is-limits.html |
| 文档/格式 | 批量文档（S3）：Txt、HTML、DOCX、PPTX、XLSX、XLIFF；**实时文档：Txt、HTML、DOCX，保留源格式，且仅支持"英语 ↔ 任一语言"**（不能非英语→非英语）；**无 PDF 支持** | https://aws.amazon.com/translate/pricing/ ；https://docs.aws.amazon.com/translate/latest/dg/what-is-languages.html |
| 其他控制 | Formality（正式度）、Brevity（简洁）、Profanity masking（粗话遮蔽），各有自己的语言列表 | https://docs.aws.amazon.com/translate/latest/dg/what-is-languages.html |
| QA | **未发现内置 QA 或质量评估**；未确证 | 上述页面 |
| 价格（USD） | 标准文本、批量文档：**$15 / 百万字符**；实时文档（Text/HTML）$15；实时文档（DOCX）**$30**；**ACT $60 / 百万字符**；免费档：标准/批量 **200 万字符/月，限 12 个月**；ACT **50 万字符/月，限 2 个月**；平行数据存储 200 GB 免费，超出 $0.023/GB/月；设置源=目标语言不收费；`auto` 检测可能收费 | https://aws.amazon.com/translate/pricing/ ；https://docs.aws.amazon.com/translate/latest/dg/what-is-languages.html |
| 限速 | 同步：输入文本 ≤10,000 字节；文档 ≤100,000 字符 / 100,000 字节；批量：每文档 ≤100 万字符、≤20 MB、文档内可翻译文本 ≤1 MB、≤10 目标语言、批内 ≤100 万文档、≤5 GB、并发作业 ≤10、排队 ≤1000；StartTextTranslationJob 5 TPS；持续限流需找 AWS Support（无公布 QPS） | https://docs.aws.amazon.com/translate/latest/dg/what-is-limits.html |
| 数据留存 | 文档称 Amazon Translate"可能存储你的数据以改进分析模型"，可联系 Support 要求删除并不再留存（可能降低译质） | 同 what-is-limits 页 |

### 4.2 对本系统最值得借鉴（Amazon）

1. **"术语不保证命中"的官方承认 + 后检**：Amazon、DeepL 都不承诺 100% 命中。印证我们必须把"术语命中"当作**需验证的断言**，而不是翻译引擎的属性——QA 闸口对每个锁定术语做**回检**（译文中是否出现目标术语/学名原样），缺失即入人工队列。
2. **术语条目 ≤200 字节、单文件 ≤30 目标语言**这类"短条目"约束：术语表应存**短语级条目**，不存整句。我们对"检索表要点（key couplets）"不要放进术语表，应放进单独的"片段级必保留断言库"（检索表要点逐条断言，QA 闸口逐条检查）。
3. **ACT 把"自适应"仅限批量作业、并按价 4 倍（$60 vs $15）计费**：说明检索式 few-shot 的**成本主要在推理端**。我们用廉价 LLM（DeepSeek flash）做同样的事，成本显著更低；应把"每段注入几对示例"作为可调参数并记录每段 token 成本，用于预算控制。

---

## 5. ModernMT → Lara（Translated；自适应 TM 的原型）

**状态（重要）**：ModernMT 官网横幅："ModernMT is evolving into Lara and will sunset by the end of 2026"；旧 ModernMT API key **至 2026-12-31 仍可用**；TM 与术语表由官方代为迁移到 Lara（https://www.modernmt.com/pricing/ 页面文本；Lara 侧迁移指南 https://developers.laratranslate.com/docs/switch-from-modernmt ）。故本节以 **Lara** 为主，ModernMT 仅作历史参照（今天 2026-11-15，距停服约 6 周）。

### 5.1 总表

| 维度 | 结论 | 出处 |
|---|---|---|
| 语言 | 官网对比表称 200+ 语言；开发者文档语言列表**含 Bulgarian `bg-BG`、Japanese `ja-JP`、Russian `ru-RU`、Latin `la-VA`**（对文档列表逐行核对）；代码形如 `la-VA`，也可只给基础语言码 | https://developers.laratranslate.com/docs/supported-languages ；https://www.modernmt.com/pricing/ |
| 模型 | Lara Base（默认）、**Lara Think**（"对术语表、风格指南、上下文元数据做多步语言分析"，官方称可自动发现并纠正约 80% 重大语言问题；低/中/高三档推理力度）、**Lara Prosa**（面向文学/高编辑价值内容的风格服务，用"风格指南"保留作者节奏与口吻）、Lara Flash（中位延迟 50 ms）、Lara Batch（成本约低 10 倍，需联系销售）。**"80%"为厂商自述，未经独立验证（未确证）** | https://developers.laratranslate.com/docs/translation-api ；https://developers.laratranslate.com/docs/translate-text |
| 术语机制 | 术语表：对命中词条"优先采用你的译法，同时调整周围句子的语法"（屈折），文档称"绝对控制"；**术语表 > TM > 模型预测**（"glossary terms take precedence"）；建议只放"不容许创造性解释"的词，别放普通词（避免 over-indexing）；大小写需与源文一致；建议同时给 context 以便正确屈折。**厂商称"always respected"但未给出可验证保证，未确证** | https://developers.laratranslate.com/docs/adapt-to-glossaries ；https://developers.laratranslate.com/docs/optimizing-laras-results |
| 记忆/自适应 | **推理时适配**（adaptive at inference，无需训练）：多个 TM 仓库（每个代表一个领域），`adapt_to=[mem_id…]`；可 TMX 批量导入、单条 TU 增删；文档称"往 TM 里加几条正确译文即可立刻修正生产环境的反复错误"；可手动指定或让引擎自动选最相关的 TM；`adapt_to=[]` 表示不适配 | https://developers.laratranslate.com/docs/adapt-to-translation-memories ；https://developers.laratranslate.com/docs/optimizing-laras-results |
| 上下文 | 内部上下文（默认，按句并行翻译但把周围句作为额外输入）+ 外部上下文（标题配正文、聊天历史、CAT 中的相邻句段）；**上下文字符不计费**；官方称内外上下文并用可减少约 40% 译后编辑（厂商自述，未确证） | https://developers.laratranslate.com/docs/adapt-to-context ；https://developers.laratranslate.com/docs/optimizing-laras-results |
| 指令 | `instructions`：**少于 20 词**的"本地化指令，不是 LLM 提示词"；只对满足条件的内容使用，用于一般内容会降质（官方举例：对不含 EUR 的串强行"EUR 改 USD"） | https://developers.laratranslate.com/docs/adapt-to-instructions |
| 文档/格式 | 官方称 60+ 原生格式（Office、**PDF**、InDesign、FrameMaker、DITA、JSON/YAML、Markdown、XLIFF、PO、字幕、HTML 等；对比表还说 70+）；文档翻译支持 `adapt_to`、`glossaries`、`output_format`、`style`；"图像/扫描类文件可能影响准确度"（官方警告）；计费按提取字符数，**每份文档最低 2 万字符** | https://developers.laratranslate.com/docs/supported-file-formats ；https://developers.laratranslate.com/docs/translate-document ；https://www.modernmt.com/pricing/ |
| QA | 介绍页称平台含"翻译与质量评估"，但**开发者文档中未找到独立 QA/QE 接口说明；未确证**；有"粗话检测""语言识别"接口 | https://developers.laratranslate.com/llms.txt ；https://developers.laratranslate.com/docs/pricing-page |
| 价格 | 仅按**源文字符**计费，不收目标字符：Lara Standard Pro **€20 / $24.99 每百万字符**，Team €15 / $19.99；Free 每月 **10,000 字符**（与语言识别共用）；文档翻译同价（最低 2 万字符/份）；**Lara Think 每百万字符：低推理 €50（$62）、中 €500（$625）、高 €2,000（$2,499）**（Pro 档）；**Lara Prosa €200（$249）每百万字符，叠加在基础模型费用之上**；Flash/Batch 需联系销售 | https://developers.laratranslate.com/docs/pricing-page （更新于 2026-11-02） |
| 限速 | **免费：1,000 字符/秒；付费：10,000 字符/秒**；可申请定制；token 10 分钟过期（需刷新）；推荐用 SDK（Python/Node/Java/PHP/Go），底层 REST 需联系销售 | https://support.laratranslate.com/en/api-rate-limits ；https://developers.laratranslate.com/docs/switch-from-modernmt |
| 数据留存 | 默认"Learning Mode"：源文、译文、上下文**可能被存储并用于改进模型**；设 `noTrace: true` 开启 Incognito | https://developers.laratranslate.com/docs/translation-api |

### 5.2 对本系统最值得借鉴（Lara/ModernMT）

1. **"术语表 > TM > 模型"的显式优先级**：我们的管线里把优先级固定成：①占位符锁定的学名/专名 > ②术语表 > ③已校对 TM 的相似句 > ④LLM 自由发挥，并把这个顺序写入提示词与回检脚本；冲突（TM 句与术语表矛盾）时术语表赢，并记日志供人工审阅。
2. **"往 TM 里加几条正确译文即可立即修正反复错误"的闭环**：人工队列里每改一处，就把"源句→终稿"追加进 TM（TMX 或 TSV），下一次同类句子自动命中。这是自适应 TM 最小可用闭环：人工校对 = 数据标注 = 下次的 few-shot。
3. **上下文不计费 + 按句并行但带周围句**：我们的 LLM 修订可采用"每句 + 前后各 N 句作为只读上下文"的窗口化提示，既保留段内指代，又让成本与句数线性相关；Lara 的"内部上下文"思路与此同构。
4. **ModernMT 停服的教训（2026 年底）**：商用自适应 MT 的供应商风险高。我们的 TM/术语资产必须以**TMX/TBX/TSV 本地为准**，不依赖任何厂商私有格式；这与已有的 OmegaT/TMX/TBX 选择一致。

---

## 6. Yandex Translate（Yandex Cloud / AI Studio；对俄语源书重要）

**取证说明**：`yandex.cloud/en/docs/translate/*` 现被 SmartCaptcha 挡住自动抓取，并 301 到 `aistudio.yandex.ru/docs/en/translate/...`（同样出验证码）。以下事实来自 **Internet Archive 存档的官方文档页**，各页存档日期不同，已逐条标注；**这些数字不是 2026-11 的现状，需在购买前到控制台复核（未确证为现行）**。

### 6.1 总表

| 维度 | 结论 | 出处（存档快照） |
|---|---|---|
| 语言 | 语言表含 `bg` Bulgarian、`ja` Japanese、`ru` Russian、`zh` Chinese、**`la` Latin**（还有 `kazlat`、`sr-Latn` 等） | https://web.archive.org/web/20260211100557/https://yandex.cloud/en/docs/translate/concepts/supported-languages （快照 2026-02-11） |
| 术语机制 | 术语表**随请求内联传递**（词对数组，"未来将支持预先从文件建库"）；两种：①**Neuroglossary**：翻译时考虑词形变化（格、性），官方例：词条 `черный`→`dark`，则 "самая черная комната" 译为 "the darkest room"；每条词对带 `exact`(bool) 标志可强制精确形式（例：table→таблицей 会得到 "Это таблицей"，说明 `exact` 可造成不合语法的输出）；适用语言：ar, bg, cs, de, en, es, fr, it, kk, pl, ru, tr, tt, uk；不支持的语言"没必要用该参数，可能工作不正确"；②**Multiglossary**：给同一词写多个候选译法，由神经网络按上下文选择（例：cat→кошка/кот；官方警告含义差异大的候选（letter→письмо/буква）会造成混淆）；译文大小写按术语表规则（小写词条随源文，首字母大写/全大写按词条） | https://web.archive.org/web/20250814220744/https://yandex.cloud/en/docs/translate/concepts/glossary （页面注明 Updated at February 12, 2024） |
| 术语限额 | 每次请求术语表词对 **≤50 对**；总字符 ≤20,000（源 10,000 + 目标 10,000）；仅指不含 CGI 参数的文本 | https://web.archive.org/web/20240918214340/https://yandex.cloud/en/docs/translate/concepts/limits （快照 2024-09-18） |
| 记忆/自适应 | **未发现**服务端 TM / 自适应机制；术语表是唯一定制手段。**未确证（可能存在而未见于存档页）** | 同上各页 |
| 文档/格式 | API v2 为文本/HTML 翻译（有"特殊字符与 HTML 标记翻译"概念页）；**文档翻译（docx/pdf）接口：未确证** | 概念页导航：https://web.archive.org/web/20250814220744/https://yandex.cloud/en/docs/translate/concepts/glossary |
| QA | **未发现**任何 QA 或质量评估功能；未确证 | 同上 |
| 价格 | **$4.101665 / 百万字符**（不含增值税，"俄罗斯区域"价目表；语言检测同价；按"日历月内提交字符总数"计费；空请求按 1 字符计）；币种取决于合同主体：Iron Hive doo Beograd（塞尔维亚）/ Direct Cursus Technology L.L.C.（迪拜）→ 美元，Yandex.Cloud LLC → 卢布。**未见官方免费档**（第三方文章称有免费额度，**未确证**） | https://web.archive.org/web/20250814103607/https://yandex.cloud/en/docs/translate/pricing （页面 "Updated at July 14, 2025"） |
| 限速 | 配额：**单方法 20 次/秒**；**每小时 100 万字符**（可向技术支持申请提高；"配额"可调，"限制"不可调）；快照仅 2024-09，**现行值未确证** | https://web.archive.org/web/20240918214340/https://yandex.cloud/en/docs/translate/concepts/limits |

### 6.2 对本系统最值得借鉴（Yandex）

1. **Multiglossary：一词多候选 + 由模型按上下文择一**。分类学旧专著里同一个俄/德/法词在不同语境有不同译名（举例，推测：同一个俄语 *щетинка* 在不同类群/语境可能需要不同英文译名；具体对应需查证）。我们的术语表可允许"主译名 + 备选 + 触发条件（类群/章节）"，在提示词里把候选列给 LLM，并在 QA 回检时接受任一候选，而不是单值硬匹配。
2. **`exact` 标志的双刃剑**：Yandex 官方自己举例说明强制精确形式会产生不合语法的输出。我们的"锁定"应分两级：**strict**（拉丁学名、模式产地、人名：原样保留）与 **lemma**（普通术语：允许屈折/语法适配），不要把普通术语 strict 化。
3. **Neuroglossary 的语言覆盖表（含 bg、ru）**：说明"带屈折适配的术语约束"并非所有语言对都可靠——对我们最关键的**保加利亚语/俄语 → 英语**，应在小样本上实测术语命中率再决定是否信任。

---

## 7. 百度翻译开放平台（中国市场）

取证说明：站点为 JS 单页，普通抓取只得到导航；以下全部来自本机 headless Chrome 渲染后的官方页面（`api.fanyi.baidu.com/product/*`、`doc/*`，渲染日期 2026-11-15，页脚 "© 2026 Baidu"）。

| 维度 | 结论 | 出处 |
|---|---|---|
| 产品线 | 大模型文本翻译（LLM，默认）、通用文本翻译（NMT）、领域文本翻译、大模型文档翻译、图片/语音翻译、语种识别 | https://api.fanyi.baidu.com/product/131 |
| 语言 | 通用文本翻译 API 称支持 **201 种语种**；"常见语种（28 种）"所有用户可调，**含保加利亚语 `bul`、俄语 `ru`、日语 `jp`**；**拉丁语 `lat` 属"非常见语种"，仅企业认证的尊享版可调，未认证/个人版调用返回错误 58001**（语种表同时含 `lat`）。大模型文本翻译接入文档的语种表同样列出 bul/ru/lat/jp | 通用：https://api.fanyi.baidu.com/product/113 （§5 语种代码对照表）；LLM：https://api.fanyi.baidu.com/product/133 ；分版语种：https://api.fanyi.baidu.com/product/112 |
| 术语机制 | "自定义术语"（术语库）：控制台上传，请求加 `needIntervene=1`；仅对当前 APPID 生效、需实名认证；**官方明说"并非生硬替换，类似调优；若术语与原释义差距过大会出现不可控结果"**；术语修改后约 10 分钟生效；开启干预可能增加延时；通用文本 API 的术语定制**仅支持中英、中日、中韩**；LLM 文本翻译的术语库当前仅支持**中、英、日、韩**四种；单条建议 ≤50 字节 | https://api.fanyi.baidu.com/product/114 （常见问题）；https://api.fanyi.baidu.com/product/131 |
| 指令/不翻译 | LLM 接口有 `reference`（自定义翻译指令，如"使用学术风格来翻译"，仅 `model_type=llm`）；`tag_handling=1` 保留尖括号标签 + `ignore_tags`（最多 20 个标签名，仅 `model_type=nmt` 且开启标签保持）；**通用文本 API"暂不支持设置对某个字符过滤及原样输出"，官方建议自行译前预处理** | https://api.fanyi.baidu.com/product/133 ；https://api.fanyi.baidu.com/product/114 |
| 记忆/自适应 | **未发现翻译记忆（TM）或检索式自适应**（只有术语库与指令） | 同上 |
| 文档翻译 | doc/docx/xls/xlsx/ppt/pptx/xml/html/htm/txt/pdf；文件 ≤50 MB（Base64 后）；PDF 可导出 docx 或 pdf；**支持扫描件/图片内文字**（`input.transImage=1`）；译文可能使页码错位（官方说明，英译中反之英文长度为中文 3-4 倍）；支持术语库；下载链接有效期 3 个月；QPS 5（可扩） | https://api.fanyi.baidu.com/product/151 ；https://api.fanyi.baidu.com/product/154 |
| QA | 无翻译质量检查；有"文本语种识别"接口 | 产品目录 https://api.fanyi.baidu.com/product/114 |
| 价格 | 通用文本：标准版 5 万字符/月免费、高级版 100 万/月、尊享版 200 万/月；超出 **¥49 / 百万字符**；领域文本：认证后每月前 50 万免费，**¥69 / 百万字符**；**大模型文本翻译：¥49 / 百万字符**（LLM；认证用户一次性 100 万字符测试额度），NMT 调用同价；大模型文档翻译：NMT ¥49/百万、LLM **¥69/百万**（LLM 为一次性 50 万字符免费）；术语库与指令功能免费；统计口径：源语言字符，空格/标点/HTML 标签均计 1 字符 | https://api.fanyi.baidu.com/product/112 ；.../product/122 ；.../product/132 ；.../product/152 |
| 限速 | 通用文本：QPS 1 / 10 / 100（标准/高级/尊享），单次请求上限 1000 / 6000 / 6000 字符；LLM 文本：QPS 10，建议单次 ≤2000 字符（上限 6000）；领域文本 QPS 5；100 字符左右请求约 100 ms，超时 2 秒；海外可用但延迟略高 | https://api.fanyi.baidu.com/product/112 ；.../product/131 ；.../product/133 ；.../product/114 |

**对本系统的借鉴（百度）**：
1. **"术语干预是调优不是替换，差距过大反而失控"**——与 DeepL/Amazon 的"不保证"同类结论，强化"锁定靠占位符，不靠引擎"。
2. **LLM 与 NMT 同一接口 `model_type` 切换 + 单价透明（LLM ¥49 vs 文档 LLM ¥69）**：我们的管线可保留"同一调用参数切换引擎"的抽象层（Google/DeepSeek/Codex 皆走同一 `translate(chunk, engine=…)` 接口），便于按成本/语种路由。
3. **文档翻译 FAQ 如实承认"页码错位"**：版面还原不是翻译引擎能解决的问题；我们的书籍管线应在"逐页对照版"与"流式排版版"之间二选一并向用户声明（与 PDFMathTranslate/BabelDOC 讨论衔接，此处不展开）。

---

## 8. 有道智云（中国市场）

取证：官方文档页 headless Chrome 渲染（`ai.youdao.com/DOCSIRMA/html/trans/...`，2026-11-15）。

| 维度 | 结论 | 出处 |
|---|---|---|
| 语言 | "常见语种"仅 17 项（含 **ru、ja**）；**保加利亚语 `bg` 在"非常见语种"表**；语言代码表含 **Latin `la`（支持自动识别=Y）** | 价目/语种表：https://ai.youdao.com/DOCSIRMA/html/trans/price/wbfy/index.html ；接口语言表：https://ai.youdao.com/DOCSIRMA/html/trans/api/wbfy/index.html |
| 术语 | 用户术语表：控制台新建，请求带 `vocabId`；**官方写明"支持英中互译，更多方向请到控制台查询"**；领域化翻译 `domain`：计算机、金融、医学、游戏四个领域，**仅中英双向**；`rejectFallback` 控制领域翻译失败时是否降级为通用翻译 | https://ai.youdao.com/DOCSIRMA/html/trans/api/wbfy/index.html |
| 记忆/文档 | 文本翻译 API 页面未见 TM；批量翻译 API 另有页（`plwbfy`）；**文档翻译与 PDF 版面保留：本次未取证，未确证** | 同上；https://ai.youdao.com/DOCSIRMA/html/trans/api/plwbfy/index.html |
| QA | 未发现 | — |
| 价格 | 后付费：通用版 常见语种互译 **¥48 / 百万字符**；中文↔非常见语种 **¥100**；其他语种间互译 **¥100**；专业领域（中英）**¥60**；新用户体验金 ¥50；资源包 500 万字符 ¥204 / 1000 万 ¥398 / 1 亿 ¥3,840（常见语种）。**拉丁语/保加利亚语 → 英语 按"其他语种间互译"¥100/百万** | https://ai.youdao.com/DOCSIRMA/html/trans/price/wbfy/index.html |
| 限速 | 默认：单次 ≤5000 字符；每小时 ≤100 万次查询；每小时 ≤120 万字符（可联系调整）；错误码 9411=访问频率受限 | https://ai.youdao.com/DOCSIRMA/html/trans/api/wbfy/index.html ；价目页"免费体验"节 |

**对本系统的借鉴（有道）**：
1. **`domain` + `rejectFallback`**：领域化模型失败时"是拒绝还是降级为通用"是显式开关。我们的"分类学术语库匹配失败/拉丁学名保护失败"也应有同样的显式策略：**默认拒绝（进人工队列），不静默降级**。
2. **按语种对分档计价（常见 ¥48 vs 非常见 ¥100）**：我们的成本估算表应按语种对分档（俄/保/日/拉 → 英/中 的实际单价不同），避免用单一单价预算整套书。

---

## 9. 腾讯机器翻译 TMT / TranSmart / Hy-MT2（中国市场；**两项服务正在退市**）

| 维度 | 结论 | 出处 |
|---|---|---|
| **服务状态（最重要）** | ①**TranSmart（腾讯交互翻译）官网横幅："将于 2026 年 11 月 24 日正式关闭"**（距今 9 天）；②**TMT 文本翻译/批量文本翻译**：退市通知（2026-10-26 发布）：停售 EOM=2027-01-31，停止标准支持 EOSS=2027-07-31，**完全停服 EOMS=2030-12-31**；推荐迁移到"大模型服务平台 TokenHub"的 hy-mt2-plus / pro / lite；③**QPS 调整公告（2026-09-03）**：自 2026-10-01 至 2027-01-31 每月在上月基础上下调 5%（向下取整，最低 1），2027-02-01 至 2027-09-30 每月下调 10%，**2027-10-01 起 QPS 降为 0（列出的接口全部不可用）**；**自 2026-10-01 起停止发放免费资源包**；注意③与②的完全停服日期（2027-10-01 vs 2030-12-31）在两份公告间不一致，**以哪一份为准未确证**，务必视作"不可依赖"。受影响接口：文本翻译、批量文本翻译、图片翻译、语音翻译、文件翻译、语种识别 | TranSmart：https://transmart.qq.com/zh-CN/intro ；TMT 退市：https://cloud.tencent.com/announce/detail/2482 ；QPS/免费包：https://cloud.tencent.com/announce/detail/2448 ；公告目录：https://cloud.tencent.com/document/product/551/131164 |
| 语言 | TMT 产品页称支持 **18 个语种**（无拉丁语；保加利亚语也不在公开列出的常见语种中，**未逐项核对，未确证**）。替代品 **Hy-MT2**（开源，1.8B/7B/30B-A3B，33 种语言）语种表含 zh/en/ja/ru 等，**不含保加利亚语和拉丁语** | https://cloud.tencent.com/product/tmt （搜索摘要："目前支持 18 个语种"）；https://github.com/Tencent-Hunyuan/Hy-MT2 （README 语种表） |
| 术语/TM | TMT 有"术语库"（控制台创建、指定语言方向、接口调用）；**限额与屈折处理未取证，未确证**。TranSmart 官方介绍：交互式机器翻译（译文片段推荐、整句补全）、**翻译记忆融合**（"动态结合用户已完成的双语句对"）、翻译输入法 | TranSmart 同上；术语库：仅见搜索结果摘要（"管理术语库"页，2025-05-09），**未取到页面本身，细节未确证** |
| 价格（TMT，页面更新 2026-07-15） | 文本翻译后付费：**0–1 亿字符/月 ¥58 / 百万；≥1 亿 ¥50 / 百万**（月度阶梯）；文本翻译曾每月 **500 万字符免费**，**2026-10-01 起不再发放新免费包**；文件翻译 **¥2.5 / 万字符（= ¥250 / 百万）**，日结，无免费额度；预付费包：1000 万字符 ¥550 / 1 亿 … ；失败调用与语种识别不计费 | https://cloud.tencent.com/document/product/551/35017 ；https://cloud.tencent.com/announce/detail/2448 |
| 文档 | 文件翻译接口存在（¥250/百万字符，较文本贵 4 倍以上） | 同上 |
| QA | 未发现 | — |

**对本系统的借鉴（腾讯）**：
1. **TranSmart 的"翻译记忆融合"思路**（动态结合已完成的双语句对生成更贴近预期的自动译文）——与 Lara 的推理时适配同类；它被关闭恰好说明**依赖单一厂商的交互式/自适应工具有停服风险**（与 ModernMT 同年同样退场）。资产放本地 TMX/TBX。
2. **公告式"逐月递减 QPS"退市方式**：厂商 API 可能在无功能变化下被逐步降配。我们的引擎适配层必须做**健康探测 + 自动切换备选引擎**（Google → DeepL → DeepSeek 等）。

---

## 10. CAT/QA 领袖：Trados Studio QA Checker / memoQ QA / Xbench / Verifika

这四者**不是 MT**，是"译后检查器"。重点回答：每个工具到底查什么、哪些检查能被我们的自动 QA 闸口复刻。

### 10.1 检查项对照

| 检查类别 | Trados Studio（QA Checker 3.0 + Tag/Terminology Verifier） | memoQ（QA settings，12.6 文档） | Xbench 3.0 | Verifika |
|---|---|---|---|---|
| 数字 | Numbers：检查数字、时间、日期是否被正确转换 | **数字匹配**（按语言格式"语言学解释"，如 1,000 vs 1.000）；数字格式一致；**字母数字码**（产品码、测量值、URL）须源目一致；可纳入计量单位 | 数字不匹配；字母数字不匹配；URL/邮箱不匹配 | 官方称 55 种错误类型（清单未取到，**细项未确证**） |
| 标签/格式 | Tag Verifier：多/少标签、标签顺序、**幽灵标签**、标签周围空格 | 缺失/多余标签、顺序变化、重叠成对标签、良构性；粗体/斜体/下划线一致 | 标签不匹配 | 官方称含"错位标签" |
| 术语 | **Terminology Verifier**（基于术语库）；**Word List**（"不得使用词 → 正确形式"的简易术语检查，不依赖术语库） | 术语表一致使用：源→目 / 目→源 / 双向；**禁用术语**警告（可含"源文中出现禁用术语"）；**非翻译项**（non-translatables）源目一致 | **Key Terms**：关键术语偏离（多个同义词中任一出现即通过） | **Termbases / Wordforms 词形库**（API 里有 `Wordforms`、`WordformsBases` 资源）、`UntranslatablesAnalysis` |
| 一致性 | Inconsistencies：同源异译、重复词 | 相同源句不同译文；**与 TM 最佳/最近精确匹配不一致**；同一 TM 有多个互异精确匹配；目标重复词 | 同源异译 / 同译异源 / **目标=源（疑似未译，默认关）** | 官方称含一致性 |
| 标点/空格/大写 | Punctuation（按语言对设置）；Trademark（商标/版权符号） | 语言特定标点、括号引号**未配对**、标点序列合法性、句末标点一致；双空格/行尾空格/首字母大小写 | 未配对符号（括号、引号）、重复词、双空格；**CamelCase、全大写词无对应（默认关）** | 官方称含 |
| 长度 | Length verification | 目标/源长度比（字符/词，均值×容差）、绝对长度、像素长度 | — | — |
| 未译/空译 | Segments verification：缺译、未完成 | 目标为空；目标等于源 | 未译段 | — |
| 正则/自定义 | **Regular Expressions**（.NET 语法） | **Regex 检查**，"几乎可以做任何自动检查"，可写修正建议 | **Checklists**（用户自定义检索，支持正则/Word 通配符）、项目清单与个人清单 | 可自定义规则（API 文档："Customization and Extensibility"） |
| 拼写/语法 | （另有拼写） | 拼写、语法（调用外部检查器）；可忽略非翻译词表 | Hunspell 拼写，48 种语言 | 官方称 70+ 语言 |
| 严重度 | 每项可设 Error / Warning / Note | **按项设为警告或错误** | — | — |
| 出处 | https://docs.rws.com/en-US/sdl-trados-studio-783545/specifying-settings-for-qa-checker-359765 （页面为 Studio 2019 文档，经 webReader 取得；docs.rws.com 对直接抓取返回 403）；https://www.xbench.net （Xbench 3.0，年费 €99）；https://docs.xbench.net/online-help/dialogs/main-window/qa/ | https://docs.memoq.com/current/en/Workspace/edit-qa-settings.html ；https://docs.memoq.com/current/en/Things/things-quality-assurance-qa-warnings.html （官方称 "over a hundred different types of checks"） | 同左 | https://e-verifika.com/ （"Locate 55 error types in over 70 languages"）；https://qa-api.e-verifika.com/ （API 1.1 beta） |

### 10.2 其他关键事实

| 项 | 结论 | 出处 |
|---|---|---|
| memoQ QA 档位 | 默认 QA 设置不可直接编辑，须克隆；QA 设置属于项目；QA（自动）与 **LQA（人工打分、结构化反馈）**分开 | https://docs.memoq.com/current/en/Workspace/edit-qa-settings.html |
| memoQ 数字检查的已知麻烦 | 文档自己承认"可能出现矛盾的数字警告"（社区抱怨）；本项为论坛讨论，**非官方结论，仅作旁证（未确证）** | 搜索结果：r/MemoQ 帖 "Numbers - false positives issue" |
| Xbench 误报管理 | Xbench 官方博客/文章主题含"按风险排序 500 条 QA 报告、标记确认误报"（2026-10-02）；说明**误报治理是 QA 工具的核心工作量**（页面未取全，**未确证细节**） | 搜索结果摘要；https://www.xbench.net |
| Verifika 产品形态 | Verifika App/Desktop/Web、**Verifika API（beta，OpenAPI 规范，可由 TMS 触发：建项目→上传（>100 MB 分块）→套 QA 配置→运行→取 QualityIssues/Reports）**、**Verifika EQA（对人工或机翻做"快速质量评估"）** | https://e-verifika.com/ ；https://qa-api.e-verifika.com/ |
| 价格 | Xbench：**€99/年**起（30 天试用）；memoQ、Trados：许可证/订阅价本次未取到，**未确证**；Verifika：定价页本次未取到，**未确证** | https://www.xbench.net |

### 10.3 对本系统最值得借鉴（CAT/QA 工具）

1. **memoQ 的"数字检查"设计要点**（我们的数字闸口应逐条对标）：①按语言格式解释（千分位/小数点）而不是字符串比较；②**把数字解释为"数量"而非章节编号**（官方例：英文里的 1.5 被解释为 "one and a half"，不当作 "1.5 节"；匈牙利语里 1.5 因句点不符合其小数格式而不能当数量）——旧专著中"1.5"既可能是小数也可能是章节号，俄/保文本用逗号作小数点，这条规则直接相关；③**字母数字码**（标本号 BMNH 1985.123、`USNM 12345`、测量值 "3.5 mm"）须源目一致；④可选把**计量单位纳入比较**（mm/cm 换算错误是分类学描述的高频事故）；⑤全角数字在非 CJK 文本中报警。这五条几乎覆盖我们 "numbers" 闸口的需求。
2. **Xbench Key Terms 的"同义词任一出现即通过"**：术语回检要允许一组可接受译名（与 Yandex Multiglossary 呼应），不通过才进人工队列，降低误报。
3. **Trados Word List 的"禁用形式 → 正确形式"对**：专为"某错误形式不得出现"设计（官方例：不得出现 "Website"，正确形式为 "web site"）。这比"必须出现某术语"更便于从历史校对记录自动生成：人工把译文中的 A 改成 B 之后，自动登记"A 为禁用形式、B 为规定形式"。
4. **memoQ 的"目标重复词、双空格、未配对括号引号、标点序列"**：全部是廉价、确定性、低误报的检查，应作为 QA 闸口第 0 层（先于数字/学名/否定/要点）。
5. **严重度三档 + 可强制"不修正不得确认"（Smartcat 同）**：我们的人工队列也应有"阻断级"（拉丁学名被改、数字缺失、否定丢失）与"提示级"（风格）。
6. **Verifika API 的"TMS 触发 → 建项目 → 套 QA 配置 → 取 QualityIssues 报告"流程**：我们的闸口输出也应是机器可读的 `QualityIssues[]`（段号、类型、严重度、span），并能被"第二模型核意"步骤读取。

---

## 11. Phrase 与 Smartcat（MT + TM + QA 编排）

### 11.1 Smartcat：六步 AI 翻译流水线（与我们的管线结构最接近）

| 步骤 | Smartcat 官方描述 | 出处 |
|---|---|---|
| 1 分段 | 每个文件切成段（通常一句），TM 查找/AI 翻译/QA 均在段级运行 | https://help.smartcat.com/ai-translation-overview （2026-10-13 更新） |
| 2 TM 查找 | 先查"已审译文"（TM）精确匹配，命中则自动确认、**不再送 AI、也不进人工审校范围** | 同上 |
| 3 AI 翻译 | 按语言对**自动路由**到最佳 AI 引擎，可在项目设置里改 | 同上 |
| 4 质量检查 | 缺格式标签、**数字错误**、标点、大小写、**目标长度异常** + **术语错误**（最重要） | 同上 |
| 5 术语修复 | QA 发现术语错误时，对**非 LLM 引擎**自动触发 OpenAI 修正；LLM 引擎被"信任"能处理术语，不再修复 | 同上 |
| 6 兜底 | 段仍有严重错误（缺格式、引擎失败）则自动用 **Google NMT 重跑**；未来可自选兜底引擎 | 同上 |

| 维度 | Smartcat | 出处 |
|---|---|---|
| AI 译者看到的输入 | 固定的封闭集合：源/目标语言、源文、**术语（含禁用术语）、TM 模糊匹配**；**看不到**段落批注、内容类型、参考图；段落按批送入模型（批内相邻段可见，**批间可能漂移**）；AI Review/LQA 代理按约 30 段一批，术语带 Preferred/Allowed/Forbidden 状态，**官方明说这是"上下文指示，不是硬强制"** | 同上 |
| QA | 拼写、标点、术语（**考虑词形变化：用了不同词形不算错**）、格式、与 TM 一致性；三档：忽略 / 通知（黄三角）/ **要求修正（红三角，未修正不可确认）**；"目标超长"与所有标签错误默认为严重且不可关闭；可导出 Excel 报告（带回到编辑器的链接） | https://help.smartcat.com/quality-assurance/ （2026-10-12） |
| 质量评分 | **TQS（0–100）**：仅评估 AI 译文；高于阈值的段可（手动或按规则）**自动确认**，低于阈值的段推荐审校；人工审校后的段给满分；**TM 精确匹配固定分（100%→95，101%→99，102–103%→100），<100% 模糊匹配不打分**；审校者的所有修改入 TM，"AI 从这些修改中学习" | https://help.smartcat.com/understanding-translation-quality-score/ （2026-10-27） |
| TM 匹配分级 | 50–74 / 75–84 / 85–94 / 95–99（模糊）、100（精确，未验证上下文）、**101（精确 + 一侧相邻段上下文匹配）、102（两侧）、103（精确 + 段键/ID，仅软件文件）**；TM 存前后源段作为上下文元数据（`x-context-pre/post`） | https://help.smartcat.com/how-tm-matching-works-in-smartcat/ （2026-11-10） |
| 语言 | 称 280+ 语言；语言表含 Latin（页面中多处出现 "Latin"）；**TM/术语/AI 路由对拉丁语的实际引擎未核对，未确证** | https://help.smartcat.com/pricing-plan-overview/ ；https://help.smartcat.com/supported-languages/ |
| 价格 | 全部为按 **Smartwords** 消耗计费（不按人头，不限用户）：Adapt **$1,200/年**（10 万 Smartwords）、Accelerate **$24,000/年**（100 万）、Anticipate **$60,000/年**（200 万；含 API、QA Co-worker）、Autonomous 定制（600 万）；新方案下 **≥100% TM 匹配、重复段、自动复制、数字转换不耗 Smartword；50–99% 模糊匹配仍每源词耗 1 个**；无独立免费档（本页未写，**未确证**） | https://help.smartcat.com/pricing-plan-overview/ ；https://help.smartcat.com/how-tm-matching-works-in-smartcat/ |

### 11.2 Phrase（Phrase TMS / Strings / Language AI / Orchestrator）

| 维度 | 结论 | 出处 |
|---|---|---|
| 产品 | 一个平台含 TMS、Strings、Language AI（机器翻译）、Orchestrator（工作流自动化）、Custom AI、QPS | https://phrase.com/pricing （headless Chrome 渲染，2026-11-15） |
| MT 编排 | **MT Autoselect**（自动选最合适的引擎）、托管引擎、Phrase NextMT / Next Gen MT、**Auto Adapt**、**MT Optimize**（Orchestrator）、**Automated Asset Curation**（Custom AI）、AI Translation Agent；MT Profiles（Team 档 6 个）与 **MT Glossaries（Team 档 10 个；Business/Enterprise 无限）** | 同上 |
| QA/质量 | **Phrase QPS**：AI 质量估计，输入源文+译文，输出 0–100，目标是预测"若由人工按 MQM 评审会得多少分"；分级 95–100 优秀 / 90–94 很好 / 75–89 良好 / 0–74 差；段级显示；有 Analytics 看板帮助找"节省成本与质量风险之间的最优阈值"；API 提供**文档级**分数；**Orchestrator 可按 QPS 阈值自动路由**（低分段送人审，或一组段送 LQA）；另有 LQA（人工）。**QPS 支持的语言对表中：ru→en、en→ru、ja→en、en→ja、ja→zh-hans 在内；保加利亚语只作目标语言出现，不能作源语言（按页面表格解析）；无拉丁语** | https://support.phrase.com/hc/en-us/articles/5709672289180-Phrase-QPS-Overview |
| 价格 | Team 档页面标价 **$1,245/月（按年付）**，含 12,000,000 MTU/年（Phrase Language AI），无限 TMS 席位、20 Strings 席位；Business 定制，50,000,000 MTU/年；开发者/设计师与自由译者/LSP 档另列（第三方称自由译者档 $27/月，**官方页面渲染中未核到，未确证**）；全部方案 14 天试用，无独立免费档；**MTU 的单位定义本次未核对（未确证）** | https://phrase.com/pricing |
| 限速 | 本次未取到公开限速数字；**未确证** | — |

### 11.3 对本系统最值得借鉴（Phrase / Smartcat）

1. **Smartcat 的六步流水线几乎就是我们的管线**（分段 → TM 优先 → MT 路由 → QA → 术语修复 → 兜底）。直接采纳两点：**TM 命中即跳过 LLM 与人审**；**严重错误自动回退到另一引擎重跑**（我们的回退链可为 Google → DeepSeek → Codex）。
2. **"LLM 引擎被信任处理术语，不再做术语修复"的假设是危险的**——我们的"第二模型核意"不能因为用了 LLM 就跳过术语回检；对分类学术语，应对 LLM 输出同样强制回检（Smartcat 的省略是为了省成本，不是因为 LLM 可靠）。
3. **QPS/TQS 阈值自动路由**：低于阈值的段进人工队列，高于阈值自动放行。我们没有 QE 模型，可用"多信号打分"近似：Google 初稿与 LLM 修订稿的编辑距离、两个模型对同一段的意译一致度、QA 闸口失败数。阈值按抽检的人工通过率校准，并像 Phrase 那样**用看板找成本-风险最优阈值**。
4. **QE 模型的语言覆盖有限（Phrase 无拉丁语、保加利亚语不能作源）**：对我们的核心语种（保/拉）不能依赖商用 QE，要用自建的核意步骤。
5. **TM 上下文匹配 101/102%**：把"前后相邻源句相同"作为更高置信的 TM 命中，对重复出现的检索表句式、标本列表格式特别有效。

---

## 12. 汇总对照表

### 12.1 四个关键语种的支持情况（官方页面，逐产品核对）

符号：✓ = 官方列表中有；✗ = 官方列表中未见（按页面检索）；△ = 有条件；? = 未确证。

| 产品 | 保加利亚语 | 俄语 | 日语 | 拉丁语 | 备注 |
|---|---|---|---|---|---|
| DeepL API | ✓（含术语表/TM/指令） | ✓（同左） | ✓（同左） | **✓ 但仅翻译+标签，无术语表/TM/指令** | 官方 API 语言表 |
| Google NMT | ✓ | ✓ | ✓ | ✓（`la`） | 官方语言页 |
| Google TLLM / Adaptive | ✓ | ✓ | ✓ | **✗**（TLLM 列表无 Latin） | 同页；Adaptive 与 TLLM 同列表 |
| Azure Translator | ✓ | ✓ | ✓ | **✗**（"Latn"是文字系统） | LLM 路径的语言覆盖 ? |
| Amazon Translate | ✓ | ✓ | ✓ | **✗** | 75 种语言 |
| Lara（ModernMT 继任） | ✓ | ✓ | ✓ | ✓（`la-VA`） | 200+ 语言；2026 年底 ModernMT 停服 |
| Yandex | ✓ | ✓ | ✓ | ✓（`la`） | 存档页（2026-02），现行 ? |
| 百度（通用/LLM 文本） | ✓（28 常见语种内） | ✓ | ✓（`jp`） | △（`lat`，仅企业认证尊享版） | |
| 有道 | △（"非常见语种"，¥100/百万） | ✓ | ✓ | ✓（`la`） | |
| 腾讯 TMT / Hy-MT2 | ?（18 语种） / ✗ | ✓ / ✓ | ✓ / ✓ | ✗? / ✗ | TMT 文本翻译在退市 |
| Phrase QPS（质量估计） | **✗ 作源**（仅目标） | ✓（ru→en、en→ru） | ✓（ja→en、en→ja） | ✗ | 页面表格解析 |
| Smartcat | ? | ? | ? | 语言表含 Latin | 280+ 语言，引擎路由细节 ? |

### 12.2 术语强制机制的"硬度"

| 产品 | 机制 | 官方对"是否保证命中"的说法 |
|---|---|---|
| DeepL | 术语表（含屈折适配）、TM（≥阈值复用）、style rules/custom instructions（最多 10 条×300 字符） | 未承诺 100%（未确证有保证）；context 明说不可当指令 |
| Google | 术语表（TSV/CSV/TMX，大小写敏感，stopwords 忽略）、Adaptive（≤5 句示例） | 术语表页未写保证级别（未确证）；Adaptive 称"风格贴近" |
| Azure | 动态词典标记、Custom Translator 词典（"100% 概率"）、文档术语表 | 动态词典"仅对复合名词安全"；词典 100% 为官方表述（Custom Translator 内） |
| Amazon | 自定义术语、ACT 平行数据、不翻译标签 | **明说不保证** |
| Lara | 术语表 > TM > 模型 | 称"绝对控制/always respected"，无可验证保证（未确证） |
| Yandex | Neuroglossary（`exact`）、Multiglossary | `exact` 可产生不合语法输出；不支持语言上"可能不正确" |
| 百度 | 术语库 `needIntervene` | **明说"调优而非替换"，差距大时结果不可控**；仅中英/中日/中韩 |
| 有道 | `vocabId` 术语表（英中互译）、领域模型（中英 4 个领域） | 未见保证表述（未确证） |

### 12.3 价格（每百万源字符；官方页面；货币各异，不可直接比较）

| 产品 | 标准价 | 免费/起步额度 | 备注 |
|---|---|---|---|
| DeepL API Growth | 含 1200 万字符/年（$26/月年付）；超出 $27.50（HK-USD）或 €22（DE-EUR） | Developer：一次性 100 万字符 | 价格随地区变；Free/Pro 已停售 |
| Google NMT | $20 | 每月前 50 万字符（$10 抵扣） | 文档 $0.08/页 |
| Google TLLM | $10 输入 + $10 输出 | — | Adaptive：$25 + $25；定制 TLLM $10 + $10 |
| Azure S1 | $10；文档 $15；定制 $40 | F0：每月 200 万字符 | LLM 路径按 Azure OpenAI token 计费 |
| Amazon | $15；ACT $60 | 200 万字符/月 × 12 个月；ACT 50 万/月 × 2 个月 | 实时 DOCX $30 |
| Lara Standard（Pro） | €20 / $24.99 | 每月 1 万字符 | Think €50–2,000；Prosa €200（叠加） |
| Yandex | $4.101665 | 无官方免费档（未见） | 价目页 2025-07 版 |
| 百度 | ¥49（通用/LLM）；领域 ¥69；LLM 文档 ¥69 | 标准 5 万 / 高级 100 万 / 尊享 200 万 字符每月 | 术语库、指令免费 |
| 有道 | ¥48（常见语种）；¥100（含非常见语种）；中英专业领域 ¥60 | 新用户体验金 ¥50 | |
| 腾讯 TMT | ¥58（<1 亿/月）、¥50（≥1 亿）；文件 ¥250 | **2026-10-01 起不再发放免费包** | 文本翻译退市中 |
| Phrase Team | $1,245/月（年付），含 1200 万 MTU/年 | 14 天试用 | MTU 定义 ? |
| Smartcat | Adapt $1,200/年起（10 万 Smartwords） | — | ≥100% TM 不耗 |
| Xbench | €99/年起 | 30 天试用 | |

**算术推算（非官方数字，仅作量级）**：一本约 100 万字符的专著，纯机翻费用（不含免费额度）约为：Yandex ≈ $4.1、Azure ≈ $10、Google NMT ≈ $20（扣 50 万免费后 ≈ $10）、Amazon ≈ $15、Lara Standard ≈ €20、百度 ≈ ¥49。与整条人工校对队列的成本相比可忽略——**成本不是选 MT 的约束，术语/学名可控性与语种覆盖才是**。

### 12.4 时间敏感事项（供决策，距 2026-11-15）

| 日期 | 事件 | 出处 |
|---|---|---|
| 2026-11-24 | TranSmart（腾讯交互翻译）关闭 | https://transmart.qq.com/zh-CN/intro |
| 2026-12-31 | ModernMT 旧 API key 失效，停服 | https://www.modernmt.com/pricing/ |
| 2027-01-31 | 腾讯 TMT 文本/批量文本翻译停售（EOM）；2027-07-31 停止标准支持；2030-12-31 完全停服（另有 QPS 递减至 2027-10-01 为 0 的公告，二者冲突，以哪份为准未确证） | https://cloud.tencent.com/announce/detail/2482 ；https://cloud.tencent.com/announce/detail/2448 |
| 已发生 | DeepL API Free/Pro 停售；腾讯免费包 2026-10-01 停发；Azure API 2026-06-06 有破坏性变更 | 各节出处 |

---

## 13. 未确证清单（本次未能从官方页面核实）

| 项 | 原因 |
|---|---|
| DeepL 术语表/TM 的**命中保证**与屈折处理的失败率 | 官方只说"flexes"，未给保证 |
| Google 术语表是否可与 TLLM/Adaptive 组合 | 术语表页与 TLLM 页均未写 |
| Google/Azure/Amazon/Lara/Yandex/Smartcat 的**内置 QA** | 文档中未找到；非"确证不存在" |
| Yandex 的现行价格/限额/语言表 | 官方站 SmartCaptcha；用 Wayback 存档（2024-09 至 2026-02 不同页面） |
| Yandex 文档翻译接口 | 存档页未见 |
| 百度"28 种常见语种"之外的文档翻译语种限制；有道文档翻译 | 未取到对应页面 |
| 腾讯 TMT 术语库细节、语言表逐项 | 页面为 SPA，只取到计费页与公告 |
| Lara"80% 重大问题自动纠正""减少 40% 译后编辑"等 | 厂商自述，无独立验证 |
| Phrase MTU 定义、Phrase/Smartcat 限速、Smartcat 引擎路由对拉丁语的实际引擎 | 页面未写 |
| memoQ/Trados 订阅价、Verifika 定价 | 页面未取到 |
| Verifika 55 种错误类型的完整清单 | 官网只给总数 |
| Trados 文档版本 | 取到的是 Studio 2019 版文档页（docs.rws.com 直接抓取 403，经 webReader 取得），现行版本的检查项可能更多 |

---

## 最值得借鉴（排序）

排序依据：(a) 对"分类学感知书籍翻译"的价值；(b) 是否已被多家独立厂商的官方文档印证；(c) 实现成本。

| 序 | 借鉴点 | 来源产品 | 在我们系统里怎么做（具体） |
|---|---|---|---|
| 1 | **术语/学名"双通道"：占位符锁定 + 术语表 + 译后回检，永不信任引擎的"命中"** | Amazon（明说不保证）、百度（"调优而非替换"）、Azure（动态词典仅对复合名词安全）、DeepL（context 不是指令通道） | ①strict 级：拉丁学名、模式产地、人名、馆藏号 → 翻译前换成 `⟦T0007⟧`，翻译后回填，缺失/多出即阻断；②lemma 级：普通形态术语 → 术语表 + 提示词，允许屈折；③QA 闸口对每个锁定术语回检并记录"命中/缺失/改写" |
| 2 | **人工校对回灌的检索式 few-shot 与 TM 命中分级** | Google Adaptive（取最相似 5 对）、Azure AdaptCT（5–10,000 对，≤250 字符/段）、Lara（`adapt_to`、术语表>TM>模型）、DeepL TM（阈值默认 75、下限 50）、Smartcat（101/102% 上下文匹配） | 校对通过的"源句→终稿"追加到本地 TMX/TSV；LLM 修订前对每段检索 top-3~5 相似句对注入提示词；≥75%（可调）直接复用并跳过 LLM；前后句同时命中记为"上下文匹配"，置信更高；入库校验（超长/错位拒收并指出段号） |
| 3 | **机器可读的段级质量问题 schema** | DeepL 质量评估（type/sub_type/severity/源目 span/`segment_score`/`applied_glossary_term_pairs`）、Verifika API（`QualityIssues`）、memoQ（严重度可配） | QA 闸口与"第二模型核意"都输出统一 `issues[]`：`{seg_id, type: Accuracy.Omission/Mistranslation/Untranslated, Fluency.Inconsistency, severity: Critical/Major/Minor, src_span, tgt_span}`，并附"本段命中的术语对"，供人工队列精确定位与统计 |
| 4 | **memoQ 式确定性检查层（QA 第 0/1 层）** | memoQ、Xbench、Trados | 数字：按语言格式解释；区分"数量 vs 章节号"（1.5）；字母数字码（标本号、测量值）源目一致；可选带计量单位比较（mm/cm 错位）；全角数字告警。另加：括号/引号未配对、标点序列、目标重复词、目标=源（疑似漏译）、空译。这些确定性、低误报，放在数字/学名/否定/要点检查之前 |
| 5 | **管线骨架：TM 优先 → 引擎路由 → QA → 术语修复 → 兜底重跑；且 LLM 也要回检** | Smartcat 六步流水线 | 在现有"Google 初稿 → 廉价 LLM 修订"之外补三件：TM 命中即跳过；严重错误（学名被改/数字缺失/否定丢失）自动换引擎重跑（Google→DeepSeek→Codex 回退链）；**不采纳 Smartcat"LLM 免术语修复"的假设**，对 LLM 输出同样强制术语回检 |
| 6 | **分数阈值路由人工队列，并用看板找最优阈值** | Phrase QPS（0–100、Orchestrator 阈值路由、Analytics 看板）、Smartcat TQS（高于阈值自动确认） | 无商用 QE 覆盖保/拉：用多信号近似分数（Google 稿与 LLM 稿的差异度、两个模型的意译一致度、QA 失败数）；抽检校准阈值；看板展示"阈值 vs 人工通过率 vs 人工小时" |
| 7 | **禁用形式表 + 同义词任一通过 + 一词多候选** | Trados Word List、memoQ 禁用术语、Xbench Key Terms、Yandex Multiglossary | 人工把 A 改成 B 时自动登记"A=禁用、B=规定"；术语条目允许"主译名+备选+触发条件（类群/章节）"，回检接受任一备选；条目保持短语级（Amazon ≤200 字节、Google 通常 <5 词），整句要点放"断言库"逐条检查 |
| 8 | **引擎适配层 + 供应商风险对冲** | ModernMT 停服（2026-12-31）、TranSmart 关闭（2026-11-24）、腾讯 TMT 文本翻译退市与 QPS 逐月递减 | 所有 TM/术语/断言以本地 TMX/TBX/TSV 为准；引擎接口统一 `translate(chunk, engine, params)`；周期性健康探测，失败自动切换；记录每段使用的引擎与版本，便于重跑 |
| 9 | **按语种对做引擎路由，针对拉丁语/保加利亚语缺口** | 语种矩阵（§12.1） | 拉丁语段：DeepL 无术语/TM/指令、Google TLLM 无拉丁、Azure/Amazon 无拉丁 → 路由到 Google NMT/Lara/Youdao/Yandex 初稿 + LLM 修订，并把术语锁定放在我们自己侧；保加利亚语：Phrase QPS 不能作源 → 用自建核意；俄/日：多数产品完整支持，可优先评估 DeepL（带术语表+TM）作对照基线 |
| 10 | **上下文只给"语境"、规则走结构化表；扫描/原生 PDF 分流与混合页告警** | DeepL（context 不是指令、不计费）、Lara（上下文不计费）、Google 文档翻译（混合页扫描部分不翻译） | 提示词里只放前后各 1–2 句与章节/阶元路径作为只读上下文；规则（术语、学名、否定保护）不放自然语言指令；OCR 入口对每页标"原生/扫描/混合"，混合页进人工队列，避免静默漏翻 |

---
（调研方法说明：站点内容均于 2026-11-15 当日抓取；JS 渲染站点用本机 headless Chrome 渲染后取文本；无法抓取者用 Internet Archive 存档并逐条注明快照日期；价格以官方页面为准，第三方文章仅作旁证且已标注。）
