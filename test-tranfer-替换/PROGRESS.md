# 进度 2026-11-23
## 目标
设计「多语种分类术语 → 英文义项 → 中文」自动映射方案（含专家修订），经 Codex 对抗审核后定稿，再做西语小试点。
## 已完成
- v0.1 → Codex 第一轮 → v0.2 → Codex 第二轮（结论「需再改」，给最少清单 6 条）。
- 2026-11-23 改成 v0.3：语境使用条件（短语整体/结构位置/逐处确认）、E/X/O 三方独立验收、统一资格接口 eligible() 封旧入口（term_presub TSV、HARD、review apply）、版本与撤销（中文侧变化也撤销）、不变量决策表、网页修订协议先行、试点冻结（阶段 A 零模型 / 阶段 B 需批准）。
- 用户新要求已写入第 13 节：revisions 追加日志，每次专家修改留痕；退回、撤销采纳、多条意见并排多选一、对象历史；命令 yiku rev import/queue/adopt/reject/return/revert/history。
- 已核源码：yiku/yiku/cli.py:208 review apply 原地 UPDATE terms，无历史表 → 需新建 revisions。
## 未完成 / 下一步
- 等用户看 v0.3，并定两件事：① 阶段 B 引擎（建议 deepseek-flash 非思考、离峰、≤5 页）；② 是否 Codex 第三轮审。
- 之后：第 11 节第 1 步最小闭环（新表+eligible()+原文枚举器+三方核对+旧入口回归测试+revisions/yiku rev）→ 阶段 A 零模型试点；用户提供西语文章目录。
## 关键决定
- 英文作义项中枢/检索标签，不强制两跳翻译；术语只进 yiku；默认不用大模型。
- 库内唯一≠语境唯一；无使用条件的 link 按逐处确认。
- 专家修改只追加不覆盖；外部修订默认是建议，本地裁定人采纳才生效。
- 同源转写「主力」改为未确证，由试点数据定。
## 文件位置
- 方案 v0.3：/mnt/p/翻译-译作/Taxonomy-Aware-Scientific-Book-Translation/docs/plan_multilingual_terms.md（副本：本目录 plan_multilingual_terms.md，内容一致）
- 审核：同 docs/ 下 plan_multilingual_terms.codex_review.md、plan_multilingual_terms.codex_review2.md
- yiku：~/.yiku/yiku.db；日语候选 bench/term_cand/cand_ja.tsv（未入库）
## 坑
- codex exec 的 -o 要绝对路径；调用：codex exec --skip-git-repo-check -s read-only -m gpt-6.1-sol -o <abs> - < prompt文件。
- shell 命令里写 U+3000 会被 guard 拦（E1）；查全角空格用 JS includes。
- 工作区 89 个未提交改动，未 commit。
## 仍在跑的任务
- 无
