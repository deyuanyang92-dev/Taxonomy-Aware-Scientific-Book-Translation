# 零模型翻译实测（Task 4）2026-11-22

**设置**：谷歌翻译免费端点，`auto_translate.py run --engine none`，无术语表、无 presub、无模型（各目录 usage.tsv 不存在，费用 0）。
**样本**：日文 Imajima 2001 PDF p.57/61/66/110/137；德文 Hartmann-Schröder 1962 p.1/13/15/26/40（各 n=5 页，便利样本，非随机）。
**无人工译文可对**：Imajima 无人工译本，现有 gt_en/gt_zh 是机翻稿；德文同。故只用确定性评分（`scripts/bench/zero_model_score.py`、`transqa.check_all`），不是对人工真值的准确率。
**路径**：A 源→英；B 源→英→中（枢纽，两跳都谷歌）；C 源→中（直译）。产物 `bench/zero_model/<路径>/`。

## 结果（transqa 计数，critical/major）
| 路径 | 日 critical | 日 major | 德 critical | 德 major |
|---|---|---|---|---|
| A 源→英 | 4 | 4 | 3 | 1 |
| B 枢纽→中 | 6 | 3 | 5 | 1 |
| C 直译→中 | 5 | 3 | 5 | 1 |
注：日 A 为 /root/github 版（含 _junk 修复）；本目录版见缺口 1。

## 缺口排序（影响大→小）
1. **【已确证，阻断】本目录 `transqa/taxoblocks.py::_junk` 缺日文修复**：日文 84 段中 28 段（junk_kept=28）被还原成日文原文，译稿残留假名 541 个（`ja_en/`）；`/root/github` 版有修复，同样输入残留 0（`ja_en_fix/`）。两份检出分叉，需合并（先 git log 比对，不盲目覆盖）。
2. **【已确证】检索表结构在日文源阶段就已丢**：p.137 检索表各条目挤在一段，「Ephesiella gallardi(図78)」与条文顺序被谷歌重排，条目号与跳转无法还原。需在翻译前按条切段（prep_ja 已有逻辑，pilot 外的页是否覆盖未确证）。
3. **【已确证】中文输出改写拉丁记号**：德文源 8 处 `n. sp.`，直译中文 2+6 处变 `n。`/`sp。`；Typosyllis anoculata 在中文里成 anculata（丢字母）。学名与 n. sp. 须翻译前占位符保护。
4. **【已确证】日期被改写**：德文「29. 12. 59」→「2059 年 12 月 29 日」；「60 年 9 月 28 日」。采集日期（两位年）须保护。
5. **【已确证】斜体 `*学名*` 在谷歌输出里被剥掉（直译路径无 taxoformat 补斜体前，正文学名为正体）。
6. **枢纽 vs 直译**：学名/数字指标两条路径近乎相同（日 num_missing 12 vs 13；德 6 vs 6）。枢纽未显示明显额外损失，但 n=5，**未确证**；中文流畅度、术语未做盲评（需用户或确定性术语命中率，不用大模型）。
7. **transqa 数字报警多为误报（未确证）**：日文「第2,4,5,7,9…」谷歌译成「2nd, 4th, 5th…」被判缺/多数字；「4gliedrig」→「4-part」被判缺 4。实际语义无错，但检查器无法区分，会淹没真错误。需修检查器（序数、连字符数词）。
8. 命名人括号年份（authority_changed）：德文页 p.15/26 报 5+3 处，多为 OCR 大小写异形（UscHAKov、O0 HARTMANN）与谷歌改写，未逐条核（未确证）。

## 未做
- 术语命中率（需 yiku 术语表对照，且无人工参照）；术语译名质量未量。
- 5 页太少，不下结论。
- 未加术语前置替换/presub，测的是裸谷歌基线。

## 建议后续任务（各自另立）
a. 合并 _junk 修复到本目录（含回归测试，已有 test_taxoblocks 用例在 /root/github）。
b. 翻译前占位符保护：学名、n. sp.、两位年份日期、检索表编号。
c. transqa 数字检查：序数与连字符数词归一。
d. 检索表按条切段（日文源）。



## 补记 2026-11-22：四项修复及复测（同样 5+5 页，--engine none，无模型）

