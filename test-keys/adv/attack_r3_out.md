OpenAI Codex v0.171.0
--------
workdir: /mnt/p/翻译-译作/Taxonomy-Aware-Scientific-Book-Translation/test-keys/adv
model: gpt-6.2-astra
provider: openai
approval: never
sandbox: workspace-write [workdir, /tmp, $TMPDIR]
reasoning effort: medium
reasoning summaries: none
session id: 01a2086c-b51b-7f20-bc7c-dbef5d08acfb
--------
user
你是攻击方审查员（第 3 轮，最后一轮）。只在 /mnt/p/翻译-译作/Taxonomy-Aware-Scientific-Book-Translation/test-keys/adv/corpus/ 内新建文件（文件名以 r3_ 开头），并写 /mnt/p/翻译-译作/Taxonomy-Aware-Scientific-Book-Translation/test-keys/adv/review_r3.md；不得修改仓库其他任何文件，不派生子任务。中文。

背景：/mnt/p/翻译-译作/Taxonomy-Aware-Scientific-Book-Translation/test-keys/adv/SPEC.md 是共用规范（新增「正反条成对编号」一节，俄/苏定检表 1(8)…8(1)）。第 1、2 轮共 92 例现全部通过 /mnt/p/翻译-译作/Taxonomy-Aware-Scientific-Book-Translation/booklayout/keygraph.py（LIMITS 列表写了已知未支持项）。keygraph 已接入发布流程。
任务：
1. 审接入代码：`cd /mnt/p/翻译-译作/Taxonomy-Aware-Scientific-Book-Translation && git diff -- booklayout/keymodel.py booklayout/cli.py scripts/publish_book.py`，以及新文件 tests/test_keygraph_wiring.py。重点：闸口能否被绕过（0 张表、文件缺失、旧调用、译文有表原文无表、--expect-keys 与 --entries 组合）、退出码、报告字段、与 keyrender 合并的判定。
2. 审 keygraph.py 第 2 轮改动后的版本：正反条成对编号与括号回指式的判别（混排、成对不全、多表同页、编号重启）、隐式 +1 跳转、「1. Genus X Author」去向、LIMITS 里列的四项是否可以低成本解决。
3. 写 r3_*.json 样例 20–30 个（格式同 SPEC），覆盖上述弱点，以及原译对照（translation 字段：中/日/俄译文里去向号、学名、页码被改、分支漏译、顺序被调）。每例 why 写攻击的 file:line。期望值必须符合真实书籍惯例；不确定的惯例在 why 里写「未确证」，不要硬造。
4. review_r3.md：发现列表（file:line、问题、P0/P1/P2），≤80 行；末尾写 `cd /mnt/p/翻译-译作/Taxonomy-Aware-Scientific-Book-Translation && python3 test-keys/adv/run_corpus.py` 的通过数（允许写 corpus_report.json）。
最后输出「第3轮攻击完毕」。
codex
我会先核对工作区指令、共用规范和接入代码，再编写第 3 轮样例并运行语料检查。所有写入都限定在你指定的位置。
exec
/bin/bash -lc 'cat /mnt/p/翻译-译作/AGENTS.md
if test -f AGENTS.md; then cat AGENTS.md; fi
pwd
ls
cat SPEC.md' in /mnt/p/翻译-译作/Taxonomy-Aware-Scientific-Book-Translation/test-keys/adv
 succeeded in 6ms:
# 翻译工作区 · 通用指令（Codex / Claude Code / 其他模型共用）

本文件是所有模型的唯一入口。Claude Code 通过同目录 `CLAUDE.md` 的 `@AGENTS.md` 读取；Codex 直接读取。

## 0. 用户目标（先理解这一节，再做任何事）
用户是分类学家，要把英文专业书（分类学、动物学、进化生物学、生物学思想史）译成中文。
- **难点是术语，不是普通句子。** 普通句子任何模型都能译；术语译名要有出处，不能靠模型或网络临时生成。
- **术语从名家译本学。** 经典译本的译者对术语做过考证，可信度高于网络和模型的译法。用户会**陆续加入新的「英文原著 + 中文译本」或名家中文论著**。每加入一本，都按同一条流水线抽出术语，写进术语库 yiku。现有的洪德元、Mayr 只是先加入的两份，不是全部。
- **多模型协作。** Claude Code 额度有限，日常抽取、初译和核译交给 Codex、DeepSeek 等模型；裁定和定稿由主会话完成。所以本文件和各目录的 `AGENTS.md` 要写到任何模型无需追问也能接着做的程度。

**整体结构与原则见 `/mnt/p/翻译-译作/顶层设计.md`（一页，先读）；具体做法见 `/mnt/p/翻译-译作/方案.md`**，包括五层结构、核验与定名规则、模型分工和抽查标准。

接手规则（Codex 尤其注意）：
- 用户只说「你理解吗」「继续」「开始」时，不要回答「不知道需求」。先用 2 到 3 句复述第 0 节的目标，再读当前目录 `AGENTS.md` 的「任务队列」，说明下一项准备做什么，然后开始做。
- 每个子目录都有自己的 `AGENTS.md`，写明本目录用途、做法和任务队列。进度只记在该目录的任务队列里，做完一项随即更新。

## 0b. 本地资料库：所有模型共用一个（用户 2026-11-10）
- 任何 PDF/资料的文本化、OCR、校正、检索，一律通过 `docstore` 命令（仓库 `/root/github/Taxonomy-Aware-Scientific-Book-Translation`，库根 `参考资料/_资料库/`），**不得另建页面库、知识库或临时目录**。
- 写入时用 `--by <你的模型名>`（或设环境变量 `DOCSTORE_AGENT`），每页、每次校正都会记下是谁做的。
- 发现库外已有别人建的页面数据：先 `docstore detect <目录>`，再 `docstore import` 收编，不要另起一套。
- 术语只进 yiku；物种记述只进 taxadb。组件与接口见仓库 `docs/architecture.md`。

## 0c. 软件优先与持续改进（用户 2026-11-16）
- 翻译交付与软件改进是并行目标。文本提取、OCR、章节切分、批量翻译、校正、检索表/图注整理、排版、PDF 生成和质量检查，优先查找并运行仓库已有脚本/CLI；不要用大模型手工代替可自动化的批处理。
- 先核对脚本帮助、输入输出和适用范围，再用小样本运行并检查结果；确认通过后再扩展到全书。交付物必须由可追溯的脚本流程生成并记录命令与版本。
- 缺少脚本、脚本失败或现有输出无法保留源结构时，先记录可复现证据并报 GitHub issue，再诊断、修复或补充脚本及回归检查；不得把临时的大模型拼接结果称为正式成品。
- 模型用于需要语言理解的翻译、核译和疑难裁定；结构化抽取、格式变换、批量替换、对齐和验证尽量由确定性脚本完成。临时绕行只作明确标记的中间产物，并说明限制。

## 1. 先读技能
- 主技能：`/root/.claude/skills/yzz-translate/SKILL.md`（Codex 侧软链接为 `~/.codex/skills/yzz-translate`，同一份文件）。
- 术语：技能 `yiku`（`/root/.claude/skills/yiku/SKILL.md`，Codex 侧 `~/.codex/skills/yiku`）。常用命令有 `yiku pair / paren / table / check / lookup / review`，库在 `~/.yiku/yiku.db`。
- 动手前按顺序读（三份文件都在技能目录，不在本工作区根部）：`/root/.claude/skills/yzz-translate/RULES.md`（硬规则）→ `STYLE.md`（译风）→ `TERMS.md`（术语来源优先级）。
- 交付 .docx/.pdf：读 `/root/.claude/skills/yzz-zh/SKILL.md`，交付前运行 `python3 /mnt/p/yzz-分类工作流/yzz.py zh check <文件>`。

## 2. 语言与态度
- 只用中文或英文回复，不用其他语言。
- 用户是科学家。结论要有依据（书名+页码、文件:行号、DOI）；依据不足写「未确证」，不编造。
- 被质疑时先查证再回应；没有新证据不改立场。

## 3. 不可违反
- 不凭空拟科名、属名、术语译名。没有权威中文依据的分类阶元，可依 WoRMS（上级类群派生、原始描述 Etymology）或拉丁/希腊词源拟名，但必须标「暂定」、保留拉丁名并写明依据；其他术语标「暂定」并保留英文。
- 子代理/子任务不得再派生子任务；每完成一节就写盘，中断不丢进度。
- 不删除、不覆盖用户已有译文；改动走 `核译/issues/*.jsonl` + `scripts/apply_issues.py` 闸口。
- 禁用全角空格 U+3000。

## 4. 目录
| 目录 | 内容 |
|---|---|
| `Rouse2022_Annelida/`、`Handbook_Annelida/` | 多毛类专著翻译工程（src_en / 译文 / 核译） |
| `参考资料/` | 动物志、专著、学位论文扫描本 |
| `一些经典译作/` | 参考作品原件；`参考库/` 下是抽取结果和文风笔记 |
| `yiku/` | 术语库 yiku.db（`~/.yiku` 软链接指向这里） |
| `红宝书/` | 另一翻译工程 |

## 5. 多模型分工
- 批量初译/核译：`python3 /root/.claude/skills/yzz-translate/scripts/run_batches.py <书> --mode review --engine codex|claude`。先加 `--dry` 检查提示词，先试点 1 批。
- 模型分配（用户 2026-11-13 改定）：**DeepSeek（`deepseek-flash`）可作核译/校对的第二家（用户 2026-11-13 恢复），避开官方忙时（工作日北京时间 09–12、14–18 点；晚上 18:00–次日 09:00 与周末全天可用，用户 2026-11-15 改定、2026-11-19 再确认）（`llm_engines` 自动等待；YZZ_DEEPSEEK_NIGHT=18-9 可收紧为只在 18:00–次日 09:00），max_tokens 64000；不做初译。** 初译用 Claude Sonnet（Cursor 在本地区不能用 Claude/GPT）；核译换另一家：Codex `codex-sol`（gpt-6.1-sol，ChatGPT Pro 账号，注意额度；`codex-astra` 只用于最难的少数段）；Opus 只用于关键部分——歧义/长难句段、系统发育与命名论证段、检索表与鉴别特征、两模型分歧段的复核。盲评用 `codex-sol` + `cursor-grok`（Grok 4.5）。Haiku 不做全文翻译（以版权为由拒译）。
- 翻译前先把正文、图、图注分开整理，图注单独成批翻译。
- 裁定、抽查、术语定稿：由能力最强的会话（主会话）完成，术语写回 yiku（`yiku review apply` / `yiku import --status 已核`），译风写回 `STYLE.md`。

## 6. 工作区安装的补充技能（2026-11-10）
- 长书分块、相邻上下文与续译：`.claude/skills/translate-book/SKILL.md`。
- 原文段落编号、对照审校与交付包检查：`.claude/skills/translation-quality-codex/SKILL.md`。
- 使用这两个技能前，必须读 `技能配置/分类学专著适配.md`。它们补充现有 yzz-translate 流程；术语来源、异模型核译和已有译文修改仍遵守本文件及 yzz-translate 硬规则。
- Codex 从本入口按路径读取技能；本次未写入全局技能目录或 Codex 自动发现目录，不保证 `$技能名` 菜单自动出现。Claude Code 使用本工作区 `.claude/skills/` 安装。
- 安装来源、版本、检查结果和任务队列见 `技能配置/AGENTS.md` 与 `技能配置/安装记录.md`。
/mnt/p/翻译-译作/Taxonomy-Aware-Scientific-Book-Translation/test-keys/adv
SPEC.md
_patch_test.py
attack_r1.log
attack_r1_out.md
attack_r1_prompt.txt
attack_r2.log
attack_r2_out.md
attack_r2_prompt.txt
attack_r3_out.md
attack_r3_prompt.txt
corpus
corpus_report.json
review_r2.md
run_corpus.py
wiring_realrun.md
# 检索表通用性对抗审核：共用规范（v1，2026-11-23）

## 目的
检索表的抽取、检查、修正、排版要对任何书、任何编号格式、任何语种都成立。
Codex 为攻击方：写样例（corpus）及期望结果，尽量击穿实现。
Claude 为实现方：实现 booklayout/keygraph.py（通用图层），并接入现有入口。
双方互审：Claude 可质疑 Codex 期望值是否合理（须给原书惯例依据）；Codex 审 Claude 的 diff。

## 规范化分支号（canonical lead）
每条分支写成「偶句号 + 字母」：第一支 a，第二支 b，多歧依次 c、d……
- 1 / 1' / 1′ / 1’ → 1a / 1b；1a / 1b → 1a / 1b；1A / 1B 同
- 1 / — / -（横线或 • 表示上一号的备择支）→ 1a / 1b
- 1(3) 括号回指式：1a，且 backref=3（表示从偶句 3 跳来）
- 多歧 1a/1b/1c 合法（polytomy），不报错
- **正反条成对编号（俄/苏定检表式，Marinov 1977 等）**：每条各有号，括号内为对立条号，如 1(8) … 8(1)、2(5) … 5(2)。
  识别：同一表内带括号的号各出现一次且 n(m) 与 m(n) 成对出现 → 按此式解析，否则按括号回指式。
  偶句号取成对中较小者，出现顺序给 a/b（1(8)→1a，8(1)→1b）。无去向的条隐式跳到「本条号+1」所在偶句。
  同一表内两种括号式不能混判；成对不全（只有 n(m) 无 m(n)）报 lone_alternate 或 single_branch。
- 去向中的「1. Genus Harmothoe Kinberg」「2. H. reticulata (Claparède)」：去掉前导序号、阶元词（Genus/Род/属）与命名人，taxon 记学名。
- 缩进式（indented key，无编号或 A/AA、字母层级）：按出现顺序给偶句号 1,2,3…，同层同前缀的两支为一对

## 去向（target）
- jump：偶句号（"5"、"5'"不常见，规范化为 5）；范围 "5-6" 记 jump 到 5
- page：(p. 76)、p. 76、S. 12、第 12 页、pág. 3
- taxon：类群名（可带页码，如 "Nereis pelagica (p. 76)" 记 taxon，另记 page）
- none：缺去向

## 问题码（findings code，固定词表）
| code | 含义 |
|---|---|
| no_keys | 预期有表（调用方声明）却识别出 0 张 |
| single_branch | 偶句只有一支 |
| lone_alternate | 有备择支（b/'/—）而无主支 a |
| duplicate_lead | 同一规范化分支号出现两次 |
| no_target | 分支无去向 |
| dangling_jump | 跳到本表不存在的偶句 |
| unreachable | 从入口偶句（默认最小号，可声明多入口）走不到的偶句 |
| cycle | 有环（给出路径） |
| multi_parent | 一个偶句被多处跳入（仅 warn，网状检索表合法） |
| backref_mismatch | 1(3) 形式中回指号与实际跳入来源不符 |
| key_count | 原译表数不同 |
| missing_branch / extra_branch | 译文缺/多分支 |
| target_changed | 译文去向变化（跳转号、页码、拉丁学名任一不同） |
| order_changed | 译文分支顺序变化 |

## 样例文件格式（corpus/*.json，一例一文件）
{
 "id": "en_prime_basic",
 "format": "prime|ab|dash|bullet|backref|indented|polytomy|table|other",
 "lang": "en|ja|ru|fr|de|la|es|zh",
 "source": "原文文本，分页用 <!-- PDF p.N --> 标记，一行一支或按原书折行",
 "translation": "可选，译文文本，同样分页",
 "declared_entries": ["1"],            // 可选
 "expect": {
   "keys": 1,
   "branches": [["1a","jump","2"],["1b","taxon","Nereis pelagica"], ...],  // 按出现顺序；taxon 只写学名部分
   "findings": ["dangling_jump"]       // 期望命中的问题码集合（多余的、缺的都算失败）
 },
 "why": "这个样例要击穿什么、依据（原书惯例、文献）"
}

