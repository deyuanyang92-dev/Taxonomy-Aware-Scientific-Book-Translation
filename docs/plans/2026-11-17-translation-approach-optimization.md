# 翻译思路比对与优化（Cursor，2026-11-17）

对照：ISO 17100:2015 / ISO 18587、国内出版「三审三校」、主流 CAT/长书流程；本仓库 `docs/comparison.md`、`docs/workflow.md`、`docs/booklayout.md`、`skill/STYLE.md`、Cursor 省 token 档。

**结论一句话：** 分章做、按档交付；「省 token 默认」只等于试译/量产草稿，**正式交付必须走异模型双语审 + 三校脚本闸 + 文风通读**，不能拿 lean/verify=none 当出版合格。

---

## 1. 主流在做什么

| 来源 | 核心要求 | 我们已有 | 缺口 |
|---|---|---|---|
| ISO 17100 | 译 → 自检 → **另一人双语修订** →（可选）领域单语审 → 交付前核验 | M4 初译、M5 异模型译审、M8 裁定 | `auto_translate` 默认 verify=none 易误当「已审」 |
| ISO 18587 | 机翻后译后编辑（轻/全） | Google + lean 改写 ≈ 轻编辑 | 交付档须标明轻/全，不可混称「已全编」 |
| 国内三审三校 | 一/二/三审（内容）+ 三校（校样） | 排版侧 `booklayout qa` 三审三校（结构/版式/文字脚本） | **译文内容三审**未与排版三审对齐；复盘：三审文字只扫 body≈25% 块 |
| 长书实践 | **按章**译与审、样章试译、术语冻结、并行章 | `run_batches --chapters`、`fast_book chapters`、M3 样章 | 整书 md 一条龙多，章级进度/交付清单弱 |
| CAT/QA | 术语一致、数字、空译、TM | yiku、transqa、human_review_queue | 交付闸须阻断，不能只写 report |
| 文风 | 领域语体 + 终稿单语通读 | STYLE / POLISH / 志书表述；进化书有「名家通读」 | 分类电报体「优雅」= 志书体，不是散文腔 |

---

## 2. 三个焦点的优化定案

### 2.1 是否分章节？——**必须分章（交付与并行都以章为单元）**

| 做法 | 定案 |
|---|---|
| 切分 | 按原书章/篇；检索表、图版、索引可独立「章」 |
| 进度 | 每章：术语表 → 初译 → 译审 → 验证 → 裁定；全书术语与异写共享 |
| 并行 | `fast_book chapters`：章互不抢写同一文件；块内再 `-j` |
| 整书 md | 只作内部拼接或试跑；**交付物以章审通过后再合** |
| 样章 | M3：1–2 章错误率 ≤5% 再铺开（已有，坚持） |

依据：ISO 与行业长书均章级管理；本仓库 term_impact、yiku 均按章受益。

### 2.2 「三审三校」严格交付质控？——**要，但映射成两套闸，勿与省 token 默认混用**

把国内出版用语映射到本系统（避免空喊口号）：

| 出版用语 | 本系统对应（交付档强制） | 可否用 LLM |
|---|---|---|
| **一审**（责编：忠实、漏增、术语） | 异模型双语核译（M5）或 `auto_translate check` + **非 none 的 verify**；critical → 人工队列 | **1 次 LLM 找错 + 1 次异模型裁定**（交付例外：允许第二模型；与「试译档至多 1 次」分开） |
| **二审**（室主任：学科与一致） | 分类学验证 + 表述核译（M6/M7）+ yiku/drift；主会话抽查 | 脚本为主；表述可用模型出问题单 |
| **三审**（终审：可否出书） | 主会话 + 用户：样章/抽检页签字；`report` + `audit_sample` | 人；可选 Sonnet 盲评抽检（不计自动通过） |
| **一校** | 对齐/覆盖：`transqa`、段 ID、页标记、normalize | 脚本 |
| **二校** | 排版：`booklayout qa` 一/二审（结构+版式） | 脚本 |
| **三校** | 文字+成品：`booklayout qa` 三审（扩到 caption/entry）+ `zh check` + italic | 脚本 |

