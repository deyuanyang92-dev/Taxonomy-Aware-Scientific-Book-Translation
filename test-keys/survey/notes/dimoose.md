# dimoose (Leipzig, R) -- 本批最有价值

## 1 定位与许可证
- R 包 v0.3.0：读/建/检/裁/拼/分享二歧检索表；可导入 SDD、DELTA、Lucid、Xper、FishBase、纯文本、表格。dimoose/DESCRIPTION:2-12；README.md:30-40
- 许可证 GPL (>= 3)（有第三方数据另见 inst/COPYRIGHTS）。DESCRIPTION:14-16。思路可借鉴，代码不可直接拷入非 GPL 项目。

## 2 输入格式
- 性状矩阵：data.frame，Taxon 列 + 性状列；单元格内状态用 "/" 分隔表示多态，NA=未知/不适用；列名不得重复，必须每行有 taxon 名。dimoose/R/matrix.R:231-262（genParseMatrix），示例 matrix.R:128-141
- 性状表（可选）：Character、Cost(正数)、Season、Needs、InapplicableIf（"他性状=状态/状态; ..."）、Type(integer/real/text)。R/matrix.R:270-300,500-531,533-540
- 已有检索表 = leads 表：Statement、Choice、Character、Next("-"=终点)、Taxon（可选 Image、Feature、Threshold）。R/keys.R:29-48
- 电子表格 key（Couplet,Choice,Question,Description,Goes to,Species,Photo）。inst/extdata/montana/montana-key.csv:1-4
- 纯文本检索表（1a/1b、点线、跨行、OCR 修复）经 keyFromText。R/textkey.R:163；示例 inst/extdata/textkeys/trees-bracketed.txt

## 3 输出格式
- dimoose R6 对象（leads、taxa、meta、features）；导出自包含 HTML 向导 exportWizard、箱图 keyDiagram、电子表格、DELTA/SDD/Lucid/Xper、Newick、data.tree、igraph、Auspice JSON。README.md:36-38,44-45

## 4 建表算法（keyFromMatrix，variable="both" 默认）
- 候选分裂 = 每个（性状,状态）一列；has[i,j]=taxon i 确有状态 j；known=该性状已知。R/matrix.R:340-355（genPartition 内，行 331 起）
- 可用性条件：该状态至少一个 taxon 显示、另一支留有其他状态、且至少排除一 taxon（a>0|b>0）。R/matrix.R:394
  其中 a=只显示该状态的 taxon 数(colSums(only))，b=已知但不具该状态的数(colSums(never))。R/matrix.R:388-392
- 打分：score = a*b/cost（乘积，偏好平衡且便宜）；若全部 <=0 退化为 (a+b)/cost；取 which.max。R/matrix.R:409-411
- 多态/未知：同一 taxon 同时进入两支（first = !never；second = !only），即"变异或未知则两支都走"，代价是同一 taxon 出现多个终点，键可能膨胀。R/matrix.R:423-424,430
- 缺失：未知(known=FALSE)的 taxon 两支都留；maxCouplets（默认 10000）超限报错，且 couplets > 10*n 警告。R/matrix.R:415-421,461-465
- 数值性状：genTypedStates 把范围（"3","4-6","(1-)2-8(-12)","2-8 mm"）解析为区间，重叠/相接的合并为一个状态；全重叠则弃用；text 型弃用。R/matrix.R:533-592,594-613
- 权重/成本：Cost 除分数；Season 过滤可观察性状；Needs 记入 lead；InapplicableIf 使依赖性状延后提问（父性状未定时被 blocked）。R/matrix.R:57-70,71-90（genCharacterInfo）；R/matrix.R:396-403（blocked）
- 终止：剩 1 个 taxon，或无可用分裂（多个 taxon 共享一个结果 "A / B"）。R/matrix.R:383,396
- 子表复用（DAG）：子表以 (剩余 taxa 位集, 仍开放的状态位集, blockers) 为 id 记忆化，相同则指回已有 couplet，不重复生成；之后 genMergeCouplets 合并逐字相同的 couplet 并按阅读顺序重编号。R/matrix.R:405-408,472-509
- 用显式栈而非递归（防深层溢出）；先走第一支再走第二支，保证编号按阅读顺序。R/matrix.R:442-447,483-492
- 备选：variable="missing" 用 rpart（variable 视为 NA）。R/matrix.R:616-668
- 贪心、无回溯/无前瞻；未确证最优性（有 keyQuality 的下界对比）。R/quality.R:4-14

## 5 混合层级能力
- mergeKeys(key, subkey, at)：把子表接到 key 中结果为 at 的叶子（科表→属表→种表），支持共享结果 "A / B"、多条叶共指同一子表；labels="renumber"（全局阅读序重编号）或 "prefix"（"Salicaceae.1"）；同 id 不同内容的图/features 自动改名 _2；合并 citation/taxa/meta。R/prune.R:384-524
- pruneKey/regionalKey：按 taxon 保留/删除（属级或精确匹配）并 prnCollapse 去掉只剩一支的 couplet，再重编号；regionalKey 按 GBIF/iNat 区域记录裁剪。R/prune.R:95,281,685
- 单入口 vs 多入口：exportWizard 默认按 couplet 顺序走；另有 "I'm not sure"(u/?) 键和"任意顺序挑性状"模式（需性状矩阵，选状态淘汰 taxa）。R/export.R:16-29,162,1049
- 多入口/科内属内混编：mergeKeys 为链式，非"一表多入口"；未见专用的多入口数据结构（未确证）。

## 6 校验与错误处理
- validate()/checkLeads：指向缺失 couplet、终点无 taxon、couplet 少于 2 个 lead、环（无未被引用的 couplet）、从根不可达。R/export.R:705-745；R/dimoose.R:155-159
- 矩阵：重名列、空 taxon 名、无性状列、嵌套列、Cost 非正、季节全无可观测性状等都有明确报错。R/matrix.R:231-262,270-300
- 文本表：问题（含行号）、自动修复（l→1、断开点线）一并报告，strict=TRUE 则停。R/textkey.R:163-170（README.md:100-117）
- 质量：keyQuality/summary 报平均步数、与理论下界之比、信息熵效率。R/quality.R:4-73
- 名称：checkNames 用 GBIF 查拼写/异名。README.md:35

## 7 可借鉴 / 不足
- 借鉴（最重要）：①a*b/cost 贪心打分+退化项；②多态=两支都走、未知=两支都走的明确语义；③数值区间重叠合并成状态；④记忆化子表 id + genMergeCouplets 去重 = 输出 DAG（节省篇幅）；⑤InapplicableIf 依赖性状；⑥Season/Needs/Cost 元数据；⑦leads 五列规范 + validate 五类检查；⑧mergeKeys 的子表嫁接与 renumber/prefix 两种命名；⑨keyQuality 下界评价；⑩文本→leads 解析并附行号问题清单。
- 不足：贪心无回溯；打分不看性状在分类群间的"诊断可靠度"或可见性权重以外的信息（只有 Cost）；多态展开可致膨胀（要靠 maxCouplets 限制）；a*b 并非信息增益，未确证优于其他准则；多入口表需自行编排；GPL 不可直接复制代码。