exec
/bin/bash -lc 'cat -n booklayout/keygraph.py' in /mnt/p/翻译-译作/Taxonomy-Aware-Scientific-Book-Translation
exec
/bin/bash -lc 'git diff -- booklayout/keymodel.py booklayout/cli.py scripts/publish_book.py
cat -n tests/test_keygraph_wiring.py' in /mnt/p/翻译-译作/Taxonomy-Aware-Scientific-Book-Translation
exec
/bin/bash -lc 'cat -n test-keys/adv/run_corpus.py
cat test-keys/adv/review_r2.md
ls test-keys/adv/corpus' in /mnt/p/翻译-译作/Taxonomy-Aware-Scientific-Book-Translation
 succeeded in 51ms:
     1	"""Language- and book-independent dichotomous-key graph layer.
     2	
     3	Parses key text (page-marked markdown/plain text) into couplets and branches,
     4	normalises lead numbers (1 / 1' / 1a / 1(3) / dash alternates / indented keys),
     5	checks the graph (dangling jumps, cycles, unreachable couplets ...), aligns
     6	a source key with its translation and gates "expected keys" documents.
     7	
     8	CLI: python3 -m booklayout.keygraph --source a.md [--translation b.md]
     9	     [--expect-keys] [--entries 1,5] [--out r.json]
    10	
    11	Known limits: see ``LIMITS`` at the bottom of the module.
    12	"""
    13	from __future__ import annotations
    14	
    15	import argparse
    16	import json
    17	import re
    18	import sys
    19	import unicodedata
    20	from collections import OrderedDict
    21	from dataclasses import asdict, dataclass, field
    22	from pathlib import Path
    23	from typing import Any, NamedTuple, Sequence
    24	
    25	PAGE_MARK = re.compile(r"<!--\s*PDF p\.(\d+)\s*-->")
    26	LEADER = re.compile(r"(?:[.…·・⋯]\s*){3,}|(?:[…⋯]\s*){2,}|(?<=\s)(?:\.\s+){2,}(?=\S)")
    27	DASH_CHARS = "—–-•·▪●*"
    28	DASHES = "—–\\-•·▪●*"  # regex character-class form
    29	PRIMES = "'’′´"
    30	HEADING_RE = re.compile(
    31	    r"^\W*(?:[^\W\d]+\s+){0,5}?(?:Keys?|Claves?|Clavis|Cl[eé]fs?|Cl[eé]s?|Bestimmungs\w*|Schl[uü]ssel|"
    32	    r"[Тт]аблица|Ключ\w*|Определител\w*)(?!\w)|.{0,12}?(?:検索|检索|檢索)")
    33	CONT_RE = re.compile(r"continued|cont\.|suite\b|Fortsetzung|continuaci|продолжение|続き|续|續", re.I)
    34	RUNNING_HEAD = re.compile(
    35	    r"^\s*(?:\d{1,4}\s+[^\W\d_a-z][^\W\d_a-z ,.\-]{2,}(?: [^\W\d_a-z ,.\-]+)*|"
    36	    r"[^\W\d_a-z][^\W\d_a-z ,.\-]{2,}(?: [^\W\d_a-z ,.\-]+)*\s+\d{1,4})\s*$")
    37	PAGE_ONLY = re.compile(r"^\s*(?:\d{1,4}|[ivxlc]+)\s*$", re.I)
    38	JUMP_ONLY = re.compile(r"^\d{1,3}['’′]?(?:\s*[-–]\s*\d{1,3}['’′]?)?$")
    39	
    40	_PAGE_WORDS = r"(?:pp?\.|S\.|págs?\.|pags?\.|pág\b|pag\b|páginas?|paginas?|seite|стр\.|с\.|pages?)"
    41	PAGE_RES = [
    42	    re.compile(r"(?<![^\W\d_])\(?\s*" + _PAGE_WORDS + r"\s*(?P<p>\d{1,4})(?:\s*[-–]\s*\d{1,4})?\s*\)?", re.I),
    43	    re.compile(r"\(?\s*第\s*(?P<p>\d{1,4})\s*[页頁]\s*\)?"),
    44	    re.compile(r"\(?\s*(?P<p>\d{1,4})\s*(?:[页頁]|ページ)\s*\)?"),
    45	]
    46	_JUMP_PRE = r"(?:(?:→|->|⇒|see|go to|goto|vide|siehe|voir|ir a|vaya a|转|見|见)\s*)?"
    47	JUMP_RE = re.compile(
    48	    r"^" + _JUMP_PRE + r"(?P<n>\d{1,3})['’′]?(?:\s*(?:[-–—]|to|bis)\s*\d{1,3}['’′]?)?\s*(?:へ)?$", re.I)
    49	TRAIL_ARROW = re.compile(
    50	    r"\s(?P<t>(?:→|->|⇒|see|go to|goto|转|見|见)\s*\d{1,3}['’′]?)\s*$|(?P<j>\d{1,3})へ\s*$", re.I)
    51	TRAIL_TARGET = re.compile(r"[\s(](?P<t>\d{1,3}['’′]?(?:\s*[-–]\s*\d{1,3}['’′]?)?)\s*$")
    52	TRAIL_PAGE = re.compile(
    53	    r"(?<![^\W\d_])(?P<t>\(?\s*(?:" + _PAGE_WORDS + r"\s*\d{1,4}(?:\s*[-–]\s*\d{1,4})?|第\s*\d{1,4}\s*[页頁]|"
    54	    r"\d{1,4}\s*(?:[页頁]|ページ))\s*\)?)\s*$", re.I)
    55	GAP_TARGET = re.compile(r"(?:\t|\s{3,})(?P<t>\S.{0,80})$")
    56	
    57	_LTAIL = (r"(?:\s+(?:(?:subsp|ssp|var|subvar|fo|cf|aff|sp|spp|nov)\.|"
    58	          r"(?!(?:and|or|und|oder|et|ou|with|the|via)\b)[a-zà-ÿ][a-zà-ÿ\-]{2,}))*")
    59	LATIN_RE = re.compile(r"[A-Z]\.\s*[a-z][a-z\-]{2,}" + _LTAIL + r"|[A-Z][a-zà-ÿ]{2,}" + _LTAIL)
    60	
    61	_LET = "[A-Za-zа-яА-ЯёЁ]"
    62	_LEADTOK = re.compile(
    63	    r"^\s*(?P<tok>[" + DASHES + r"]|\d{1,3}(?:" + _LET + r"(?!" + _LET + r"))?(?:\(\d{1,3}\))?[" + PRIMES +
    64	    r"]*(?:\(\d{1,3}\))?[.)、:]?|[IVX]{1,4}[" + PRIMES + r"]?[.)])(?=\s|$|(?<=[.)、:])[^\x00-\x7f])")
    65	_NUM = re.compile(
    66	    r"(?P<n>\d{1,3})(?P<l>" + _LET + r")?(?:\((?P<b1>\d{1,3})\))?(?P<p>[" + PRIMES +
    67	    r"]*)(?:\((?P<b2>\d{1,3})\))?[.)、:]?")
    68	_ROMAN = re.compile(r"(?P<r>[IVX]{1,4})(?P<p>[" + PRIMES + r"]?)[.)]")
    69	_REP_LABEL = re.compile(r"^(?P<l>[A-Za-z])(?P=l)*[.)](?=\s)")
    70	FIG_WORDS = r"(?:図|图|圖|Figs?\.?|рис\.?|Abb\.?|Taf\.?|Pls?\.?|Plates?|Tab\.?)"
    71	_FIGNUM = r"\d+[A-Za-z]?(?:\s*[-–、,&]\s*\d+[A-Za-z]?)*"
    72	FIG_PRE = re.compile(r"^\(?\s*" + FIG_WORDS + r"\s*" + _FIGNUM + r"\s*\)?[\s,:;]*", re.I)
    73	FIG_SUF = re.compile(r"[\s,;]*\(?\s*" + FIG_WORDS + r"\s*" + _FIGNUM + r"\s*\)?$", re.I)
    74	FIG_TAIL = re.compile(FIG_WORDS + r"\s*$", re.I)
    75	PART_RE = re.compile(r"\s*\((?:part|pars|partim|p\.\s?p\.|in part|部分|一部)\)", re.I)
    76	RANK_WORDS = {"Genus", "Subgenus", "Family", "Subfamily", "Superfamily", "Tribe", "Order", "Suborder", "Class",
    77	              "Phylum", "Section", "Series", "Род", "Подрод", "Семейство", "Подсемейство", "Отряд"}
    78	RANK_MARKS = {"subsp.", "ssp.", "var.", "subvar.", "f.", "fo.", "forma", "subf.", "sect.", "ser.", "cv."}
    79	QUAL_MARKS = {"cf.", "aff.", "sp.", "spp.", "nov.", "n.", "gen.", "indet.", "inc."}
    80	AUTH_PARTICLES = {"ex", "et", "in", "and", "und", "y", "e", "&", "de", "van", "von", "der", "den", "du", "la", "le"}
    81	SERIAL_TAXON = re.compile(
    82	    r"(?:^|(?<=[\s—–-]))(?P<t>(?:\d{1,3}|[IVXl]{1,4})[.)]\s*(?:(?:Genus|Subgenus|Family|Subfamily|Род|Семейство|Подсемейство)\s+)"
    83	    r"\*?[A-ZА-Я][^\d]{2,100})$")
    84	ABBR_TAIL = re.compile(r"(?<=\s)(?P<t>[A-Z]\.\s*[a-z][a-z\-]{2,}(?:\s+[a-z][a-z\-]{2,})?)\s*$")
    85	_BULLET = re.compile(r"^[-*•·▪●–—]\s+")
    86	
    87	
    88	@dataclass
    89	class GBranch:
    90	    lead: str
    91	    couplet: str = ""
    92	    alt: str = ""
    93	    raw_lead: str = ""
    94	    text: str = ""
    95	    kind: str = "none"
    96	    target: str = ""
    97	    jump: str | None = None
    98	    page: int | None = None
    99	    backref: str | None = None
   100	    src_page: int = 0
   101	    hint: str = ""
   102	    bare: bool = False
   103	
   104	    def asdict(self) -> dict[str, Any]:
   105	        return asdict(self)
   106	
   107	
   108	@dataclass
   109	class GKey:
   110	    heading: str = ""
   111	    branches: list[GBranch] = field(default_factory=list)
   112	    entries: list[str] = field(default_factory=list)
   113	
   114	    def asdict(self) -> dict[str, Any]:
   115	        return {"heading": self.heading, "entries": self.entries, "branches": [b.asdict() for b in self.branches]}
   116	
   117	
   118	class Target(NamedTuple):
   119	    kind: str  # jump | page | taxon | none
   120	    jump: str | None
   121	    page: int | None
   122	    taxon: str
   123	
   124	
   125	def _roman(s: str) -> int | None:
   126	    vals = {"I": 1, "V": 5, "X": 10}
   127	    tot = 0
   128	    for i, ch in enumerate(s):
   129	        v = vals[ch]
   130	        tot += -v if i + 1 < len(s) and vals[s[i + 1]] > v else v
   131	    return tot if 0 < tot < 40 else None
   132	
   133	
   134	def _is_dash(tok: str) -> bool:
   135	    return len(tok) == 1 and tok in DASH_CHARS
   136	
   137	
   138	def _alt_letter(ch: str) -> str:
   139	    c = ch.lower()
   140	    cyr = "абвгде"
   141	    return "abcdef"[cyr.index(c)] if c in cyr else c
   142	
   143	
   144	def norm_lead(raw: str, prev_num: str | None) -> tuple[str, str, str | None] | None:
   145	    """Normalise a lead token. Returns (couplet, alt_hint, backref) or None.
   146	
   147	    alt_hint: "" plain number, a letter (explicit letter or prime count),
   148	    "+" dash/bullet alternate of prev_num.
   149	    """
   150	    s = unicodedata.normalize("NFKC", raw).strip()
   151	    if not s:
   152	        return None
   153	    if _is_dash(s):
   154	        return (prev_num, "+", None) if prev_num else None
   155	    m = _NUM.fullmatch(s)
   156	    if m:
   157	        hint = ""
   158	        dg = m.group("n")
   159	        if prev_num and not m.group("p") and (
   160	                (m.group("l") in ("l", "I") and str(int(dg)) == prev_num)
   161	                or (not m.group("l") and len(dg) == 2 and dg[0] == dg[1] == prev_num)):
   162	            return prev_num, "b", None  # OCR read a prime as l / I / a second digit
   163	        if m.group("l"):
   164	            hint = _alt_letter(m.group("l"))
   165	        elif m.group("p"):
   166	            hint = chr(min(97 + len(m.group("p")), 122))
   167	        bk = m.group("b1") or m.group("b2")
   168	        return str(int(m.group("n"))), hint, str(int(bk)) if bk else None
   169	    m = _ROMAN.fullmatch(s)
   170	    if m:
   171	        v = _roman(m.group("r"))
   172	        if v is None:
   173	            return None
   174	        return str(v), (chr(min(97 + len(m.group("p")), 122)) if m.group("p") else ""), None
   175	    return None
   176	
   177	
   178	_KEEP_DOT = re.compile(r"(?:(?<![A-Za-z])(?:sp|spp|cf|aff|ssp|subsp|var|nov|gen|n)|(?<![A-Za-z])[A-Z])\.$")
   179	_NAME_OPEN = re.compile(r"(?:^|\s)(?:[A-Z]\.|[A-Z][a-zà-ÿ]{2,}\s+[a-zà-ÿ]{3,}(?:\s+[a-zà-ÿ]{3,})?)$")
   180	_EPI = re.compile(r"[a-zà-ÿ][a-zà-ÿ\-]{2,}")
   181	
   182	
   183	def _clean_taxon(s: str) -> str:
   184	    s = s.strip(" \t,;:—–-·…・")
   185	    if s.endswith(".") and not _KEEP_DOT.search(s):
   186	        s = s.rstrip(". ")
   187	    return s
   188	
   189	
   190	def canon_taxon(s: str) -> str:
   191	    """Canonical taxon text: names, ranks, cf./aff./sp. kept; authorities, years and (part) dropped."""
   192	    s = PART_RE.sub("", s).strip()
   193	    toks = s.split()
   194	    k = 1 if len(toks) > 1 and toks[0] in RANK_WORDS else 0
   195	    if k >= len(toks) or not re.fullmatch(r"[A-ZА-Я][a-zà-ÿа-я\-]*\d{0,2}\.?,?", toks[k]):
   196	        return s
   197	    out = [re.sub(r"(?<=[^\W\d])\d{1,2}(?=\.?,?$)", "", toks[k]).rstrip(",")]  # drop glued footnote digit
   198	    rest = toks[k + 1:]
   199	    if len(rest) > 1 and re.fullmatch(r"\([A-Z][a-zà-ÿ]+\)", rest[0]) and _EPI.fullmatch(rest[1]):
   200	        out.append(rest[0])
   201	        rest = rest[1:]
   202	    auth = False
   203	    for i, t in enumerate(rest):
   204	        tl = t.rstrip(",;")
   205	        nxt_epi = i + 1 < len(rest) and bool(_EPI.fullmatch(rest[i + 1].rstrip(",;")))
   206	        if tl.lower() in RANK_MARKS and nxt_epi:
   207	            auth = False
   208	            out.append(tl)
   209	        elif auth:
   210	            continue
   211	        elif tl in QUAL_MARKS:
   212	            out.append(tl)
   213	        elif tl in AUTH_PARTICLES:
   214	            auth = True
   215	        elif _EPI.fullmatch(tl) or re.fullmatch(r"\d{1,3}", tl):
   216	            out.append(tl)
   217	        else:
   218	            auth = True
   219	    return " ".join(out)
   220	
   221	
   222	def parse_target(s: str) -> Target:
   223	    """Classify a branch target: jump number, page reference, taxon (+page) or none."""
   224	    t = unicodedata.normalize("NFKC", s or "").strip()
   225	    t = re.sub(r"^[.…·・⋯\s]+", "", t.replace("*", "")).strip()
   226	    t = re.sub(r"^\d{1,3}\s*[.)]\s+(?=[^\W\d_])", "", t)
   227	    t = re.sub(r"^[IVXl]{1,4}[.)]\s+(?=(?:Genus|Subgenus|Family|Род|Семейство)\s)", "", t)  # OCR'd serial
   228	    page: int | None = None
   229	    for rx in PAGE_RES:
   230	        last = None
   231	        for last in rx.finditer(t):
   232	            pass
   233	        if last is not None:
   234	            page = int(last.group("p"))
   235	            t = (t[:last.start()] + " " + t[last.end():]).strip()
   236	            break
   237	    rem = _clean_taxon(t)
   238	    if not JUMP_RE.match(rem):
   239	        rem = _clean_taxon(FIG_SUF.sub("", FIG_PRE.sub("", rem)))
   240	    rem = _clean_taxon(PART_RE.sub("", rem))
   241	    if not rem:
   242	        return Target("page" if page is not None else "none", None, page, "")
   243	    jm = JUMP_RE.match(rem)
   244	    if jm:
   245	        return Target("jump", str(int(jm.group("n"))), page, "")
   246	    rm = re.fullmatch(r"([IVX]{1,4})[" + PRIMES + r"]?", rem)
   247	    if rm and _roman(rm.group(1)):
   248	        return Target("jump", str(_roman(rm.group(1))), page, "")
   249	    return Target("taxon", None, page, canon_taxon(rem))
   250	
   251	
   252	def _split(text: str) -> tuple[str, str, bool]:
   253	    """(text, target, bare); bare = target is only a trailing number with no leader/gap/arrow."""
   254	    m = None
   255	    for m in LEADER.finditer(text):
   256	        pass
   257	    if m is not None:
   258	        return text[:m.start()].strip(), text[m.end():].strip(), False
   259	    a = TRAIL_ARROW.search(text)
   260	    if a:
   261	        return text[:a.start()].strip(), (a.group("t") or a.group("j")).strip(), False
   262	    g = GAP_TARGET.search(text)
   263	    if g and (JUMP_RE.match(g.group("t").strip()) or LATIN_RE.match(g.group("t").strip())
   264	              or any(r.fullmatch(g.group("t").strip()) for r in PAGE_RES)):
   265	        return text[:g.start()].strip(), g.group("t").strip(), False
   266	    p = TRAIL_PAGE.search(text)
   267	    if p:
   268	        return text[:p.start()].strip(), p.group("t").strip(), False
   269	    st = SERIAL_TAXON.search(text)
   270	    if st:
   271	        return text[:st.start()].strip(" —–-"), st.group("t").strip(), False
   272	    ab = ABBR_TAIL.search(text)
   273	    if ab:
   274	        return text[:ab.start()].strip(), ab.group("t").strip(), False
   275	    t = TRAIL_TARGET.search(text)
   276	    if t and not FIG_TAIL.search(text[:t.start()]):
   277	        return text[:t.start()].strip(), t.group("t").strip(), True
   278	    return text.strip(), "", False
   279	
   280	
   281	def split_target(text: str) -> tuple[str, str]:
   282	    """Split branch text from its target (dot leader, arrow, wide gap, page, abbreviated name, trailing number)."""
   283	    left, target, _ = _split(text)
   284	    return left, target
   285	
   286	
   287	def _has_target(text: str) -> bool:
   288	    return bool(split_target(text)[1])
   289	
   290	
   291	def _mk(info: tuple[str, str, str | None], raw_lead: str, text: str, target: str, page: int,
   292	        bare: bool = False) -> GBranch:
   293	    couplet, hint, back = info
   294	    tg = parse_target(target)
   295	    return GBranch(lead=couplet + (hint if hint != "+" else ""), couplet=couplet, alt="", raw_lead=raw_lead,
   296	                   text=text.strip(), kind=tg.kind, target=tg.taxon if tg.kind == "taxon" else target.strip(), jump=tg.jump, page=tg.page,
   297	                   backref=back, src_page=page, hint=hint, bare=bare)
   298	
   299	
   300	class _Open:
   301	    def __init__(self, info: tuple[str, str, str | None], raw_lead: str, text: str, page: int) -> None:
   302	        self.info, self.raw_lead, self.text, self.page = info, raw_lead, text, page
   303	
   304	    def add(self, more: str) -> None:
   305	        a = self.text
   306	        self.text = a[:-1] + more if a.endswith("-") and more[:1].islower() else f"{a} {more}".strip()
   307	
   308	    def complete(self) -> bool:
   309	        return _has_target(self.text)
   310	
   311	    def done(self) -> GBranch:
   312	        left, target, bare = _split(self.text)
   313	        return _mk(self.info, self.raw_lead, left, target, self.page, bare)
   314	
   315	
   316	def _match_lead(line: str, prev_num: str | None) -> tuple[tuple[str, str, str | None], str, str, bool] | None:
   317	    """Return (info, raw_lead, rest, weak) for a line starting with a lead token."""
   318	    m = _LEADTOK.match(line)
   319	    if not m:
   320	        return None
   321	    tok = m.group("tok")
   322	    rest = line[m.end():].strip()
   323	    if _is_dash(tok):
   324	        inner = _LEADTOK.match(rest)
   325	        if inner and not _is_dash(inner.group("tok")):
   326	            r2 = _match_lead(rest, prev_num)
   327	            if r2 and not r2[3]:
   328	                return r2
   329	        info = norm_lead(tok, prev_num)
   330	        return (info, tok, rest, False) if info else None
   331	    info = norm_lead(tok, prev_num)
   332	    if info is None:
   333	        return None
   334	    weak = bool(re.fullmatch(r"\d{1,3}", tok))
   335	    return info, tok, rest, weak
   336	
   337	
   338	def _assign_alts(key: GKey) -> None:
   339	    groups: OrderedDict[str, list[GBranch]] = OrderedDict()
   340	    for b in key.branches:
   341	        groups.setdefault(b.couplet, []).append(b)
   342	    for c, brs in groups.items():
   343	        used: set[str] = set()
   344	        for b in brs:
   345	            h = b.hint
   346	            alt = h if h and h != "+" else next(chr(x) for x in range(97, 123) if chr(x) not in used)
   347	            used.add(alt)
   348	            b.alt = alt
   349	            b.lead = c + alt
   350	
   351	
   352	def _pair_backrefs(key: GKey) -> None:
   353	    """Soviet-style paired numbering 1(8) ... 8(1): bracket = opposite lead, not a back reference."""
   354	    brs = key.branches
   355	    nums = [b.couplet for b in brs]
   356	    if len(brs) < 2 or len(set(nums)) != len(nums) or any(b.backref is None or b.hint != "" for b in brs):
   357	        return
   358	    pairs = {(b.couplet, b.backref) for b in brs}
   359	    if any(n == m or (m, n) not in pairs for n, m in pairs):
   360	        return
   361	    by_num = {b.couplet: b for b in brs}
   362	
   363	    def cp(n: str) -> str:
   364	        return str(min(int(n), int(by_num[n].backref or n)))
   365	    for b in brs:
   366	        nxt = str(int(b.couplet) + 1)
   367	        if b.kind == "none" and nxt in by_num and nxt != b.backref:
   368	            b.kind, b.jump, b.target = "jump", cp(nxt), cp(nxt)
   369	    for b in brs:
   370	        b.couplet, b.backref = cp(b.couplet), None
   371	
   372	
   373	def _drop_bare(key: GKey) -> None:
   374	    """A bare trailing number is a jump only when that couplet exists in the key."""
   375	    have = {b.couplet for b in key.branches}
   376	    for b in key.branches:
   377	        if b.bare and b.kind == "jump" and b.jump not in have:
   378	            b.kind, b.jump, b.target = "none", None, ""
   379	
   380	
   381	def _complete_couplets(key: GKey) -> bool:
   382	    cnt: dict[str, int] = {}
   383	    for b in key.branches:
   384	        cnt[b.couplet] = cnt.get(b.couplet, 0) + 1
   385	    return any(n >= 2 for n in cnt.values())
   386	
   387	
   388	def _indent(raw: str) -> int:
   389	    w = 0
   390	    for ch in raw:
   391	        if ch == " ":
   392	            w += 1
   393	        elif ch == "\t":
   394	            w += 4
   395	        else:
   396	            break
   397	    return w
   398	
   399	
   400	def _looks_tree(items: list[tuple[int, str | None]], i: int) -> bool:
   401	    raw = items[i][1]
   402	    if raw is None:
   403	        return False
   404	    if not _REP_LABEL.match(_BULLET.sub("", raw.strip())):
   405	        return False
   406	    for j in range(i + 1, len(items)):
   407	        r = items[j][1]
   408	        if r is None or not r.strip():
   409	            continue
   410	        return bool(_REP_LABEL.match(_BULLET.sub("", r.strip())))
   411	    return False
   412	
   413	
   414	def parse_text(md: str, heading_re: re.Pattern[str] | None = None) -> list[GKey]:
   415	    """Parse page-marked text into keys (numbered, tabular and indented styles)."""
   416	    hre = heading_re or HEADING_RE
   417	    items: list[tuple[int, str | None]] = []
   418	    page = 0
   419	    for r in md.splitlines():
   420	        pm = PAGE_MARK.search(r)
   421	        if pm:
   422	            page = int(pm.group(1))
   423	            items.append((page, None))
   424	            rest = r[:pm.start()] + r[pm.end():]
   425	            if rest.strip():
   426	                items.append((page, unicodedata.normalize("NFKC", rest)))
   427	        else:
   428	            items.append((page, unicodedata.normalize("NFKC", r)))
   429	    n = len(items)
   430	
   431	    def next_sig(i: int) -> int | None:
   432	        for j in range(i + 1, n):
   433	            r = items[j][1]
   434	            if r is None or r.strip():
   435	                return j
   436	        return None
   437	
   438	    def next_page_leads(i: int) -> bool:
   439	        nj = next_sig(i)
   440	        if nj is None or items[nj][1] is not None:
   441	            return False
   442	        k = next_sig(nj)
   443	        nxt = items[k][1] if k is not None else None
   444	        return nxt is not None and _match_lead(nxt.strip(), None) is not None
   445	
   446	    def at_page_end(i: int) -> bool:
   447	        nj = next_sig(i)
   448	        return nj is None or items[nj][1] is None
   449	
   450	    keys: list[GKey] = []
   451	    key: GKey | None = None
   452	    mode = ""
   453	    cur: _Open | None = None
   454	    pending = ""
   455	    last_num = ""
   456	    fresh = False
   457	    hdr_cols: dict[str, int] = {}
   458	
   459	    def flush() -> None:
   460	        nonlocal cur
   461	        if cur is not None and key is not None:
   462	            key.branches.append(cur.done())
   463	        cur = None
   464	
   465	    def close() -> None:
   466	        nonlocal key, mode, last_num
   467	        flush()
   468	        if key is not None:
   469	            _pair_backrefs(key)
   470	            _drop_bare(key)
   471	            _assign_alts(key)
   472	        key = None
   473	        mode = ""
   474	        last_num = ""
   475	
   476	    def open_key(m: str) -> GKey:
   477	        nonlocal key, mode, pending, last_num
   478	        key = GKey(heading=pending)
   479	        keys.append(key)
   480	        pending = ""
   481	        mode = m
   482	        last_num = ""
   483	        return key
   484	
   485	    def tree_from(i: int) -> int | None:
   486	        """Consume an indented / letter-hierarchy key starting at item i; return next index or None."""
   487	        stack: list[int] = []
   488	        rows: list[dict[str, Any]] = []
   489	        j = i
   490	        while j < n:
   491	            pg, raw = items[j]
   492	            if raw is None or not raw.strip():
   493	                j += 1
   494	                continue
   495	            line = raw.strip()
   496	            if PAGE_ONLY.match(line):
   497	                if rows and not rows[-1]["target"] and JUMP_ONLY.match(line) and not at_page_end(j):
   498	                    rows[-1]["target"] = line
   499	                j += 1
   500	                continue
   501	            if hre.match(line) and not _LEADTOK.match(line) and len(line) <= 120:
   502	                if CONT_RE.search(line):
   503	                    j += 1
   504	                    continue
   505	                break
   506	            ind = _indent(raw)
   507	            bm = _BULLET.match(line)
   508	            content = line[bm.end():] if bm else line
   509	            lab = _REP_LABEL.match(content)
   510	            raw_lead = ""
   511	            letter = ""
   512	            if lab:
   513	                letter = lab.group("l").lower()
   514	                raw_lead = lab.group(0).strip()
   515	                content = content[lab.end():].strip()
   516	            text, target = split_target(content)
   517	            if rows and not rows[-1]["target"] and not lab and JUMP_ONLY.match(content):
   518	                rows[-1]["target"] = content
   519	                j += 1
   520	                continue
   521	            nj = next_sig(j)
   522	            nxt = items[nj][1] if nj is not None else None
   523	            deeper = nxt is not None and _indent(nxt) > ind
   524	            if not (target or deeper or lab):
   525	                break
   526	            while stack and stack[-1] > ind:
   527	                stack.pop()
   528	            if not stack or stack[-1] < ind:
   529	                stack.append(ind)
   530	            rows.append({"level": len(stack), "text": text, "target": target, "raw": raw_lead, "page": pg,
   531	                         "letter": letter})
   532	            j += 1
   533	        if not rows:
   534	            return None
   535	        k = open_key("tree")
   536	        st: list[int] = []
   537	        groups: dict[tuple[int, str], str] = {}
   538	        for idx, r in enumerate(rows):
   539	            while st and rows[st[-1]]["level"] >= r["level"]:
   540	                st.pop()
   541	            parent = st[-1] if st else -1
   542	            r["parent"] = parent
   543	            gk = (parent, r["letter"])
   544	            if gk not in groups:
   545	                groups[gk] = str(len(groups) + 1)
   546	                if parent >= 0:
   547	                    pb = rows[parent]["branch"]
   548	                    if pb.kind == "none":
   549	                        pb.kind, pb.target, pb.jump = "jump", groups[gk], groups[gk]
   550	            st.append(idx)
   551	            b = _mk((groups[gk], "", None), r["raw"], r["text"], r["target"], r["page"])
   552	            r["branch"] = b
   553	            k.branches.append(b)
   554	        for r in rows:  # a lone-letter target ("B") jumps to that letter's couplet
   555	            b = r["branch"]
   556	            if b.kind == "taxon" and re.fullmatch(r"[A-Za-z]", b.target):
   557	                lt = b.target.lower()
   558	                dest = groups.get((r["parent"], lt)) or next((v for (p, lg), v in groups.items() if lg == lt), None)
   559	                if dest:
   560	                    b.kind, b.jump, b.target = "jump", dest, dest
   561	        close()
   562	        return j
   563	
   564	    i = 0
   565	    while i < n:
   566	        pg, raw = items[i]
   567	        if raw is None:
   568	            fresh = True
   569	            i += 1
   570	            continue
   571	        line = raw.strip()
   572	        first_on_page = fresh and bool(line)
   573	        if line:
   574	            fresh = False
   575	        if not line:
   576	            i += 1
   577	            continue
   578	        incomplete = cur is not None and not cur.complete()
   579	        if first_on_page and (RUNNING_HEAD.match(line) or (
   580	                any(ch.isupper() for ch in line) and line == line.upper() and len(line) >= 4
   581	                and not _LEADTOK.match(line) and not hre.match(line) and not LEADER.search(line))):
   582	            i += 1
   583	            continue
   584	        if key is not None and len(line) <= 120 and hre.match(line) and CONT_RE.search(line):
   585	            i += 1
   586	            continue
   587	        if PAGE_ONLY.match(line):
   588	            if cur is not None and incomplete and not first_on_page and JUMP_ONLY.match(line) \
   589	                    and (not at_page_end(i) or next_page_leads(i)):
   590	                cur.add(line)
   591	            i += 1
   592	            continue
   593	        if line.startswith("|"):
   594	            cells = [c.strip() for c in line.strip("|").split("|")]
   595	            if all(re.fullmatch(r":?-{2,}:?", c) or not c for c in cells) and any(cells):
   596	                i += 1
   597	                continue
   598	            lm = _match_lead(cells[0] + " x", last_num or None) if cells and cells[0] else None
   599	            if mode != "table":
   600	                close()
   601	                if lm is None:
   602	                    hdr_cols.clear()
   603	                    for ci, c in enumerate(cells):  # header row: remember taxon / page columns
   604	                        if ci and re.fullmatch(r"(?i)类群|類群|分类群|分類群|taxon|taxa|target|destination|去向", c):
   605	                            hdr_cols["tax"] = ci
   606	                        elif ci and re.fullmatch(r"(?i)页码|頁碼|页|頁|pages?|págs?\.?|seite|стр\.?", c):
   607	                            hdr_cols["page"] = ci
   608	                    i += 1
   609	                    continue
   610	                open_key("table")
   611	            assert key is not None
   612	            if lm is None:
   613	                if key.branches and len(cells) > 1:  # continuation row
   614	                    b = key.branches[-1]
   615	                    b.text = (b.text + " " + " ".join(cells[1:-1] if len(cells) > 2 else cells[1:2])).strip()
   616	                    if len(cells) > 2 and cells[-1]:
   617	                        tg = parse_target(cells[-1])
   618	                        b.target, b.kind, b.jump, b.page = (tg.taxon if tg.kind == "taxon" else cells[-1]), \
   619	                            tg.kind, tg.jump, tg.page
   620	                i += 1
   621	                continue
   622	            info, rl, _, _ = lm
   623	            tc, pc = hdr_cols.get("tax", -1), hdr_cols.get("page", -1)
   624	            if 0 < tc < len(cells):
   625	                target = cells[tc] + (" " + cells[pc] if 0 < pc < len(cells) and cells[pc] else "")
   626	                text = " ".join(c for ci, c in enumerate(cells) if ci not in (0, tc, pc) and c)
   627	            elif len(cells) >= 3:
   628	                text, target = " ".join(cells[1:-1]), cells[-1]
   629	            else:
   630	                text, target = split_target(cells[1] if len(cells) > 1 else "")
   631	            key.branches.append(_mk(info, rl, text, target, pg))
   632	            if not _is_dash(rl):
   633	                last_num = info[0]
   634	            i += 1
   635	            continue
   636	        if mode == "table":
   637	            close()
   638	        if len(line) <= 120 and not incomplete and hre.match(line) and not _LEADTOK.match(line):
   639	            close()
   640	            pending = line.lstrip("# ").strip().strip("*").strip()
   641	            hdr_cols.clear()
   642	            i += 1
   643	            continue
   644	        lm = _match_lead(line, last_num or None)
   645	        if lm is not None and mode != "tree":
   646	            info, rl, rest, weak = lm
   647	            ok = True
   648	            if weak:
   649	                exp = int(last_num) if last_num else 0
   650	                want = {b.jump for b in key.branches} if key is not None else set()
   651	                if cur is not None:
   652	                    want.add(parse_target(_split(cur.text)[1]).jump)
   653	                if key is None and not pending:
   654	                    ok = False
   655	                elif info[0] in want and key is not None:
   656	                    ok = True
   657	                elif incomplete and int(info[0]) != exp + 1:
   658	                    ok = False
   659	                elif incomplete and cur is not None and key is not None \
   660	                        and not any(b.couplet == cur.info[0] for b in key.branches):
   661	                    ok = False  # a couplet needs two branches: a lone open branch cannot be followed by a new one
   662	                elif key is not None and int(info[0]) not in (exp, exp + 1):
   663	                    ok = False
   664	            if ok and _ROMAN.fullmatch(rl) and key is None and not pending:
   665	                ok = False
   666	            if ok:
   667	                flush()
   668	                if key is not None and info[0] == "1" and info[1] in ("", "a") and last_num != "1" \
   669	                        and _complete_couplets(key):
   670	                    close()
   671	                if key is None:
   672	                    open_key("num")
   673	                cur = _Open(info, rl, rest, pg)
   674	                if not _is_dash(rl):
   675	                    last_num = info[0]
   676	                i += 1
   677	                continue
   678	        if key is None and (pending or _looks_tree(items, i)):
   679	            j = tree_from(i)
   680	            if j is not None:
   681	                pending = ""
   682	                i = j
   683	                continue
   684	        if key is None:
   685	            i += 1
   686	            continue
   687	        if cur is not None and incomplete:
   688	            cur.add(line)
   689	        elif cur is not None and _EPI.fullmatch(line) and _NAME_OPEN.search(_split(cur.text)[1]):
   690	            cur.add(line)  # species / subspecies epithet wrapped onto its own line
   691	        else:
   692	            close()
   693	        i += 1
   694	    close()
   695	    keys = [k for k in keys if any(ch.isalnum() for b in k.branches for ch in b.text + b.target)]  # lost glyphs
   696	    return [k for k in keys if k.heading or len(k.branches) != 1 or k.branches[0].kind != "none"]
   697	
   698	
   699	# ---------------------------------------------------------------- checks
   700	
   701	def _cnum(c: str) -> int:
   702	    return int(c) if c.isdigit() else 10 ** 6
   703	
   704	
   705	def _f(code: str, severity: str, lead: str, detail: str) -> dict[str, Any]:
   706	    return {"code": code, "severity": severity, "lead": lead, "detail": detail}
   707	
   708	
   709	def check(key: GKey, entries: Sequence[str] | None = None) -> list[dict[str, Any]]:
   710	    """Graph problems of one key (single_branch ... backref_mismatch)."""
   711	    out: list[dict[str, Any]] = []
   712	    groups: OrderedDict[str, list[GBranch]] = OrderedDict()
   713	    for b in key.branches:
   714	        groups.setdefault(b.couplet, []).append(b)
   715	    for c, brs in groups.items():
   716	        alts = [b.alt for b in brs]
   717	        if "a" not in alts:
   718	            out.append(_f("lone_alternate", "error", brs[0].lead, f"couplet {c} has alternate(s) {alts} but no 'a'"))
   719	        if len(brs) == 1:
   720	            out.append(_f("single_branch", "error", brs[0].lead, f"couplet {c} has one branch"))
   721	    seen: dict[str, int] = {}
   722	    for b in key.branches:
   723	        seen[b.lead] = seen.get(b.lead, 0) + 1
   724	    for lead, cnt in seen.items():
   725	        if cnt > 1:
   726	            out.append(_f("duplicate_lead", "error", lead, f"{lead} appears {cnt} times"))
   727	    for b in key.branches:
   728	        if b.kind == "none":
   729	            out.append(_f("no_target", "error", b.lead, f"no target (p.{b.src_page})"))
   730	    edges: dict[str, list[str]] = {c: [] for c in groups}
   731	    incoming: dict[str, list[GBranch]] = {}
   732	    for b in key.branches:
   733	        if b.kind == "jump" and b.jump is not None:
   734	            if b.jump not in groups:
   735	                out.append(_f("dangling_jump", "error", b.lead, f"jump to missing couplet {b.jump}"))
   736	                continue
   737	            edges[b.couplet].append(b.jump)
   738	            incoming.setdefault(b.jump, []).append(b)
   739	    for b in key.branches:
   740	        if b.backref is not None and not any(x.jump == b.couplet for x in groups.get(b.backref, [])):
   741	            out.append(_f("backref_mismatch", "error", b.lead, f"backref {b.backref} does not jump to {b.couplet}"))
   742	    ents = [e for e in (entries or key.entries or []) if e in groups]
   743	    if not ents and groups:
   744	        ents = [min(groups, key=_cnum)]
   745	    reach: set[str] = set()
   746	    todo = list(ents)
   747	    while todo:
   748	        c = todo.pop(0)
   749	        if c in reach:
   750	            continue
   751	        reach.add(c)
   752	        todo += [t for t in edges.get(c, []) if t not in reach]
   753	    for c in groups:
   754	        if c not in reach:
   755	            out.append(_f("unreachable", "error", c, f"couplet {c} unreachable from {ents}"))
   756	    out += _cycles(groups, edges)
   757	    for t, srcs in incoming.items():
   758	        if len(srcs) >= 2:
   759	            out.append(_f("multi_parent", "warn", t, f"couplet {t} entered from {[s.lead for s in srcs]}"))
   760	    return out
   761	
   762	
   763	def _cycles(groups: OrderedDict[str, list[GBranch]], edges: dict[str, list[str]]) -> list[dict[str, Any]]:
   764	    out: list[dict[str, Any]] = []
   765	    color: dict[str, int] = {}
   766	    reported: set[tuple[str, ...]] = set()
   767	    for root in sorted(groups, key=_cnum):
   768	        if color.get(root):
   769	            continue
   770	        path = [root]
   771	        iters = [iter(sorted(set(edges[root]), key=_cnum))]
   772	        color[root] = 1
   773	        while path:
   774	            nxt = next(iters[-1], None)
   775	            if nxt is None:
   776	                color[path.pop()] = 2
   777	                iters.pop()
   778	                continue
   779	            st = color.get(nxt, 0)
   780	            if st == 1:
   781	                cyc = path[path.index(nxt):]
   782	                r = cyc.index(min(cyc, key=_cnum))
   783	                canon = tuple(cyc[r:] + cyc[:r])
   784	                if canon not in reported:
   785	                    reported.add(canon)
   786	                    out.append(_f("cycle", "error", canon[0], "cycle " + ">".join(canon + (canon[0],))))
   787	            elif st == 0:
   788	                color[nxt] = 1
   789	                path.append(nxt)
   790	                iters.append(iter(sorted(set(edges[nxt]), key=_cnum)))
   791	    return out
   792	
   793	
   794	# ---------------------------------------------------------------- align
   795	
   796	def latin_names(s: str) -> list[str]:
   797	    return [re.sub(r"\s+", " ", m.group(0)) for m in LATIN_RE.finditer(s or "")]
   798	
   799	
   800	def _ta(b: GBranch) -> tuple[Any, ...]:
   801	    taxon = canon_taxon(parse_target(b.target).taxon)
   802	    names = tuple(latin_names(taxon))
   803	    return (b.kind, b.jump, b.page, names, tuple(re.findall(r"\d+", taxon)))
   804	
   805	
   806	def align(src_keys: Sequence[GKey], tgt_keys: Sequence[GKey]) -> list[dict[str, Any]]:
   807	    """Compare source and translated keys branch by branch."""
   808	    out: list[dict[str, Any]] = []
   809	    if len(src_keys) != len(tgt_keys):
   810	        out.append({**_f("key_count", "error", "", f"source {len(src_keys)} keys, translation {len(tgt_keys)}"),
   811	                    "key": 0})
   812	    for ki, (s, t) in enumerate(zip(src_keys, tgt_keys), start=1):
   813	        tmap: dict[str, GBranch] = {}
   814	        for b in t.branches:
   815	            tmap.setdefault(b.lead, b)
   816	        smap: dict[str, GBranch] = {}
   817	        for b in s.branches:
   818	            smap.setdefault(b.lead, b)
   819	        for lead, b in smap.items():
   820	            o = tmap.get(lead)
   821	            if o is None:
   822	                out.append({**_f("missing_branch", "error", lead, "missing in translation"), "key": ki})
   823	            elif _ta(b) != _ta(o):
   824	                out.append({**_f("target_changed", "error", lead, f"{b.target!r} -> {o.target!r}"), "key": ki})
   825	        for lead in tmap:
   826	            if lead not in smap:
   827	                out.append({**_f("extra_branch", "error", lead, "not in source"), "key": ki})
   828	        so = [x for x in dict.fromkeys(b.lead for b in s.branches) if x in tmap]
   829	        to = [x for x in dict.fromkeys(b.lead for b in t.branches) if x in smap]
   830	        if so != to:
   831	            out.append({**_f("order_changed", "error", "", f"{so} -> {to}"), "key": ki})
   832	    return out
   833	
   834	
   835	def gate(keys: Sequence[GKey], expect_keys: bool) -> list[dict[str, Any]]:
   836	    """no_keys when keys are expected but none were recognised."""
   837	    if expect_keys and not keys:
   838	        return [_f("no_keys", "error", "", "keys expected but none recognised")]
   839	    return []
   840	
   841	
   842	# ---------------------------------------------------------------- CLI
   843	
   844	def main(argv: Sequence[str] | None = None) -> int:
   845	    ap = argparse.ArgumentParser(prog="python3 -m booklayout.keygraph", description="dichotomous key graph check")
   846	    ap.add_argument("--source", type=Path, required=True)
   847	    ap.add_argument("--translation", type=Path)
   848	    ap.add_argument("--expect-keys", action="store_true")
   849	    ap.add_argument("--entries", default="", help="comma-separated entry couplets")
   850	    ap.add_argument("--out", type=Path)
   851	    a = ap.parse_args(argv)
   852	    entries = [e.strip() for e in a.entries.split(",") if e.strip()]
   853	    src = parse_text(a.source.read_text(encoding="utf-8"))
   854	    findings: list[dict[str, Any]] = gate(src, a.expect_keys)
   855	    for i, k in enumerate(src, 1):
   856	        findings += [{**f, "key": i} for f in check(k, entries or None)]
   857	    report: dict[str, Any] = {"keys": [k.asdict() for k in src]}
   858	    if a.translation:
   859	        tgt = parse_text(a.translation.read_text(encoding="utf-8"))
   860	        findings += align(src, tgt)
   861	        report["translation_keys"] = [k.asdict() for k in tgt]
   862	    report["findings"] = findings
   863	    errs = sum(1 for f in findings if f["severity"] == "error")
   864	    report["ok"] = errs == 0
   865	    if a.out:
   866	        a.out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
   867	    print(f"keys={len(src)} branches={sum(len(k.branches) for k in src)} errors={errs} "
   868	          f"warnings={len(findings) - errs}")
   869	    return 1 if errs else 0
   870	
   871	
   872	LIMITS = [
   873	    "indented keys: wrapped (multi-line) branch text is read as child lines",
   874	    "headingless indented keys unsupported; headingless letter-label keys need two consecutive labels",
   875	    "taxon target without dot leader / wide gap / table cell is not separated from text",
   876	    "Latin-name extraction is regex based; author names count as names",
   877	    "bare trailing number counts as a jump only if that couplet exists (a count equal to a couplet no. is misread)",
   878	    "OCR prime read as a doubled digit / l is recognised only right after the same number (11. after 1.)",
   879	    "paired numbering 1(8)..8(1): needs every branch bracketed and symmetric; one malformed lead disables it",
   880	    "wrapped epithet joined only when it is a single lowercase word after an abbreviated genus or binomial",
   881	]
   882	
   883	if __name__ == "__main__":
   884	    sys.exit(main())

 succeeded in 53ms:
     1	"""Run adversarial corpus against booklayout.keygraph; write report."""
     2	from __future__ import annotations
     3	
     4	import json
     5	import sys
     6	from pathlib import Path
     7	
     8	ROOT = Path(__file__).resolve().parents[2]
     9	sys.path.insert(0, str(ROOT))
    10	from booklayout import keygraph as kg  # noqa: E402
    11	
    12	CORPUS = Path(__file__).parent / "corpus"
    13	
    14	
    15	def run_case(case: dict) -> dict:
    16	    src = kg.parse_text(case["source"])
    17	    entries = case.get("declared_entries")
    18	    codes: set[str] = set()
    19	    got_branches = []
    20	    for k in src:
    21	        if entries:
    22	            k.entries = list(entries)
    23	        for f in kg.check(k, entries=entries):
    24	            codes.add(f["code"])
    25	        for b in k.branches:
    26	            tgt = b.jump if b.kind == "jump" else (b.page if b.kind == "page" else b.target)
    27	            got_branches.append([b.lead, b.kind, str(tgt or "")])
    28	    for f in kg.gate(src, expect_keys=bool(entries) or case["expect"].get("keys", 0) > 0):
    29	        codes.add(f["code"])
    30	    if case.get("translation"):
    31	        tgt = kg.parse_text(case["translation"])
    32	        for f in kg.align(src, tgt):
    33	            codes.add(f["code"])
    34	    exp = case["expect"]
    35	    want = set(exp.get("findings", []))
    36	    errs = []
    37	    if exp.get("keys") is not None and exp["keys"] != len(src):
    38	        errs.append(f"keys want {exp['keys']} got {len(src)}")
    39	    if want != codes:
    40	        errs.append(f"findings missing {sorted(want - codes)} extra {sorted(codes - want)}")
    41	    wb = [[str(x) for x in b] for b in exp.get("branches", [])]
    42	    if wb and wb != got_branches:
    43	        errs.append(f"branches want {wb} got {got_branches}")
    44	    return {"id": case["id"], "ok": not errs, "errs": errs}
    45	
    46	
    47	def main() -> int:
    48	    res = []
    49	    for p in sorted(CORPUS.glob("*.json")):
    50	        case = json.loads(p.read_text(encoding="utf-8"))
    51	        try:
    52	            res.append(run_case(case))
    53	        except Exception as e:  # noqa: BLE001
    54	            res.append({"id": case.get("id", p.stem), "ok": False, "errs": [f"crash {type(e).__name__}: {e}"]})
    55	    bad = [r for r in res if not r["ok"]]
    56	    out = Path(__file__).parent / "corpus_report.json"
    57	    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    58	    print(f"pass {len(res) - len(bad)}/{len(res)}")
    59	    for r in bad:
    60	        print(r["id"], "|", " ; ".join(r["errs"])[:400])
    61	    return 1 if bad else 0
    62	
    63	
    64	if __name__ == "__main__":
    65	    raise SystemExit(main())
