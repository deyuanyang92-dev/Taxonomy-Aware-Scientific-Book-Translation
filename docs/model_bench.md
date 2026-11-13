# 模型比测（2026-11-12）

目的：为初译和核译选模型提供依据。同一提示词（RULES + 分类学领域包 + STYLE + 输出要求 + yiku 术语表）下，各模型翻译同样的样段，先脚本粗筛，再由评者盲评。

工具：`scripts/bench/bench.py`（`terms` 生成术语表，`run` 多 engine 翻译，`eval` 自动评分，`blind` 生成盲评目录并把字母映射另存 json，`tally` 汇总评者填的表）；调用走 `scripts/llm_engines.py`，每次调用的 token 与耗时记入工作目录的 `usage.tsv`。

## 样本与评者

- 样段 4 段，每段约 3300 至 3700 字符，取自环节动物专著工程（Rouse 2022、Handbook of Zoology Annelida）的章节：P1 系统学（ch01）、P2 刚毛（ch02）、P3 齿吻沙蚕形态（ch12）、P4 龙介虫形态（ch39）。
- 每段的各份译文用随机字母编号，评者不看映射，评完再对照。重大 = 改变原意或违反硬规则；轻微 = 表达或格式。
- 评者是 Claude Opus 5.5，**可能偏向 Claude 一家**；样本只有 4 段，差一两条不构成显著差异。本表是选型的初步依据，不是定论。

## 盲评结果

| 模型 | 重大 | 轻微 | 说明 |
|---|---|---|---|
| Claude Opus | 0 | 2 | 4 段全部忠实完整；唯一识别出跨页未完句并注明、页脚不译 |
| Claude Sonnet | 1 | 2 | 重大 1 条为跨页未完句误接页眉 |
| DeepSeek flash | 2 | 6 | 重大 2 条在 P1（跨页句误接；自拟类群名 Vestimentifera 未标暂定） |
| DeepSeek v4-pro | 2 | 9 | 重大含 P3 把 pre-/postchaetal lamellae 译成「鳃小瓣」；轻微条数最多 |
| Codex（GPT-6 Luna） | 5 | 6 | P3 把 antennae 与 palps 都译成「触角」；P2 漏译 "similar in all cases" |
| Claude Haiku 5.5 | — | — | P2、P3、P4 以版权为由拒译，只完成 P1（重大 1、轻微 1）；P2 加了「用途说明」句后仍拒译，原件存档于比测目录 |

## 自动评分（脚本粗筛，只用于发现异常）

术语落实率只统计 yiku「已核」且原文出现的术语，按字面匹配译名，同义写法会被当作漏。四段合计（Haiku 只有 P1 一段，不可比，略）：

| 模型 | 术语落实 | 数字保留 | 拉丁学名保留 |
|---|---|---|---|
| Claude Opus | 90/108（83%） | 121/121 | 90/91 |
| Claude Sonnet | 91/108（84%） | 121/121 | 89/91 |
| Codex | 91/108（84%） | 121/121 | 88/91 |
| DeepSeek flash | 87/108（81%） | 121/121 | 55/91 |
| DeepSeek v4-pro | 93/108（86%） | 121/121 | 63/91 |

读法：数字全部保住；术语落实率各家只差几个百分点，不能据此排名；**DeepSeek 两个型号的拉丁学名保留明显偏低**（55/91、63/91，其余在 88 以上），译文里学名常被改写或译成中文，核译时要把学名列入重点核对项。

## 运行中的发现

- **推理耗尽**：DeepSeek 在 `max_tokens=16000` 时，推理占满上限、正文为空。flash 在 P4 出现 1 次，v4-pro 在 P2、P3 各 1 次（4 段中 2 段）。改为 64000 后重试成功，`llm_engines` 因此默认 64000，并在正文为空且输出达上限时报「推理耗尽」。
- **版权拒译**：Haiku 5.5 对整段连续正文以版权为由拒译。系统提示词开头的「用途说明」句（用户拥有本书、仅供个人学习研究）在初译提示词里保留，作为保险；它对 Sonnet、Opus 等是否必要未单独对照，未确证。
- **跨页未完句**：多数模型把页眉词（如 Annelida）误接到一句未完的话后面。分块前应先用 `split_figures.py` 去掉图注、清理页眉页脚碎片。
- **闲时计价**：DeepSeek 忙时不发请求，等到闲时再调（`deepseek_offpeak.py`）。

## 据此的默认分配

初译 `claude-sonnet`，核译 `deepseek-flash`（初译与核译必须是不同的模型）。依据：Sonnet 重大错误最少的一档，仅次于 Opus；flash 价格低、核译只需读和报问题，不需要自己写出完整译文。这是成本与质量的折中，不是 flash 译文质量最好；最终仍由主会话抽查裁定。

## 复现

