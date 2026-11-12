# 子代理提示词模板

模板与模型无关。用 `scripts/run_batches.py --engine codex|claude --domain <D>` 自动渲染 A、B 两个模板（智能体模式）；`--engine deepseek-flash|deepseek-v4-pro|claude-sonnet|claude-opus` 为直调模式，系统提示词由 RULES + 领域包 + STYLE（核译用「核译输出要求」）拼成；手工派发时（例如 Claude Code 子代理或 DeepSeek），内容相同。初译和核译要交给不同的模型。`<书>` 为工程目录绝对路径，`S`/`T` 见 SKILL.md。

## A. 初译（每章一个）

```
工作目录 <书>。禁止再调用 Agent 开子代理。
先读 ~/.claude/skills/yzz-translate/RULES.md、domains/<D>.md 与 STYLE.md，并严格执行。
第一步 术语预扫：通读原文，列出本章术语（含术语表没有的），写入 核译/tmp/chNN/terms_scan.tsv，列为 English\t义项\t译法\t依据（表中已核/经典译本/暂定）。
第二步 翻译：把 src_en/chNN.txt 译成中文，写入 译文/chNN_<中文章名>.md（Markdown：# 章标题，## / ### 小节，图注用 **图 N.N** …）。术语按 terms_scan.tsv。
本章术语表（用法见表头；义项不同或不明的登记到 核译/tmp/chNN/uncertain_terms.tsv）：
<粘贴 yiku table src_en/chNN.txt --domain <D> 的输出>
每译完一节就写盘（追加）。不要自造科名、属名。
结束回报 ≤150 字。
```

## B. 逐句核译（每批一个）

```
工作目录 <书>。禁止再调用 Agent 开子代理。
先读 ~/.claude/skills/yzz-translate/RULES.md、domains/<D>.md、STYLE.md 与 ~/.claude/skills/yzz-translate/PROMPTS.md 的「核译输出要求」。
本批范围：<chNN…>。英文 src_en/chNN.txt；中译 译文/chNN_*.md（用 ls 确认文件名）。临时脚本放 核译/tmp/bNN/。
各章术语表：先对每章运行 yiku table src_en/chNN.txt --domain <D>。
<本批已知系统性问题，如：本章「梯额虫科」处须核对英文是否 Orbiniidae>
输出：核译/issues/bNN.jsonl（每核完一节就追加写入）。
结束前运行 python3 S/apply_issues.py <书> 核译/issues/bNN.jsonl --dry，修好所有拒绝行。不要去掉 --dry，不要改译文。
```

### 核译输出要求
- 术语按「英文 + 义项」核：同一义项译法不一、套用了义项不同的表中译名，报「术语」。
- 只报：误译、漏译、增译、术语（与术语表同义项而不符/义项套错/残留英文普通词）、语序（确实读不通）、格式（多余空格、标点、星号）。不报风格偏好、同义替换、已列为「全书统一」的项。
- JSONL 一行一条：`{"file":"chNN_xx.md","old":"<逐字复制自译文，8–150 字，文件中恰好出现 1 次>","new":"<改后>","type":"误译|漏译|增译|术语|语序|格式","reason":"<一句>","en":"<英文原句≤200字符>"}`
- 拿不准的术语写 核译/tmp/bNN/uncertain_terms.tsv（English\t现译\t建议\t理由），不硬改。
- 怀疑经典译作、名家论著给出的译名有误时，不报为误译，写入 核译/质疑清单.tsv（en\t经典译法\t出处页码\t质疑理由\t建议译法\t依据）。
- **核对方法（取自 translation-quality-codex 的防编造清单，2026-11-10 引入）**：
  1. 正向：译文每段都要在原文找到对应段；译文多出的内容报「增译」。
  2. 反向：原文每段（含图注、表格每格、引文括号）都要在译文找到；缺的报「漏译」。限定词 usually/only/may/apparently/presently 单独过一遍。
  3. 数字与专名：列出原文所有数字、单位、年份、引文（作者, 年份）、学名，逐一核对译文出现且一致。
  4. 结构计数：本批原文与译文的段数、图注数、表格行数、引文数各数一遍，写进回报。
- **问题类型（type）按 MQM 错误分类再加分类学专项**（MQM：https://www.themqm.org/mqm-pillars/the-mqm-full-typology/）：
  - 通用（MQM Accuracy/Terminology/Style/Locale）：误译｜漏译｜增译｜术语｜语序｜格式｜表述（不合志书写法）。
  - **分类学专项**（一律至少 Major）：计数（节数、刚毛数、范围起止，如 chaetiger 11 to 26）｜方位（dorsal/ventral/anterior/posterior/dorso-lateral）｜性状状态（present/absent、fused/separate、smooth/serrated）｜比较关系（longer than、subequal）｜学名（拼写、命名人、年份、组合）｜检索表（编号、分支条件、跳转目标）｜异名（异名历史、旧组合）｜分布（地名、水深、采集记录）｜图号（图注、交叉引用）。
- 每条 JSONL 另加两个字段：`"severity":"Critical|Major|Minor"`（编造/改变事实=Critical，漏限定、范围误读、漏引文=Major 或 Minor，格式=Minor）；`"confidence":"confirmed|needs_verification"`。**用字类意见**（方位词、形状词、术语换字）若没有附志书依据（知识库或 OCR 的计数 + 例句页码），一律标 needs_verification，由主会话按 domains/分类学.md 第 7 节裁定。
- 回报 ≤150 字：各类条数、结构计数是否一致、最严重 2–3 处。

## C. 术语查证（新科名/分科术语）

```
禁止再调用 Agent。为以下术语在指定类群中的中文规范用法查证，每条给书名+页码：<列表：English｜类群>
依据优先级见 ~/.claude/skills/yzz-translate/TERMS.md。先 grep OCR 全文（OCR 目录见 TERMS.md），找该科「科的特征/形态描述」段落里的实际用词；查不到写「未确证」，不得编造。
输出追加到 ~/.claude/skills/yzz-translate/terms/形态术语_分科.tsv 的候选文件 terms/候选_<日期>.tsv（同列结构，状态=候选），由主线程审核后转「已核」。
```