# 第 2 轮分类检索表解析审查

35 例均为合成转写，覆盖多毛类、昆虫、植物志及中日俄文版式。按 SPEC.md 核对表数、有序分支及问题码集合。下列样例名省略 r2_ 前缀和 .json 后缀。行号指本轮运行的 booklayout/keygraph.py。

P0 表示去向确已改变却通过原译对照，或整表、大段分支丢失。P1 表示局部结构、去向或告警错误。P2 表示仅影响终点的书写形式。

| 级别 | 源码位置 | 实测问题 | 样例 |
|---|---|---|---|
| P0 | booklayout/keygraph.py:57、649–652 | 双名后的第三词、subsp. 后的加词、cf. 后的种加词均能被替换而不触发 target_changed。 | trinomial、subspecies_rank、cf_epithet |
| P0 | booklayout/keygraph.py:507–514 | 无标点编号只能持平或加一。105 偶句的表在 82 明确跳往 86 时截断，210 支只读出 164 支。 | long_sparse |
| P0 | booklayout/keygraph.py:60–61、310 | 中日文编号后紧排正文，或俄文以西里尔 а、б 标支，均可令整表识别为零。全角数字本身可正常归一。 | compact_zh、compact_ja、ru_cyrillic |
| P1 | booklayout/keygraph.py:177、645–652 | 动物命名人及年份、植物作者缩写进入学名字段；略去 Linnaeus, 1758 还会误报去向改变。LIMITS 第 725 行已提示作者识别问题。 | authority、botanical_author |
| P1 | booklayout/keygraph.py:166–177 | 科或亚科后的 (part) 进入学名字段；亚科例中，另行改变页码仍能正确告警。 | part_family、part_subfamily |
| P1 | booklayout/keygraph.py:51、196–198 | 行末的末鳃刚节号和俄文图号被读作跳转，缺去向被报成悬空跳转。 | count_range、count_fig |
| P1 | booklayout/keygraph.py:237–244、507–514 | 横线后的触角节数使整支漏读；续行开头的 2 aciculae 则凭空生成分支 2a。 | dash_count、wrap_count |
| P1 | booklayout/keygraph.py:60–64、135–139 | OCR 把撇号读成 1 或 l 后，规范化分别产生 11a 和 1l。配对清稿提供期望读法，孤立字形不足以确定原号。 | ocr_one、ocr_ell |
| P1 | booklayout/keygraph.py:26、193–199 | 两个居中三点符不足匹配门槛；点线完全消失时，单空格后的缩写学名也丢失。后一情形已列于 LIMITS 第 724 行。 | double_ellipsis、lost_dots |
| P1 | booklayout/keygraph.py:190–195 | 先截页码再检测宽空格，导致带页码的科名终点退化为单独页码。 | gap_page |
| P1 | booklayout/keygraph.py:202–203、538–541 | 编号式检索表的种或亚种加词折到下一行时被丢弃，同一偶句拆成两张表。LIMITS 第 722 行仅提缩进式折行。 | wrapped_genus、wrapped_subspecies |
| P1 | booklayout/keygraph.py:47–48 | 日文「１２ページ」被解释为跳偶句 12，继而误报悬空。 | jp_page |
| P1 | booklayout/keygraph.py:67–68、166–170 | 页码与分图或图号列表并列时，Fig. 4A 残留在学名中；中文页码终点凭空产生类群「、4)」。 | plate_panel、page_figure_list |
| P1 | booklayout/keygraph.py:481–488 | 续行写回原单元格，学名中残留页码；独立页码列排在科名列之后时，两支科名都消失。 | table_cont、table_split_columns |
| P1 | booklayout/keygraph.py:458–463 | 页尾单列跳号被作印刷页码丢弃。底稿将同一目标内联，可核对下一页实际接到的偶句。 | detached_pageend |
| P1 | booklayout/keygraph.py:305–310 | 页标后同行紧接分支时，整行丢弃，只剩备择支。 | inline_marker |
| P1 | booklayout/keygraph.py:139、589 | 去掉了偶句号的前导零，却用原字符串 01 查回指来源，误报 backref_mismatch。 | padded_backref |
| P2 | booklayout/keygraph.py:149–150 | sp. 和 spp. 的缩写点被剥去。两例按保留开放命名原写法断言；SPEC 未单列缩写标点规则。 | sp_terminal、spp_terminal |

通过的对照为 abbr_control（六个连续点、缩写属名、换种告警）、prime_control（全角数字、直撇号及空格分隔点线）、fig_page_control（简单俄文图号与页码并存，仅改页码即可告警）。

运行命令为 PYTHONDONTWRITEBYTECODE=1 python3 test-keys/adv/run_corpus.py。退出码 1；逐例差异见同目录 corpus_report.json。
全量 90 例，58 例通过，32 例失败。第 1 轮 55 例全部通过；第 2 轮 35 例中 3 例通过，32 例失败。
INDEX.md
de_page_only.json
de_two_entry_join.json
en_ascii_prime.json
en_backref_one.json
en_backref_wrong.json
en_backwards_ok.json
en_dangling_range.json
en_diamond.json
en_duplicate_b.json
en_duplicate_prime.json
en_empty_cell.json
en_indent_siblings.json
en_island_cycle.json
en_letter_jump.json
en_letters.json
en_no_stop.json
en_prime_jump.json
en_range.json
en_running_head.json
en_same_terminal.json
en_single_primary.json
en_trichotomy.json
en_two_entries.json
en_two_titles.json
en_unreachable_chain.json
es_bullet_page.json
es_crosspage_cycle.json
fr_backref_self.json
fr_empty_tail.json
fr_prose_boundary.json
fr_wrap.json
ja_figure_anchor.json
ja_image_only.json
la_ab_caps.json
pair_chinese_only.json
pair_equivalent_pages.json
pair_extra_fourth.json
pair_extra_third.json
pair_genus_only.json
pair_missing_fourth.json
pair_missing_last.json
pair_numeric.json
pair_order_three.json
pair_order_two.json
pair_page_dropped.json
pair_taxa_swapped.json
pair_whole_key_added.json
pair_whole_key_lost.json
r2_abbr_control.json
r2_authority.json
r2_botanical_author.json
r2_cf_epithet.json
r2_compact_ja.json
r2_compact_zh.json
r2_count_fig.json
r2_count_range.json
r2_dash_count.json
r2_detached_pageend.json
r2_double_ellipsis.json
r2_fig_page_control.json
r2_gap_page.json
r2_inline_marker.json
r2_jp_page.json
r2_long_sparse.json
r2_lost_dots.json
r2_ocr_ell.json
r2_ocr_one.json
r2_padded_backref.json
r2_page_figure_list.json
r2_part_family.json
r2_part_subfamily.json
r2_plate_panel.json
r2_prime_control.json
r2_ru_cyrillic.json
r2_sp_terminal.json
r2_spp_terminal.json
r2_subspecies_rank.json
r2_table_cont.json
r2_table_split_columns.json
r2_trinomial.json
r2_wrap_count.json
r2_wrapped_genus.json
r2_wrapped_subspecies.json
real_marinov_thesis.json
real_marinov_two_leads.json
ru_lost_glyphs.json
ru_prime_page.json
ru_single_prime.json
zh_dangling_nextline.json
zh_page_detached.json
zh_single_dash.json
zh_three_columns.json

 succeeded in 265ms:
diff --git a/booklayout/cli.py b/booklayout/cli.py
index e25c6a5..4bcb22c 100755
--- a/booklayout/cli.py
+++ b/booklayout/cli.py
@@ -358,7 +358,51 @@ def cmd_build(args: argparse.Namespace) -> int:
     return 0
 
 
+def cmd_restyle(args: argparse.Namespace) -> int:
+    """Re-apply the heading styles of a profile to a finished DOCX (no re-typesetting)."""
+    import time
+
+    from docx import Document
+
+    from .builder import apply_profile, define_heading_styles
+    from .profile import StyleProfile
+
+    t0 = time.time()
+    prof = StyleProfile.from_file(args.profile)
+    apply_profile(prof)
+    doc = Document(str(args.docx))
+    define_heading_styles(doc, prof)
+    args.out.parent.mkdir(parents=True, exist_ok=True)
+    doc.save(str(args.out))
+    t_docx = time.time() - t0
+    msg = f"restyled={args.out} docx_s={t_docx:.2f}"
+    if args.pdf:
+        _convert_pdf(args.out, args.pdf_out)
+        msg += f" total_s={time.time() - t0:.2f}"
+    if args.html:
+        from .htmlout import docx_to_html
+        docx_to_html(args.out, args.html, prof)
+        msg += f" html={args.html}"
+    print(msg)
+    return 0
+
+
+def cmd_html(args: argparse.Namespace) -> int:
+    from .builder import apply_profile
+    from .htmlout import docx_to_html
+    from .profile import StyleProfile
+
+    prof = StyleProfile.from_file(args.profile)
+    apply_profile(prof)
+    print(docx_to_html(args.docx, args.out, prof, args.title or ""))
+    return 0
+
+
 def cmd_map_pages(args: argparse.Namespace) -> int:
+    if getattr(args, "profile", None):
+        from .builder import apply_profile
+        from .profile import StyleProfile
+        apply_profile(StyleProfile.from_file(args.profile))
     data = load_aligned(args.aligned)
     meta = _meta(args)
     page_map = make_page_map(args.pdf, data, meta)
@@ -966,6 +1010,56 @@ def _text_qa(data: dict, meta: BookMeta | None = None) -> dict:
     }
 
 
+def _delivery_problems(data: dict, pdf: str | None) -> dict:
+    """Added 2026-11-23 after Fauna Iberica Vol. 21: key couplets vanished.
+
+    Hard checks that ok:true must never skip: key pages carrying blocks the
+    builder cannot print, targets cut off from their couplet, hand-broken
+    lines inside justified text, and printed blocks that are absent from the PDF.
+    """
+    from .keyfix import repair_key_page
+
+    repaired: list[dict] = []
+    orphans: list[dict] = []
+    manual_breaks: list[dict] = []
+    expected: list[tuple[int, str]] = []
+    for page in data.get("pages", []):
+        _, counts = repair_key_page(page)
+        if counts["index_to_key"] or counts["targets_merged"]:
+            repaired.append({"page": page["page"], **counts})
+        if counts["orphan_targets"]:
+            orphans.append({"page": page["page"], "count": counts["orphan_targets"]})
+        for block in page.get("blocks", []):
+            tr = (block.get("translation") or "").strip()
+            if block.get("role") in ("body", "caption", "note") and "\n" in tr:
+                manual_breaks.append({"page": page["page"], "text": tr[:80]})
+            if block.get("role") in ("body", "caption", "heading", "key") and len(tr) >= 24:
+                expected.append((page["page"], tr))
+    missing: list[dict] = []
+    literal_tags: list[dict] = []
+    if pdf:
+        try:
+            import fitz
+
+            with fitz.open(pdf) as doc:
+                blob = "".join(page.get_text() for page in doc)
+            def squeeze(s: str) -> str:  # drop spaces, marks, half/full-width punctuation
+                return re.sub(r"[\W_]+", "", s)
+
+            for m in re.finditer(r".{0,25}</?(?:sup|sub|i|b|em)>.{0,10}", blob):
+                literal_tags.append({"text": m.group(0)})
+            blob = squeeze(blob)
+            for number, tr in expected:
+                probe = squeeze(tr)[:14]
+                if probe and probe not in blob:
+                    missing.append({"page": number, "text": tr[:60]})
+        except Exception:  # pragma: no cover - PDF reader unavailable
+            pass
+    return {"key_repaired_pages": repaired, "key_orphan_targets": orphans,
+            "manual_line_breaks": manual_breaks, "blocks_missing_in_pdf": missing,
+            "literal_markup_in_pdf": literal_tags}
+
+
 def cmd_qa(args: argparse.Namespace) -> int:
     """Run the three deterministic reviews used before delivery."""
     _require_figure_audit(args.figures)
@@ -991,6 +1085,26 @@ def cmd_qa(args: argparse.Namespace) -> int:
         )
 
     layout_problems = []
+    delivery = _delivery_problems(data, args.pdf)
+    if getattr(args, "profile", None) and json.loads(Path(args.profile).read_text(encoding="utf-8")).get("unwrap_lines"):
+        delivery["manual_line_breaks"] = []  # the builder joins them
+    report.update(delivery)
+    if delivery["key_orphan_targets"]:
+        structure_problems.append(f"{len(delivery['key_orphan_targets'])} key pages have a target with no couplet")
+    from .headings import stray_label_blocks
+    if getattr(args, "profile", None) and json.loads(Path(args.profile).read_text(encoding="utf-8")).get("promote_captions"):
+        from .headings import drop_stray_labels
+        drop_stray_labels(data)  # the builder drops them under this profile
+    strays = stray_label_blocks(data)
+    report["stray_label_blocks"] = strays
+    if strays:
+        structure_problems.append(f"{len(strays)} body blocks are lone figure-panel letters (pages {sorted({s['page'] for s in strays})[:6]}); enable promote_captions or remove them")
+    if delivery["literal_markup_in_pdf"]:
+        structure_problems.append(f"{len(delivery['literal_markup_in_pdf'])} literal <sup>/<sub>/<i> tags are printed in the PDF")
+    if delivery["blocks_missing_in_pdf"]:
+        structure_problems.append(f"{len(delivery['blocks_missing_in_pdf'])} printed blocks are missing from the PDF")
+    if delivery["manual_line_breaks"]:
+        layout_problems.append(f"{len(delivery['manual_line_breaks'])} justified paragraphs contain hand-made line breaks")
     if args.pdf:
         try:
             import fitz
@@ -1648,6 +1762,24 @@ def cmd_gate(args: argparse.Namespace) -> int:
         problems.append(f"{len(key['breaks'])} key couplets still need a forced break")
     if key.get("defects"):
         problems.append(f"{len(key['defects'])} key leader defects remain")
+    km_path = getattr(args, "key_model", None)
+    if km_path:
+        try:
+            kmj = json.loads(km_path.read_text(encoding="utf-8"))
+            if not kmj.get("ok"):
+                g = kmj.get("graph", {})
+                problems.append(f"key-model not ok ({km_path.name}): graph errors {g.get('errors', '?')}")
+        except (OSError, ValueError) as e:
+            problems.append(f"key-model unreadable ({km_path}): {e}")
+    kr_path = getattr(args, "keyrender", None)
+    if kr_path:
+        try:
+            krj = json.loads(kr_path.read_text(encoding="utf-8"))
+            fails = {r: n for r, n in (krj.get("summary") or {}).items() if n}
+            if fails or krj.get("findings"):
+                problems.append(f"keyrender FAIL ({kr_path.name}): {fails or len(krj.get('findings', []))}")
+        except (OSError, ValueError) as e:
+            problems.append(f"keyrender unreadable ({kr_path}): {e}")
     for style_path in args.style_report or []:  # scripts/taxostyle.py compare|audit 的 JSON 报告
         style = json.loads(style_path.read_text(encoding="utf-8"))
         if not style.get("ok"):
