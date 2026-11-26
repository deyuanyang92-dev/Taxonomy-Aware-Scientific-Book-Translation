# 检索表算法盘点（2026-11-24）

范围：key.txt、key2.txt、survey/notes、PLAN.md 涉及的全部算法。
每行：来源 ｜ 原文读过吗 ｜ 能否确定性实现 ｜ 状态。
"原文"= 论文或官方手册本身；"代码"= 只读过开源实现（survey/notes）。原文副本在 `survey/papers/`。
公式测试：`survey/checks/test_formulas.py`（5 项，通过）。引用核对：`survey/papers/verify_refs.tsv`（26 项）。

## 一、建表算法

| # | 算法 | 来源 | 原文 | 确定性实现 | 状态与备注 |
|---|---|---|---|---|---|
| B1 | DELTA KEY 贪心（K=c+cmin[Σf·log2n_j/Σf+V]） | Dallwitz 1974；DELTA User's Guide §5.4 | **手册已读**（uguide.pdf p.81–82）；1974 论文未读（付费） | 是，公式完整 | **已确证**：默认 RBASE1.40/ABASE2.00/REUSE1.01/VARYWT0.80（手册 §5.3）；V=((1−v)/v)·((n+8)/(n·log2n))·(Σn_j−n)；非常规子组再乘 (1+100m)。open-delta KeyBest.java:80,215 与手册一致。**已实现并验收（2026-11-24）**：`keykit/build.py`（7 项手算测试）；用 open-delta 自带 grass 数据（`survey/checks/delta_loader.py`）重建手册 Key 1，17 行与手册完全一致（`survey/checks/test_key1_acceptance.py`）。未实现：REUSE、强制/控制性状、混合阶元。 |
| B2 | GENKEY（最小化期望步长，多歧，先验概率） | Payne 1975；Payne & Preece 1980 | **未读** | 未确证 | 只有 key2 二手描述。key2 勘误#6（不可约测试集属诊断表）合理但未核。 |
| B3 | IKey+（单入口生成，基于 PD） | Burguière 2013 *Syst Biol* 62:157 | **未读**（OUP 拦截；正确 DOI 是 10.1093/sysbio/sys069） | PD 部分是；IKey+ 的分裂准则未确证 | key2 §8 未给出 Burguière 的 DOI；若按 sys065 查会得到别的文章（见下）。 |
| B4 | Xper3 判别力 PD(k)=Σ comp_k(i,j)；父性状取子性状最大值 | Kerner et al. 2025 *EJT* 987 | **已读**（kerner2025.pdf，PD 定义 + 父性状注） | 是 | **已实现（2026-11-24，`keykit/metrics.py`，手算测试）**；**已确证**：父性状 PD = 子性状 PD 的最大值（原文 "Note: in the case of a parent descriptor…"）。 |
| B5 | rpart/CART 建二分表（Gini，cost 权重，多态 expand.grid） | monographaR dichoKey | 代码已读（notes/monographaR.md） | 是，CART 自实现 | GPL，只借思路。多态展开会组合爆炸（代码 dataKey.R:36）。 |
| B6 | dimoose keyFromRpart / Alignment / Sniglets | leipzig/dimoose | 代码已读 | Alignment：是；Sniglets（CLIP 图像）：否（依赖模型） | GPL≥3，只借思路。DESCRIPTION:16 已确认。 |
| B7 | FRIDA：多入口初筛 + 动态生成单入口表 | Martellos 等 | **未读** | 未确证 | 只有 key.txt 二手描述。 |
| B8 | Clavis polythetic（0–1 频率，继承不覆写） | Artsdatabanken/Clavis | 代码/schema 已读（notes/Clavis.md） | 是（多入口评分） | 非二分；对应我们的"性状频率"设计。 |
| B9 | 3I 交互辅助构建可印刷二分表 | Dmitriev | **未读** | 未确证 | key2 勘误#3 称其有此功能，仅二手。 |
| B10 | key2 §5.4 混合阶元打分 S(k\|V) | key2 自创 | 无文献 | 是，但**无依据** | 除 DELTA 子项外的 λ_tax、ω_rank、γ_reuse、β、α 均无出处，不得当算法引用。PLAN §3 已改"待标定"。 |

## 二、检索表质量/审计指标