| 项 | 改动 | 测试 |
|---|---|---|
| a | transqa/taxoblocks.py `_junk`：含假名/汉字或单个首字母大写类群名不判垃圾 | tests/test_taxoblocks.py |
| b | scripts/protect.py：学名+命名人年份、n. sp. 等、两位年份日期送机翻前换 `[[n]]`，丢占位符则退回不保护重译 | tests/test_protect.py |
| c | transqa/core.py `numbers()`：日期 `10. 3. 60` 与 `3/10/60` 计同一记号。**原假设「序数词/连字号数词误报」未证实**：2nd、4-part 的数字本就与原文各计一次；真正的误报来自日期被谷歌改写 | tests/test_transqa.py |
| d | scripts/keysplit.py：日文检索表以「(図N)」收尾后紧跟日文时断段（≥2 处才动），auto_translate 对 ja 自动调用 | tests/test_keysplit.py |

复测（critical 数 / 学名保留 / 缺年份）：

| 路径 | 修前 | 修后 |
|---|---|---|
| de>zh 直译 | 4 / 0 of 3 / 4 | 2 / 2 of 3 / 4 |
| de>en | 3 / 3 / 2 | 1 / 3 / 2 |
| ja>zh 直译 | 4 / 3 / 0 | 4 / 3 / 0 |
| ja>en | 4 / 3 / 0 | 4 / 3 / 0 |

结论：德语受益明显；日语的 number.missing 未变，因为是机翻真实丢数字（「第3背鱗」「1列」等被省略或改写），不是误报，不能靠放宽检查消除。d 项在样本 p.137 上未单独量化效果（该页缺条目编号，断段只是减少重排，未证实）。德语仍有 4 个年份缺失、1 个 taxon.authority_changed，待查。pivot 路径未重跑。

### 再补（第二轮前处理）

德语残留逐项查明后再加两条前处理（tests/test_protect.py、tests/test_transqa.py 已加用例）：
- OCR 把日期首个点识成逗号（`10, 3. 60`）：protect 与 transqa.numbers 都按日期处理。
- 括号内单独的「命名人, 年份」及大写人名「O. HARTMAN (1959)」（含 Ö 等非 ASCII 字母）：送机翻前占位，防谷歌音译（哈特曼-施罗德）；「(Abb. 27, 1957)」不动。

复测（v4，无模型）：德→英 critical 3→1，authority_changed 清零；德→中 critical 4→2，authority_changed 2→1；日→中 authority_changed 清零。
剩余均为非前处理可解的真问题：谷歌丢「10 Paar」「2 bis 2½」等数字；OCR 把 Eurytho@ KinsErc 等原文识错（需回 OCR/校对层）；p.26 谷歌凭空写「100 厘米」。这些正是 QA 该拦的，保留报警。

### 第三轮：残留逐项处理（v7，无模型）

| 残留 | 根因 | 措施（确定性） | 测试 |
|---|---|---|---|
| 「10 Paar」报缺 | 译文写成「十对」，检查只认阿拉伯数字 | number.missing 放行目标语言数词（zh/ja 汉字数词按位值解析：十五=15、二十三=23；en 序数词 first…twentieth） | tests/test_transqa.py |
| 「2,4,5,7,9…」被当成 2.4、5.7 | 逗号小数规则误吞并列编号 | ≥3 项无空格逗号串拆成独立数字 | 同上 |
| 「15対」被谷歌译成「1枚。有5对」 | 长句里数字被吞/错位 | 日文「数字+量词」数字单独占位 | tests/test_protect.py |
| 引文换行（`(FAUVVEL,\n1953)`）没被保护 | 正则只认空格不认换行 | 保护正则改用 \s，年份后单字母（1901 a）也算 | 同上 |
| 占位符被吞后整段失去保护 | 退回未保护原文 | 先按句、日文再按分句（，、）各自保护重译，单句仍丢才用原文 | tests/test_auto_translate.py 通过 |

复测（v7）：德→英、德→中、日→中 critical = 0（修前 3、4、4）；日→英 critical 2 页（p.61 的「1列」、p.66 的「1剛毛束」被译成「per bundle」省略数字，属谷歌改写，保留报警）。
仍保留的非前处理问题：德→中 number.added「100 厘米」(p.26 谷歌凭空加)、OCR 错字（Eurytho@ KinsErc）须回 OCR/校对层；这些由 QA 报警拦截，不静默放过。

### 第四轮：全部残留清零（v8/v9，无模型，同样 5+5 页）

