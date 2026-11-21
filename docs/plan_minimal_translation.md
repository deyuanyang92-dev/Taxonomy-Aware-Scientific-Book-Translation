# 极简翻译方案（规划，2026-11-14）

目标：一本书的翻译主要靠本地库和脚本完成，模型只译「库里没有的新句子」，且用最便宜的模型。

## 1. 本地三库
| 库 | 内容 | 状态 |
|---|---|---|
| 术语库 yiku（~/.yiku/yiku.db） | 已核术语、义项、出处 | 已有；Harrison 新增 53 条 |
| 人名库 skill/person_names.tsv | 通行中文名（达尔文、华莱士…） | 已有（fidelity_check 用） |
| 译忆库 tm.db（~/.yiku/tm.db，待建） | 已译书稿逐句中英对照 + 固定句式表 | 待建 |

译忆库来源：Harrison 全书（/mnt/p/解剖学/<单元>/试译.md ↔ /mnt/p/翻译-译作/Harrison1992_Annelida/<单元>/src_en/，页码标记对齐）、Mayr/Futuyma 对照段（_比测/）、Rouse（如能干净对齐）。
对齐：页 → 段 → 句；句级用锚点（数字、年份、引文、学名、图号）+ 长度比；只收高置信度对。
句式表：自动挖掘高频固定句式（Scale bar = N µm → 比例尺 = N µm；(After X, 1980) → （仿 X, 1980）；图注缩写「xx, word」→「xx，中文」），出现 ≥3 次且译法 ≥80% 一致才收。

## 2. 翻译流程（按成本从低到高）
1. 脚本预翻译 `tm pretranslate`：整句命中直接复用；骨架命中（只有数字/学名/引文/图号不同）复用并替换；句式命中填空；缩写行查表；其余标〔待译〕。
2. 只把〔待译〕句交给模型：本机免费模型（ollama 已装，GTX 1660S 6GB 可跑 7–8B 量化中文模型）或夜间 DeepSeek（关 thinking）；每句附译忆库中最相似的 2–3 对作示例。
3. 脚本核验与自动修：fidelity_check（学名、人名、数字、术语首现括注）、heading_bilingual（标题双语）、species_format、cite_diff、split_check。
4. Claude 只用于术语裁定和难段，不做全文。

## 3. 待办（按顺序，测试一律用小段落）
- [ ] tm build：建库 + 句式表（脚本，不调模型）
- [ ] tm pretranslate：预翻译 + 相似例句输出
- [ ] 留一法覆盖率测试（脚本，不调模型）：拿掉 Harrison 一章，统计复用率与复用错误率
- [ ] 本机模型 1 段试译（免费）：与 DeepSeek 译文对比
- [ ] Harrison 排版：裁图放回原位、图注在图下、标题/目录中英双语（heading_bilingual、fidelity_check 先对各单元跑 --fix）——上次中途停止，单元稿有 _试译_before_gloss.md 等备份

## 4. 规则
- 能脚本做的不用模型；DeepSeek 只在折扣时段调用（北京时间 18:00–次日 09:00 可用，工作日 09–12、14–18 点高峰不调用）。
- 新方法先用 1–2 段测试，不整章跑。

## 5. 低成本流程：gtrans.py（Google 免费初译 → 脚本修正 → DeepSeek flash 不开思考一次核对润色 → 报警段才开思考）
已实现（scripts/gtrans.py，tests/test_gtrans.py）。与第 2 节的区别：不等译忆库，先用 Google 免费初译，术语和格式由脚本修，模型只做一次「只出改动」的核对。
- 流程：英文 → 分单元（页码标记、标题、图注、正文各自成单元）→ Google 初译（缓存、限速、退避）→ `skill/google_fixes.tsv` 固有错译 → yiku HARD 术语替换 → 一致性警告 → fidelity_check --fix、heading_bilingual、cite_diff → DeepSeek flash 不开思考（每单元 ≤1500 词，JSON 改动，polish_guard 护栏）→ 仅报警单元 `--think-escalate` 开思考重跑。
- 成本：Google 免费；DeepSeek 一段 225 词约 0.5–0.9k 输入、0.1–0.25k 输出 token（不开思考）；开思考同一段输出约 2.8k token，所以只对真有问题的单元升级。
- 试验（探索记录/Google+DeepSeek试验/smoke/，S2 第一段）：脚本修正「脑电波→灵感」；不开思考的核对改出 6 处，其中误译 4 处（小猎犬号、增殖、隔离、漏译「生态位」）。遗留：个别翻译腔长句未改；「Patagonia」被拉丁名启发式误报（已改为不触发升级）。
- 规则：DeepSeek 只在折扣时段调用（北京时间 18:00–次日 09:00 可用，工作日 09–12、14–18 点高峰不调用），除非用户授权（`LLM_SKIP_OFFPEAK=1`）；护栏会拒绝改数字、年份、学名的改动，这类问题由脚本或人工处理。