@@ -1751,12 +1883,27 @@ def build_parser() -> argparse.ArgumentParser:
     b.add_argument("--title", help="fallback title when --metadata is omitted")
     b.set_defaults(func=cmd_build)
 
+    rs = sub.add_parser("restyle", help="re-apply heading styles of a profile to a finished DOCX (seconds, no re-typesetting)")
+    rs.add_argument("--docx", type=Path, required=True)
+    rs.add_argument("--profile", type=Path, required=True)
+    rs.add_argument("--out", type=Path, required=True)
+    rs.add_argument("--pdf", action="store_true", help="also convert to PDF")
+    rs.add_argument("--pdf-out", type=Path)
+    rs.add_argument("--html", type=Path, help="also write HTML (CSS from the same profile)")
+    rs.set_defaults(func=cmd_restyle)
+    ht = sub.add_parser("html", help="HTML from a finished DOCX; CSS generated from the profile")
+    ht.add_argument("--docx", type=Path, required=True)
+    ht.add_argument("--profile", type=Path, required=True)
+    ht.add_argument("--out", type=Path, required=True)
+    ht.add_argument("--title")
+    ht.set_defaults(func=cmd_html)
     m = sub.add_parser("map-pages", help="map source printed pages to output PDF pages")
     m.add_argument("--pdf", type=Path, required=True)
     m.add_argument("--aligned", type=Path, required=True)
     m.add_argument("--metadata", type=Path)
     m.add_argument("--out", type=Path, required=True)
     m.add_argument("--title")
+    m.add_argument("--profile", type=Path, help="same profile as the build (needed for heading contents)")
     m.set_defaults(func=cmd_map_pages)
 
     c = sub.add_parser("check", help="check an aligned package and optional PDF")
@@ -1780,6 +1927,7 @@ def build_parser() -> argparse.ArgumentParser:
     q.add_argument("--metadata", type=Path)
     q.add_argument("--out", type=Path)
     q.add_argument("--title")
+    q.add_argument("--profile", type=Path, help="build profile (unwrap_lines makes hand-made breaks harmless)")
     q.set_defaults(func=cmd_qa)
 
     n = sub.add_parser("normalize", help="apply deterministic block repairs to aligned JSON")
@@ -1845,6 +1993,8 @@ def build_parser() -> argparse.ArgumentParser:
     g.add_argument("--key-report", type=Path, required=True)
     g.add_argument("--style-report", type=Path, action="append",
                    help="taxostyle JSON report (compare/audit); repeatable; not ok blocks delivery")
+    g.add_argument("--key-model", type=Path, help="key_model.json; ok=false blocks delivery")
+    g.add_argument("--keyrender", type=Path, help="keyrender --report JSON; any finding blocks; missing file blocks")
     g.add_argument("--out", type=Path)
     g.set_defaults(func=cmd_gate)
     from . import alignmd, keymodel, pdffigures
diff --git a/booklayout/keymodel.py b/booklayout/keymodel.py
index efcdf58..09ec964 100755
--- a/booklayout/keymodel.py
+++ b/booklayout/keymodel.py
@@ -339,9 +339,40 @@ def add_parser(sub: Any) -> None:
     k.add_argument("--source", type=Path, required=True, help="source markdown with <!-- PDF p.N --> markers")
     k.add_argument("--translation", type=Path, help="translated markdown with the same markers")
     k.add_argument("--out", type=Path, help="write JSON report (keys, validation, alignment, blocks)")
+    k.add_argument("--expect-keys", action="store_true",
+                   help="source is declared to contain keys; zero recognised keys fails (auto if a key heading is present)")
+    k.add_argument("--entries", help="comma-separated expected entry numbers, e.g. 1,5")
     k.set_defaults(func=cmd_key_model)
 
 
+def _graph_report(args: Any, report: dict[str, Any]) -> int:
+    """Add report["graph"] from booklayout.keygraph; return the number of error-severity findings."""
+    from . import keygraph
+
+    src_md = args.source.read_text(encoding="utf-8")
+    entries = [e.strip() for e in (getattr(args, "entries", None) or "").split(",") if e.strip()] or None
+    expect = bool(getattr(args, "expect_keys", False)) or any(
+        keygraph.HEADING_RE.match(ln) for ln in src_md.splitlines())
+    sk = keygraph.parse_text(src_md)
+    graph: dict[str, Any] = {"expect_keys": expect, "source_keys": len(sk), "source": [], "translation": [],
+                             "alignment": [], "gate": keygraph.gate(sk, expect)}
+    for i, k in enumerate(sk, 1):
+        graph["source"] += [{**f, "key": i} for f in keygraph.check(k, entries)]
+    if args.translation:
+        tk = keygraph.parse_text(args.translation.read_text(encoding="utf-8"))
+        graph["translation_keys"] = len(tk)
+        for i, k in enumerate(tk, 1):
+            graph["translation"] += [{**f, "key": i} for f in keygraph.check(k, entries)]
+        graph["alignment"] = keygraph.align(sk, tk)
+        if expect and not tk:
+            graph["gate"] += [f for f in keygraph.gate(tk, True)]
+    items = graph["source"] + graph["translation"] + graph["alignment"] + graph["gate"]
+    graph["errors"] = sum(1 for f in items if f.get("severity") == "error")
+    graph["warnings"] = sum(1 for f in items if f.get("severity") == "warn")
+    report["graph"] = graph
+    return int(graph["errors"])
+
+
 def cmd_key_model(args: Any) -> int:
     src = parse_key_text(args.source.read_text(encoding="utf-8"))
     report: dict[str, Any] = {"source_keys": [k.asdict() for k in src],
@@ -353,9 +384,12 @@ def cmd_key_model(args: Any) -> int:
         findings = align_keys(src, tgt)
         report["translation_keys"] = [k.asdict() for k in tgt]
         report["alignment"] = findings
-    bad = sum(len(v) for v in report["source_problems"].values()) + len(findings)
+    graph_bad = _graph_report(args, report)
+    bad = sum(len(v) for v in report["source_problems"].values()) + len(findings) + graph_bad
     report["ok"] = bad == 0
     if args.out:
         args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
-    print(f"keys={len(src)} branches={sum(len(k.branches) for k in src)} problems={bad}")
+    g = report["graph"]
+    print(f"keys={len(src)} branches={sum(len(k.branches) for k in src)} problems={bad} "
+          f"graph_keys={g['source_keys']} graph_errors={g['errors']} graph_warn={g['warnings']}")
     return 0 if bad == 0 else 1
diff --git a/scripts/publish_book.py b/scripts/publish_book.py
index cc8f732..0b47df5 100755
--- a/scripts/publish_book.py
+++ b/scripts/publish_book.py
@@ -119,7 +119,9 @@ def plan(args: argparse.Namespace) -> list[dict[str, Any]]:
         add("gate", None, [], "no PDF：没有 key-report，闸口不运行；产物只是草稿，不得交付")
     else:
         add("gate", _bl("gate", "--qa", str(w / "qa.json"), "--check", str(w / "check.json"),
-                        "--key-report", str(w / "key_report.json"), "--out", str(w / "gate.json")),
+                        "--key-report", str(w / "key_report.json"),
+                        "--key-model", str(w / "key_model.json"), "--keyrender", str(w / "keyrender.json"),
+                        "--out", str(w / "gate.json")),
             [w / "gate.json"])
     for s in out:
         s["extra"] = []
@@ -128,6 +130,8 @@ def plan(args: argparse.Namespace) -> list[dict[str, Any]]:
             s["extra"].append(ck)
             if has_pdf:
                 s["extra"].append(_bl("key-report", "--pdf", str(pdf), "--out", str(w / "key_report.json")))
+                s["extra"].append([sys.executable, "-m", "booklayout.keyrender", str(pdf),
+                                   "--report", str(w / "keyrender.json")])
     return out
 
 
     1	"""key-model graph wiring and gate inputs (--key-model, --keyrender)."""
     2	from __future__ import annotations
     3	
     4	import json
     5	import subprocess
     6	import sys
     7	from pathlib import Path
     8	
     9	ROOT = Path(__file__).resolve().parents[1]
    10	
    11	GOOD = """<!-- PDF p.1 -->
    12	Key to species
    13	
    14	1. Body long ........ 2
    15	1'. Body short ........ Aus bus
    16	2. Eyes present ........ Aus cus
    17	2'. Eyes absent ........ Aus dus
    18	"""
    19	
    20	
    21	def bl(*a: str) -> subprocess.CompletedProcess[str]:
    22	    return subprocess.run([sys.executable, "-m", "booklayout", *a], cwd=ROOT, capture_output=True, text=True)
    23	
    24	
    25	def j(p: Path, obj: object) -> Path:
    26	    p.write_text(json.dumps(obj), encoding="utf-8")
    27	    return p
    28	
    29	
    30	def test_zero_keys_with_heading_fails(tmp_path: Path) -> None:
    31	    s = tmp_path / "s.md"
    32	    s.write_text("<!-- PDF p.1 -->\nKey to species\n\nsome prose only here.\n", encoding="utf-8")
    33	    out = tmp_path / "o.json"
    34	    r = bl("key-model", "--source", str(s), "--out", str(out))
    35	    assert r.returncode == 1, r.stdout + r.stderr
    36	    rep = json.loads(out.read_text(encoding="utf-8"))
    37	    assert rep["ok"] is False
    38	    assert any(f["code"] == "no_keys" for f in rep["graph"]["gate"])
    39	
    40	
    41	def test_expect_keys_flag_without_heading(tmp_path: Path) -> None:
    42	    s = tmp_path / "s.md"
    43	    s.write_text("plain text\n", encoding="utf-8")
    44	    assert bl("key-model", "--source", str(s)).returncode == 0
    45	    assert bl("key-model", "--source", str(s), "--expect-keys").returncode == 1
    46	
    47	
    48	def test_small_key_passes(tmp_path: Path) -> None:
    49	    s = tmp_path / "s.md"
    50	    s.write_text(GOOD, encoding="utf-8")
    51	    out = tmp_path / "o.json"
    52	    r = bl("key-model", "--source", str(s), "--out", str(out))
    53	    rep = json.loads(out.read_text(encoding="utf-8"))
    54	    assert r.returncode == 0, r.stdout + rep["graph"].__repr__()
    55	    assert rep["graph"]["source_keys"] == 1 and rep["graph"]["errors"] == 0
    56	
    57	
    58	def _base(tmp_path: Path) -> list[str]:
    59	    return ["gate", "--qa", str(j(tmp_path / "qa.json", {"ok": True})),
    60	            "--check", str(j(tmp_path / "ck.json", {"ok": True})),
    61	            "--key-report", str(j(tmp_path / "kr0.json", {"breaks": [], "defects": []}))]
    62	
    63	
    64	def test_gate_legacy_call_ok(tmp_path: Path) -> None:
    65	    assert bl(*_base(tmp_path)).returncode == 0
    66	
    67	
    68	def test_gate_key_model_not_ok(tmp_path: Path) -> None:
    69	    ok = j(tmp_path / "km_ok.json", {"ok": True})
    70	    bad = j(tmp_path / "km_bad.json", {"ok": False, "graph": {"errors": 2}})
    71	    assert bl(*_base(tmp_path), "--key-model", str(ok)).returncode == 0
    72	    assert bl(*_base(tmp_path), "--key-model", str(bad)).returncode == 1
    73	
    74	
    75	def test_gate_keyrender(tmp_path: Path) -> None:
    76	    clean = j(tmp_path / "r_ok.json", {"rules": {}, "summary": {"KR1": 0}, "findings": []})
    77	    fail = j(tmp_path / "r_bad.json", {"rules": {}, "summary": {"KR3": 1},
    78	                                       "findings": [{"rule": "KR3", "page": 1, "detail": "x", "lead": "1"}]})
    79	    assert bl(*_base(tmp_path), "--keyrender", str(clean)).returncode == 0
    80	    assert bl(*_base(tmp_path), "--keyrender", str(fail)).returncode == 1
    81	    assert bl(*_base(tmp_path), "--keyrender", str(tmp_path / "missing.json")).returncode == 1