先纠正：第三轮报告里的「de years_missing=2」和「de>zh 学名丢 1」是**评分器 bug**，不是译文问题——`zero_model_score.py` 用 \b 匹配，中文「1922年」「如Typosyllis…」里数字/字母与汉字同属 \w，\b 不成立，把保留下来的年份和学名误判丢失。已改为 `(?<!\d)…(?!\d)` / `(?<![A-Za-z])`，回归测试 tests/test_zero_model_score.py。

| 残留 | 根因（证据） | 确定性措施 | 测试 |
|---|---|---|---|
| de>zh「100 厘米」(p.26) | 源「ca. 10 mm lang」，谷歌无中生有「约为 100 厘米。10毫米」 | protect：数字+mm/cm/µm（含 ca. 与范围）整体占位 | test_measure_protected |
| ja>en p.61「1列」、p.66「1剛毛束」critical | 谷歌把「1列」写成 a row、「1剛毛束」写成 per bundle，数字被省 | protect：N列/N剛毛束 连量词占位，按目标语言还原（en「1 row」「5 rows」「1 seta bundle」，zh「1列」「1刚毛束」） | test_ja_number_before_counter_protected |
| 「2対の眼」→「2那双眼睛」 | 量词 対 在占位符外 | N対 整体占位，还原 zh「2对」、en「2 pairs」 | 同上 |
| OCR「Eurytho@ KinsErc」 | OCR 把词尾 e 识成 @ | docstore/rules/ocr_fix.toml 新增 at_sign_for_e；auto_translate 翻译前 protect.clean_ocr 套用正则规则 | test_fixer_at_sign_is_e、test_clean_ocr_at_sign |
| 缩写属名「T. anoculata n. sp.」、「n.g.」 | 谷歌改写缩写属名后的标记 | protect 增 缩写属名+标记、n.g.（源里「n.g.n.sSp.」「anocuülata」是 OCR 原错，译前不改） | test_abbrev_binomial_and_ng_tag |

复测（critical / major 数）：ja>en 2/1→0/1（major 仅 text.word_join），ja>zh 0/0，de>en 0/1，de>zh 0/0；学名保留 3/3（四路径）；缺年份 0；usage.tsv 不存在（零模型）。num_missing 仍 8~9（ja）、2~5（de），为谷歌改写数字的真实残留，由 QA 在 minor 以下计数。

### 第五轮：德文基础术语、数量词、参考文献（v10，无模型）

| 项 | 措施 | 测试 |
|---|---|---|
| 德文基础形态术语（谷歌把 Borstensegmente 译成「刷毛段」） | scripts/term_de.py：14 个德文词（Borstensegment、Parapodium、Prostomium、Peristomium、Elytre、Analcirrus、Tentakelcirrus、Rückencirrus、Aciculum、Pygidium、Nuchalorgan、Pharynx、Antenne、Palpe）送机翻前占位，回来写 yiku 已核定名（刚节、疣足、口前叶…；en 目标写英文单复数）。只收已核词，Kiefer/Rüssel 等无已核定名的不收 | tests/test_term_de.py（含与 ~/.yiku/yiku.db 已核条目对照，库里改名则报错） |
| 「2 bis 2½」「10 Paar」「1,5 bis 3 mm」丢数字 | protect 占位，还原为「2–2½」「10对/10 pairs」「1,5–3 mm」 | 同上 |
| OCR「KinsErc」 | ocr_fix.toml 作者名规则 → KINBERG | test_clean_ocr_at_sign |
| 参考文献 | 已有机制：transqa.blocks 判 reference 不送谷歌，只换缩写；补回归 | tests/test_de_references.py |

复测（德，5 页）：de>en num_missing 2→1，de>zh 5→3；critical 0；学名 3/3；缺年份 0。
残留：谷歌括号不成对（zh_typo review，需人工）、OCR 把 anoculata 识成 anocuülata（原文错，不改）。

### 第六轮：回应 Stop 钩子四条反对（v11/v12，无模型）

