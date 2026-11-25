# monographaR (dataKey / dichoKey / interactiveKey)

## 1 定位与许可证
- CRAN R 包 v1.3.0，作者 Marcelo Reginato，面向植物分类专著辅助（描述、采集者表、检索表、地图）。monographaR/DESCRIPTION:1-18
- 许可证 GPL (>= 2)。monographaR/DESCRIPTION:16（注：属 copyleft，直接复制代码会传染；借鉴思路无碍）
- 检索表相关仅 3 个函数：dataKey（预处理）、dichoKey（二歧表）、interactiveKey（Shiny 多入口表）。

## 2 输入格式
- data.frame：第 1 列物种名（强制改名为 species），其余列为性状，值为状态字符串。monographaR/R/dichoKey.R:4；R/dataKey.R:3
- 多态用分隔符 poly.sep（默认 "/"）拼在单元格内，如 "red/blue"。R/dataKey.R:2,13
- 缺失 = NA；dataKey 把缺失替换为该列全部观察到的状态并集（即视为"任何状态"）。R/dataKey.R:11-20
- interactiveKey：第 1 列分类群、第 2 列性状名(Character)、第 3 列起为各分类群（宽表，行=性状状态来源）。R/interactiveKey.R:14-34（由代码推断）
- 示例数据 data(monographaR_examples)$dichoKey（二进制 rda，未解包，列内容未确证）。man/dichoKey.Rd:43-45

## 3 输出格式
- dichoKey 返回 list(rpart=拟合对象, key=单个字符串, depth=各节点深度, unresolved=未分开种名向量)，并 cat 打印。R/dichoKey.R:144
- 检索表为缩进纯文本：编号"n)" + 性状 + "..........种名"，每对分支共用同一编号，缩进=深度，不是"→跳转号"式。R/dichoKey.R:115-141
- interactiveKey 写出 Dat_characters.csv、Dat_matrix.csv、app.R/server.R/ui.R/about.Rmd（Shiny 应用）。R/interactiveKey.R:46,51,55-94

## 4 建表算法
- 核心完全委托 rpart（CART 决策树，类别=物种）：formula species ~ .，minbucket=1, minsplit=1, cp 默认 0.01, xval=1000, maxsurrogate=999, usesurrogate=2。R/dichoKey.R:7
- 分裂性状选择=rpart 默认（分类树 Gini 不纯度最大下降；此为 rpart 默认，包内未显式设置 parms，未确证）。包内无自写打分公式。
- 多态：dataKey 对含 "/" 的行用 expand.grid 展开成所有状态组合的多行（同一物种多行）。R/dataKey.R:36-37。结果：多态不致误分，但行数组合爆炸。
- 缺失：见上，并集填充后同样被展开。R/dataKey.R:11-20
- 性状成本/权重：cost 参数传 rpart(cost=)，dataKey 返回 summary=各性状多态比例，示例用 summary+1 作成本（多态越多越贵）并手工抬高某些性状成本。man/dichoKey.Rd:62-67
- 数值性状：无专门处理，rpart 对数值会做阈值分裂，但输出文本转换假设"性状=状态"（labels 拆 "="）。R/dichoKey.R:77（推断）
- 终止：cp 剪枝 + 叶纯；种间不可分者落入 unresolved，并在已分出的叶标注 "sp A / sp B"。R/dichoKey.R:35-67
- 补充"附加性状"：每层把左右分支内各自单一状态且不同的非分裂性状追加到分支描述（弥补 rpart 只用最少性状）。R/dichoKey.R:74-109
- 回溯/重编号：无回溯；编号按深度逐层配对生成。R/dichoKey.R:119-138

## 5 混合层级能力
- 无。单层（物种为类别）、单一入口；无科→属→种链接、无子表跳转。interactiveKey 为多入口（自由选性状）但同样无层级。未确证有其他层级函数（R/ 目录仅上述函数）。

## 6 校验与错误处理
- 基本无：无输入合法性检查、无重复物种/空列报错；dataKey 只打印多态比例（前后两次）。R/dataKey.R:8-9,25-26
- dichoKey 对 depth 和 grep(i, depth.n) 的实现脆弱（grep 数字匹配，如 1 会匹配 10）。R/dichoKey.R:75（疑似 bug，未实测）

## 7 可借鉴 / 不足
- 借鉴：①多态用 "/" 约定、②缺失=并集的保守处理、③用 unresolved 列表+"A / B"标注无法分开的种、④成本向量=多态比例+1 的权重思路、⑤分支末追加"附加性状"的写法。
- 不足：依赖 rpart 黑箱，不可控；每个分支只给一个性状（缺 couplet 对称描述）；多态展开组合爆炸；无层级/分表；无校验；无数值性状阈值文本化；GPL。