exec
/bin/bash -lc "nl -ba booklayout/keygraph.py | sed -n '28,340p;380,681p'" in /mnt/p/翻译-译作/Taxonomy-Aware-Scientific-Book-Translation
 succeeded in 0ms:
    28	DASHES = "—–\\-•·▪●*"  # regex character-class form
    29	PRIMES = "'’′´"
    30	HEADING_RE = re.compile(
    31	    r"^\W*(?:[^\W\d]+\s+){0,5}?(?:Keys?|Claves?|Clavis|Cl[eé]fs?|Cl[eé]s?|Bestimmungs\w*|Schl[uü]ssel|"
    32	    r"[Тт]аблица|Ключ\w*|Определител\w*)(?!\w)|.{0,12}?(?:検索|检索|檢索)")
    33	CONT_RE = re.compile(r"continued|cont\.|suite\b|Fortsetzung|continuaci|продолжение|続き|续|續", re.I)
    34	RUNNING_HEAD = re.compile(
    35	    r"^\s*(?:\d{1,4}\s+[^\W\d_a-z][^\W\d_a-z ,.\-]{2,}(?: [^\W\d_a-z ,.\-]+)*|"
    36	    r"[^\W\d_a-z][^\W\d_a-z ,.\-]{2,}(?: [^\W\d_a-z ,.\-]+)*\s+\d{1,4})\s*$")
    37	PAGE_ONLY = re.compile(r"^\s*(?:\d{1,4}|[ivxlc]+)\s*$", re.I)
    38	JUMP_ONLY = re.compile(r"^\d{1,3}['’′]?(?:\s*[-–]\s*\d{1,3}['’′]?)?$")
    39	
    40	_PAGE_WORDS = r"(?:pp?\.|S\.|págs?\.|pags?\.|pág\b|pag\b|páginas?|paginas?|seite|стр\.|с\.|pages?)"
    41	PAGE_RES = [
    42	    re.compile(r"(?<![^\W\d_])\(?\s*" + _PAGE_WORDS + r"\s*(?P<p>\d{1,4})(?:\s*[-–]\s*\d{1,4})?\s*\)?", re.I),
    43	    re.compile(r"\(?\s*第\s*(?P<p>\d{1,4})\s*[页頁]\s*\)?"),
    44	    re.compile(r"\(?\s*(?P<p>\d{1,4})\s*(?:[页頁]|ページ)\s*\)?"),
    45	]
    46	_JUMP_PRE = r"(?:(?:→|->|⇒|see|go to|goto|vide|siehe|voir|ir a|vaya a|转|見|见)\s*)?"
    47	JUMP_RE = re.compile(
    48	    r"^" + _JUMP_PRE + r"(?P<n>\d{1,3})['’′]?(?:\s*(?:[-–—]|to|bis)\s*\d{1,3}['’′]?)?\s*(?:へ)?$", re.I)
    49	TRAIL_ARROW = re.compile(
    50	    r"\s(?P<t>(?:→|->|⇒|see|go to|goto|转|見|见)\s*\d{1,3}['’′]?)\s*$|(?P<j>\d{1,3})へ\s*$", re.I)
    51	TRAIL_TARGET = re.compile(r"[\s(](?P<t>\d{1,3}['’′]?(?:\s*[-–]\s*\d{1,3}['’′]?)?)\s*$")
    52	TRAIL_PAGE = re.compile(
    53	    r"(?<![^\W\d_])(?P<t>\(?\s*(?:" + _PAGE_WORDS + r"\s*\d{1,4}(?:\s*[-–]\s*\d{1,4})?|第\s*\d{1,4}\s*[页頁]|"
    54	    r"\d{1,4}\s*(?:[页頁]|ページ))\s*\)?)\s*$", re.I)
    55	GAP_TARGET = re.compile(r"(?:\t|\s{3,})(?P<t>\S.{0,80})$")
    56	
    57	_LTAIL = (r"(?:\s+(?:(?:subsp|ssp|var|subvar|fo|cf|aff|sp|spp|nov)\.|"
    58	          r"(?!(?:and|or|und|oder|et|ou|with|the|via)\b)[a-zà-ÿ][a-zà-ÿ\-]{2,}))*")
    59	LATIN_RE = re.compile(r"[A-Z]\.\s*[a-z][a-z\-]{2,}" + _LTAIL + r"|[A-Z][a-zà-ÿ]{2,}" + _LTAIL)
    60	
    61	_LET = "[A-Za-zа-яА-ЯёЁ]"
    62	_LEADTOK = re.compile(
    63	    r"^\s*(?P<tok>[" + DASHES + r"]|\d{1,3}(?:" + _LET + r"(?!" + _LET + r"))?(?:\(\d{1,3}\))?[" + PRIMES +
    64	    r"]*(?:\(\d{1,3}\))?[.)、:]?|[IVX]{1,4}[" + PRIMES + r"]?[.)])(?=\s|$|(?<=[.)、:])[^\x00-\x7f])")
    65	_NUM = re.compile(
    66	    r"(?P<n>\d{1,3})(?P<l>" + _LET + r")?(?:\((?P<b1>\d{1,3})\))?(?P<p>[" + PRIMES +
    67	    r"]*)(?:\((?P<b2>\d{1,3})\))?[.)、:]?")
    68	_ROMAN = re.compile(r"(?P<r>[IVX]{1,4})(?P<p>[" + PRIMES + r"]?)[.)]")
    69	_REP_LABEL = re.compile(r"^(?P<l>[A-Za-z])(?P=l)*[.)](?=\s)")
    70	FIG_WORDS = r"(?:図|图|圖|Figs?\.?|рис\.?|Abb\.?|Taf\.?|Pls?\.?|Plates?|Tab\.?)"
    71	_FIGNUM = r"\d+[A-Za-z]?(?:\s*[-–、,&]\s*\d+[A-Za-z]?)*"
    72	FIG_PRE = re.compile(r"^\(?\s*" + FIG_WORDS + r"\s*" + _FIGNUM + r"\s*\)?[\s,:;]*", re.I)
    73	FIG_SUF = re.compile(r"[\s,;]*\(?\s*" + FIG_WORDS + r"\s*" + _FIGNUM + r"\s*\)?$", re.I)
    74	FIG_TAIL = re.compile(FIG_WORDS + r"\s*$", re.I)
    75	PART_RE = re.compile(r"\s*\((?:part|pars|partim|p\.\s?p\.|in part|部分|一部)\)", re.I)
    76	RANK_WORDS = {"Genus", "Subgenus", "Family", "Subfamily", "Superfamily", "Tribe", "Order", "Suborder", "Class",
    77	              "Phylum", "Section", "Series", "Род", "Подрод", "Семейство", "Подсемейство", "Отряд"}
    78	RANK_MARKS = {"subsp.", "ssp.", "var.", "subvar.", "f.", "fo.", "forma", "subf.", "sect.", "ser.", "cv."}
    79	QUAL_MARKS = {"cf.", "aff.", "sp.", "spp.", "nov.", "n.", "gen.", "indet.", "inc."}
    80	AUTH_PARTICLES = {"ex", "et", "in", "and", "und", "y", "e", "&", "de", "van", "von", "der", "den", "du", "la", "le"}
    81	SERIAL_TAXON = re.compile(
    82	    r"(?:^|(?<=[\s—–-]))(?P<t>(?:\d{1,3}|[IVXl]{1,4})[.)]\s*(?:(?:Genus|Subgenus|Family|Subfamily|Род|Семейство|Подсемейство)\s+)"
    83	    r"\*?[A-ZА-Я][^\d]{2,100})$")
    84	ABBR_TAIL = re.compile(r"(?<=\s)(?P<t>[A-Z]\.\s*[a-z][a-z\-]{2,}(?:\s+[a-z][a-z\-]{2,})?)\s*$")
    85	_BULLET = re.compile(r"^[-*•·▪●–—]\s+")
    86	
    87	
    88	@dataclass
    89	class GBranch:
    90	    lead: str
    91	    couplet: str = ""
    92	    alt: str = ""
    93	    raw_lead: str = ""
    94	    text: str = ""
    95	    kind: str = "none"
    96	    target: str = ""
    97	    jump: str | None = None
    98	    page: int | None = None
    99	    backref: str | None = None
   100	    src_page: int = 0
   101	    hint: str = ""
   102	    bare: bool = False
   103	
   104	    def asdict(self) -> dict[str, Any]:
   105	        return asdict(self)
   106	
   107	
   108	@dataclass
   109	class GKey:
   110	    heading: str = ""
   111	    branches: list[GBranch] = field(default_factory=list)
   112	    entries: list[str] = field(default_factory=list)
   113	
   114	    def asdict(self) -> dict[str, Any]:
   115	        return {"heading": self.heading, "entries": self.entries, "branches": [b.asdict() for b in self.branches]}
   116	
   117	
   118	class Target(NamedTuple):
   119	    kind: str  # jump | page | taxon | none
   120	    jump: str | None
   121	    page: int | None
   122	    taxon: str
   123	
   124	
   125	def _roman(s: str) -> int | None:
   126	    vals = {"I": 1, "V": 5, "X": 10}
   127	    tot = 0
   128	    for i, ch in enumerate(s):
   129	        v = vals[ch]
   130	        tot += -v if i + 1 < len(s) and vals[s[i + 1]] > v else v
   131	    return tot if 0 < tot < 40 else None
   132	
   133	
   134	def _is_dash(tok: str) -> bool:
   135	    return len(tok) == 1 and tok in DASH_CHARS
   136	
   137	
   138	def _alt_letter(ch: str) -> str:
   139	    c = ch.lower()
   140	    cyr = "абвгде"
   141	    return "abcdef"[cyr.index(c)] if c in cyr else c
   142	
   143	
   144	def norm_lead(raw: str, prev_num: str | None) -> tuple[str, str, str | None] | None:
   145	    """Normalise a lead token. Returns (couplet, alt_hint, backref) or None.
   146	
   147	    alt_hint: "" plain number, a letter (explicit letter or prime count),
   148	    "+" dash/bullet alternate of prev_num.
   149	    """
   150	    s = unicodedata.normalize("NFKC", raw).strip()
   151	    if not s:
   152	        return None
   153	    if _is_dash(s):
   154	        return (prev_num, "+", None) if prev_num else None
   155	    m = _NUM.fullmatch(s)
   156	    if m:
   157	        hint = ""
   158	        dg = m.group("n")
   159	        if prev_num and not m.group("p") and (
   160	                (m.group("l") in ("l", "I") and str(int(dg)) == prev_num)
   161	                or (not m.group("l") and len(dg) == 2 and dg[0] == dg[1] == prev_num)):
   162	            return prev_num, "b", None  # OCR read a prime as l / I / a second digit
   163	        if m.group("l"):
   164	            hint = _alt_letter(m.group("l"))
   165	        elif m.group("p"):
   166	            hint = chr(min(97 + len(m.group("p")), 122))
   167	        bk = m.group("b1") or m.group("b2")
   168	        return str(int(m.group("n"))), hint, str(int(bk)) if bk else None
   169	    m = _ROMAN.fullmatch(s)
   170	    if m:
   171	        v = _roman(m.group("r"))
   172	        if v is None:
   173	            return None
   174	        return str(v), (chr(min(97 + len(m.group("p")), 122)) if m.group("p") else ""), None
   175	    return None
   176	
   177	
   178	_KEEP_DOT = re.compile(r"(?:(?<![A-Za-z])(?:sp|spp|cf|aff|ssp|subsp|var|nov|gen|n)|(?<![A-Za-z])[A-Z])\.$")
   179	_NAME_OPEN = re.compile(r"(?:^|\s)(?:[A-Z]\.|[A-Z][a-zà-ÿ]{2,}\s+[a-zà-ÿ]{3,}(?:\s+[a-zà-ÿ]{3,})?)$")
   180	_EPI = re.compile(r"[a-zà-ÿ][a-zà-ÿ\-]{2,}")
   181	
   182	
   183	def _clean_taxon(s: str) -> str:
   184	    s = s.strip(" \t,;:—–-·…・")
   185	    if s.endswith(".") and not _KEEP_DOT.search(s):
   186	        s = s.rstrip(". ")
   187	    return s
   188	
   189	
   190	def canon_taxon(s: str) -> str:
   191	    """Canonical taxon text: names, ranks, cf./aff./sp. kept; authorities, years and (part) dropped."""
   192	    s = PART_RE.sub("", s).strip()
   193	    toks = s.split()
   194	    k = 1 if len(toks) > 1 and toks[0] in RANK_WORDS else 0
   195	    if k >= len(toks) or not re.fullmatch(r"[A-ZА-Я][a-zà-ÿа-я\-]*\d{0,2}\.?,?", toks[k]):
   196	        return s
   197	    out = [re.sub(r"(?<=[^\W\d])\d{1,2}(?=\.?,?$)", "", toks[k]).rstrip(",")]  # drop glued footnote digit
   198	    rest = toks[k + 1:]
   199	    if len(rest) > 1 and re.fullmatch(r"\([A-Z][a-zà-ÿ]+\)", rest[0]) and _EPI.fullmatch(rest[1]):
   200	        out.append(rest[0])
   201	        rest = rest[1:]
   202	    auth = False
   203	    for i, t in enumerate(rest):
   204	        tl = t.rstrip(",;")
   205	        nxt_epi = i + 1 < len(rest) and bool(_EPI.fullmatch(rest[i + 1].rstrip(",;")))
   206	        if tl.lower() in RANK_MARKS and nxt_epi:
   207	            auth = False
   208	            out.append(tl)
   209	        elif auth:
   210	            continue
   211	        elif tl in QUAL_MARKS:
   212	            out.append(tl)
   213	        elif tl in AUTH_PARTICLES:
   214	            auth = True
   215	        elif _EPI.fullmatch(tl) or re.fullmatch(r"\d{1,3}", tl):
   216	            out.append(tl)
   217	        else:
   218	            auth = True
   219	    return " ".join(out)
   220	
   221	
   222	def parse_target(s: str) -> Target:
   223	    """Classify a branch target: jump number, page reference, taxon (+page) or none."""
   224	    t = unicodedata.normalize("NFKC", s or "").strip()
   225	    t = re.sub(r"^[.…·・⋯\s]+", "", t.replace("*", "")).strip()
   226	    t = re.sub(r"^\d{1,3}\s*[.)]\s+(?=[^\W\d_])", "", t)
   227	    t = re.sub(r"^[IVXl]{1,4}[.)]\s+(?=(?:Genus|Subgenus|Family|Род|Семейство)\s)", "", t)  # OCR'd serial
   228	    page: int | None = None
   229	    for rx in PAGE_RES:
   230	        last = None
   231	        for last in rx.finditer(t):
   232	            pass
   233	        if last is not None:
   234	            page = int(last.group("p"))
   235	            t = (t[:last.start()] + " " + t[last.end():]).strip()
   236	            break
   237	    rem = _clean_taxon(t)
   238	    if not JUMP_RE.match(rem):
   239	        rem = _clean_taxon(FIG_SUF.sub("", FIG_PRE.sub("", rem)))
   240	    rem = _clean_taxon(PART_RE.sub("", rem))
   241	    if not rem:
   242	        return Target("page" if page is not None else "none", None, page, "")
   243	    jm = JUMP_RE.match(rem)
   244	    if jm:
   245	        return Target("jump", str(int(jm.group("n"))), page, "")
   246	    rm = re.fullmatch(r"([IVX]{1,4})[" + PRIMES + r"]?", rem)
   247	    if rm and _roman(rm.group(1)):
   248	        return Target("jump", str(_roman(rm.group(1))), page, "")
   249	    return Target("taxon", None, page, canon_taxon(rem))
   250	
   251	
   252	def _split(text: str) -> tuple[str, str, bool]:
   253	    """(text, target, bare); bare = target is only a trailing number with no leader/gap/arrow."""
   254	    m = None
   255	    for m in LEADER.finditer(text):
   256	        pass
   257	    if m is not None:
   258	        return text[:m.start()].strip(), text[m.end():].strip(), False
   259	    a = TRAIL_ARROW.search(text)
   260	    if a:
   261	        return text[:a.start()].strip(), (a.group("t") or a.group("j")).strip(), False
   262	    g = GAP_TARGET.search(text)
   263	    if g and (JUMP_RE.match(g.group("t").strip()) or LATIN_RE.match(g.group("t").strip())
   264	              or any(r.fullmatch(g.group("t").strip()) for r in PAGE_RES)):
   265	        return text[:g.start()].strip(), g.group("t").strip(), False
   266	    p = TRAIL_PAGE.search(text)
   267	    if p:
   268	        return text[:p.start()].strip(), p.group("t").strip(), False
   269	    st = SERIAL_TAXON.search(text)
   270	    if st:
   271	        return text[:st.start()].strip(" —–-"), st.group("t").strip(), False
   272	    ab = ABBR_TAIL.search(text)
   273	    if ab:
   274	        return text[:ab.start()].strip(), ab.group("t").strip(), False
   275	    t = TRAIL_TARGET.search(text)
   276	    if t and not FIG_TAIL.search(text[:t.start()]):
   277	        return text[:t.start()].strip(), t.group("t").strip(), True
   278	    return text.strip(), "", False
   279	
   280	
   281	def split_target(text: str) -> tuple[str, str]:
   282	    """Split branch text from its target (dot leader, arrow, wide gap, page, abbreviated name, trailing number)."""
   283	    left, target, _ = _split(text)
   284	    return left, target
   285	
   286	
   287	def _has_target(text: str) -> bool:
   288	    return bool(split_target(text)[1])
   289	
   290	
   291	def _mk(info: tuple[str, str, str | None], raw_lead: str, text: str, target: str, page: int,
   292	        bare: bool = False) -> GBranch:
   293	    couplet, hint, back = info
   294	    tg = parse_target(target)
   295	    return GBranch(lead=couplet + (hint if hint != "+" else ""), couplet=couplet, alt="", raw_lead=raw_lead,
   296	                   text=text.strip(), kind=tg.kind, target=tg.taxon if tg.kind == "taxon" else target.strip(), jump=tg.jump, page=tg.page,
   297	                   backref=back, src_page=page, hint=hint, bare=bare)
   298	
   299	
   300	class _Open:
   301	    def __init__(self, info: tuple[str, str, str | None], raw_lead: str, text: str, page: int) -> None:
   302	        self.info, self.raw_lead, self.text, self.page = info, raw_lead, text, page
   303	
   304	    def add(self, more: str) -> None:
   305	        a = self.text
   306	        self.text = a[:-1] + more if a.endswith("-") and more[:1].islower() else f"{a} {more}".strip()
   307	
   308	    def complete(self) -> bool:
   309	        return _has_target(self.text)
   310	
   311	    def done(self) -> GBranch:
   312	        left, target, bare = _split(self.text)
   313	        return _mk(self.info, self.raw_lead, left, target, self.page, bare)
   314	
   315	
   316	def _match_lead(line: str, prev_num: str | None) -> tuple[tuple[str, str, str | None], str, str, bool] | None:
   317	    """Return (info, raw_lead, rest, weak) for a line starting with a lead token."""
   318	    m = _LEADTOK.match(line)
   319	    if not m:
   320	        return None
   321	    tok = m.group("tok")
   322	    rest = line[m.end():].strip()
   323	    if _is_dash(tok):
   324	        inner = _LEADTOK.match(rest)
   325	        if inner and not _is_dash(inner.group("tok")):
   326	            r2 = _match_lead(rest, prev_num)
   327	            if r2 and not r2[3]:
   328	                return r2
   329	        info = norm_lead(tok, prev_num)
   330	        return (info, tok, rest, False) if info else None
   331	    info = norm_lead(tok, prev_num)
   332	    if info is None:
   333	        return None
   334	    weak = bool(re.fullmatch(r"\d{1,3}", tok))
   335	    return info, tok, rest, weak
   336	
   337	
   338	def _assign_alts(key: GKey) -> None:
   339	    groups: OrderedDict[str, list[GBranch]] = OrderedDict()
   340	    for b in key.branches:
   380	
   381	def _complete_couplets(key: GKey) -> bool:
   382	    cnt: dict[str, int] = {}
   383	    for b in key.branches:
   384	        cnt[b.couplet] = cnt.get(b.couplet, 0) + 1
   385	    return any(n >= 2 for n in cnt.values())
   386	
   387	
   388	def _indent(raw: str) -> int:
   389	    w = 0
   390	    for ch in raw:
   391	        if ch == " ":
   392	            w += 1
   393	        elif ch == "\t":
   394	            w += 4
   395	        else:
   396	            break
   397	    return w
   398	
   399	
   400	def _looks_tree(items: list[tuple[int, str | None]], i: int) -> bool:
   401	    raw = items[i][1]
   402	    if raw is None:
   403	        return False
   404	    if not _REP_LABEL.match(_BULLET.sub("", raw.strip())):
   405	        return False
   406	    for j in range(i + 1, len(items)):
   407	        r = items[j][1]
   408	        if r is None or not r.strip():
   409	            continue
   410	        return bool(_REP_LABEL.match(_BULLET.sub("", r.strip())))
   411	    return False
   412	
   413	
   414	def parse_text(md: str, heading_re: re.Pattern[str] | None = None) -> list[GKey]:
   415	    """Parse page-marked text into keys (numbered, tabular and indented styles)."""
   416	    hre = heading_re or HEADING_RE
   417	    items: list[tuple[int, str | None]] = []
   418	    page = 0
   419	    for r in md.splitlines():
   420	        pm = PAGE_MARK.search(r)
   421	        if pm:
   422	            page = int(pm.group(1))
   423	            items.append((page, None))
   424	            rest = r[:pm.start()] + r[pm.end():]
   425	            if rest.strip():
   426	                items.append((page, unicodedata.normalize("NFKC", rest)))
   427	        else:
   428	            items.append((page, unicodedata.normalize("NFKC", r)))
   429	    n = len(items)
   430	
   431	    def next_sig(i: int) -> int | None:
   432	        for j in range(i + 1, n):
   433	            r = items[j][1]
   434	            if r is None or r.strip():
   435	                return j
   436	        return None
   437	
   438	    def next_page_leads(i: int) -> bool:
   439	        nj = next_sig(i)
   440	        if nj is None or items[nj][1] is not None:
   441	            return False
   442	        k = next_sig(nj)
   443	        nxt = items[k][1] if k is not None else None
   444	        return nxt is not None and _match_lead(nxt.strip(), None) is not None
   445	
   446	    def at_page_end(i: int) -> bool:
   447	        nj = next_sig(i)
   448	        return nj is None or items[nj][1] is None
   449	
   450	    keys: list[GKey] = []
   451	    key: GKey | None = None
   452	    mode = ""
   453	    cur: _Open | None = None
   454	    pending = ""
   455	    last_num = ""
   456	    fresh = False
   457	    hdr_cols: dict[str, int] = {}
   458	
   459	    def flush() -> None:
   460	        nonlocal cur
   461	        if cur is not None and key is not None:
   462	            key.branches.append(cur.done())
   463	        cur = None
   464	
   465	    def close() -> None:
   466	        nonlocal key, mode, last_num
   467	        flush()
   468	        if key is not None:
   469	            _pair_backrefs(key)
   470	            _drop_bare(key)
   471	            _assign_alts(key)
   472	        key = None
   473	        mode = ""
   474	        last_num = ""
   475	
   476	    def open_key(m: str) -> GKey:
   477	        nonlocal key, mode, pending, last_num
   478	        key = GKey(heading=pending)
   479	        keys.append(key)
   480	        pending = ""
   481	        mode = m
   482	        last_num = ""
   483	        return key
   484	
   485	    def tree_from(i: int) -> int | None:
   486	        """Consume an indented / letter-hierarchy key starting at item i; return next index or None."""
   487	        stack: list[int] = []
   488	        rows: list[dict[str, Any]] = []
   489	        j = i
   490	        while j < n:
   491	            pg, raw = items[j]
   492	            if raw is None or not raw.strip():
   493	                j += 1
   494	                continue
   495	            line = raw.strip()
   496	            if PAGE_ONLY.match(line):
   497	                if rows and not rows[-1]["target"] and JUMP_ONLY.match(line) and not at_page_end(j):
   498	                    rows[-1]["target"] = line
   499	                j += 1
   500	                continue
   501	            if hre.match(line) and not _LEADTOK.match(line) and len(line) <= 120:
   502	                if CONT_RE.search(line):
   503	                    j += 1
   504	                    continue
   505	                break
   506	            ind = _indent(raw)
   507	            bm = _BULLET.match(line)
   508	            content = line[bm.end():] if bm else line
   509	            lab = _REP_LABEL.match(content)
   510	            raw_lead = ""
   511	            letter = ""
   512	            if lab:
   513	                letter = lab.group("l").lower()
   514	                raw_lead = lab.group(0).strip()
   515	                content = content[lab.end():].strip()
   516	            text, target = split_target(content)
   517	            if rows and not rows[-1]["target"] and not lab and JUMP_ONLY.match(content):
   518	                rows[-1]["target"] = content
   519	                j += 1
   520	                continue
   521	            nj = next_sig(j)
   522	            nxt = items[nj][1] if nj is not None else None
   523	            deeper = nxt is not None and _indent(nxt) > ind
   524	            if not (target or deeper or lab):
   525	                break
   526	            while stack and stack[-1] > ind:
   527	                stack.pop()
   528	            if not stack or stack[-1] < ind:
   529	                stack.append(ind)
   530	            rows.append({"level": len(stack), "text": text, "target": target, "raw": raw_lead, "page": pg,
   531	                         "letter": letter})
   532	            j += 1
   533	        if not rows:
   534	            return None
   535	        k = open_key("tree")
   536	        st: list[int] = []
   537	        groups: dict[tuple[int, str], str] = {}
   538	        for idx, r in enumerate(rows):
   539	            while st and rows[st[-1]]["level"] >= r["level"]:
   540	                st.pop()
   541	            parent = st[-1] if st else -1
   542	            r["parent"] = parent
   543	            gk = (parent, r["letter"])
   544	            if gk not in groups:
   545	                groups[gk] = str(len(groups) + 1)
   546	                if parent >= 0:
   547	                    pb = rows[parent]["branch"]
   548	                    if pb.kind == "none":
   549	                        pb.kind, pb.target, pb.jump = "jump", groups[gk], groups[gk]
   550	            st.append(idx)
   551	            b = _mk((groups[gk], "", None), r["raw"], r["text"], r["target"], r["page"])
   552	            r["branch"] = b
   553	            k.branches.append(b)
   554	        for r in rows:  # a lone-letter target ("B") jumps to that letter's couplet
   555	            b = r["branch"]
   556	            if b.kind == "taxon" and re.fullmatch(r"[A-Za-z]", b.target):
   557	                lt = b.target.lower()
   558	                dest = groups.get((r["parent"], lt)) or next((v for (p, lg), v in groups.items() if lg == lt), None)
   559	                if dest:
   560	                    b.kind, b.jump, b.target = "jump", dest, dest
   561	        close()
   562	        return j
   563	
   564	    i = 0
   565	    while i < n:
   566	        pg, raw = items[i]
   567	        if raw is None:
   568	            fresh = True
   569	            i += 1
   570	            continue
   571	        line = raw.strip()
   572	        first_on_page = fresh and bool(line)
   573	        if line:
   574	            fresh = False
   575	        if not line:
   576	            i += 1
   577	            continue
   578	        incomplete = cur is not None and not cur.complete()
   579	        if first_on_page and (RUNNING_HEAD.match(line) or (
   580	                any(ch.isupper() for ch in line) and line == line.upper() and len(line) >= 4
   581	                and not _LEADTOK.match(line) and not hre.match(line) and not LEADER.search(line))):
   582	            i += 1
   583	            continue
   584	        if key is not None and len(line) <= 120 and hre.match(line) and CONT_RE.search(line):
   585	            i += 1
   586	            continue
   587	        if PAGE_ONLY.match(line):
   588	            if cur is not None and incomplete and not first_on_page and JUMP_ONLY.match(line) \
   589	                    and (not at_page_end(i) or next_page_leads(i)):
   590	                cur.add(line)
   591	            i += 1
   592	            continue
   593	        if line.startswith("|"):
   594	            cells = [c.strip() for c in line.strip("|").split("|")]
   595	            if all(re.fullmatch(r":?-{2,}:?", c) or not c for c in cells) and any(cells):
   596	                i += 1
   597	                continue
   598	            lm = _match_lead(cells[0] + " x", last_num or None) if cells and cells[0] else None
   599	            if mode != "table":
   600	                close()
   601	                if lm is None:
   602	                    hdr_cols.clear()
   603	                    for ci, c in enumerate(cells):  # header row: remember taxon / page columns
   604	                        if ci and re.fullmatch(r"(?i)类群|類群|分类群|分類群|taxon|taxa|target|destination|去向", c):
   605	                            hdr_cols["tax"] = ci
   606	                        elif ci and re.fullmatch(r"(?i)页码|頁碼|页|頁|pages?|págs?\.?|seite|стр\.?", c):
   607	                            hdr_cols["page"] = ci
   608	                    i += 1
   609	                    continue
   610	                open_key("table")
   611	            assert key is not None
   612	            if lm is None:
   613	                if key.branches and len(cells) > 1:  # continuation row
   614	                    b = key.branches[-1]
   615	                    b.text = (b.text + " " + " ".join(cells[1:-1] if len(cells) > 2 else cells[1:2])).strip()
   616	                    if len(cells) > 2 and cells[-1]:
   617	                        tg = parse_target(cells[-1])
   618	                        b.target, b.kind, b.jump, b.page = (tg.taxon if tg.kind == "taxon" else cells[-1]), \
   619	                            tg.kind, tg.jump, tg.page
   620	                i += 1
   621	                continue
   622	            info, rl, _, _ = lm
   623	            tc, pc = hdr_cols.get("tax", -1), hdr_cols.get("page", -1)
   624	            if 0 < tc < len(cells):
   625	                target = cells[tc] + (" " + cells[pc] if 0 < pc < len(cells) and cells[pc] else "")
   626	                text = " ".join(c for ci, c in enumerate(cells) if ci not in (0, tc, pc) and c)
   627	            elif len(cells) >= 3:
   628	                text, target = " ".join(cells[1:-1]), cells[-1]
   629	            else:
   630	                text, target = split_target(cells[1] if len(cells) > 1 else "")
   631	            key.branches.append(_mk(info, rl, text, target, pg))
   632	            if not _is_dash(rl):
   633	                last_num = info[0]
   634	            i += 1
   635	            continue
   636	        if mode == "table":
   637	            close()
   638	        if len(line) <= 120 and not incomplete and hre.match(line) and not _LEADTOK.match(line):
   639	            close()
   640	            pending = line.lstrip("# ").strip().strip("*").strip()
   641	            hdr_cols.clear()
   642	            i += 1
   643	            continue
   644	        lm = _match_lead(line, last_num or None)
   645	        if lm is not None and mode != "tree":
   646	            info, rl, rest, weak = lm
   647	            ok = True
   648	            if weak:
   649	                exp = int(last_num) if last_num else 0
   650	                want = {b.jump for b in key.branches} if key is not None else set()
   651	                if cur is not None:
   652	                    want.add(parse_target(_split(cur.text)[1]).jump)
   653	                if key is None and not pending:
   654	                    ok = False
   655	                elif info[0] in want and key is not None:
   656	                    ok = True
   657	                elif incomplete and int(info[0]) != exp + 1:
   658	                    ok = False
   659	                elif incomplete and cur is not None and key is not None \
   660	                        and not any(b.couplet == cur.info[0] for b in key.branches):
   661	                    ok = False  # a couplet needs two branches: a lone open branch cannot be followed by a new one
   662	                elif key is not None and int(info[0]) not in (exp, exp + 1):
   663	                    ok = False
   664	            if ok and _ROMAN.fullmatch(rl) and key is None and not pending:
   665	                ok = False
   666	            if ok:
   667	                flush()
   668	                if key is not None and info[0] == "1" and info[1] in ("", "a") and last_num != "1" \
   669	                        and _complete_couplets(key):
   670	                    close()
   671	                if key is None:
   672	                    open_key("num")
   673	                cur = _Open(info, rl, rest, pg)
   674	                if not _is_dash(rl):
   675	                    last_num = info[0]
   676	                i += 1
   677	                continue
   678	        if key is None and (pending or _looks_tree(items, i)):
   679	            j = tree_from(i)
   680	            if j is not None:
   681	                pending = ""