| 反对 | 措施 | 测试 |
|---|---|---|
| 括号不成对留给人工 | 根因：zh.unpaired 只数译文，不看原文；原文 p.1「neu beschrieben‘)」（OCR 脚注号）、p.13 残片「21)」本身不成对。transqa/zh_typo.py 原文括号不平衡的段不报 | test_unpaired_suppressed_when_source_unbalanced |
| 半角括号「(2对 触须)」 | auto_translate 对 zh 目标定稿前套用 zh_typo.fix_mechanical（只做 kind=auto，学名/命名人括号在受保护区间外不动），数量写 zh_typo_fixed.txt | test_halfwidth_parens_fixed_but_latin_kept |
| KinsErc→KINBERG 未复跑 | v11 重跑：text.word_join 消失 | （ocr_fix 规则已有测试） |
| 参考文献未用真实页测 | 取 Hartmann-Schröder 1962 p.210/212 真实 OCR（53 段）：修前 classify 全判 free（会送谷歌，因折行、「— ‚, 年份」、OCR 杂符、「D.. 1852:」）。blocks.classify 新增：段首 70 字内「, 年份:」（含 190la、1856—1858）与「pp. 1—84」类折行残片判 reference；修后 44 段 reference，其余 9 段为页眉/杂符（IE、'、HC 2 eG）。整页过流水线：46/53 段与原文逐字相同，其余只换缩写（u.→and、S.→p.）；不送谷歌 | tests/test_de_references.py（真实片段 8 条、叙述句反例、页标记反例） |
| 术语只 14 个 | term_de 增 9 个已核词（Dorsalcirrus、Ventralcirrus、Borste、Notochaeta、Neurochaeta、Kieme、Cirrophor、Uncinus、Genitalporus；yiku 已核对照测试覆盖）。Borste 在样本里原被译成「刷毛/鬃毛」，现为「刚毛」 | test_second_batch_and_longest_first |

复测：v11 de>en、de>zh critical/major/minor 全 0（zh_typo 仅 info）；v12 加术语后 de>en num_missing 0，de>zh 4（缺的是「2」，谷歌把 zwei 写成「两」；评分器只数阿拉伯数字，transqa 的数词放行已覆盖，评分器未同步，属评分口径）。

### 第七轮：补齐钩子余项（v13，无模型）
- Kiefer、Rüssel 其实有已核名（yiku：jaws→颚、proboscis→吻、mandible→下颚、maxilla→上颚），前几轮漏查。term_de 增 Kiefer、Rüssel、Mandibel、Maxille（共 27 词，yiku 对照测试覆盖）。
- 真实参考文献页余下的 9 段「free」：OCR 杂符（IE、'、HC 2 eG、» 7）与孤立「pls.」改判 index（原样保留）；页眉「Literaturverzeichnis N」与页标记仍按正文，机翻成「参考文献 N」本就正确。整页 53 段：42 reference + 7 index + 4（2 页标记、2 页眉）。
- 评分器 num_missing 口径与 transqa 一致：译文用数词（zwei→两/two）写的数字不算缺。v13 de>en、de>zh：缺数字 0、多出 1、学名 3/3、缺年份 0、zh_typo 无告警。

## 第 8 轮（2026-11-22，v14）：命名法术语、页眉、混宽括号

- 谷歌实测（de→zh）：科/属/亚科/Typuslokalität/Holotypus/Typusart 译得对；错的有 Synonymie→同义词、neue Art→新物种、neue Gattung→新流派、Lectotypus/Syntypen→选型/同型。yiku 无这些词的已核条目。
- 加 6 条命名法术语到 `scripts/term_de.py`（Holotypus 正模标本、Paratypus 副模标本、Typusart 模式种、neue Art 新种、neue Gattung 新属、Synonymie 同物异名），定名依据：动物志09/33 全文检索（正模标本 3 页、副模标本 3 页、模式种 72 页、新种 50 页、同物异名 22 页）。Lectotypus/Syntypen 无依据，不收，仍由 QA 报警。表共 33 条。
- 页眉「Literaturverzeichnis N」：`blocks.classify` 判 index，确定性换成「References N」（原先被 taxoblocks 判 junk 原样留在译文，已改为受保护块优先于 junk）。页标记 `<!-- PDF p.N -->` 在 auto_translate 里剥离，从不送机翻（结构行）。
- 真实文献页（Hartmann-Schröder 1962 p.210/212，53 段）：reference 42、index 9、free 2（仅页标记）。
- `coverage.segment_empty` 误报：原文本身是标点残符（「,」「'」）的段不再算空译。
- `zh_typo`：谷歌「(…）」半角/全角混用，补成全角（kind=auto）。
- v14（5 页德文）：de>en、de>zh 均为 binomials 3/3、years_missing 0、num_missing 0、num_extra 1；de>zh 无 minor 以上问题。
