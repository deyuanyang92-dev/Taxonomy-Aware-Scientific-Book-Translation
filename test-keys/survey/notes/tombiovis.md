# tombiovis（FSC Identikit，多入口交互检索，JS）

## 1 定位与许可证
- 英国野外研究委员会的生物鉴定框架，多入口（multi-access）检索，不生成纸质二叉表 (`README.md:15-18`)。许可 GPL-3.0 (`LICENSE:1-2`)。
- 用户任意顺序输入性状，软件对所有分类单元打分排序，不是“下一步选哪个性状”的决策树。

## 2 输入格式（知识库 = 4 个 CSV，示例 `identikit/kb/biscuits/`）
- `taxa.csv`：首列 Taxon，其余每列一个性状；单元格 `|` 分多值（或），数值/序数范围 `[x-y]`，`n/a` 不适用，`?`/空 缺失 (`documentation/Character scoring.pdf` 4.2/4.3；`kbchecks.js:217`)。例：`Rich Highland Shortie,Round,Pale brown,None,Yes,...,57,57`。
- `characters.csv` 列：Group,Character,Label,Help,HelpShort,Status,ValueType(text|numeric|ordinal|ordinalcircular),ControlType(single|multi),Params,Weight(1-10),Latitude (`characters.csv:1`; `kbchecks.js:304`)。
- `values.csv`：Character,CharacterState,翻译,StateGroup,帮助 — 序数性状的状态顺序由此行序定。
- `config.csv`：元数据/版本；`media.csv`：图。

## 3 输出格式
- 无文件输出；浏览器中 6+ 种可视化（单栏/双栏、并排对比等，`tombio/vis1..vis6`），按 taxa 总分排序。

## 4 建表算法（实为“匹配打分”）
- 单性状得 [for, against]，against = 1 − for，总分 overall = for − against − na (`tombiovis.js:1897`; `score.js:30-34`)。
- 文本：输入集与分类单元值集交集非空 for=1，否则 0 (`score.js:124-165`)。多选视为“或”。
- 数值：落在 [min,max] 内=1；越界按 latitude 线性衰减 `1 − 距离/latitude`，≥latitude 记 0 (`score.js:6-28`)。
- 序数：先转秩，再套数值函数，latitude+1；环状序数取距离更近的一侧再算一次 (`score.js:38-122`)。
- 权重：总分 = Σ 性状 overall × Weight/10 (`tombiovis.js:1901-1907`)。
- 缺失：`?`/空 → for=0 against=0（不计）；`n/a`：用户输入了值时该 taxon 记 −1 (`Character scoring.pdf` 4.2)。
- 分类单元间比较：Jaccard (`score.js:169-190`)；数值取上下界两次平均。
- 无终止条件、无回溯，无下一步性状推荐；无成本概念。

## 5 混合层级能力
- 弱。Taxonomy 组性状可当层级列用于上色 (`tombiovis.js:1746`; `vis5.js:100`)，但无科→属→种子表跳转。多入口天然，单入口二叉未提供。

## 6 校验与错误处理
- `kbchecks.js` (772 行) 三级报告：3 严重 / 2 中 / 1 提示 (`:67-70`)。检查：缺 taxa.csv (:76)、必需列缺失 (:125, :344)、性状名须字母数字无空格 (:189)、数值非数字或 `[x-y]` (:217)、序数值未在 values 表 (:275)、序数范围倒序 (:288)、taxa 列在 characters 表无行 (:385)、Strictness 弃用 (:359-362)。

## 7 可借鉴与不足
- 借鉴：①“证据支持 + 证据反对”双分，让缺失与不适用区分；②latitude 容差线性衰减，适合我们的数值性状模糊匹配；③`[x-y]`、`|`、`n/a`、`?` 四个单元格记号，可直接作 keykit 矩阵约定；④分三级严重度的知识库检查；⑤序数/环状序数。
- 不足：无信息增益/判别力计算，不会生成二叉表；无子表；校验在浏览器里跑，不可批量。
