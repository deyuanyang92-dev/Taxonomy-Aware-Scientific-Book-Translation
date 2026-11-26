# 进度 2026-11-21
## 目标
全书结构化拆分的顶层设计（扫描 PDF → OCR → 对齐 JSON → 按页/章翻译排版，改错快且省 token），在 booklayout 里实现补丁协议并小测优化。
## 已完成
- 第 1–13 轮审查全部处理；第 13 轮由 Claude sonnet 子代理复审，无实质问题（review13_claude.md）。
- 修 _with_locks fd 泄漏（booklayout/cli.py:1378）。
- 提交 d2fc61e（main，未推送）：booklayout 8 个文件 + 8 个测试 + 3 份 docs + test_dividepagraph/*.md。
- tests/test_block_old_hash.py 81 项通过；ruff 通过。
## 未完成 / 下一步
- 看全仓库 pytest（不带 -x）结果：test_dividepagraph/full_pytest2.log。
- 已知失败：tests/test_usage_monitor.py::test_summary_exports（usage_monitor CSV 改成按组汇总，断言还找 deepseek-flash；与本方案无关，未改，需确认该保留引擎列还是改测试）。
## 关键决定
- 用户 2026-11-21 明确：停用 Codex，不再要求放行，不再把 Codex「无实质问题」作收尾条件。
- 6 条已知限制保留（都等持久 block id）：见 00_top_design.md 末尾。
## 文件位置
- 设计：test_dividepagraph/00_top_design.md
- 审查记录：test_dividepagraph/codex_review*.md、review13_claude.md
- 任务清单：test_dividepagraph/.claude/tasks-32eb70ed-ed35-4fe0-bdb5-d1033a1c4ef8.md
## 坑
- codex exec 被权限分类器拒绝，不要重试。
- 从 /tmp 运行脚本会导入 /root/github 那份 booklayout，不是本目录；在仓库根用 python3 -m 或 pytest。
- 提交只含 booklayout 相关文件；scripts/、docstore/ 等其他未提交改动原样留在工作区。builder.py、profile.py 带了其他改动一并提交。
## 仍在跑的任务
- 全仓库 pytest｜约 4 分钟｜test_dividepagraph/full_pytest2.log