**硬规则（Cursor 优化后的澄清）：**

1. **试译/量产草稿档**（省 token）：lean 开、verify=none、跨书 memory —— 见 `docs/CURSOR_OPTIMIZATION_2026-11-17.md`。产物标 `draft`，**不得标交付**。
2. **交付档**：必须分章；必须异模型双语审；critical 人审；`booklayout` 三审全 ok；复盘缺口（caption 等）未修前 gate 不得当「无译文错误」。
3. 禁止用多轮 LLM 代替三校脚本；禁止同模型「自审」冒充一审。

### 2.3 翻译是否足够优雅？——**分体裁定义「优雅」**

| 体裁 | 「优雅」标准 | 做法 |
|---|---|---|
| 物种描述 / 检索表 / 产地 | **志书电报体**（具/无、阿拉伯数字、短句、方位词统一） | 领域包第 5 节 + 例句检索；**不**为流畅加字 |
| 叙述 / 总论 / 进化思想 | **名家中文**：先结论后条件、少名词化、括注克制 | `polish` 单语通读（STYLE §6）+ cite_diff 防改坏事实 |
| 图注 | 短、术语准、学名斜体 | taxoformat + 图注通道；图注宜进 lean 改写 kinds 或单独档 |
| 一律禁止 | AI 腔、生造四字、无依据拔高、同段多译名 | `de_ai_tone` / zh_style 规则 |

人工评读已证：**准确性可优于名家译本，可读性常落后**——交付档叙述段必须跑 polish；分类描述以志书体为准，不追「文学优雅」。

---

## 3. 推荐流水线（交付）

```
样章 1–2 章（全流程）→ 通过
    ↓
按章并行：术语 → Google+表 → lean 改写叙述/图注
    ↓
异模型双语审（verify ≠ none）→ human_review critical
    ↓
脚本：transqa / taxon_validate / yiku / italic
    ↓
叙述段 polish（单语）→ cite_diff
    ↓
合章 → booklayout 三审三校 → zh check
    ↓
抽检签字 → 交付（标档位与引擎）
```

试译可停在「lean + verify=none + transqa」，并写 `status=draft`。

---

## 4. 与 Cursor 省 token 档的关系

| | 试译档（默认 CLI） | 交付档 |
|---|---|---|
| lean | 开 | 开（描述仍不上全文改写） |
| verify-engine | none | **必设异模型**（如 flash 找错 + sol/luna 裁定） |
| 分章 | 建议 | **强制** |
| polish | 可选 | 叙述/总论 **强制** |
| booklayout qa | 可不跑 | **强制 ok** |
| 标签 | draft | release |

省 token 不取消质控，只是把「默认烧三轮模型」改成「草稿省、交付严」。

---

## 5. 待实现（软件，按优先级）

| ID | 项 | 验收 |
|---|---|---|
| T1 | CLI/报告区分 `tier=draft|release`；release 缺 verify 或未分章则拒绝 | 命令行拦截 |
| T2 | 章级交付清单（每章：draft/revised/checked/polish/qa） | 一文件看齐 |
| T3 | booklayout 三审扩到 caption/entry（复盘 P1） | 覆盖率门槛 |
| T4 | lean kinds 默认含 `caption`（或交付档自动加） | 图注不再最差 |
| T5 | 交付门一键：`scripts/delivery_gate.py` 串 transqa+验证+qa+zh check | 非 ok 退出码 1 |

本轮（Cursor）先落**思路文档与档位澄清**；T1–T5 实现另开或挂 #26/#32。

---

## 6. 依据

- ISO 17100 流程概述：https://iso17100.com/translation-process/
- 国内三审三校制度说明：中国编辑出版人才网相关条目（责编/室主任/总编 + 三校）
- 本仓库：`docs/comparison.md`、`docs/workflow.md` §2.1、`docs/booklayout.md`「三审三校」、`docs/research/2026-11-17/booklayout-delivery-postmortem.md`、`skill/STYLE.md`、`docs/research/2026-11-15/budget_tiers.md`