exec
/bin/bash -lc "nl -ba scripts/publish_book.py | sed -n '35,285p'
nl -ba booklayout/keyrender.py | tail -110
nl -ba booklayout/cli.py | sed -n '1744,1810p'
cat test-keys/adv/corpus/{real_marinov_thesis,real_marinov_two_leads,en_backref_one,r2_lost_dots,r2_gap_page}.json" in /mnt/p/翻译-译作/Taxonomy-Aware-Scientific-Book-Translation
 succeeded in 10ms:
    35	import shlex
    36	import subprocess
    37	import sys
    38	import time
    39	from pathlib import Path
    40	from typing import Any
    41	
    42	ROOT = Path(__file__).resolve().parent.parent
    43	STAGES = ["export", "translate", "figures", "align", "keycheck", "build", "qa", "gate"]
    44	SOFT = {"qa"}  # 失败不立刻停：闸口汇总
    45	
    46	
    47	def _sha(p: Path) -> str | None:
    48	    if not p.is_file():
    49	        return None
    50	    h = hashlib.sha256()
    51	    h.update(p.read_bytes())
    52	    return h.hexdigest()
    53	
    54	
    55	def _bl(*a: str) -> list[str]:
    56	    return [sys.executable, "-m", "booklayout", *a]
    57	
    58	
    59	def plan(args: argparse.Namespace) -> list[dict[str, Any]]:
    60	    """返回 [{stage, cmd(list)|None, note, outputs}]，不执行。"""
    61	    w: Path = args.work
    62	    src = args.source_md or w / "src.md"
    63	    tgt = args.translation_md or w / "tgt.md"
    64	    fig, aligned = w / "figures", w / "aligned.json"
    65	    docx, pdf = w / "book.docx", w / "book.pdf"
    66	    meta = ["--metadata", str(args.metadata)] if args.metadata else []
    67	    title = ["--title", args.title] if args.title else []
    68	    has_pdf = not args.no_pdf
    69	    out: list[dict[str, Any]] = []
    70	
    71	    def add(stage: str, cmd: list[str] | None, outputs: list[Path], note: str = "") -> None:
    72	        out.append({"stage": stage, "cmd": cmd, "outputs": outputs, "note": note})
    73	
    74	    if args.source_md:
    75	        add("export", None, [src], "给了 --source-md，跳过导出")
    76	    else:
    77	        if not args.key:
    78	            raise SystemExit("需要 --key（docstore 资料）或 --source-md")
    79	        ex = [sys.executable, "-c", "import sys; from docstore.cli import main; sys.exit(main(sys.argv[1:]))",
    80	              "--by", "publish_book", "export", args.key, "--translate", "--strict", "-o", str(src)]
    81	        if args.pages:
    82	            ex += ["--pages", args.pages]
    83	        add("export", ex, [src])
    84	    if args.translation_md:
    85	        add("translate", None, [tgt], "给了 --translation-md，跳过翻译")
    86	    else:
    87	        tr = [sys.executable, str(ROOT / "scripts" / "auto_translate.py"), "run", str(src), "-o", str(w / "translate"),
    88	              "--sl", args.sl, "--tl", args.tl]
    89	        if args.glossary:
    90	            tr += ["--glossary", str(args.glossary)]
    91	        if args.engine:
    92	            tr += ["--engine", args.engine]
    93	        add("translate", tr, [tgt], "产物 translate/checked.md|revised.md|draft.md 取最后一个存在的复制为 tgt.md")
    94	    if args.pdf:
    95	        fg = _bl("figures", "extract", "--pdf", str(args.pdf), "--out", str(fig), "--dpi", str(args.dpi))
    96	        if args.pages:
    97	            a, _, b = args.pages.partition("-")
    98	            fg += ["--first", a, "--last", b or a]
    99	        add("figures", fg, [fig / "figures_manifest.json", fig / "source_figure_audit.json"])
   100	    else:
   101	        add("figures", None, [fig / "source_figure_audit.json"], "未给 --pdf：不抽图，写空 source_figure_audit.json")
   102	    add("align", _bl("align-md", "--source", str(src), "--translation", str(tgt), "--out", str(aligned),
   103	                     "--report", str(w / "align_report.json")), [aligned])
   104	    add("keycheck", _bl("key-model", "--source", str(src), "--translation", str(tgt),
   105	                        "--out", str(w / "key_model.json")), [w / "key_model.json"])
   106	    build = _bl("build", "--aligned", str(aligned), "--figures", str(fig), "--translation", str(tgt),
   107	                "--out", str(docx), "--report", str(w / "build_report.json"), *meta, *title)
   108	    if has_pdf:
   109	        build += ["--pdf", "--pdf-out", str(pdf)]
   110	    add("build", build, [docx] + ([pdf] if has_pdf else []),
   111	        "两遍排版（map-pages 后 build --map）在 build 阶段内部执行" if has_pdf else "")
   112	    qa = _bl("qa", "--aligned", str(aligned), "--figures", str(fig), "--out", str(w / "qa.json"), *meta, *title)
   113	    ck = _bl("check", "--aligned", str(aligned), "--figures", str(fig), "--out", str(w / "check.json"), *meta, *title)
   114	    if has_pdf:
   115	        qa += ["--pdf", str(pdf)]
   116	        ck += ["--pdf", str(pdf)]
   117	    add("qa", qa, [w / "qa.json"], "qa、check、key-report 依次执行")
   118	    if not has_pdf:
   119	        add("gate", None, [], "no PDF：没有 key-report，闸口不运行；产物只是草稿，不得交付")
   120	    else:
   121	        add("gate", _bl("gate", "--qa", str(w / "qa.json"), "--check", str(w / "check.json"),
   122	                        "--key-report", str(w / "key_report.json"),
   123	                        "--key-model", str(w / "key_model.json"), "--keyrender", str(w / "keyrender.json"),
   124	                        "--out", str(w / "gate.json")),
   125	            [w / "gate.json"])
   126	    for s in out:
   127	        s["extra"] = []
   128	    for s in out:
   129	        if s["stage"] == "qa":
   130	            s["extra"].append(ck)
   131	            if has_pdf:
   132	                s["extra"].append(_bl("key-report", "--pdf", str(pdf), "--out", str(w / "key_report.json")))
   133	                s["extra"].append([sys.executable, "-m", "booklayout.keyrender", str(pdf),
   134	                                   "--report", str(w / "keyrender.json")])
   135	    return out
   136	
   137	
   138	def _versions() -> dict[str, str]:
   139	    v = {"python": platform.python_version()}
   140	    try:
   141	        import booklayout
   142	        v["booklayout"] = getattr(booklayout, "__version__", "?")
   143	    except ImportError:  # pragma: no cover
   144	        pass
   145	    try:
   146	        import fitz
   147	        v["pymupdf"] = fitz.VersionBind
   148	    except ImportError:  # pragma: no cover
   149	        pass
   150	    return v
   151	
   152	
   153	def _run(cmd: list[str]) -> dict[str, Any]:
   154	    t0 = time.time()
   155	    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
   156	    return {"cmd": shlex.join(cmd), "rc": p.returncode, "seconds": round(time.time() - t0, 1),
   157	            "stdout_tail": p.stdout[-400:], "stderr_tail": p.stderr[-400:]}
   158	
   159	
   160	def _post(stage: str, args: argparse.Namespace) -> None:
   161	    w: Path = args.work
   162	    if stage == "translate" and not args.translation_md:
   163	        for name in ("checked.md", "revised.md", "draft.md"):
   164	            f = w / "translate" / name
   165	            if f.exists():
   166	                (w / "tgt.md").write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
   167	                return
   168	    if stage == "figures" and not args.pdf:
   169	        (w / "figures").mkdir(parents=True, exist_ok=True)
   170	        (w / "figures" / "source_figure_audit.json").write_text('{"figures": []}', encoding="utf-8")
   171	
   172	
   173	def _second_pass(args: argparse.Namespace, steps: list[dict[str, Any]]) -> None:
   174	    """build 之后：量页 → 带映射再 build，使目录与索引页码指对页。"""
   175	    w: Path = args.work
   176	    mp = w / "page_map.json"
   177	    meta = ["--metadata", str(args.metadata)] if args.metadata else []
   178	    r = _run(_bl("map-pages", "--pdf", str(w / "book.pdf"), "--aligned", str(w / "aligned.json"),
   179	                 "--out", str(mp), *meta))
   180	    steps.append({"stage": "build", **r, "note": "map-pages"})
   181	    if r["rc"] == 0:
   182	        b = [c for c in plan(args) if c["stage"] == "build"][0]["cmd"]
   183	        steps.append({"stage": "build", **_run([*b, "--map", str(mp)]), "note": "build --map"})
   184	
   185	
   186	def run(args: argparse.Namespace) -> int:
   187	    args.work.mkdir(parents=True, exist_ok=True)
   188	    steps_plan = plan(args)
   189	    only = set(args.only.split(",")) if args.only else set(STAGES)
   190	    skip = set(args.skip.split(",")) if args.skip else set()
   191	    record: dict[str, Any] = {"versions": _versions(), "argv": sys.argv[1:], "steps": [], "failed": None,
   192	                              "inputs_sha256": {k: _sha(Path(p)) for k, p in
   193	                                                (("pdf", args.pdf), ("source_md", args.source_md),
   194	                                                 ("translation_md", args.translation_md),
   195	                                                 ("metadata", args.metadata)) if p}}
   196	    rc = 0
   197	    record["releasable"] = False
   198	    for s in steps_plan:
   199	        if s["stage"] not in only or s["stage"] in skip:
   200	            continue
   201	        cmds = ([s["cmd"]] if s["cmd"] else []) + s["extra"]
   202	        if args.dry:
   203	            print(f"[{s['stage']}] {s['note']}")
   204	            for c in cmds:
   205	                print("   " + shlex.join(c))
   206	            continue
   207	        if not cmds:
   208	            _post(s["stage"], args)
   209	            record["steps"].append({"stage": s["stage"], "skipped": s["note"]})
   210	            continue
   211	        ok = True
   212	        for c in cmds:
   213	            r = _run(c)
   214	            record["steps"].append({"stage": s["stage"], **r})
   215	            if r["rc"] != 0:
   216	                ok = False
   217	        if ok and s["stage"] == "build" and not args.no_pdf:
   218	            _second_pass(args, record["steps"])
   219	            ok = all(x["rc"] == 0 for x in record["steps"] if x["stage"] == "build" and "rc" in x)
   220	        _post(s["stage"], args)
   221	        if not ok and s["stage"] not in SOFT:
   222	            record["failed"] = s["stage"]
   223	            rc = 1
   224	            break
   225	        if not ok and s["stage"] == "gate":
   226	            rc = 1
   227	    if not args.dry:
   228	        last = record["steps"][-1] if record["steps"] else {}
   229	        if last.get("stage") == "gate" and "rc" in last:
   230	            record["releasable"] = last["rc"] == 0 and rc == 0
   231	            rc = 0 if record["releasable"] else 1
   232	        (args.work / "publish_run.json").write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
   233	        print(f"publish_run={args.work / 'publish_run.json'} failed={record['failed']} "
   234	              f"releasable={record['releasable']} rc={rc}")
   235	    return rc
   236	
   237	
   238	def main(argv: list[str] | None = None) -> int:
   239	    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
   240	    sub = ap.add_subparsers(dest="cmd", required=True)
   241	    sub.add_parser("stages")
   242	    r = sub.add_parser("run")
   243	    r.add_argument("--key", help="docstore 资料 key")
   244	    r.add_argument("--pdf", type=Path, help="源 PDF（抽图、量页）")
   245	    r.add_argument("--work", type=Path, required=True)
   246	    r.add_argument("--source-md", type=Path)
   247	    r.add_argument("--translation-md", type=Path)
   248	    r.add_argument("--sl", default="es")
   249	    r.add_argument("--tl", default="en")
   250	    r.add_argument("--glossary", type=Path)
   251	    r.add_argument("--engine")
   252	    r.add_argument("--pages", help="PDF 页范围，如 1-5（小样）")
   253	    r.add_argument("--metadata", type=Path)
   254	    r.add_argument("--title")
   255	    r.add_argument("--dpi", type=int, default=300)
   256	    r.add_argument("--no-pdf", action="store_true", help="只出 DOCX，不转 PDF（无 LibreOffice 时）")
   257	    r.add_argument("--only")
   258	    r.add_argument("--skip")
   259	    r.add_argument("--dry", action="store_true")
   260	    a = ap.parse_args(argv)
   261	    if a.cmd == "stages":
   262	        print("\n".join(STAGES))
   263	        return 0
   264	    return run(a)
   265	
   266	
   267	if __name__ == "__main__":
   268	    sys.exit(main())
   192	            text += c
   193	            ital.append(s.italic)
   194	            boxes.append((x0, x1))
   195	    return text, ital, boxes
   196	
   197	
   198	def check_page_leads(leads: list[Lead], right: float) -> list[dict]:
   199	    from .builder import italicize_key_address  # one rule for builder and check
   200	
   201	    out: list[dict] = []
   202	
   203	    def bad(rule: str, lead: Lead, detail: str) -> None:
   204	        out.append({"rule": rule, "page": lead.page + 1, "lead": (lead.marker + " " + lead.rows[0].text)[:60],
   205	                    "detail": detail})
   206	
   207	    if not leads:
   208	        return out
   209	    col = Counter(round(ld.text_x) for ld in leads).most_common(1)[0][0]
   210	    for ld in leads:
   211	        if abs(ld.text_x - col) > TOL:
   212	            bad("KR1", ld, f"text starts at x={ld.text_x:.1f}, column at x={col}")
   213	        for r in ld.rows[1:]:
   214	            if abs(r.x0 - ld.text_x) > TOL and abs(r.x0 - col) > TOL:
   215	                bad("KR2", ld, f"wrapped line starts at x={r.x0:.1f}, text column x={col}")
   216	        addr = _address(ld)
   217	        last = ld.rows[-1]
   218	        if not addr:
   219	            bad("KR5", ld, "lead has no dots + address" if not last.spans[-1].leader else "dots without address")
   220	            continue
   221	        if abs(last.x1 - right) > TOL:
   222	            bad("KR4", ld, f"address ends at x={last.x1:.1f}, margin x={right:.1f}")
   223	        for a, b in zip(ld.rows, ld.rows[1:]):
   224	            if b.spans[0].leader and not a.spans[-1].leader and right - a.x1 > 3 * 72 / 25.4:
   225	                bad("KR3", ld, f"blank tail of {(right - a.x1) * 25.4 / 72:.1f} mm before the leader line")
   226	            ta, tb = a.text.rstrip(" " + GLUE), b.text.lstrip()
   227	            if ta[-1:].isdigit() and HAN.match(tb[:1]):
   228	                bad("KR6", ld, f"number split from its measure word: '{ta[-6:]} / {tb[:4]}'")
   229	            if re.search(r"(?:^|\s)[A-Z][a-z]*\.?$", ta) and re.match(r"[a-z]", tb) and not b.spans[0].leader:
   230	                bad("KR4", ld, f"address split across lines: '{ta[-12:]} / {tb[:12]}'")
   231	        text, ital, boxes = _plain(addr)
   232	        flat = text.replace(GLUE, " ")
   233	        if re.search(r"[A-Za-z][0-9]", flat):
   234	            bad("KR4", ld, f"address words glued: '{flat.strip()}'")
   235	        if flat.count("（") != flat.count("）") or flat.count("(") != flat.count(")"):
   236	            bad("KR4", ld, f"unpaired brackets in address: '{flat.strip()}'")
   237	        for i, ch in enumerate(text):
   238	            if ch in (" ", GLUE) and 0 < i < len(text) - 1 and text[i - 1].strip() and text[i + 1].strip():
   239	                if boxes[i + 1][0] - boxes[i - 1][1] < 0.15 * addr[0].size:
   240	                    bad("KR4", ld, f"space in address renders near zero: '{flat.strip()}'")
   241	                    break
   242	        lead_off = len(flat) - len(flat.lstrip())
   243	        want = italicize_key_address(flat.strip())
   244	        m = re.match(r"\*([^*]+)\*", want)
   245	        if m:
   246	            seg = range(lead_off, lead_off + len(m.group(1)))
   247	            if not all(ital[i] for i in seg if flat[i].strip()):
   248	                bad("KR6", ld, f"taxon name not italic: '{m.group(1)}'")
   249	    return out
   250	
   251	
   252	def check_pdf(pdf: Path, pages: range | None = None) -> list[dict]:
   253	    import fitz
   254	
   255	    doc = fitz.open(pdf)
   256	    findings: list[dict] = []
   257	    prev: Lead | None = None
   258	    for n in pages or range(doc.page_count):
   259	        if n >= doc.page_count:
   260	            break
   261	        leads = leads_of(rows_of(doc[n], n))
   262	        if not leads:
   263	            prev = None
   264	            continue
   265	        right = max(ld.rows[-1].x1 for ld in leads)
   266	        findings += check_page_leads(leads, right)
   267	        first = leads[0]
   268	        if prev is not None and first.marker == "—" and prev.marker != "—":
   269	            findings.append({"rule": "KR7", "page": n + 1, "lead": first.rows[0].text[:60],
   270	                             "detail": f"couplet {prev.marker} split over pages {n} and {n + 1}"})
   271	        prev = leads[-1]
   272	    return findings
   273	
   274	
   275	def _pages(spec: str | None) -> range | None:
   276	    if not spec:
   277	        return None
   278	    a, _, b = spec.partition("-")
   279	    return range(int(a) - 1, int(b or a))
   280	
   281	
   282	def main(argv: list[str] | None = None) -> int:
   283	    ap = argparse.ArgumentParser(prog="python3 -m booklayout.keyrender", description=__doc__.split("\n")[0])
   284	    ap.add_argument("pdf", type=Path)
   285	    ap.add_argument("--pages", help="1-based range, e.g. 3-4")
   286	    ap.add_argument("--report", type=Path)
   287	    args = ap.parse_args(argv)
   288	    found = check_pdf(args.pdf, _pages(args.pages))
   289	    summary = {rule: sum(f["rule"] == rule for f in found) for rule in RULES}
   290	    if args.report:
   291	        args.report.write_text(json.dumps({"rules": RULES, "summary": summary, "findings": found},
   292	                                          ensure_ascii=False, indent=1), encoding="utf-8")
   293	    for rule, text in RULES.items():
   294	        print(f"{rule} {'OK ' if not summary[rule] else 'FAIL'} {summary[rule]:3d}  {text}")
   295	    for f in found[:40]:
   296	        print(f"  p{f['page']} {f['rule']} {f['detail']} | {f['lead']}")
   297	    return 1 if found else 0
   298	
   299	
   300	if __name__ == "__main__":
   301	    sys.exit(main())
  1744	    unique = sorted(set(breaks))
  1745	    payload = {"breaks": unique, "defects": defects}
  1746	    _write_json(args.out, payload)
  1747	    print(json.dumps({"breaks": len(unique), "defects": len(defects)},
  1748	                     ensure_ascii=False))
  1749	    return 0
  1750	
  1751	
  1752	def cmd_gate(args: argparse.Namespace) -> int:
  1753	    """Refuse delivery unless every deterministic review is clean."""
  1754	    problems: list[str] = []
  1755	    for label, path in (("qa", args.qa), ("check", args.check)):
  1756	        payload = json.loads(path.read_text(encoding="utf-8"))
  1757	        if not payload.get("ok"):
  1758	            detail = payload.get("problems", [])
  1759	            problems.append(f"{label} not ok: {detail}")
  1760	    key = json.loads(args.key_report.read_text(encoding="utf-8"))
  1761	    if key.get("breaks"):
  1762	        problems.append(f"{len(key['breaks'])} key couplets still need a forced break")
  1763	    if key.get("defects"):
  1764	        problems.append(f"{len(key['defects'])} key leader defects remain")
  1765	    km_path = getattr(args, "key_model", None)
  1766	    if km_path:
  1767	        try:
  1768	            kmj = json.loads(km_path.read_text(encoding="utf-8"))
  1769	            if not kmj.get("ok"):
  1770	                g = kmj.get("graph", {})
  1771	                problems.append(f"key-model not ok ({km_path.name}): graph errors {g.get('errors', '?')}")
  1772	        except (OSError, ValueError) as e:
  1773	            problems.append(f"key-model unreadable ({km_path}): {e}")
  1774	    kr_path = getattr(args, "keyrender", None)
  1775	    if kr_path:
  1776	        try:
  1777	            krj = json.loads(kr_path.read_text(encoding="utf-8"))
  1778	            fails = {r: n for r, n in (krj.get("summary") or {}).items() if n}
  1779	            if fails or krj.get("findings"):
  1780	                problems.append(f"keyrender FAIL ({kr_path.name}): {fails or len(krj.get('findings', []))}")
  1781	        except (OSError, ValueError) as e:
  1782	            problems.append(f"keyrender unreadable ({kr_path}): {e}")
  1783	    for style_path in args.style_report or []:  # scripts/taxostyle.py compare|audit 的 JSON 报告
  1784	        style = json.loads(style_path.read_text(encoding="utf-8"))
  1785	        if not style.get("ok"):
  1786	            problems.append(f"taxonomic typography not ok ({style_path.name}): "
  1787	                            f"{style.get('errors', '?')} errors")
  1788	    report = {"ok": not problems, "problems": problems,
  1789	              "files": {"qa": str(args.qa), "check": str(args.check),
  1790	                        "key_report": str(args.key_report),
  1791	                        "style_reports": [str(x) for x in args.style_report or []]}}
  1792	    if args.out:
  1793	        _write_json(args.out, report)
  1794	    print(json.dumps(report, ensure_ascii=False))
  1795	    return 0 if report["ok"] else 1
  1796	
  1797	
  1798	def cmd_profile(args: argparse.Namespace) -> int:
  1799	    """Print the default style profile (a template to edit) or validate a file."""
  1800	    from .profile import StyleProfile
  1801	
  1802	    if args.validate:
  1803	        prof = StyleProfile.from_file(args.validate)
  1804	        print(json.dumps({"ok": True, "name": prof.name, "sha256": prof.sha256()}, ensure_ascii=False))
  1805	    else:
  1806	        print(json.dumps(StyleProfile().to_dict(), ensure_ascii=False, indent=2))
  1807	    return 0
  1808	
  1809	
  1810	def cmd_validate_aligned(args: argparse.Namespace) -> int:
{
 "id": "real_marinov_thesis",
 "format": "backref",
 "lang": "en",
 "source": "<!-- PDF p.31 -->\n### Key to the genera of subfamily *Polynoinae*\n1(8) 15 pairs of elytra, with lateral and one median antenna\n2(5) Body short, entirely covered by elytra\n3(4) Lateral antennae attached almost terminally . . . . 1. Genus *Harmothoe* Kinberg\n4(3) Lateral antennae attached ventrally . . . . 4. Genus *Antinoe* Kinberg\n5(2) Body not completely covered by elytra; posterior end without elytra\n6(7) Body short, narrowing posteriorly. 40—50 body segments . . . . . . . . 2. Genus *Lagisca* Malmgren\n7(6) Body long, worm-like, 50—100 segments . . 3. Genus *Polynoe* Savigny\n8(1) Elytra numerous, extending to posterior end of body . . . . . 5. Genus *Lepidasthenia* Malmgren\n\n### 1. Genus *Harmothoe* Kinberg, 1855\nBody relatively short, with no more than 40—50 segments.",
 "expect": {
  "keys": 1,
  "branches": [
   [
    "1a",
    "jump",
    "2"
   ],
   [
    "2a",
    "jump",
    "3"
   ],
   [
    "3a",
    "taxon",
    "Harmothoe"
   ],
   [
    "3b",
    "taxon",
    "Antinoe"
   ],
   [
    "2b",
    "jump",
    "6"
   ],
   [
    "6a",
    "taxon",
    "Lagisca"
   ],
   [
    "6b",
    "taxon",
    "Polynoe"
   ],
   [
    "1b",
    "taxon",
    "Lepidasthenia"
   ]
  ],
  "findings": []
 },
 "why": "真实写法：Marinov 1977 b07.md 第 8–16 行（正反条成对编号，括号为对立条号，无去向接下一号）。结构照原书，3/4 去向据原书补全为合成值。旧 key-model 对原文识别 0 张表，keygraph 报 53 个 single_branch 误报。"
}{
 "id": "real_marinov_two_leads",
 "format": "backref",
 "lang": "en",
 "source": "### Key to the species of genus *Harmothoe*\n1(2) Surface of elytra spotted, evenly covered with numerous claw-like spinules ..... 1. *H. imbricata* (Linnaeus)\n\n2(1) Ventral chaetae slender, with two fine denticles at the tip ..... 2. *H. reticulata* (Claparède)\n\n### 1. *Harmothoe imbricata* (Linnaeus, 1767) (Plate VI, 2a–2g)",
 "expect": {
  "keys": 1,
  "branches": [
   [
    "1a",
    "taxon",
    "H. imbricata"
   ],
   [
    "1b",
    "taxon",
    "H. reticulata"
   ]
  ],
  "findings": []
 },
 "why": "真实写法：Marinov 1977 b07.md 第 25–28 行，两条之间有空行，表后紧接种记述标题。"
}{
  "id": "en_backref_one",
  "format": "backref",
  "lang": "en",
  "source": "Key to specimens (start at 3)\n1(3). Leaves opposite ........ p. 10\n— Leaves alternate ........ p. 11\n3. Shoots leafy ........ 1\n— Shoots leafless ........ p. 12",
  "declared_entries": [
    "3"
  ],
  "expect": {
    "keys": 1,
    "branches": [
      [
        "1a",
        "page",
        "10"
      ],
      [
        "1b",
        "page",
        "11"
      ],
      [
        "3a",
        "jump",
        "1"
      ],
      [
        "3b",
        "page",
        "12"
      ]
    ],
    "findings": []
  },
  "why": "依 SPEC，1(3) 表示从 3 来；已声明以 3 为入口，核对实际边 3→1。"
}
{
  "id": "r2_lost_dots",
  "format": "ab",
  "lang": "en",
  "source": "1a. Pharynx with jaws N. pelagica\n1b. Pharynx unarmed ...... Nephtys",
  "expect": {
    "keys": 1,
    "branches": [
      [
        "1a",
        "taxon",
        "N. pelagica"
      ],
      [
        "1b",
        "taxon",
        "Nephtys"
      ]
    ],
    "findings": []
  },
  "why": "合成例。booklayout/keygraph.py:193–199 点线消失只剩一空格，缩写双名紧跟性状。LIMITS 第724行已知。"
}
{
  "id": "r2_gap_page",
  "format": "ab",
  "lang": "en",
  "source": "1a. Elytra striate    Carabidae (p. 18)\n1b. Elytra smooth ...... Staphylinidae",
  "expect": {
    "keys": 1,
    "branches": [
      [
        "1a",
        "taxon",
        "Carabidae"
      ],
      [
        "1b",
        "taxon",
        "Staphylinidae"
      ]
    ],
    "findings": []
  },
  "why": "合成例。booklayout/keygraph.py:190–195 优先裁下末尾页码，宽空格后的科名留在性状内。"
}

exec
/bin/bash -lc "nl -ba ../../booklayout/keygraph.py | sed -n '338,381p;505,550p;570,679p'
nl -ba ../../scripts/publish_book.py | sed -n '30,134p'
ls -ld ../../docs/{design,architecture,workflow}.md
cat corpus/en_indent_siblings.json
cat wiring_realrun.md | head -40" in /mnt/p/翻译-译作/Taxonomy-Aware-Scientific-Book-Translation/test-keys/adv
 succeeded in 0ms:
   338	def _assign_alts(key: GKey) -> None:
   339	    groups: OrderedDict[str, list[GBranch]] = OrderedDict()
   340	    for b in key.branches:
   341	        groups.setdefault(b.couplet, []).append(b)
   342	    for c, brs in groups.items():
   343	        used: set[str] = set()
   344	        for b in brs:
   345	            h = b.hint
   346	            alt = h if h and h != "+" else next(chr(x) for x in range(97, 123) if chr(x) not in used)
   347	            used.add(alt)
   348	            b.alt = alt
   349	            b.lead = c + alt
   350	
   351	
   352	def _pair_backrefs(key: GKey) -> None:
   353	    """Soviet-style paired numbering 1(8) ... 8(1): bracket = opposite lead, not a back reference."""
   354	    brs = key.branches
   355	    nums = [b.couplet for b in brs]
   356	    if len(brs) < 2 or len(set(nums)) != len(nums) or any(b.backref is None or b.hint != "" for b in brs):
   357	        return
   358	    pairs = {(b.couplet, b.backref) for b in brs}
   359	    if any(n == m or (m, n) not in pairs for n, m in pairs):
   360	        return
   361	    by_num = {b.couplet: b for b in brs}
   362	
   363	    def cp(n: str) -> str:
   364	        return str(min(int(n), int(by_num[n].backref or n)))
   365	    for b in brs:
   366	        nxt = str(int(b.couplet) + 1)
   367	        if b.kind == "none" and nxt in by_num and nxt != b.backref:
   368	            b.kind, b.jump, b.target = "jump", cp(nxt), cp(nxt)
   369	    for b in brs:
   370	        b.couplet, b.backref = cp(b.couplet), None
   371	
   372	
   373	def _drop_bare(key: GKey) -> None:
   374	    """A bare trailing number is a jump only when that couplet exists in the key."""
   375	    have = {b.couplet for b in key.branches}
   376	    for b in key.branches:
   377	        if b.bare and b.kind == "jump" and b.jump not in have:
   378	            b.kind, b.jump, b.target = "none", None, ""
   379	
   380	
   381	def _complete_couplets(key: GKey) -> bool:
   505	                break
   506	            ind = _indent(raw)
   507	            bm = _BULLET.match(line)
   508	            content = line[bm.end():] if bm else line
   509	            lab = _REP_LABEL.match(content)
   510	            raw_lead = ""
   511	            letter = ""
   512	            if lab:
   513	                letter = lab.group("l").lower()
   514	                raw_lead = lab.group(0).strip()
   515	                content = content[lab.end():].strip()
   516	            text, target = split_target(content)
   517	            if rows and not rows[-1]["target"] and not lab and JUMP_ONLY.match(content):
   518	                rows[-1]["target"] = content
   519	                j += 1
   520	                continue
   521	            nj = next_sig(j)
   522	            nxt = items[nj][1] if nj is not None else None
   523	            deeper = nxt is not None and _indent(nxt) > ind
   524	            if not (target or deeper or lab):
   525	                break
   526	            while stack and stack[-1] > ind:
   527	                stack.pop()
   528	            if not stack or stack[-1] < ind:
   529	                stack.append(ind)
   530	            rows.append({"level": len(stack), "text": text, "target": target, "raw": raw_lead, "page": pg,
   531	                         "letter": letter})
   532	            j += 1
   533	        if not rows:
   534	            return None
   535	        k = open_key("tree")
   536	        st: list[int] = []
   537	        groups: dict[tuple[int, str], str] = {}
   538	        for idx, r in enumerate(rows):
   539	            while st and rows[st[-1]]["level"] >= r["level"]:
   540	                st.pop()
   541	            parent = st[-1] if st else -1
   542	            r["parent"] = parent
   543	            gk = (parent, r["letter"])
   544	            if gk not in groups:
   545	                groups[gk] = str(len(groups) + 1)
   546	                if parent >= 0:
   547	                    pb = rows[parent]["branch"]
   548	                    if pb.kind == "none":
   549	                        pb.kind, pb.target, pb.jump = "jump", groups[gk], groups[gk]
   550	            st.append(idx)
   570	            continue
   571	        line = raw.strip()
   572	        first_on_page = fresh and bool(line)
   573	        if line:
   574	            fresh = False
   575	        if not line:
   576	            i += 1
   577	            continue
   578	        incomplete = cur is not None and not cur.complete()
   579	        if first_on_page and (RUNNING_HEAD.match(line) or (
   580	                any(ch.isupper() for ch in line) and line == line.upper() and len(line) >= 4
   581	                and not _LEADTOK.match(line) and not hre.match(line) and not LEADER.search(line))):
   582	            i += 1
   583	            continue
   584	        if key is not None and len(line) <= 120 and hre.match(line) and CONT_RE.search(line):
   585	            i += 1
   586	            continue
   587	        if PAGE_ONLY.match(line):
   588	            if cur is not None and incomplete and not first_on_page and JUMP_ONLY.match(line) \
   589	                    and (not at_page_end(i) or next_page_leads(i)):
   590	                cur.add(line)
   591	            i += 1
   592	            continue
   593	        if line.startswith("|"):
   594	            cells = [c.strip() for c in line.strip("|").split("|")]
   595	            if all(re.fullmatch(r":?-{2,}:?", c) or not c for c in cells) and any(cells):
   596	                i += 1
   597	                continue
   598	            lm = _match_lead(cells[0] + " x", last_num or None) if cells and cells[0] else None
   599	            if mode != "table":
   600	                close()
   601	                if lm is None:
   602	                    hdr_cols.clear()
   603	                    for ci, c in enumerate(cells):  # header row: remember taxon / page columns
   604	                        if ci and re.fullmatch(r"(?i)类群|類群|分类群|分類群|taxon|taxa|target|destination|去向", c):
   605	                            hdr_cols["tax"] = ci
   606	                        elif ci and re.fullmatch(r"(?i)页码|頁碼|页|頁|pages?|págs?\.?|seite|стр\.?", c):
   607	                            hdr_cols["page"] = ci
   608	                    i += 1
   609	                    continue
   610	                open_key("table")
   611	            assert key is not None
   612	            if lm is None:
   613	                if key.branches and len(cells) > 1:  # continuation row
   614	                    b = key.branches[-1]
   615	                    b.text = (b.text + " " + " ".join(cells[1:-1] if len(cells) > 2 else cells[1:2])).strip()
   616	                    if len(cells) > 2 and cells[-1]:
   617	                        tg = parse_target(cells[-1])
   618	                        b.target, b.kind, b.jump, b.page = (tg.taxon if tg.kind == "taxon" else cells[-1]), \
   619	                            tg.kind, tg.jump, tg.page
   620	                i += 1
   621	                continue
   622	            info, rl, _, _ = lm
   623	            tc, pc = hdr_cols.get("tax", -1), hdr_cols.get("page", -1)
   624	            if 0 < tc < len(cells):
   625	                target = cells[tc] + (" " + cells[pc] if 0 < pc < len(cells) and cells[pc] else "")
   626	                text = " ".join(c for ci, c in enumerate(cells) if ci not in (0, tc, pc) and c)
   627	            elif len(cells) >= 3:
   628	                text, target = " ".join(cells[1:-1]), cells[-1]
   629	            else:
   630	                text, target = split_target(cells[1] if len(cells) > 1 else "")
   631	            key.branches.append(_mk(info, rl, text, target, pg))
   632	            if not _is_dash(rl):
   633	                last_num = info[0]
   634	            i += 1
   635	            continue
   636	        if mode == "table":
   637	            close()
   638	        if len(line) <= 120 and not incomplete and hre.match(line) and not _LEADTOK.match(line):
   639	            close()
   640	            pending = line.lstrip("# ").strip().strip("*").strip()
   641	            hdr_cols.clear()
   642	            i += 1
   643	            continue
   644	        lm = _match_lead(line, last_num or None)
   645	        if lm is not None and mode != "tree":
   646	            info, rl, rest, weak = lm
   647	            ok = True
   648	            if weak:
   649	                exp = int(last_num) if last_num else 0
   650	                want = {b.jump for b in key.branches} if key is not None else set()
   651	                if cur is not None:
   652	                    want.add(parse_target(_split(cur.text)[1]).jump)
   653	                if key is None and not pending:
   654	                    ok = False
   655	                elif info[0] in want and key is not None:
   656	                    ok = True
   657	                elif incomplete and int(info[0]) != exp + 1:
   658	                    ok = False
   659	                elif incomplete and cur is not None and key is not None \
   660	                        and not any(b.couplet == cur.info[0] for b in key.branches):
   661	                    ok = False  # a couplet needs two branches: a lone open branch cannot be followed by a new one
   662	                elif key is not None and int(info[0]) not in (exp, exp + 1):
   663	                    ok = False
   664	            if ok and _ROMAN.fullmatch(rl) and key is None and not pending:
   665	                ok = False
   666	            if ok:
   667	                flush()
   668	                if key is not None and info[0] == "1" and info[1] in ("", "a") and last_num != "1" \
   669	                        and _complete_couplets(key):
   670	                    close()
   671	                if key is None:
   672	                    open_key("num")
   673	                cur = _Open(info, rl, rest, pg)
   674	                if not _is_dash(rl):
   675	                    last_num = info[0]
   676	                i += 1
   677	                continue
   678	        if key is None and (pending or _looks_tree(items, i)):
   679	            j = tree_from(i)
    30	
    31	import argparse
    32	import hashlib
    33	import json
    34	import platform
    35	import shlex
    36	import subprocess
    37	import sys
    38	import time
    39	from pathlib import Path
    40	from typing import Any
    41	
    42	ROOT = Path(__file__).resolve().parent.parent
    43	STAGES = ["export", "translate", "figures", "align", "keycheck", "build", "qa", "gate"]
    44	SOFT = {"qa"}  # 失败不立刻停：闸口汇总
    45	
    46	
    47	def _sha(p: Path) -> str | None:
    48	    if not p.is_file():
    49	        return None
    50	    h = hashlib.sha256()
    51	    h.update(p.read_bytes())
    52	    return h.hexdigest()
    53	
    54	
    55	def _bl(*a: str) -> list[str]:
    56	    return [sys.executable, "-m", "booklayout", *a]
    57	
    58	
    59	def plan(args: argparse.Namespace) -> list[dict[str, Any]]:
    60	    """返回 [{stage, cmd(list)|None, note, outputs}]，不执行。"""
    61	    w: Path = args.work
    62	    src = args.source_md or w / "src.md"
    63	    tgt = args.translation_md or w / "tgt.md"
    64	    fig, aligned = w / "figures", w / "aligned.json"
    65	    docx, pdf = w / "book.docx", w / "book.pdf"
    66	    meta = ["--metadata", str(args.metadata)] if args.metadata else []
    67	    title = ["--title", args.title] if args.title else []
    68	    has_pdf = not args.no_pdf
    69	    out: list[dict[str, Any]] = []
    70	
    71	    def add(stage: str, cmd: list[str] | None, outputs: list[Path], note: str = "") -> None:
    72	        out.append({"stage": stage, "cmd": cmd, "outputs": outputs, "note": note})
    73	
    74	    if args.source_md:
    75	        add("export", None, [src], "给了 --source-md，跳过导出")
    76	    else:
    77	        if not args.key:
    78	            raise SystemExit("需要 --key（docstore 资料）或 --source-md")
    79	        ex = [sys.executable, "-c", "import sys; from docstore.cli import main; sys.exit(main(sys.argv[1:]))",
    80	              "--by", "publish_book", "export", args.key, "--translate", "--strict", "-o", str(src)]
    81	        if args.pages:
    82	            ex += ["--pages", args.pages]
    83	        add("export", ex, [src])
    84	    if args.translation_md:
    85	        add("translate", None, [tgt], "给了 --translation-md，跳过翻译")
    86	    else:
    87	        tr = [sys.executable, str(ROOT / "scripts" / "auto_translate.py"), "run", str(src), "-o", str(w / "translate"),
    88	              "--sl", args.sl, "--tl", args.tl]
    89	        if args.glossary:
    90	            tr += ["--glossary", str(args.glossary)]
    91	        if args.engine:
    92	            tr += ["--engine", args.engine]
    93	        add("translate", tr, [tgt], "产物 translate/checked.md|revised.md|draft.md 取最后一个存在的复制为 tgt.md")
    94	    if args.pdf:
    95	        fg = _bl("figures", "extract", "--pdf", str(args.pdf), "--out", str(fig), "--dpi", str(args.dpi))
    96	        if args.pages:
    97	            a, _, b = args.pages.partition("-")
    98	            fg += ["--first", a, "--last", b or a]
    99	        add("figures", fg, [fig / "figures_manifest.json", fig / "source_figure_audit.json"])
   100	    else:
   101	        add("figures", None, [fig / "source_figure_audit.json"], "未给 --pdf：不抽图，写空 source_figure_audit.json")
   102	    add("align", _bl("align-md", "--source", str(src), "--translation", str(tgt), "--out", str(aligned),
   103	                     "--report", str(w / "align_report.json")), [aligned])
   104	    add("keycheck", _bl("key-model", "--source", str(src), "--translation", str(tgt),
   105	                        "--out", str(w / "key_model.json")), [w / "key_model.json"])
   106	    build = _bl("build", "--aligned", str(aligned), "--figures", str(fig), "--translation", str(tgt),
   107	                "--out", str(docx), "--report", str(w / "build_report.json"), *meta, *title)
   108	    if has_pdf:
   109	        build += ["--pdf", "--pdf-out", str(pdf)]
   110	    add("build", build, [docx] + ([pdf] if has_pdf else []),
   111	        "两遍排版（map-pages 后 build --map）在 build 阶段内部执行" if has_pdf else "")
   112	    qa = _bl("qa", "--aligned", str(aligned), "--figures", str(fig), "--out", str(w / "qa.json"), *meta, *title)
   113	    ck = _bl("check", "--aligned", str(aligned), "--figures", str(fig), "--out", str(w / "check.json"), *meta, *title)
   114	    if has_pdf:
   115	        qa += ["--pdf", str(pdf)]
   116	        ck += ["--pdf", str(pdf)]
   117	    add("qa", qa, [w / "qa.json"], "qa、check、key-report 依次执行")
   118	    if not has_pdf:
   119	        add("gate", None, [], "no PDF：没有 key-report，闸口不运行；产物只是草稿，不得交付")
   120	    else:
   121	        add("gate", _bl("gate", "--qa", str(w / "qa.json"), "--check", str(w / "check.json"),
   122	                        "--key-report", str(w / "key_report.json"),
   123	                        "--key-model", str(w / "key_model.json"), "--keyrender", str(w / "keyrender.json"),
   124	                        "--out", str(w / "gate.json")),
   125	            [w / "gate.json"])
   126	    for s in out:
   127	        s["extra"] = []
   128	    for s in out:
   129	        if s["stage"] == "qa":
   130	            s["extra"].append(ck)
   131	            if has_pdf:
   132	                s["extra"].append(_bl("key-report", "--pdf", str(pdf), "--out", str(w / "key_report.json")))
   133	                s["extra"].append([sys.executable, "-m", "booklayout.keyrender", str(pdf),
   134	                                   "--report", str(w / "keyrender.json")])
