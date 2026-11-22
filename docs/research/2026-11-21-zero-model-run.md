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
