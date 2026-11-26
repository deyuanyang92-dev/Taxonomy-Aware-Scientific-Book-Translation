# DELTA 兼容 + 文献性状表建检索表：计划（2026-11-24）

## 需求（用户原话归纳）
1. 兼容 DELTA：以 Travisia（Avery et al. 2023；Wilson & Avery 2023 的 DELTA/Intkey 包）为例，读/写 DELTA 数据，整理性状，用 keykit 自己建检索表；并与 DELTA（Key 程序/Intkey）的结果对比差异。
2. 用文献整理的性状表（用户本地已整理 Travisia、Ophelia，P 盘）直接建指定类群的检索表。
3. Avery 2023 数据由我自行下载（不用用户给的副本代替）。

## 已确证的现状
- 本地已有：/mnt/p/Travisia/02_原始数据/DELTA_Wilson_Avery_2023/travisia_delta.zip（2023-09-06 v1.01，41 种）。包内**只有** Intkey 编译二进制 ichars/iitems、Travisia_characters.rtf、Travisia_species.rtf、info/*.rtf、nex；**没有**原始 specs/chars/items 文本。zenodo_meta.json 是一页 403，来源未记录。
- Avery 2023 PDF 已在 /mnt/p/Travisia/01_文献/01_Travisia/；DOI 10.24199/j.mmv.2023.82.07。
- 本机有 java 21；open-delta 源码在 survey/repos/open-delta（IntkeyDatasetFileReader.java、BinFile.java、DeltaWriter.java；KeyBest.java 是 Key 程序）。MPL：只借格式知识，代码自写。
- keykit 已有：matrix.py（Matrix/Character/Taxon）、build.py（KeyBest 式贪心）、audit.py、metrics.py、tabkey.py（性状表→检索表）、__main__ 的 tabkey 子命令。
- 用户 Travisia 规则（/mnt/p/Travisia/CLAUDE.md）：检索表只用原始描述 L3 / 模式重检 L1-2；DELTA 属 L5，只作对照，不作证据。因此“文献表 vs DELTA”的差异本身就是要给出的结果。
- 用户本地 Travisia 检索表工作：04_处理数据/Travisia_keys_and_character_tables_2026-10-08.xlsx、Travisia_key_designs_compare_*.xlsx、70_travisia_publication_keys.py（Codex 版）。Ophelia：/mnt/p/粘海蛹新种-宁德合作-2026/*.xlsx。

## 分阶段
- P0 取数（sonnet）：从 Zenodo 找到并下载 Wilson & Avery DELTA 包，与本地 zip 比 sha256；Avery 2023 PDF 从 MMV 开放获取站重下并比对；来源写入 SOURCES.md。
- P1 DELTA 读入（sonnet，我给规格）：keykit/delta_io.py
  - 读 Intkey 二进制 ichars/iitems → Matrix（性状、状态、可靠度、种、多态、?、-、数值区间）；对照 Travisia_species.rtf 的生成描述逐种逐性状验证。
  - 读/写文本 DELTA（specs/chars/items 子集：*CHARACTER TYPES、*CHARACTER DESCRIPTIONS、*CHARACTER RELIABILITIES、*DEPENDENT CHARACTERS、items #taxon/ 性状,状态）。写出的 DELTA 须能被 open-delta 读入（java 验证）。
- P2 文献表 → Matrix（sonnet 执行，我定编码）：从用户 xlsx 抽 Travisia、Ophelia，经 codebook（性状→部位+论文体措辞，沿用 tabkey codebook 机制）进 Matrix；未知=?，不用他人数据填。
- P3 建检索表（主线程）：同一 Matrix 走 build.py；输出：DELTA 矩阵版、文献矩阵版两张表，各附 audit/metrics。
- P4 差异对比（主线程判断，sonnet 出表）：①性状集合差（DELTA 有而文献无，反之）；②同种同性状取值差（按性状映射表）；③两张检索表的导句性状、分组、步数差；④DELTA 自带 Key 程序结果（open-delta key 命令行）与 keykit build 同矩阵的差，作为 build.py 正确性检验。差异给种对/性状证据，不下“谁对”的判决。
- P5 CLI：python3 -m keykit delta {import|export|key|diff} 与 keykit key --chars <xlsx|delta> --taxa <列表>；“指定检索表”= 选性状子集/选种子集/选性状优先序。

## 模型分工
- 主线程（最强模型）：本计划、codebook 决策、差异判读、验收抽查。不另开 Opus 子代理（全局规则）。
- sonnet：P0、P1、P2 执行、P4 出表。haiku：文件清点、跑测试汇总。
- 子代理不得再开子代理；每步写盘；回报 ≤200 字。

## 验收
- P1：41 种全部读入；随机 10 个种×全部性状与 RTF 描述一致；pytest 过；ruff/mypy 过。
- P2：每个单元格有出处（文献+页码）或标 ?。
- P4：差异表每行带种/性状证据。


## P4 结果（2026-11-24）
- 更正：此前认为 open-delta Key 遇未知值即弃用该性状——错。证据：110 行/45 条目（含未知多的条目重复出现，如 trianulata 出现 10 次）；keykit 开 unknown_all 后用到 17 个性状，与 open-delta 的 17 个共有 16（仅 keykit 用 11、仅 open-delta 用 17），不开则只有 12 个。
- 因此 DELTA 对照一律 build(unknown_all=True)；run_delta_key.py 已改。keykit 平均步数 6.09、32 个未分开组；open-delta 平均路径 7.26、35 组（统计口径不同，仅量级参考）。
- 文献表 vs DELTA 取值差异见 survey/checks/delta_travisia/delta_vs_lit_report.md 与 delta_vs_lit_values.tsv（映射为我手拟，未经用户确认）。