-rwxrwxrwx 1 root root 19155 Nov 19 16:28 ../../docs/architecture.md
-rwxrwxrwx 1 root root 14670 Nov 10 15:34 ../../docs/design.md
-rwxrwxrwx 1 root root 33534 Nov 21 00:05 ../../docs/workflow.md
{
  "id": "en_indent_siblings",
  "format": "indented",
  "lang": "en",
  "source": "Key to leaves\nLeaves opposite\n    Blades lobed ........ p. 12\n    Blades unlobed ........ p. 13\nLeaves alternate\n    Blades toothed ........ p. 14\n    Blades entire ........ p. 15",
  "expect": {
    "keys": 1,
    "branches": [
      [
        "1a",
        "jump",
        "2"
      ],
      [
        "2a",
        "page",
        "12"
      ],
      [
        "2b",
        "page",
        "13"
      ],
      [
        "1b",
        "jump",
        "3"
      ],
      [
        "3a",
        "page",
        "14"
      ],
      [
        "3b",
        "page",
        "15"
      ]
    ],
    "findings": []
  },
  "why": "纯缩进表按子树先后编号。第二个子树与第一个深度相同，但父支不同。"
}
# key-model wiring real run

- source: /mnt/p/翻译-译作/Marinov1977_Polychaeta/md_en/b07.md
- cmd: python3 -m booklayout key-model --source <src> --out <scratch>/b07.json
- exit: 1; stdout: keys=0 branches=0 problems=53 graph_keys=4 graph_errors=53 graph_warn=0
- keymodel keys (old): 0; graph keys: 4; expect_keys: true
- graph errors: 53; warnings: 0
- first 5 errors (raw, not triaged):
  - {"code":"single_branch","severity":"error","lead":"1a","detail":"couplet 1 has one branch","key":1}
  - {"code":"single_branch","severity":"error","lead":"2a","detail":"couplet 2 has one branch","key":1}
  - {"code":"single_branch","severity":"error","lead":"3a","detail":"couplet 3 has one branch","key":1}
  - {"code":"single_branch","severity":"error","lead":"4a","detail":"couplet 4 has one branch","key":1}
  - {"code":"single_branch","severity":"error","lead":"5a","detail":"couplet 5 has one branch","key":1}

codex
接入代码中，发布流程会传入两份新报告，但 `gate` 的旧调用仍可省略它们。另一个值得核验的差异是，语料运行器把 `declared_entries` 视为“预期有表”，而 `key-model` 单独计算这项预期。我会用同一份输入对照两个入口。
exec
/bin/bash -lc "PYTHONDONTWRITEBYTECODE=1 python3 - <<'PY'
from pathlib import Path
import json
D=Path('corpus')
def put(id,src,b,why,line,*,keys=1,find=(),tr=None,fmt='backref',lang='en',entries=None):
    id='r3_'+id
    obj=dict(id=id,format=fmt,lang=lang,source=src)
    if tr is not None: obj['translation']=tr
    if entries: obj['declared_entries']=entries
    obj['expect']=dict(keys=keys,branches=[list(row.split('|')) for row in b.splitlines()],findings=list(find))
    obj['why']=f'booklayout/keygraph.py:{line}。'+why
    with (D/(id+'.json')).open('x') as f: f.write(json.dumps(obj,indent=2,ensure_ascii=False)+'\\n')
h='Key to genera\\n'
a='1(4) Elytra present\\n2(3) Body narrow ...... Harmothoe\\n3(2) Body broad ...... Antinoe\\n4(1) Elytra absent ...... Nereis'
b='1a|jump|2\\n2a|taxon|Harmothoe\\n2b|taxon|Antinoe\\n1b|taxon|Nereis'
s='1(2) Eyes present ...... Harmothoe\\n2(1) Eyes absent ...... Antinoe'
sb='1a|taxon|Harmothoe\\n1b|taxon|Antinoe'
put('implicit_next',h+a,b,'按 SPEC 正反条及 real_marinov_thesis 的结构缩写；第 1 条无终点，接第 2 条。',367)
put('pair_across_page',h+a.replace('3(2)','<"'!-- PDF p.32 -->'"\\nKey to genera (continued)\\n3(2)'),b,'换页续表标题不改变 2(3) 与 3(2) 的对应。',584)
put('restart_titled',h+a+'\\nKey to a second group\\n'+s,b+'\\n'+sb,'同页两标题，各从 1 编起。',638,keys=2)
put('restart_plain',h+a+'\\n\\n'+s,b+'\\n'+sb,'两组分别完整闭合且各从 1 重启，中间空行。依据 SPEC 同一表内条号唯一。',668,keys=2)
p='1(3). Leaves opposite ...... p. 10\\n— Leaves alternate ...... p. 11\\n3. Shoots leafy ...... 1\\n— Shoots bare ...... p. 12'
pb='1a|page|10\\n1b|page|11\\n3a|jump|1\\n3b|page|12'
put('mixed_two_headings',h+s+'\\nKey to leaves\\n'+p,sb+'\\n'+pb,'同页先正反条，后接 en_backref_one 的回指结构；显式标题划界，各表使用声明中存在的入口。',356,keys=2,entries=['1','3'])
put('incomplete_reciprocal',h+s.splitlines()[0],sb.splitlines()[0],'单独 1(2) 无对立条，按 SPEC 退回回指式，来源 2 也缺失。',356,find=['single_branch','backref_mismatch'])
put('mixed_hints',h+'1(2). Head broad ...... 2\\n1′. Head narrow ...... p. 10\\n2(1). Eyes large ...... 1\\n2′. Eyes small ...... p. 11','1a|jump|2\\n1b|page|10\\n2a|jump|1\\n2b|page|11','同表两个括号号互指但均有撇号备择；按回指式可检出真实回路。',356,find=['cycle'])
put('count_fallthrough',h+a.replace('Elytra present','Number of antennae 1'),b,'末尾 1 是触角数，依原条序隐式接 2；前面的数量名词消除裸数歧义。',367)
put('last_missing_target',h+s.rsplit(' ......',1)[0],sb.replace('taxon|Antinoe','none|'),'末条无去向且无下一条，报告缺终点。',367,find=['no_target'])
def serial(id,t,canonical,line,why,**kwargs):
    src=h+'1a. Elytra spotted'+t+'\\n1b. Elytra smooth ...... Antinoe'
    put(id,src,'1a|taxon|'+canonical+'\\n1b|taxon|Antinoe',why,line,fmt='ab',**kwargs)
serial('serial_author',' ...... 1. Genus Harmothoe Kinberg, 1855','Harmothoe',226,'点线、属序号、作者及年份齐全。依据 SPEC 及 real_marinov_thesis。')
serial('serial_year_noleader',' 1. Genus Harmothoe Kinberg, 1855','Harmothoe',82,'去掉点线，仍有属序号、显式阶元和作者年份；1855 不属于性状。')
serial('serial_page_noleader',' 1. Genus Harmothoe Kinberg (p. 76)','Harmothoe',266,'带页码的编号属名为同一终点，按 SPEC 保留学名和页。')
serial('serial_species_noleader',' 2. H. reticulata (Claparède)','H. reticulata',272,'沿用 real_marinov_two_leads 的编号种名和作者，仅模拟点线丢失。')
ru='1а. Глаза есть ...... 1. Род Harmothoe Kinberg\\n1б. Глаз нет ...... 2. Род Antinoe Kinberg'
zh='1a. 有眼 ...... 1. 属 Harmothoe Kinberg\\n1b. 无眼 ...... 2. 属 Antinoe Kinberg'
put('rank_zh',zh,sb,'SPEC 明列中文阶元词「属」；终点字段只存拉丁属名。',194,fmt='ab',lang='zh')
put('rank_ru',ru,sb,'SPEC 明列 Род，西里尔分支字母按已有 r2_ru_cyrillic。',194,fmt='ab',lang='ru')
simple='1a. Eyes present ...... Harmothoe (p. 76)\\n1b. Eyes absent ...... Antinoe'
z='1a. 有眼 ...... Harmothoe（第76页）\\n1b. 无眼 ...... Antinoe'
j='1a. 眼あり ...... Harmothoe（76ページ）\\n1b. 眼なし ...... Antinoe'
r='1а. Глаза есть ...... Harmothoe (с. 76)\\n1б. Глаз нет ...... Antinoe'
for id,tr,code,why,line in [
('zh_page',z.replace('76','67'),'target_changed','仅将 76 页改为 67 页。',803),
('ja_taxon',j.replace('Antinoe','Polynoe'),'target_changed','仅替换第二支的学名。',823),
('ru_order','\\n'.join(reversed(r.splitlines())),'order_changed','俄译显式 а/б 保留身份，仅交换排印顺序。',828),
('ja_omission',j.splitlines()[0],'missing_branch','日译漏第二支。按运行器约定，译侧只计对照码。',821),
('ru_page_equiv',r,'','俄文 с. 76 对应原页，无去向变化。',803)]:
    put(id,simple,sb,why,line,tr=tr,find=[code] if code else [],fmt='ab')
put('zh_jump',h+a,b,'原文 1(4) 隐式接 2；中文改成显式回到 1。期望原译对照识别改号。',823,tr='1(4) 有鞘翅 ...... 1\\n2(3) 体窄 ...... Harmothoe\\n3(2) 体宽 ...... Antinoe\\n4(1) 无鞘翅 ...... Nereis',find=['target_changed'])
put('translation_only','General introduction.','','原文纯叙述，俄译多出整表，应报表数不同。',809,keys=0,tr=ru,find=['key_count'],fmt='other')
put('entries_empty','General introduction.','','声明入口即预期有表；对照 booklayout/keymodel.py:355 和 run_corpus.py:28。',835,keys=0,entries=['1','5'],find=['no_keys'],fmt='other')
tree=json.loads((D/'en_indent_siblings.json').read_text())
tb='\\n'.join('|'.join(row) for row in tree['expect']['branches'])
put('indent_no_heading',tree['source'].split('\\n',1)[1],tb,'同 en_indent_siblings 去标题；两个子树均有两个带点线的页码终点。',400,fmt='indented')
put('indent_wrapped',tree['source'].replace('Blades lobed ........','Blades deeply\\n        lobed ........'),tb,'同 en_indent_siblings，只将第一个叶节点性状折行；另一同层的 Blades unlobed 保留。',524,fmt='indented')
serial('wrap_full_genus',' ...... Nereis\\npelagica','Nereis pelagica',689,'完整属名后单独一行种加词；同 r2_wrapped_genus 的折行，属名写全。')
serial('epithet_two_letters',' ...... Ficus so','Ficus so',180,'二字母加词识别测试；此组合的分类学地位未确证。为避免拟名，采用下例写入前替换。') if False else None
# Io io is a real binomial with a two-letter epithet. Keep source semantics neutral.
put('short_binomial','1a. Tail long ...... Io io\\n1b. Tail short ...... Myotis myotis','1a|taxon|Io io\\n1b|taxon|Myotis myotis','以二字母属、种名 Io io 检查短词下限；性状是合成占位。日译改作另一合法属名 Ia（具体组合未确证）。',180,tr='1a. 尾が長い ...... Ia io\\n1b. 尾が短い ...... Myotis myotis',fmt='ab',find=['target_changed'])
put('ocr_nonadjacent','1. Eyes present ...... 2\\n2. Body short ...... Harmothoe\\n2′. Body long ...... Antinoe\\n11. Eyes absent ...... Nereis',b,'原稿 1′ 在子偶句之后，模拟 OCR 错读 11。中文清稿保留 1′ 供对照；孤立读作撇号未确证。',159,fmt='prime',tr='1. 有眼 ...... 2\\n2. 体短 ...... Harmothoe\\n2′. 体长 ...... Antinoe\\n1′. 无眼 ...... Nereis')
PY
cd ../..
PYTHONDONTWRITEBYTECODE=1 python3 test-keys/adv/run_corpus.py" in /mnt/p/翻译-译作/Taxonomy-Aware-Scientific-Book-Translation/test-keys/adv
 exited 1 in 581ms:
