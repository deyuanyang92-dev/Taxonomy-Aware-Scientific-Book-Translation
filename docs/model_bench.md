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