```bash
python3 scripts/bench/bench.py terms D            # D/src/*.txt 放样段原文
python3 scripts/bench/bench.py run D --engines claude-sonnet,claude-opus,deepseek-flash,deepseek-v4-pro,codex
python3 scripts/bench/bench.py eval D             # scores.tsv、term_miss.tsv
python3 scripts/bench/bench.py blind D --seed 1   # 盲评目录，映射在 D/blind_key_*.json
python3 scripts/bench/bench.py tally D            # 评者填完 D/盲评_*.md 后汇总
```

## 参照译本对照比测（refcompare，2026-11-13）

用途：拿本流水线的译文去对照名家中译本（或对照本流水线的两次运行，例如改了技能规则之后），回答「差在哪里、规则改了有没有用」。工具 `scripts/bench/refcompare.py`，翻译与评审调用都走 `llm_engines`，单元测试 `tests/test_refcompare.py`（假引擎，不联网）。

工作目录 D 里放配置 `refcompare.json`（或 `.yaml`）和样段：`D/<段>_en.txt` 原文、`D/<段>_pub.txt` 参照译本（先清洗对齐，只留正文）。配置要点（全部字段见脚本开头的说明）：

```json
{"passages": ["S1", "S2", "S3"], "domain": "进化生物学", "term_domains": ["进化生物学", "科学史"],
 "book_desc": "（作者，书名，年份 的一段）", "skill_dir": "/root/.claude/skills/yzz-translate",
 "engines": {"draft": "claude-sonnet", "review": "codex-sol", "judges": ["codex-sol", "cursor-grok"]},
 "leakage": {"exclude_sources": [], "exclude_note_like": ["Mayr 中译本"], "no_usage": true,
             "exclude_docstore_keys": ["Mayr1982_zh"]}}
```

防泄漏：参照译本不能进术语表。`leakage` 把 yiku 库复制一份（`terms/yiku_filtered.db`，原库不动），删掉 `exclude_sources` 来源的术语和 note 含 `exclude_note_like` 子串的术语（例如 note 写着「与某中译本一致」的核定条目）；`no_usage` 对应 `yiku table --no-usage`（不从资料库取中文用例）；不关用例时，`exclude_docstore_keys` 经环境变量 `YIKU_USAGE_EXCLUDE_KEYS` 让这些 docstore 键不当用例来源。

流程（每步已有产物先查 `.meta.json`，引擎、系统提示词、用户消息的 sha256 一致才跳过，不一致报 `StaleOutputError`，`--force` 重做）：

```bash
refcompare.py terms D/refcompare.json                           # 术语表（已有则不重做）
refcompare.py draft D/refcompare.json --run ours3 -j 3          # 初译 -> D/ours3/<段>_draft.txt
refcompare.py review D/refcompare.json --run ours3 -j 3         # 核译 + 精确替换 -> D/<段>_ours3.txt，拒收记 D/ours3/<段>_rejects.jsonl
refcompare.py judge D/refcompare.json --run ours3 -j 6          # 盲评 pub 对 ours3 -> D/judge/pub_vs_ours3/
refcompare.py compare-runs D/refcompare.json ours2 ours3 -j 6   # 两次运行互比（同一盲评方案）
refcompare.py aggregate D/refcompare.json pub_vs_ours2 pub_vs_ours3 ours2_vs_ours3
```

- 核译：问题单 old 必须在译文里恰好出现 1 次，新旧不同；非「术语/误译/漏译/增译」类改动不得丢英文词或数字；改动若把 HARD 术语译名改掉则拒收（纯删除除外）。拒收原因逐条记 `rejects.jsonl`。
- 盲评：每段每评委独立随机 A/B，映射存 `judge/<对>/key.json`；评委按 MQM 输出严格 JSON（错误的 category 与 severity、每版本 0 到 100 分、preferred）。输出不合格重试，至多 3 次。`aggregate` 解盲后给逐段分数、偏好、错误计数表（合计和分评委）和 MQM 罚分（major=5、minor=1），多对时末尾加「版本 × 类别」对照。
- 读法：评委是 LLM，偏爱贴近原文、带括注原词的译法；核译员兼评委有自我偏好风险（用不同厂家的评委对照）；同一批样段上反复改规则再测是样本内检验，只能说明规则「被执行了」，不能说明对新段落也有效。
- 隔离：codex 在新建空临时目录里运行（`llm_engines._codex` 的 `-C`），但 read-only 沙箱仍可读全盘，所以核译与评委提示词都写明不得读本地文件（含 `~/.yiku`）。

首次使用的记录在 `/mnt/p/翻译-译作/_比测/2026-11-13_Mayr对照/`（Mayr《生物学思想的发展》三段对照中译本）。
第 3 轮（同一三段，当前技能重跑，`ours3`）：对中译本的盲评与第 2 轮持平（我方均分 97.7/92.0，第 2 轮 98.0/91.7，均 6/6 偏好我方）；第 2 轮对第 3 轮的互比里第 2 轮占优（4/6），翻译腔类 minor 没有减少；字面可执行的规则（Mendelism 译「孟德尔主义」、成语化、块首块末不加译不漏译）起了作用。这是样本内检验，且每个版本只采样一次，不能当作规则泛化的证据。