| # | 指标 | 来源 | 原文 | 确定性实现 | 状态与备注 |
|---|---|---|---|---|---|
| A1 | L_min、L_max（二叉树平均步长界） | DELTA 手册式(1)；key2 | 手册已读；L_max 为 key2 自推 | 是 | **已实现（`keykit/metrics.py`；E_shape 仅二歧表，多歧报错）**；**已确证**：L_min 与手册式(1)相同；L_min、L_max 对 N=2..16 全部二叉树穷举一致（test_lmin_lmax_bruteforce）。手册另说 L_min≈log2 n，误差≤0.086，已测。 |
| A2 | E_shape=(L_max−L_obs)/(L_max−L_min) | key2 自创归一化 | 无文献 | 是 | 本身无出处，只是 A1 的线性归一；只作"鉴定效率"。 |
| A3 | E_dicho（Pielou 均匀度，p_i=N_i/N） | Sinh 等 2017 *ZooKeys* 685:83 | **已读**（PMC5646650 全文；公式为图片，式子按 Pielou 定义还原） | 是 | **已确证**：PMC5646650 即该文（key2 的链接正确）。已测值域与单调性。 |
| A4 | Osborne 期望正确率 ∏(1−e_c) | Osborne 1963 *New Phytol* 62:144 | **仅读 Crossref 摘要** | 公式平凡，可实现 | 摘要说：若各问有误答概率，改变…可提高正确率（摘要被截断）；全文未读。key2 的乘积式是自己的简化，未核。 |
| A5 | Sandvik 1976；Payne & Preece 1977 | key2 提到 | 未读 | 未确证 | 只列名，未知内容。 |
| A6 | 拓扑硬错误（死链/环/孤立/重号/回溯号） | 通用图论；DKey 重编号 | DKey 论文已取（tofilski2018.pdf），算法段未细读 | 是 | keykit 已有 S1–S3；合法菱形 DAG 误报 S3 需换 check_graph。 |
| A7 | 23 条制表建议 | Packer 2024 *ZooKeys* 1215 | **已取全文**，23 条未逐条读 | 部分可自动查 | 调查数字已确证：427 篇、587 属、136 篇含表、141 份表（摘要+正文）。 |
| A8 | TaxonWorks Matrix Validation | 代码 | 代码已读（notes/TaxonWorks.md） | 是 | 对应"零距离种对"。**已实现 `keykit/audit.py`**（三档 separated/evidence_gap/matrix_silent + 弱边界，不下分类结论）；grass 数据 91 对全 separated、0 弱边界。 |
| A9 | 零距离/弱边界种对 | key2 自创（借 A8） | 无文献 | 是 | PLAN §5 A4：证据缺口≠同物异名。 |
| A10 | 网状出口膨胀 (M−(N−1))/N | key2 自创 | 无文献 | 是 | 阈值"≥3 次=隐存种"无依据。 |
| A11 | 反事实重编译四象限 + 25%/15%/30% 阈值 | key2 自创 | 无文献 | 可算，但**不用** | 与"不设作者差免责分支"冲突；阈值无校准。 |
| A12 | 蒙特卡洛压测、真实标本验表 | key2 自创 | 无文献 | 是（需真值数据） | 需 Packer 141 份表/ANNiKEY 校准集，尚未下载。 |
| A13 | WoRMS/GBIF 名录覆盖 | oworms | — | 是，已有工具 | 走 oworms，不在 keykit 写。 |

## 三、key2 "已核验"条目复核（本次）

| 条目 | 结果 |
|---|---|
| Packer 2024 DOI/卷页、427/587/136/141 | **已复核 OK** |
| Kerner 2025 DOI/卷页；PD 父性状=子最大 | **已复核 OK** |
| Tofilski 2018 DOI；DrawWing/DKey（C++，GPL-3.0） | **已复核 OK**；`adamtofilski/DKey` 不存在（PROGRESS 里的路径作废） |
| Walter&Winterton 2007、Murguía-Romero 2021、Glasby 2025 | **已复核 OK**（Crossref 卷页作者） |
| ANNiKEY Interactive/Online、Nereididae 数据集 zenodo DOI | **已复核 OK**（落地页标题吻合） |
| Osborne 1963 DOI/卷页 | **已复核 OK**（仅元数据） |
| E_dicho = PMC5646650 | **已复核 OK**，ZooKeys 685:83–89，doi 10.3897/zookeys.685.13625 |
| DELTA KEY 默认参数 | **已复核 OK**（官方手册） |
| Burguière 2013 IKey+ | **key2 无 DOI；我误查的 sys065 是别文，正确为 10.1093/sysbio/sys069（Crossref 元数据 OK），全文未读** |
| 全部仓库路径（16 个） | 存在，除 adamtofilski/DKey。注意许可：open-delta、dimoose 的 GitHub 页无许可证文件（dimoose DESCRIPTION 写 GPL≥3；open-delta 以文件头 MPL 1.1 为准）；edichokey 无许可证。 |
| 其余（AbaTax、3I、FRIDA、Lucid 等产品功能描述） | **未复核** |

## 四、对 PLAN.md 的修正（已由手册证实）

1. PLAN §2 写 `dupf = varywt·(Σn_g−n)/n`：**方向反了且少一项**。手册：V=((1−v)/v)·((n+8)/(n·log2 n))·(Σn_j−n)，v=VARYWT，v=1 无惩罚，v 越小罚越重（test_varywt_direction）。
2. PLAN 与 open-delta 笔记称"100、8 无文献依据"：**错**。手册 §5.4 明写 (n+8)/(n·log2 n) 与 (1+100m)。
3. PLAN su 里的 cost_eff 与手册 K=c+cmin·[…] 不同（手册用 cmin 近似各子键成本），实现时按手册式(5)。

## 五、下一步（需要读的原文，按价值）

1. Burguière 2013（IKey+）、Payne & Preece 1980（GENKEY）、Osborne 1963 全文：付费，需你提供 PDF 或机构下载；我不会用第三方转载冒充。
2. Packer 2024 的 23 条建议逐条读，对照 RULES.md 补缺。
3. 校准数据：Packer 141 份表（补充材料）、ANNiKEY / Nereididae DELTA（zenodo 7776745）。
