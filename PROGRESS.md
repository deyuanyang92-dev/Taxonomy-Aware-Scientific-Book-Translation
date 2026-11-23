# 进度 2026-11-22（日英对照表测试）
## 目标
测试 Google 整理的日→英对照表（bench/term_cand/cand_ja_batch_google-summary.tsv）能否优化 Imajima 日→英翻译和纠正 OCR 错字。默认译名以 Rouse 2022 + Handbook 为基准。
## 已完成
- 表 1422 条；用 bench/term_cand/ja_en_baseline.py 对照基准主表 master_en_terms.tsv：276 条命中基准(base)、986 nobase、160 无英文。输出 bench/term_cand/cand_ja_baseline.tsv。
- OCR 试算（只读、未应用）：5 条规则（鳞→鱗、侧→側、触系→触糸、内田絃臣→内田紘臣、分布一→分布―）影响 140 页，抽看无误伤。规则已还原，未写入 ocr_fix.toml。
- 翻译 A/B（Imajima2007 p.57/177/217，仅 Google 免费、0 费用；参考=en/checked.md，chrF 仅作相对）：纯Google 60.6/命中38；现有presub 63.9/139；presub+表 64.5/395；剔除12个有疑术语+OCR纠错 64.9/368（最优）；占位符还原更差(63.4)且有1处残留。
- 结论：送 Google 前用 --presub 替换英文术语有效；--glossary 在免费流程里不起作用（Google 稿直接保留）。
## 未完成 / 下一步
- 第一件：在这 3 页上让 DeepSeek（北京时间 18:00–09:00）改写 v4 结果，对比有无表术语，看能否改掉语义错误（中央感触手→median、bifid lumbar 等）。
- 有疑术语需人工核：突起、基節、上端部、歯冠、縁膜、腹足、足枝、中央、前足、後足、上顎、下顎。
- 若采用：把表术语并入 日本-imajima/terms/presub_ja_en.tsv、5 条规则加回 docstore/rules/ocr_fix.toml（配测试），再重译三卷。需用户确认。
## 关键决定
- 默认译名=Rouse+Handbook 基准（用户 2026-11-22）。用户要我自己测试，别一直问。
- 用户要的是真实测试，不是只统计；不要擅自改仓库文件。
## 文件位置
- 表：/mnt/p/翻译-译作/Taxonomy-Aware-Scientific-Book-Translation/bench/term_cand/（cand_ja_batch_google-summary.tsv、cand_ja_baseline.tsv、ja_en_baseline.py）
- 测试脚本/输出（临时）：/tmp/claude-0/-mnt-p-------Taxonomy-Aware-Scientific-Book-Translation/39cdc3d9-9439-452e-b63e-12b181a43784/scratchpad/（harness.py、mk3.py、psA/psB.tsv、v_*.md）
- 基准主表：/mnt/p/翻译-译作/参考资料/术语来源/主表/master_en_terms.tsv
## 坑
- 基准主表 zh_yiku 有错值（elytron→叫鞘翅、neuropodium→仅具腹足叶、prostomium→口前叶），未改。
- 表里 ja_fixed 多数是 n-gram 截断片段，不是 OCR 错。
- 3 页样本里没有 OCR 错字，OCR 纠错效果未量化（无金标）。
- 工作区未 commit（含上一任务的改动）。
## 仍在跑的任务
- 无
