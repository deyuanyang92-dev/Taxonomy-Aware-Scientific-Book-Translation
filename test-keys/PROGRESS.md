# 进度 2026-11-24
## 目标
设计「性状矩阵 → 多阶元混合检索表（科→属→种）」制作软件，在 keykit 内新增 matrix 模块；先调研现有软件，再 Opus 定计划，Codex 对抗优化算法与逻辑。用户要求：haiku 下载、sonnet/haiku 整理、opus 顶层计划、尽量用 REPL 省 token。
## 已完成
- haiku 下载 17 项到 survey/repos/（记录 survey/DOWNLOAD_A/B/C.tsv）。失败 3 项：DKey/DrawWing（无公开仓库）、biokey（CTAN 取不到）、Free DELTA（sourceforge 克隆失败）。monographaR 取自 CRAN Archive 1.3.0；Xper2/Xper2 仅 1 文件，未确认是原版。
- sonnet 读码笔记 15 份：survey/notes/*.md（monographaR、dimoose、dichotomousKey、dichot、Clavis、clavis-pipeline、open-delta、sdd-sdk、keybase_model、keybase、TSKey、tombiovis、TaxonWorks、Symbiota、edichokey）。
- 要点：dimoose 评分 a*b/cost，全 0 退化 (a+b)/cost（matrix.R:409-410），多态两支都走，记忆化 DAG，mergeKeys 把属表接科表叶（prune.R:384），validate() 五类错误；open-delta 含完整 KEY 算法（MPL 1.1，文件头判断）；Clavis 只有 schema+校验，无建树；monographaR 靠 rpart；dichot 与检索表无关，应剔除；sdd-sdk 仅 clavis.ts。
## 未完成 / 下一步
- 派 Opus 子代理读 survey/notes/ 出总计划（keykit/matrix.py：矩阵 IR、分裂准则、多态/数值/缺失、层级链接 mergeKeys 式、输出到现有 KeyIR），写 survey/PLAN.md。
- 再派 codex-reviewer 对抗审算法与逻辑（用户已点名 Codex）。
- 精读 open-delta KEY 算法笔记，决定借鉴点。
## 关键决定
- 新功能放 keykit，不动 booklayout；许可证 GPL 的 dimoose/monographaR 只借思路不抄码。
- 用户在中途打断过一次，后续步骤等用户确认再继续。
## 文件位置
- /mnt/p/翻译-译作/Taxonomy-Aware-Scientific-Book-Translation/test-keys/survey/{repos,notes,DOWNLOAD_*.tsv}
- keykit：.../test-keys/keykit/（README.md、RULES.md、SPEC_tool.md）
## 坑
- yzz-tasks 钩子会把子代理回报的要点行误抽成任务清单；已改写 .claude/tasks-2ccd2862-*.md。
- 工作区有 92 个未提交改动，动手前建议先 commit。
## 仍在跑的任务
- 无
