# keykit 矩阵建表 + 检索表审计：总计划（2026-11-24，主线程定）

依据：survey/notes/*.md（15 份读码笔记，行号见各份）、key2.txt。许可：dimoose、monographaR 为 GPL，只借思路不抄码；open-delta 为 MPL 1.1（文件头），KEY 公式自行实现，不拷源码。

## 0. 立场（用户 2026-11-24 定）
检索表不好，就是分类不好。使用不稳定、模糊的性状来分种，本身就说明这个类群的分类界限没有立住。审计模块因此**不设"作者写得差"的免责分支**，不做"作者表 vs 最优表"的四象限开脱。重编译只作为取证手段：矩阵本身分不清的，是分类问题，直接记为证据。

## 1. 矩阵 IR（keykit/matrix.py，新建）
- Taxon(id, rank, parent_id, name, authority, abundance 1-10, name_zh)
- Character(id, type: cat|num|count, organ, cost 1-4, reliability 1-10, stable: bool, depends_on: {char: [states]}, phrase_zh, phrase_en)
- Cell(taxon, char) 取值：状态集（每态可带频率 0-1）| 数值区间 (常规 lo-hi, 极值 xlo-xhi) | UNKNOWN | INAPPLICABLE。四者互不混用（不适用≠未知，见 DELTA / Clavis 缺口）。
- 继承：上阶元录入的值向下继承，下级可覆写；向上聚合时状态取并集、频率按丰度加权、区间取常规并极值。
- 导入：Excel/CSV 多 Sheet 模板（首选）；DELTA items（& 多态、- 不适用、a-b 区间）；Clavis JSON 列后期。导出：KeyIR（接现有 layout/verify）。
- 校验（照 KeyBase 三级）：Error=重名列、空 taxon、依赖环、区间 lo>hi；Warning=整列全同、孤立状态；Info=继承覆写。

## 2. 建表（keykit/build.py，新建）
- 贪心递归，无回溯（dimoose / DELTA / rpart 均如此；最优性未确证，不宣称）。
- 候选分裂：二叉为主。分类性状取（性状, 状态子集）；数值性状在区间端点上搜阈值。
- 打分（越小越好）：su = cost_eff + c·sup，沿 DELTA 结构：sup0=按丰度加权的 Σ(子组大小·log2 子组大小)/Σ子组丰度；变异惩罚 dupf 随多态造成的重复数增大；cost_eff = rbase^(5−reliability)·观察成本。默认 rbase=1.4、abase=2、varywt=0.8、reuse=1.01（Dallwitz 1974 / DELTA 手册默认值；open-delta KeyContext.java:100-103）。dimoose 的 a·b/cost（matrix.R:409-411）作可选准则 "ab"，做对照。open-delta 中 100、8 两个常数无依据（笔记 §7），本工具不沿用，改为可调参数并标"待标定"。
- 多态、未知：两支都走（dimoose matrix.R:423-424）；设 max_couplets 上限，超限报错而不静默截断。
- 不适用：由 depends_on 门控，前置状态未定的性状不进候选。
- 数值：先把常规区间合并成状态；分裂阈值取两组区间间隙中点，间隙 < margin（可设，默认相对宽度 5%）时该性状记"重叠"并强降权。
- 记忆化子表（剩余 taxon 集 + 开放状态集 + 阻塞集为键，dimoose matrix.R:405-408），相同则指回已有 couplet，输出 DAG；再按阅读序重编号。
- 终止：剩一个 taxon；或无可用分裂，输出 "A / B" 并写入 unresolved。unresolved 同时是审计证据。
- 确认性状：每个叶自动追加 k 个独立于路径的性状（open-delta：NUMBER OF CONFIRMATORY CHARACTERS）。
- 人工钉：Pin 指定节点的分裂性状，仅局部重算。

## 3. 多阶元混合（keykit/hier.py，新建）
- scope + 每分支 stop_rank：目标集 = 每个分支在 stop_rank 处的聚合节点（上卷），可同时含科、属、种。
- 三模式：single（单阶元表）；linked（科表→属表→种表，子表挂在叶上：mergeKeys 思路 prune.R:384 + KeyBase 的 subkey 列与 shortcut，笔记 keybase_model §5；父表已问性状透传，子表不重问）；hybrid（异构目标单表）。
- 阶元纯度项：在 su 上加 λ_tax·(1−纯度)；λ=0 为纯实用表，λ>0 倾向保持科/属聚簇。λ 的取值无文献依据，标"待标定"。
- 单型阶元可折叠开关。

## 4. 审计（keykit/audit.py，新建）——"检索表好坏 = 分类好坏"
全部确定性，无大模型。每条证据指向具体 couplet / 种对，输出可复核。
- A1 模糊性状：主观无量纲词（较长/较大/显著…）、"其他情况"类兜底、无数值的比较；矩阵层面 stable=False 或 reliability 低的性状被用作关键分裂（尤其树的上半部）。
- A2 数值区间重叠或余量不足（能从表文本直接抽 a–b 区间）。
- A3 多态膨胀与网状出口：同一种多出口次数；建表时 dupf 总量。
- A4 零距离/弱边界种对：矩阵上两种间无重叠性状数 = 0 → 候选同物异名/隐存种；=1 且该性状 reliability 低 → 界限存疑。
- A5 缺失率：某种 UNKNOWN 占比高 → 需基于模式标本重描述。
- A6 产地/生境/寄主代替形态。
- A7 重编译证据：最优建表结果出现 unresolved、或平均步数远大于理论下界（L_min 公式见 key2 §6.1，已手算验证）→ 矩阵本身分不开。
- A8 名录对照：WoRMS/GBIF 有效种遗漏、表内异名（走 oworms，不在 keykit 自拉）。
- 输出：每属一个"修订迫切度"（高/中/低）+ 证据清单；结论写成判断而非"可能"。所有阈值（含 key2 中 25%/15%/30%）**未校准**，报告里标注；校准用 Packer 2024 的 141 份表、ANNiKEY、Nereididae DELTA 数据集（Zenodo 10.5281/zenodo.7776745，未下载），在校准前仅给出排序与证据，不给绝对分。
- 分级：L1 仅检索表文本（A1 A2 A3 A6 + 由表文本反推矩阵）；L2 矩阵（A4 A5 A7）；L3 标本与分子真值（走表命中率、毒瘤项对）后做。
- 反推矩阵（L1→L2 的桥）：从 couplet 文本抽（器官, 状态/区间），沿路径给每个终点种累积；矛盾（同种路径上同一性状不同状态）记为表内不一致。这一步用现有 keygraph 解析结果，先做规则版，抽不出的标"未解析"。
- 表 vs 原始描述：taxadb 中该种的描述字段与表里的状态比对，不一致入证据（依赖 taxadb 数据，L2 之后）。

## 5. 里程碑与验收
M1 matrix.py + 导入 + 校验 + 单测。验收：玩具矩阵、含多态/未知/不适用/依赖/数值的 5 个用例。
M2 build.py 二叉建表。验收（属性测试）：①每个 taxon 沿其路径的所有状态约束都与矩阵相容；②多态/未知 taxon 不被漏检（出现在所有可能分支）；③无死链/环（接 keykit.fix.check）；④同输入同输出（确定性）。
M3 hier.py。验收：科-属-种三层玩具矩阵，linked 与 hybrid 两模式都能走通到每个种；父表性状不在子表重问。
M4 audit.py L1。验收：用 keykit/tests 现有语料与 adv/corpus 构造含已知缺陷的表，A1/A2/A3/A6 全部命中且无误报。
M5 audit.py L2 与 CLI（python3 -m keykit {matrix-build|hier|audit}）；接 layout/verify 出 docx/pdf。
全程：ruff --line-length 120、mypy、pytest 全过；新代码不改 booklayout/。

## 6. 已知不确定项（不当结论用）
- DKey（Tofilski 2018）仓库路径未找到；biokey、Free DELTA 未下载到；Xper2 仓库仅 1 文件（来源未确认）。
- key2.txt 中"联网核验确认无误"各条（E_dicho 的 PMC5646650、dimoose 更新日期等）本轮未复核。
- 贪心准则 su 与 a·b/cost 谁更优：未确证，M2 后在基准矩阵上比平均步数。