pass 109/120
r3_count_fallthrough | findings missing [] extra ['cycle', 'unreachable'] ; branches want [['1a', 'jump', '2'], ['2a', 'taxon', 'Harmothoe'], ['2b', 'taxon', 'Antinoe'], ['1b', 'taxon', 'Nereis']] got [['1a', 'jump', '1'], ['2a', 'taxon', 'Harmothoe'], ['2b', 'taxon', 'Antinoe'], ['1b', 'taxon', 'Nereis']]
r3_indent_no_heading | keys want 1 got 0 ; findings missing [] extra ['no_keys'] ; branches want [['1a', 'jump', '2'], ['2a', 'page', '12'], ['2b', 'page', '13'], ['1b', 'jump', '3'], ['3a', 'page', '14'], ['3b', 'page', '15']] got []
r3_indent_wrapped | findings missing [] extra ['single_branch'] ; branches want [['1a', 'jump', '2'], ['2a', 'page', '12'], ['2b', 'page', '13'], ['1b', 'jump', '3'], ['3a', 'page', '14'], ['3b', 'page', '15']] got [['1a', 'jump', '2'], ['2a', 'jump', '3'], ['3a', 'page', '12'], ['2b', 'page', '13'], ['1b', 'jump', '4'], ['4a', 'page', '14'], ['4b', 'page', '15']]
r3_ocr_nonadjacent | findings missing [] extra ['extra_branch', 'missing_branch', 'single_branch', 'unreachable'] ; branches want [['1a', 'jump', '2'], ['2a', 'taxon', 'Harmothoe'], ['2b', 'taxon', 'Antinoe'], ['1b', 'taxon', 'Nereis']] got [['1a', 'jump', '2'], ['2a', 'taxon', 'Harmothoe'], ['2b', 'taxon', 'Antinoe'], ['11a', 'taxon', 'Nereis']]
r3_rank_zh | branches want [['1a', 'taxon', 'Harmothoe'], ['1b', 'taxon', 'Antinoe']] got [['1a', 'taxon', '属 Harmothoe Kinberg'], ['1b', 'taxon', '属 Antinoe Kinberg']]
r3_restart_plain | keys want 2 got 1 ; findings missing [] extra ['backref_mismatch', 'no_target', 'single_branch', 'unreachable'] ; branches want [['1a', 'jump', '2'], ['2a', 'taxon', 'Harmothoe'], ['2b', 'taxon', 'Antinoe'], ['1b', 'taxon', 'Nereis'], ['1a', 'taxon', 'Harmothoe'], ['1b', 'taxon', 'Antinoe']] got [['1a', 'none', ''], ['2a', 'taxon', 'Harmothoe'], ['3a', 'taxon', 'Antinoe'], ['4a', 'taxon', 'Nereis'
r3_serial_page_noleader | branches want [['1a', 'taxon', 'Harmothoe'], ['1b', 'taxon', 'Antinoe']] got [['1a', 'page', '76'], ['1b', 'taxon', 'Antinoe']]
r3_serial_species_noleader | findings missing [] extra ['no_target'] ; branches want [['1a', 'taxon', 'H. reticulata'], ['1b', 'taxon', 'Antinoe']] got [['1a', 'none', ''], ['1b', 'taxon', 'Antinoe']]
r3_serial_year_noleader | findings missing [] extra ['no_target'] ; branches want [['1a', 'taxon', 'Harmothoe'], ['1b', 'taxon', 'Antinoe']] got [['1a', 'none', ''], ['1b', 'taxon', 'Antinoe']]
r3_short_binomial | findings missing ['target_changed'] extra [] ; branches want [['1a', 'taxon', 'Io io'], ['1b', 'taxon', 'Myotis myotis']] got [['1a', 'taxon', 'Io'], ['1b', 'taxon', 'Myotis myotis']]
r3_wrap_full_genus | keys want 1 got 2 ; findings missing [] extra ['lone_alternate', 'single_branch'] ; branches want [['1a', 'taxon', 'Nereis pelagica'], ['1b', 'taxon', 'Antinoe']] got [['1a', 'taxon', 'Nereis'], ['1b', 'taxon', 'Antinoe']]

exec
/bin/bash -lc "cd ../..
PYTHONDONTWRITEBYTECODE=1 python3 - <<'PY'
import os,json,subprocess,sys
from pathlib import Path
def fd(value):
    d=os.memfd_create('probe')
    os.write(d,value.encode())
    return f'/proc/{os.getpid()}/fd/{d}'
def go(*args):
    out=fd('')
    r=subprocess.run([sys.executable,'-m','booklayout',*args,'--out',out],capture_output=True,text=True)
    rep=json.loads(Path(out).read_text() or '{}')
    print(args[0],r.returncode,r.stdout[:150],r.stderr[-180:],rep.get('graph',{}).get('gate'))
plain=fd('plain narrative\\n')
good=fd(json.loads(Path('test-keys/adv/corpus/r3_implicit_next.json').read_text())['source'])
missing='/missing-r3-booklayout-file'
for opt in [[],['--entries','1,5'],['--entries','1,5','--expect-keys'],['--translation',good],['--translation',missing]]:
    go('key-model','--source',plain,*opt)
go('key-model','--source',good,'--expect-keys','--entries','99')
base=['gate','--qa',fd('{\"ok\":true}'),'--check',fd('{\"ok\":true}'),'--key-report',fd('{\"breaks\":[],\"defects\":[]}')]
for opt in [[],['--key-model',missing],['--keyrender',missing],['--key-model',fd('{\"ok\":true,\"graph\":{\"errors\":1}}'),'--keyrender',fd('{}')],['--keyrender',fd('{\"summary\":{\"KR1\":1},\"findings\":[]}')],['--keyrender',fd('{\"summary\":{},\"findings\":[{}]}')]]:
    go(*base,*opt)
PY
rg -n 'gate|key-model' docs/{design,workflow,architecture}.md | head -10
cat -n booklayout/keymodel.py | sed -n '347,396p'" in /mnt/p/翻译-译作/Taxonomy-Aware-Scientific-Book-Translation/test-keys/adv
 succeeded in 3315ms:
key-model 0 keys=0 branches=0 problems=0 graph_keys=0 graph_errors=0 graph_warn=0
  []
key-model 0 keys=0 branches=0 problems=0 graph_keys=0 graph_errors=0 graph_warn=0
  []
key-model 1 keys=0 branches=0 problems=1 graph_keys=0 graph_errors=1 graph_warn=0
  [{'code': 'no_keys', 'severity': 'error', 'lead': '', 'detail': 'keys expected but none recognised'}]
key-model 1 keys=0 branches=0 problems=1 graph_keys=0 graph_errors=1 graph_warn=0
  []
key-model 1  coding, errors, newline)
           ~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
FileNotFoundError: [Errno 2] No such file or directory: '/missing-r3-booklayout-file'
 None
key-model 0 keys=0 branches=0 problems=0 graph_keys=1 graph_errors=0 graph_warn=0
  []
gate 1  .py", line 75, in _write_json
    fd = os.open(tmp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
OSError: [Errno 30] Read-only file system: '/.memfd:probe (deleted).10.0.tmp'
 None
gate 1  .py", line 75, in _write_json
    fd = os.open(tmp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
OSError: [Errno 30] Read-only file system: '/.memfd:probe (deleted).11.0.tmp'
 None
gate 1  .py", line 75, in _write_json
    fd = os.open(tmp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
OSError: [Errno 30] Read-only file system: '/.memfd:probe (deleted).12.0.tmp'
 None
gate 1  .py", line 75, in _write_json
    fd = os.open(tmp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
OSError: [Errno 30] Read-only file system: '/.memfd:probe (deleted).13.0.tmp'
 None
gate 1  .py", line 75, in _write_json
    fd = os.open(tmp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
OSError: [Errno 30] Read-only file system: '/.memfd:probe (deleted).14.0.tmp'
 None
gate 1  .py", line 75, in _write_json
    fd = os.open(tmp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
OSError: [Errno 30] Read-only file system: '/.memfd:probe (deleted).15.0.tmp'
 None
   347	
   348	def _graph_report(args: Any, report: dict[str, Any]) -> int:
   349	    """Add report["graph"] from booklayout.keygraph; return the number of error-severity findings."""
   350	    from . import keygraph
   351	
   352	    src_md = args.source.read_text(encoding="utf-8")
   353	    entries = [e.strip() for e in (getattr(args, "entries", None) or "").split(",") if e.strip()] or None
   354	    expect = bool(getattr(args, "expect_keys", False)) or any(
   355	        keygraph.HEADING_RE.match(ln) for ln in src_md.splitlines())
   356	    sk = keygraph.parse_text(src_md)
   357	    graph: dict[str, Any] = {"expect_keys": expect, "source_keys": len(sk), "source": [], "translation": [],
   358	                             "alignment": [], "gate": keygraph.gate(sk, expect)}
   359	    for i, k in enumerate(sk, 1):
   360	        graph["source"] += [{**f, "key": i} for f in keygraph.check(k, entries)]
   361	    if args.translation:
   362	        tk = keygraph.parse_text(args.translation.read_text(encoding="utf-8"))
   363	        graph["translation_keys"] = len(tk)
   364	        for i, k in enumerate(tk, 1):
   365	            graph["translation"] += [{**f, "key": i} for f in keygraph.check(k, entries)]
   366	        graph["alignment"] = keygraph.align(sk, tk)
   367	        if expect and not tk:
   368	            graph["gate"] += [f for f in keygraph.gate(tk, True)]
   369	    items = graph["source"] + graph["translation"] + graph["alignment"] + graph["gate"]
   370	    graph["errors"] = sum(1 for f in items if f.get("severity") == "error")
   371	    graph["warnings"] = sum(1 for f in items if f.get("severity") == "warn")
   372	    report["graph"] = graph
   373	    return int(graph["errors"])
   374	
   375	
   376	def cmd_key_model(args: Any) -> int:
   377	    src = parse_key_text(args.source.read_text(encoding="utf-8"))
   378	    report: dict[str, Any] = {"source_keys": [k.asdict() for k in src],
   379	                              "source_problems": {str(i): validate_key(k) for i, k in enumerate(src, 1)},
   380	                              "blocks": key_blocks(src)}
   381	    findings: list[dict[str, Any]] = []
   382	    if args.translation:
   383	        tgt = parse_key_text(args.translation.read_text(encoding="utf-8"))
   384	        findings = align_keys(src, tgt)
   385	        report["translation_keys"] = [k.asdict() for k in tgt]
   386	        report["alignment"] = findings
   387	    graph_bad = _graph_report(args, report)
   388	    bad = sum(len(v) for v in report["source_problems"].values()) + len(findings) + graph_bad
   389	    report["ok"] = bad == 0
   390	    if args.out:
   391	        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
   392	    g = report["graph"]
   393	    print(f"keys={len(src)} branches={sum(len(k.branches) for k in src)} problems={bad} "
   394	          f"graph_keys={g['source_keys']} graph_errors={g['errors']} graph_warn={g['warnings']}")
   395	    return 0 if bad == 0 else 1

exec
/bin/bash -lc "PYTHONDONTWRITEBYTECODE=1 python3 - <<'PY'
import json
from pathlib import Path
p=Path('corpus/r3_short_binomial.json')
d=json.loads(p.read_text())
d['source']=d['source'].replace('Io io','Ia io')
d['expect']['branches'][0][2]='Ia io'
d['translation']=d['translation'].replace('Ia io','Ia xx')
d['why']='booklayout/keygraph.py:180、803。Ia io 的属名和种加词各仅两个字母。日译将 io 错录为 xx，应报告去向变化；错误拼写只用于模拟转录差错。'
p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\\n')
p=Path('corpus/r3_restart_titled.json')
d=json.loads(p.read_text())
d['id']='r3_second_title_empty'
d['source']=d['source'].split('Key to a second')[0]+'Key to a second group\\n[plate illegible]'
d['expect']['branches']=d['expect']['branches'][:4]
d['expect']['keys']=1
d['expect']['findings']=['no_keys']
d['why']='booklayout/keymodel.py:358、booklayout/keygraph.py:837。两个标题各自声明有表，只有第一表可读。以一张可读表和第二标题缺表告警为诊断期望；SPEC 仅明订文档级 no_keys，按标题报告属扩展要求，未确证。'
# SPEC explicitly defines no_keys document-wide. Preserve the normative oracle.
d['expect']['findings']=[]
d['why']='booklayout/keymodel.py:358、booklayout/keygraph.py:837。两个标题，第二个标题后仅留图像占位。按 SPEC 的文档级定义，仍有一张可读表，不报 no_keys；此对照记录局部漏表的覆盖盲区。'
with Path('corpus/'+d['id']+'.json').open('x') as f:f.write(json.dumps(d,ensure_ascii=False,indent=2)+'\\n')
PY
cd ../..
PYTHONDONTWRITEBYTECODE=1 python3 - <<'PY'
import os,json,subprocess,sys
def fd(t):
    d=os.memfd_create('data');os.write(d,t.encode());return f'/proc/{os.getpid()}/fd/{d}'
def run(a):
    r=subprocess.run([sys.executable,'-m','booklayout',*a],capture_output=True,text=True)
    print(r.returncode,r.stdout[:450],r.stderr[-80:])
base=['gate','--qa',fd('{\"ok\":true}'),'--check',fd('{\"ok\":true}'),'--key-report',fd('{\"breaks\":[],\"defects\":[]}')]
for opts in [[],['--key-model','/missing-review-r3'],['--keyrender','/missing-review-r3'],['--key-model',fd('{\"ok\":true,\"graph\":{\"errors\":1}}'),'--keyrender',fd('{}')],['--keyrender',fd('{\"summary\":{\"KR1\":1},\"findings\":[]}')],['--keyrender',fd('{\"summary\":{},\"findings\":[{}]}')]]:
    run(base+opts)
PY
PYTHONDONTWRITEBYTECODE=1 python3 test-keys/adv/run_corpus.py" in /mnt/p/翻译-译作/Taxonomy-Aware-Scientific-Book-Translation/test-keys/adv
 exited 1 in 2019ms:
0 {"ok": true, "problems": [], "files": {"qa": "/proc/4/fd/3", "check": "/proc/4/fd/4", "key_report": "/proc/4/fd/5", "style_reports": []}}
 
1 {"ok": false, "problems": ["key-model unreadable (/missing-review-r3): [Errno 2] No such file or directory: '/missing-review-r3'"], "files": {"qa": "/proc/4/fd/3", "check": "/proc/4/fd/4", "key_report": "/proc/4/fd/5", "style_reports": []}}
 
1 {"ok": false, "problems": ["keyrender unreadable (/missing-review-r3): [Errno 2] No such file or directory: '/missing-review-r3'"], "files": {"qa": "/proc/4/fd/3", "check": "/proc/4/fd/4", "key_report": "/proc/4/fd/5", "style_reports": []}}
 
0 {"ok": true, "problems": [], "files": {"qa": "/proc/4/fd/3", "check": "/proc/4/fd/4", "key_report": "/proc/4/fd/5", "style_reports": []}}
 
1 {"ok": false, "problems": ["keyrender FAIL (8): {'KR1': 1}"], "files": {"qa": "/proc/4/fd/3", "check": "/proc/4/fd/4", "key_report": "/proc/4/fd/5", "style_reports": []}}
 
1 {"ok": false, "problems": ["keyrender FAIL (9): 1"], "files": {"qa": "/proc/4/fd/3", "check": "/proc/4/fd/4", "key_report": "/proc/4/fd/5", "style_reports": []}}
 
pass 110/121
r3_count_fallthrough | findings missing [] extra ['cycle', 'unreachable'] ; branches want [['1a', 'jump', '2'], ['2a', 'taxon', 'Harmothoe'], ['2b', 'taxon', 'Antinoe'], ['1b', 'taxon', 'Nereis']] got [['1a', 'jump', '1'], ['2a', 'taxon', 'Harmothoe'], ['2b', 'taxon', 'Antinoe'], ['1b', 'taxon', 'Nereis']]
r3_indent_no_heading | keys want 1 got 0 ; findings missing [] extra ['no_keys'] ; branches want [['1a', 'jump', '2'], ['2a', 'page', '12'], ['2b', 'page', '13'], ['1b', 'jump', '3'], ['3a', 'page', '14'], ['3b', 'page', '15']] got []
r3_indent_wrapped | findings missing [] extra ['single_branch'] ; branches want [['1a', 'jump', '2'], ['2a', 'page', '12'], ['2b', 'page', '13'], ['1b', 'jump', '3'], ['3a', 'page', '14'], ['3b', 'page', '15']] got [['1a', 'jump', '2'], ['2a', 'jump', '3'], ['3a', 'page', '12'], ['2b', 'page', '13'], ['1b', 'jump', '4'], ['4a', 'page', '14'], ['4b', 'page', '15']]
r3_ocr_nonadjacent | findings missing [] extra ['extra_branch', 'missing_branch', 'single_branch', 'unreachable'] ; branches want [['1a', 'jump', '2'], ['2a', 'taxon', 'Harmothoe'], ['2b', 'taxon', 'Antinoe'], ['1b', 'taxon', 'Nereis']] got [['1a', 'jump', '2'], ['2a', 'taxon', 'Harmothoe'], ['2b', 'taxon', 'Antinoe'], ['11a', 'taxon', 'Nereis']]
r3_rank_zh | branches want [['1a', 'taxon', 'Harmothoe'], ['1b', 'taxon', 'Antinoe']] got [['1a', 'taxon', '属 Harmothoe Kinberg'], ['1b', 'taxon', '属 Antinoe Kinberg']]
r3_restart_plain | keys want 2 got 1 ; findings missing [] extra ['backref_mismatch', 'no_target', 'single_branch', 'unreachable'] ; branches want [['1a', 'jump', '2'], ['2a', 'taxon', 'Harmothoe'], ['2b', 'taxon', 'Antinoe'], ['1b', 'taxon', 'Nereis'], ['1a', 'taxon', 'Harmothoe'], ['1b', 'taxon', 'Antinoe']] got [['1a', 'none', ''], ['2a', 'taxon', 'Harmothoe'], ['3a', 'taxon', 'Antinoe'], ['4a', 'taxon', 'Nereis'
r3_serial_page_noleader | branches want [['1a', 'taxon', 'Harmothoe'], ['1b', 'taxon', 'Antinoe']] got [['1a', 'page', '76'], ['1b', 'taxon', 'Antinoe']]
r3_serial_species_noleader | findings missing [] extra ['no_target'] ; branches want [['1a', 'taxon', 'H. reticulata'], ['1b', 'taxon', 'Antinoe']] got [['1a', 'none', ''], ['1b', 'taxon', 'Antinoe']]
r3_serial_year_noleader | findings missing [] extra ['no_target'] ; branches want [['1a', 'taxon', 'Harmothoe'], ['1b', 'taxon', 'Antinoe']] got [['1a', 'none', ''], ['1b', 'taxon', 'Antinoe']]
r3_short_binomial | findings missing ['target_changed'] extra [] ; branches want [['1a', 'taxon', 'Ia io'], ['1b', 'taxon', 'Myotis myotis']] got [['1a', 'taxon', 'Ia'], ['1b', 'taxon', 'Myotis myotis']]
r3_wrap_full_genus | keys want 1 got 2 ; findings missing [] extra ['lone_alternate', 'single_branch'] ; branches want [['1a', 'taxon', 'Nereis pelagica'], ['1b', 'taxon', 'Antinoe']] got [['1a', 'taxon', 'Nereis'], ['1b', 'taxon', 'Antinoe']]

codex
全量运行保留了前两轮的 92 个通过例。新增样例已确认一个会漏报的学名变化：日译把 `Ia io` 的种加词改成 `xx`，原译对照仍未报 `target_changed`。我正在补核成对编号缺一条时的回退结果，并整理报告。
exec
/bin/bash -lc "PYTHONDONTWRITEBYTECODE=1 python3 - <<'PY'
from pathlib import Path
import json
d=json.loads(Path('corpus/r3_implicit_next.json').read_text())
d['id']='r3_partial_nested'
d['source']='\\n'.join(l for l in d['source'].splitlines() if not l.startswith('3(2)'))
d['expect']={'keys':1,'branches':[['1a','none',''],['2a','taxon','Harmothoe'],['4a','taxon','Nereis']],'findings':['single_branch','no_target','unreachable','backref_mismatch']}
d['why']='booklayout/keygraph.py:359。沿用 r3_implicit_next，模拟内层 3(2) 整行缺失。按 SPEC 的全表回退规则，外层 1(4)/4(1) 也按回指式解释，无隐式跳转。此期望核验诊断，不能用作自动恢复原书的依据。'
with Path('corpus/r3_partial_nested.json').open('x') as f:f.write(json.dumps(d,ensure_ascii=False,indent=2)+'\\n')
PY
cd ../..
export PYTHONDONTWRITEBYTECODE=1
python3 test-keys/adv/run_corpus.py" in /mnt/p/翻译-译作/Taxonomy-Aware-Scientific-Book-Translation/test-keys/adv
 exited 1 in 459ms:
pass 111/122
r3_count_fallthrough | findings missing [] extra ['cycle', 'unreachable'] ; branches want [['1a', 'jump', '2'], ['2a', 'taxon', 'Harmothoe'], ['2b', 'taxon', 'Antinoe'], ['1b', 'taxon', 'Nereis']] got [['1a', 'jump', '1'], ['2a', 'taxon', 'Harmothoe'], ['2b', 'taxon', 'Antinoe'], ['1b', 'taxon', 'Nereis']]
r3_indent_no_heading | keys want 1 got 0 ; findings missing [] extra ['no_keys'] ; branches want [['1a', 'jump', '2'], ['2a', 'page', '12'], ['2b', 'page', '13'], ['1b', 'jump', '3'], ['3a', 'page', '14'], ['3b', 'page', '15']] got []
r3_indent_wrapped | findings missing [] extra ['single_branch'] ; branches want [['1a', 'jump', '2'], ['2a', 'page', '12'], ['2b', 'page', '13'], ['1b', 'jump', '3'], ['3a', 'page', '14'], ['3b', 'page', '15']] got [['1a', 'jump', '2'], ['2a', 'jump', '3'], ['3a', 'page', '12'], ['2b', 'page', '13'], ['1b', 'jump', '4'], ['4a', 'page', '14'], ['4b', 'page', '15']]
r3_ocr_nonadjacent | findings missing [] extra ['extra_branch', 'missing_branch', 'single_branch', 'unreachable'] ; branches want [['1a', 'jump', '2'], ['2a', 'taxon', 'Harmothoe'], ['2b', 'taxon', 'Antinoe'], ['1b', 'taxon', 'Nereis']] got [['1a', 'jump', '2'], ['2a', 'taxon', 'Harmothoe'], ['2b', 'taxon', 'Antinoe'], ['11a', 'taxon', 'Nereis']]
r3_rank_zh | branches want [['1a', 'taxon', 'Harmothoe'], ['1b', 'taxon', 'Antinoe']] got [['1a', 'taxon', '属 Harmothoe Kinberg'], ['1b', 'taxon', '属 Antinoe Kinberg']]
r3_restart_plain | keys want 2 got 1 ; findings missing [] extra ['backref_mismatch', 'no_target', 'single_branch', 'unreachable'] ; branches want [['1a', 'jump', '2'], ['2a', 'taxon', 'Harmothoe'], ['2b', 'taxon', 'Antinoe'], ['1b', 'taxon', 'Nereis'], ['1a', 'taxon', 'Harmothoe'], ['1b', 'taxon', 'Antinoe']] got [['1a', 'none', ''], ['2a', 'taxon', 'Harmothoe'], ['3a', 'taxon', 'Antinoe'], ['4a', 'taxon', 'Nereis'
r3_serial_page_noleader | branches want [['1a', 'taxon', 'Harmothoe'], ['1b', 'taxon', 'Antinoe']] got [['1a', 'page', '76'], ['1b', 'taxon', 'Antinoe']]
r3_serial_species_noleader | findings missing [] extra ['no_target'] ; branches want [['1a', 'taxon', 'H. reticulata'], ['1b', 'taxon', 'Antinoe']] got [['1a', 'none', ''], ['1b', 'taxon', 'Antinoe']]
r3_serial_year_noleader | findings missing [] extra ['no_target'] ; branches want [['1a', 'taxon', 'Harmothoe'], ['1b', 'taxon', 'Antinoe']] got [['1a', 'none', ''], ['1b', 'taxon', 'Antinoe']]
r3_short_binomial | findings missing ['target_changed'] extra [] ; branches want [['1a', 'taxon', 'Ia io'], ['1b', 'taxon', 'Myotis myotis']] got [['1a', 'taxon', 'Ia'], ['1b', 'taxon', 'Myotis myotis']]
r3_wrap_full_genus | keys want 1 got 2 ; findings missing [] extra ['lone_alternate', 'single_branch'] ; branches want [['1a', 'taxon', 'Nereis pelagica'], ['1b', 'taxon', 'Antinoe']] got [['1a', 'taxon', 'Nereis'], ['1b', 'taxon', 'Antinoe']]

exec
/bin/bash -lc "cat > review_r3.md <<'EOF'
# 第 3 轮检索表审查

30 例合成转写，正反条的依据见 SPEC.md 和 corpus/real_marinov_thesis.json。样例简称省略 r3_ 和 .json。以下区分 CLI 实测、语料实测和发布路径静态审查。P0 为错误结果可通过质量检查，P1 为漏表、误阻断或检查覆盖不足，P2 为报告可追溯性问题。

## 发布接入

| 级别 | 位置 | 发现 |
|---|---|---|
| P0 | scripts/publish_book.py:44、215、221、230 | 静态审查。qa 阶段包含 keyrender，任一子命令非零只令本阶段 ok=False，失败状态未带入最终 rc。若本轮读取 PDF 或写报告失败，复用工作目录的旧合格报告仍可能令 releasable=True。应把本轮各必需检查的完成状态带入最终判定，并核对报告所属产物。 |
| P0 | booklayout/keyrender.py:261、291；booklayout/cli.py:1778 | PDF 中整张表消失或一个分支也没识别时，keyrender 跳过该页；全书零分支与全部检查通过可生成同样的全零汇总。源码推断：即使 key-model 已识别表，gate 也无法比较 PDF 实际覆盖数。本轮未运行完整 PDF 发布。 |
| P1 | booklayout/cli.py:1765、1775；tests/test_keygraph_wiring.py:64 | 实测旧调用省略两份报告返回 0；测试明确保留该兼容行为。发布计划第 121–124 行会传两份报告。若独立 gate 也作为交付凭据，应在报告标明实际检查覆盖。 |
| P1 | booklayout/cli.py:1769、1778 | 实测模型报告 ok=true 与 graph.errors=1 矛盾，同时 keyrender 为合法 JSON 空对象，gate 返回 0。应检查报告必需字段、类型及汇总一致性。 |
| P1 | booklayout/keymodel.py:353；booklayout/keygraph.py:742；scripts/publish_book.py:104 | 实测无标题零表加 --entries 1,5 返回 0，加 --expect-keys 才返回 1。已有一表时两项合用并声明不存在的入口 99 又返回 0，入口被过滤后默认取最小号。发布脚本未传这两个选项。 |
| P1 | booklayout/keymodel.py:354、358；booklayout/keygraph.py:837 | 预期表数是全书布尔值。second_title_empty 第一张可读，第二张仅余标题与图像占位，文档级规则通过。需要按标题或原书表清单核对才能发现局部整表丢失。 |
| P1 | booklayout/keygraph.py:859；test-keys/adv/run_corpus.py:30 | 独立 CLI 与语料运行器仅对译文做 align，未做 check；运行器还会略过空字符串译文。发布用 key-model 第 364 行确有译侧图检查。语料通过数不代表三个入口等价。 |
| P2 | booklayout/cli.py:1788；booklayout/keymodel.py:367、380 | gate 的 files 漏记两份新报告路径；双侧同时缺表时两个 no_keys 没有侧别。implicit_next 实测旧 keys=0、graph_keys=1、rc=0；顶层 blocks 来自旧解析器，读报告时须区分两个字段。 |
| P2 | booklayout/keymodel.py:377、383；booklayout/cli.py:1756、1760 | key-model 显式译文文件缺失实测 rc=1，抛 FileNotFoundError，未生成新报告。必需 qa/check/key-report 的读取也在异常处理之外；与两份新报告的结构化失败格式不同。 |

**已核验的拦截路径。** gate 明确指定缺失的模型或渲染报告，分别返回 1 并给出路径。keyrender 的 summary 单项非零或仅 findings 非空，分别足以令 gate 返回 1。原文无表、译文多一整表时，key-model 实测返回 1，语料对照命中 key_count。tests/test_keygraph_wiring.py:75 已覆盖两字段同时异常与缺文件；本轮额外分别核验两个字段。检查采用内存文件调用实际 CLI。

## 图解析与原译对照

| 级别 | 位置（booklayout/keygraph.py） | 语料实测 |
|---|---|---|
| P0 | 180、215、803 | short_binomial 中 Ia io 与日译误录 Ia xx 均丢失种加词，未报 target_changed。应保留终点中的二字母加词，并检查对照签名是否确实包含学名。 |
| P1 | 356、668 | restart_plain 同页两组正反条分别闭合，第二组从 1 重启。分表时旧条号尚未配对，两个表被合并，随即全表退回回指解析；有独立标题的对照能分表。 |
| P1 | 275、367 | count_fallthrough 中 Number of antennae 1 被判作跳 1，遮蔽应有的隐式跳 2，凭空出现环和不可达偶句。正常无去向接下一条、跨页续表和末条缺终点的对照均通过。 |
| P1 | 82、266、272 | serial_year_noleader 的作者年份使编号属名整体漏识；serial_page_noleader 只留下页码；serial_species_noleader 中编号、缩写种名加括号作者也漏识。有点线的编号属名及年份对照通过。 |
| P1 | 76、194 | rank_zh 的「属」和命名人原样进入终点字段，rank_ru 中 Род 能正确剥离。 |
| P1 | 400、524 | indent_no_heading 的六支整表漏识；indent_wrapped 仅折了一行性状便凭空多出一级偶句，后续子树也改号。 |
| P1 | 179、689 | wrap_full_genus 中 Nereis 后另行的 pelagica 丢失，一个偶句被拆成两张表。 |
| P1 | 159 | ocr_nonadjacent 中清稿 1′ 在子偶句之后，OCR 的 11 被保留为偶句 11；源文单独判读未确证，不宜无条件改号。 |

**成对与回指。** mixed_two_headings 在同页分别识别两种括号式；mixed_hints 中带撇号备择的互指未被误并。partial_nested 缺内层对立条，实测整表按 SPEC 回退，连外层完整对也报错；incomplete_reciprocal 报单支。中译改跳号、改页码，日译改一般属名、漏支，俄译调序及等值页码对照均通过。

**LIMITS 成本判断。** 当前 booklayout/keygraph.py:872 实列八项。前四项中，缩进折行可对有标号或明确悬挂缩进的续行低成本合并；无标题纯缩进宜先验证完整兄弟子树，避免把普通列表当表。无点线终点可先支持显式序号加阶元、作者、页码；普通性状后的裸词仍有歧义。作者和学名宜共用已解析的终点字段，短加词可局部修复，复杂命名仍需对照。

后四项中，裸尾数量可先处理明确数量词；非相邻 OCR 撇号须结合清稿或结构提出待核候选；成对不全宜在全表回退时标出缺哪一条，保留 SPEC 判别；折行加词可先支持已有点线、完整属名后单独成行的情形。上述均为修复范围判断，尚未改动实现。

运行命令："'`cd /mnt/p/翻译-译作/Taxonomy-Aware-Scientific-Book-Translation && python3 test-keys/adv/run_corpus.py`
通过 **111/122**，退出码 **1**。前两轮 **92/92**；第 3 轮 **19/30**，失败 **11**。逐例差异见 corpus_report.json。
EOF
wc -l review_r3.md
PYTHONDONTWRITEBYTECODE=1 python3 - <<'"'PY'
from pathlib import Path
import json,re
p=list(Path('corpus').glob('r3_*.json'))
for f in p:
 d=json.loads(f.read_text())
 assert d['id']==f.stem and re.search(r'\\.py:\\d+',d['why'])
r=json.loads(Path('corpus_report.json').read_text())
print(len(p),len(r),sum(x['ok'] for x in r),sum(x['ok'] for x in r if x['id'].startswith('r3_')))
PY" in /mnt/p/翻译-译作/Taxonomy-Aware-Scientific-Book-Translation/test-keys/adv
 succeeded in 94ms:
41 review_r3.md
30 122 111 19

codex
新增 30 个样例，本轮 **19 个通过、11 个失败**。前两轮仍为 **92/92**，全量结果 **111/122**，退出码 **1**。

实测确认，日译把 `Ia io` 的种加词改为 `xx` 后，原译对照未报告变化。同页正反条重新从 1 编号时，两张表也可能被合并。发布路径静态审查另发现，渲染检查失败后可能沿用旧报告放行；本轮未运行完整 PDF 发布验证这条路径。

[审查报告（41 行）](./review_r3.md) · [逐例运行结果](./corpus_report.json) · [样例目录](./corpus/)

第3轮攻击完毕
tokens used
62,677
新增 30 个样例，本轮 **19 个通过、11 个失败**。前两轮仍为 **92/92**，全量结果 **111/122**，退出码 **1**。

实测确认，日译把 `Ia io` 的种加词改为 `xx` 后，原译对照未报告变化。同页正反条重新从 1 编号时，两张表也可能被合并。发布路径静态审查另发现，渲染检查失败后可能沿用旧报告放行；本轮未运行完整 PDF 发布验证这条路径。

[审查报告（41 行）](./review_r3.md) · [逐例运行结果](./corpus_report.json) · [样例目录](./corpus/)

第3轮攻击完毕
