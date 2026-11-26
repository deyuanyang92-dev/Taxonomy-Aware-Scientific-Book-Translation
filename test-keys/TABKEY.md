# tabkey：性状表 -> 检索表

命令（在 test-keys/ 下）：

    python3 -m keykit tabkey 性状表.csv -o 输出前缀 [--bins 3] [--codebook cb.csv] [--include-free]
    python3 -m keykit tabkey 论文.pdf --pages 4,5 -o 输出前缀     # PDF/图片经 Datalab 识别（密钥 ~/.datalab_key）

输出：前缀.key.txt（多路检索表）、前缀.report.json（审计）、前缀.codebook.csv（编码草稿）、前缀.ocr.md（仅 PDF/图）。

## 输入模板（CSV / TSV / XLSX / Markdown 表）

- 第 1 行：第 1 格任意（分类单元），其余 = 性状名。
- 第 1 列：分类单元名（不得重复）。其余每格 = 该单元在该性状的状态。
- 空 / ? / n.r. = 未知；- / NA = 不适用（结构缺失，无从比较）。
- 括号 = 非模式材料，与括号外取并集：`40 (40-100)` = 40-100。
- 多态：状态间用 " | " 或 " / " 分隔。
- 数值（`3-9`、`12 (10-15)`）：列内 >=70% 为数值则自动识别。端点取值 <=6 种时每个值各为一个状态；否则按数据空隙分 --bins 箱，跨切点的区间计入两箱。
- 文字列：规范化（小写、去空白）后的文字即状态。状态多数只出现一次的列视为未编码自由文本，默认排除并写入报告；编辑 codebook.csv 的 state 列（把同义写法填成同一状态），用 --codebook 重跑；或 --include-free 强行使用。
- PDF/图：左右分页的续表按行序拼合，行名必须对得上，否则报错。OCR 结果须人工核（Datalab 在 Pectinariidae 表上 ~200 格错 1 处）。

## 规则与限制

- 算法：keykit.build（DELTA KEYBEST 公式，自行实现）。一个性状在某分组内只要有一个单元未知/不适用就不能用于该分组——数据缺口直接表现为「矩阵无法区分」，不会被猜填。
- 审计（audit.py）：每对单元分为 separated / evidence_gap / matrix_silent；仅一个性状分开的对列入 weak_pairs。
- 步数只是鉴定效率，不是分类证据。分箱与多态并集是编码选择，会影响树形；Pectinariidae 敏感性见 PROGRESS.md。
- 示例：examples/pectinariidae_table1.csv（Hutchings & Peart 2002 Table 1 原样），其人工编码版在 survey/checks/pect_table1/（13 叶已解 / 平均 2.42 步）；自动版未填 codebook 时自由文本列被排除或噪声大，结果较差，这是预期的——先填 codebook。
