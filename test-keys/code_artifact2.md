# 分类学检索表制作规范、出版级排版与自动化指南

分类学检索表（Identification Key）在逻辑上是将**形态性状矩阵**映射为**最小代价决策路径**的有向决策树（允许种内多态性导致同一物种多次出现时为有向无环图 DAG），在出版上则是对**基准线对齐、折行边界、点线网格与分页控制**要求极高的结构化版式。

本文整合检索表的编制规则、出版级排版调参方案、规范示例、程序化自动质检与建表代码，以及开源工具与文献资源。

---

## 一、 分类学检索表的核心编制规则

结合经典分类学教材与 Laurence Packer (2024, *ZooKeys* 1215) 对近年新发表检索表的实证审查，高质量检索表需遵守以下准则：

### 1.1 适用边界与前置诊断
* **限定范围（Scope）**：标题或导语必须写清检索表适用的**分类阶元、地理区域、性别与发育阶段**（如成体/幼体、雌/雄、生殖态/非生殖态）。
* **前置高阶诊断（Diagnosis）**：在检索表正上方简明列出该属/科的共有鉴别特征，避免使用者拿错类群强行检索。

### 1.2 项对（Couplet）编写七大原则
1. **严格对立与完备互斥**：同一项对的两条检索项（Lead A / Lead B）必须针对**相同性状**描述互斥状态，且二者并集覆盖当前分支的全部剩余类群。
2. **主语前置与平行句式**：同一项对的两条检索项尽量以**同一器官/结构名词**开头（如“疣足背须……；疣足背须……”），相邻两步的项对则尽量换不同起始词，降低跳行误读率。
3. **多性状冗余（Polythetic Couplets）**：避免仅依赖单一脆弱性状；以**最稳定、最易观察的宏观性状**打头，后附 1–2 个独立佐证性状，防止标本残缺导致检索中断。
4. **量纲明确，杜绝主观词**：禁用“较大、较长、显著、颜色较深”等无参照词，必须给出**具体测量区间、比例关系或参照结构**，并确保两条分支的数值区间不重叠（例如用 `1–4` 对 `5–10`，避免 `1–5` 对 `5–10`）。
5. **禁用消极否定项**：避免单独写“其他情况”“不具上述特征”，否则遇到未收录的新种或外群时会直接错判。
6. **允许合理网状出口（Reticulation）**：对于多态性显著或种内变异大的类群，允许同一物种在检索表中出现多次，强行只给唯一出口反而会制造系统误差。
7. **标注回溯号与图版锚点**：平行式检索表建议在编号后用括号标注上一级来源编号，如 `2(1)`，便于走错时逆向回退；关键性状直接标注图号（如 `Fig. 1A`）。

### 1.3 规范对照示例：反面案例 vs. 修订标准版

#### 反面案例（含 5 类高频问题）
> 1. 疣足背须较长，体色深褐；通常有眼…… *Taxon A*  
> – 无背须，或者吻部具角质颚齿，刚毛 2–5 根…… 2  
> 2. 刚毛 5–10 根，末端呈镰刀状…… *Taxon B*  
> – 其他情况…… *Taxon C*

**问题诊断：**
* **非对立性状**：`1a` 讨论背须、体色与眼，`1b` 却引入吻部颚齿和刚毛数，两项无法逐一核对。
* **主观无量纲词**：“较长”“深褐”缺乏参照标准，且乙醇/福尔马林固定后体色易褪。
* **数值边界重叠**：`1b` 为 `2–5 根`，`2a` 为 `5–10 根`，恰好 5 根时归属不明。
* **消极否定项**：`2b` 写“其他情况”，未说明真实鉴别特征。
* **格式失控**：纯文本手打省略号凑宽度，在比例字体下右侧目标无法对齐。

#### 修订后的规范版（平行式 + 回溯号 + 多性状冗余 + 右端严格对齐）

| 项号 | 形态特征 | 跳转 / 类群 |
| :--- | :--- | ---: |
| **1.** | 疣足背须显著延长，长度大于背舌叶的 2 倍（Fig. 1A）；口前叶具 2 对明显的眼，呈梯形排列（Fig. 1B） | ***Taxon A*** |
| **–** | 疣足背须短小或退化，长度小于背舌叶的 1.5 倍（Fig. 2A）；口前叶无眼，或仅具 1 对退化眼点 | **2** |
| **2(1).** | 腹足刚毛束具 1–4 根异齿镰状复型刚毛，端片长宽比小于 3（Fig. 2C）；吻部口环具圆锥形角质颚齿 | ***Taxon B*** |
| **–** | 腹足刚毛束具 5–10 根异齿镰状复型刚毛，端片长宽比大于 5（Fig. 3C）；吻部口环光滑无颚齿 | ***Taxon C*** |

---

## 二、 三种经典印刷体例与规范示例

### 2.1 体例对比

| 体例类型 | 结构特征 | 适用场景与优势 | 常见排版与维护隐患 |
| :--- | :--- | :--- | :--- |
| **平行式（Bracketed / Parallel）** | 同一项对的两条检索项紧邻，共享编号（`1 / –` 或 `1a / 1b`），可附回溯号 `2(1)`。 | **主流英文期刊（*Zootaxa*, *ZooKeys*）首选**；版面利用率高、对比直观、最易程序化解析与重编号。 | 亲缘相近类群在版面上可能相距较远。 |
| **定距式（Indented / Yoked）** | 第一条下的所有子分支穷尽后再出现第二条，随层级逐级向右缩进。 | 类群较少（通常不超过 15–20 个）时形态聚簇感强，常见于早期专著。 | 超过 6–8 层后右侧版心被严重挤压，极易发生缩进坍缩与跨页阅读困难。 |
| **连续平行式（Serial / Linked）** | 不缩进，顺次编号，并在括号内标注对立项编号，如 `1(4)` 与 `4(1)`。 | 《中国动物志》等传统中文专著常用，兼顾类群聚簇与版面宽度。 | 增删任一物种都会触发全表括号编号连锁重算，手工维护极易错号。 |

### 2.2 同一棵决策树的三种标准体例示例

#### 1. 平行式（Bracketed / Parallel）

| 项号 | 形态特征 | 跳转 / 类群 |
| :--- | :--- | ---: |
| **1.** | 口前叶具触角 | **2** |
| **–** | 口前叶无触角 | **3** |
| **2(1).** | 围口节具 3 对触须 | ***Sp. A*** |
| **–** | 围口节具 4 对触须 | ***Sp. B*** |
| **3(1).** | 疣足双叶型，具背刚毛 | ***Sp. C*** |
| **–** | 疣足亚双叶型，缺背刚毛 | ***Sp. D*** |

#### 2. 定距式（Indented / Yoked）
*(注：Markdown 不支持多级表格缩进与制表位，此处用等宽结构示意层级；正式排版需在 Word/Typst/LaTeX 中通过左缩进 + 固定右对齐制表位实现)*

```text
1a. 口前叶具触角
    2a. 围口节具 3 对触须 ..................................... Sp. A
    2b. 围口节具 4 对触须 ..................................... Sp. B
1b. 口前叶无触角
    3a. 疣足双叶型，具背刚毛 .................................. Sp. C
    3b. 疣足亚双叶型，缺背刚毛 ................................ Sp. D
```

#### 3. 连续平行式（Serial / Linked）

| 项号 | 形态特征 | 跳转 / 类群 |
| :--- | :--- | ---: |
| **1(4).** | 口前叶具触角 | **2** |
| **2(3).** | 围口节具 3 对触须 | ***Sp. A*** |
| **3(2).** | 围口节具 4 对触须 | ***Sp. B*** |
| **4(1).** | 口前叶无触角 | **5** |
| **5(6).** | 疣足双叶型，具背刚毛 | ***Sp. C*** |
| **6(5).** | 疣足亚双叶型，缺背刚毛 | ***Sp. D*** |

---

## 三、 出版级格式调整实战指南

决定一份检索表排版是否专业，核心在于能否同时控制住 **5 个版式硬指标**：

1. **左栏基准线统一**：全表采用**固定宽度的编号区**（按最大编号如 `125(118).` 预先留宽），折行的第二行起严格悬挂缩进到正文起始垂直线，绝不按当前行字符数动态漂移。
2. **右栏折行边界与防撞车**：多行正文描述的右侧折行边界必须全表统一，且绝不冲入右侧目标区（避免出现“目标为 `2` 时正文折得很宽、目标为长学名时正文突然收窄”的参差锯齿）。
3. **引导点阵垂直对齐**：若使用点状引导线（Leader Dots），上下行的点必须锚定到同一页面网格，避免每行从末字后机械打点导致整页视觉发花。
4. **长学名与附属信息的断行规范**：
   * 属名与种加词之间用**不间断空格（NBSP）**锁死，禁止属名留在行尾、种加词被劈到下行。
   * 学名斜体；命名人、年份、括号、`sp.`、`cf.`、`s. str.` 及页码保持正体。
5. **分页控制（禁止劈裂项对）**：同一项对的 `Lead A` 与 `Lead B` 必须作为原子单元同页显示，禁止 `1a` 落在本页底行、`1b` 跑去下一页首行。

下面按不同排版工具给出可直接调参的落地实现。

---

### 3.1 Word (DOCX) 两种专业排法

> **铁律**：在 Word 中绝对不要手动敲省略号或句点凑对齐。

#### 方案 A：固定三栏无框表（*Zootaxa* / *ZooKeys* 投稿最稳）
* **表格设置**：全表共用**同一张**三列表，取消所有边框（仅保留标题下横线，视期刊要求而定）；表格属性中关闭“自动重调尺寸以适应内容”。
* **列宽分配**（以 A4 版心宽 `16.0 cm` 为例，可按学名长度调整）：
  * 第 1 列（项号）：固定 `1.5–2.2 cm`，顶端左对齐（或右对齐）。
  * 第 2 列（特征描述）：固定 `10.0–11.0 cm`，两端对齐，顶端对齐。
  * 第 3 列（跳转 / 学名 / 页码）：固定 `3.5–4.5 cm`，**右对齐 + 底端对齐**。
* **防分页劈裂设置**：
  1. 选中整张表 → 表格属性 → 行 → **取消勾选**“允许跨页断行”。
  2. 给每个项对**第一条（Lead A）所在行的段落** → 段落设置 → 换行和分页 → **勾选“与下段同页（Keep with next）”**；`Lead B` 取消勾选。这样分页只会发生在项对之间。

#### 方案 B：段落制表位 + 点状前导符（传统专著还原与中文动物志常用）
很多人只在 Word 里加了右对齐制表位，结果多行正文直接冲进右侧目标区撞车。正确配置必须**同时设置“右缩进”与“越界右对齐制表位”**：

| 参数项 | 推荐值（A4 版心 16.0 cm 示例） | 作用原理 |
| :--- | :--- | :--- |
| 左缩进 / 悬挂缩进 | 悬挂缩进 `1.8 cm`（另设左制表位 `1.8 cm`） | 输入编号按一次 `Tab` 开始写正文，折行自动对齐到 `1.8 cm`。 |
| **右缩进** | **`3.8 cm`** | 强制所有多行正文在 `12.2 cm` 处统一折行，给右侧留出 `3.8 cm` 的专属通道。 |
| **越界右对齐制表位** | 位置 **`16.0 cm`**，对齐方式选**右对齐**，前导符选 **`2 ……`** | 设在右缩进之外！正文写完按一次 `Tab`，光标直接越过 `12.2 cm` 跳到 `16.0 cm`，点线自动垂直对齐，正文与学名永不撞车。 |
| 换行和分页 | Lead A 勾选“段中不分页”+“与下段同页”；Lead B 仅勾选“段中不分页” | 彻底防止项对在页尾被劈成两半。 |

---

### 3.2 Typst 可调参出版级模板

**避坑说明**：
* 不要给每一行单独建 `grid(columns: (2.8em, 1fr, auto))`——`auto` 会导致每条正文折行边界参差不齐。
* 不要直接用无保护的 `#box(width: 1fr, repeat[.])`——每行从末字后开始打点，上下点阵对不齐。

下面的模板采用**全局统一固定列宽 + `block(breakable: false)` 锁死项对分页 + 右锚定裁剪点阵（实现上下行点线严格垂直对齐）**，所有样式参数均集中在顶部的 `key-config` 字典中，一键可调：

```typst
#set page(paper: "a4", margin: 2.2cm)
#set text(font: ("Times New Roman", "Source Han Serif SC"), size: 10pt)

// ==========================================
// 1. 全局版式调参区（按期刊或专著要求修改）
// ==========================================
#let key-config = (
  num-width: 3.2em,       // 左栏编号固定宽（多位数含回溯号如 125(118). 可调至 4.5em）
  target-width: 11.5em,   // 右栏目标固定宽（含长学名+作者年份+页码时调大）
  left-gutter: 0.4em,     // 编号与正文间距
  right-gutter: 0.45em,   // 点线/正文与右侧目标间距
  lead-gap: 0.35em,       // 同一项对两条 lead 之间的间距
  couplet-gap: 0.75em,    // 相邻项对之间的间距
  line-leading: 0.55em,   // 正文行距
  show-dots: true,        // true = 传统点线模式；false = 现代期刊无点线模式
  dot-gap: 0.32em,        // 点阵间距
  dot-color: luma(90),    // 点阵灰度
)

// 右锚定裁剪点阵：所有行的点阵均以中栏右边缘为基准向左排布，保证上下垂直对齐
#let aligned-dots(cfg) = {
  if cfg.show-dots {
    h(0.45em)
    box(
      width: 1fr,
      height: 0.75em,
      clip: true,
      place(
        right + bottom,
        box(
          width: 22cm,
          text(fill: cfg.dot-color, repeat(gap: cfg.dot-gap)[.]),
        ),
      ),
    )
  }
}

// 单条检索项渲染
#let key-lead(
  num,
  desc,
  target,
  is-taxon: false,
  author: none,
  page-no: none,
  cfg: key-config,
) = {
  let target-content = {
    if is-taxon {
      // 将属种名中的普通空格替换为不间断空格，防止属名与种加词被拆行
      emph(target.replace(" ", sym.space.nobreak))
      if author != none [ #author]
    } else {
      strong(str(target))
    }
    if page-no != none [ (p.#sym.space.nobreak#page-no)]
  }

  grid(
    columns: (cfg.num-width, 1fr, cfg.target-width),
    column-gutter: (cfg.left-gutter, cfg.right-gutter),
    align: (left + top, left + top, right + bottom),
    [#strong(num)],
    [
      #set par(justify: true, leading: cfg.line-leading)
      #desc#aligned-dots(cfg)
    ],
    [
      #set par(justify: false, leading: 0.45em)
      #target-content
    ],
  )
}

// 成对 Couplet 封装：breakable: false 保证同一项对永不跨页劈裂
#let couplet(id, parent: none, lead-a, lead-b, cfg: key-config) = {
  let head = if parent != none [#id (#parent).] else [#id.]
  block(breakable: false, below: cfg.couplet-gap)[
    #key-lead(
      head,
      lead-a.text,
      lead-a.target,
      is-taxon: lead-a.at("taxon", default: false),
      author: lead-a.at("author", default: none),
      page-no: lead-a.at("page", default: none),
      cfg: cfg,
    )
    #v(cfg.lead-gap)
    #key-lead(
      "–",
      lead-b.text,
      lead-b.target,
      is-taxon: lead-b.at("taxon", default: false),
      author: lead-b.at("author", default: none),
      page-no: lead-b.at("page", default: none),
      cfg: cfg,
    )
  ]
}

// ==========================================
// 2. 使用示例
// ==========================================
= Key to Species of Hypothetical Genus

#couplet(
  1,
  (
    text: "疣足背须显著延长，长度大于背舌叶的 2 倍，表面具环纹且在体中段尤为明显（Fig. 1A）；口前叶具 2 对呈梯形排列的黑色眼点（Fig. 1B）",
    target: "Taxon alpha",
    taxon: true,
    author: "Smith, 1980",
    page: 57,
  ),
  (
    text: "疣足背须短小或退化，长度小于背舌叶的 1.5 倍（Fig. 2A）；口前叶无眼，或仅具 1 对退化眼点",
    target: 2,
  ),
)

#couplet(
  2,
  parent: 1,
  (
    text: "腹足刚毛束具 1–4 根异齿镰状复型刚毛，端片长宽比小于 3（Fig. 2C）；吻部口环具圆锥形角质颚齿",
    target: "Taxon beta",
    taxon: true,
    page: 61,
  ),
  (
    text: "腹足刚毛束具 5–10 根异齿镰状复型刚毛，端片长宽比大于 5（Fig. 3C）；吻部口环光滑无颚齿",
    target: "Taxon gamma",
    taxon: true,
    page: 64,
  ),
)
```

---

### 3.3 LaTeX (XeLaTeX) 出版级模板（支持严格 `\leaders` 垂直点阵）

如果需要严格还原 *Fauna Ibérica* 或传统专著的“正文统一右侧通道 + 点阵垂直对齐 + 末行目标绝对贴右”版式，TeX 原生的 `\rightskip` + `\parfillskip=-\rightskip` + `\leaders` 是最可靠的排版原语（与 LaTeX 目录 `\@dottedtocline` 原理一致）：

```latex
% 使用 XeLaTeX 编译
\documentclass[10pt,a4paper]{article}
\usepackage[margin=2.2cm]{geometry}
\usepackage{xeCJK}
\usepackage{needspace}

% ==========================================
% 1. 可调版式参数
% ==========================================
\newlength{\keynumwidth}    \setlength{\keynumwidth}{3.0em}    % 左栏编号宽
\newlength{\keyrightmargin} \setlength{\keyrightmargin}{4.2cm} % 右侧目标通道宽
\newlength{\keyleadgap}     \setlength{\keyleadgap}{2.5pt}     % 同对两条间距
\newlength{\keycoupletgap}  \setlength{\keycoupletgap}{7pt}    % 项对之间间距

% 垂直对齐点阵（0.45em 网格节距）
\newcommand{\keydotfill}{%
  \leaders\hbox to 0.45em{\hss.\hss}\hfill
}

% 学名格式化（属种间用 ~ 禁止断行，命名人正体）
\newcommand{\taxon}[2][]{\textit{#2}\if\relax\detokenize{#1}\relax\else\ #1\fi}

% 单条检索项宏：\keylead{编号}{特征描述}{右端目标}
\newcommand{\keylead}[3]{%
  \begingroup
  \par\noindent
  \leftskip=\keynumwidth
  \rightskip=\keyrightmargin
  \parfillskip=-\keyrightmargin % 末行抵消右缩进，允许点线与目标延伸至绝对右页边距
  \hspace*{-\keynumwidth}\makebox[\keynumwidth][l]{\textbf{#1}}%
  #2%
  \nobreak\hspace{0.4em}%
  \keydotfill
  \nobreak\hspace{0.4em}%
  \mbox{#3}%
  \par
  \endgroup
}

% 成对项对宏（自动防止在两条 lead 中间分页）
\newcommand{\couplet}[5]{% #1=编号, #2=leadA文本, #3=leadA目标, #4=leadB文本, #5=leadB目标
  \needspace{4\baselineskip}% 预留空间，避免项对起于页尾
  \keylead{#1}{#2}{#3}%
  \nopagebreak[4]\vspace{\keyleadgap}%
  \keylead{--}{#4}{#5}%
  \vspace{\keycoupletgap}%
}

\begin{document}

\section*{Key to Species of Hypothetical Genus}

\couplet{1.}
  {疣足背须显著延长，长度大于背舌叶的 2 倍（Fig.~1A）；口前叶具 2 对明显的眼，呈梯形排列（Fig.~1B）}
  {\taxon[Smith, 1980]{Taxon~alpha} (p.~57)}
  {疣足背须短小或退化，长度小于背舌叶的 1.5 倍（Fig.~2A）；口前叶无眼，或仅具 1 对退化眼点}
  {\textbf{2}}

\couplet{2(1).}
  {腹足刚毛束具 1--4 根异齿镰状复型刚毛，端片长宽比小于 3（Fig.~2C）；吻部口环具圆锥形角质颚齿}
  {\taxon{Taxon~beta} (p.~61)}
  {腹足刚毛束具 5--10 根异齿镰状复型刚毛，端片长宽比大于 5（Fig.~3C）；吻部口环光滑无颚齿}
  {\taxon{Taxon~gamma} (p.~64)}

\end{document}
```

---

### 3.4 HTML / CSS（网页交互查看与 WeasyPrint 导出 PDF）

同样通过 CSS 变量锁死全表一致的左右列宽，避免用 `auto` 破坏折行边界，并配合 `break-inside: avoid` 控制打印分页：

```css
.taxonomic-key {
  --num-col: 3.5em;
  --target-col: 12.5em;
  font-family: "Times New Roman", "Source Han Serif SC", serif;
  font-size: 10pt;
  line-height: 1.55;
}

.couplet {
  break-inside: avoid;
  page-break-inside: avoid;
  margin-bottom: 0.75em;
}

.key-lead {
  display: grid;
  grid-template-columns: var(--num-col) 1fr var(--target-col);
  column-gap: 0.5em;
  margin-bottom: 0.25em;
}

.key-num {
  font-weight: bold;
  align-self: start;
}

.key-desc {
  text-align: justify;
  align-self: start;
}

.key-target {
  text-align: right;
  align-self: end;
}

.taxon-name {
  font-style: italic;
  white-space: nowrap;
}
```

---

## 四、 检索表自动生成与程序化质检（QC）管线

在批量处理历史专著 OCR 文本或从自建性状矩阵生成检索表时，最稳健的架构是**三段式编译管线**：

```text
[上游输入]                       [中游中间表示与校验]                    [下游多格式渲染]
1. 性状矩阵 CSV/JSON  ──┐       ┌─ JSON IR 标准化表示                  ┌─ Typst 出版级 PDF
                        ├──▶    ├─ 拓扑质检（死链/孤立/环路/回溯号） ──┼─ LaTeX 源码
2. 专著 OCR/旧表文本  ──┘       ├─ 语义与学名质检（区间重叠/WoRMS核验） └─ Markdown / HTML
                                └─ DFS 自动重编号与树形平衡度评估
```

### 4.1 标准化 JSON 中间数据结构（IR）

```json
{
  "title": "Key to Species of Hypothetical Genus",
  "scope": "Adult specimens from Chinese coastal waters",
  "couplets": [
    {
      "id": 1,
      "parent": null,
      "leads": [
        {
          "text": "疣足背须显著延长，长度大于背舌叶的 2 倍（Fig. 1A）",
          "target_type": "taxon",
          "target": "Taxon alpha",
          "author": "Smith, 1980",
          "page": 57
        },
        {
          "text": "疣足背须短小或退化，长度小于背舌叶的 1.5 倍（Fig. 2A）",
          "target_type": "couplet",
          "target": 2
        }
      ]
    }
  ]
}
```

### 4.2 三层自动质检清单

| 校验层级 | 检测项 | 自动化方法 |
| :--- | :--- | :--- |
| **第一层：图论与拓扑（硬错误）** | 死链指针、孤立不可达节点、环路死循环、分支数异常（非 2 项）、回溯号不匹配、编号跳号或重复 | 图邻接表检查、BFS 可达性扫描、三色 DFS 环检测 |
| **第二层：格式与学名（数字化高频坑）** | 引导线/学名/页码粘连错断、学名拼写与有效名核验、图号悬空引用 | 正则拆解 + WoRMS / GBIF / COL API 模糊核验 + 图号索引核对 |
| **第三层：效率与语义优化** | 树形平衡度（对比平均步数与理论最优 $\log_2 N$）、数值区间重叠、非对立性状、主观模糊形容词 | 树深度统计、数值区间正则交叉判定、逐 Couplet LLM 语义审计 |

### 4.3 Python 实战代码 1：自动质检 + DFS 重编号 + 导出规范 Markdown / Typst

```python
import math
import re
from collections import deque


def qc_key(key_data: dict) -> dict:
    """对 JSON IR 检索表执行拓扑、数值边界与效率质检"""
    issues = []
    couplets = {c["id"]: c for c in key_data["couplets"]}
    ids = [c["id"] for c in key_data["couplets"]]

    # 1. 编号连续性与重复性
    if len(ids) != len(set(ids)):
        issues.append("[编号] 存在重复项对编号")
    expected = list(range(1, len(ids) + 1))
    if sorted(ids) != expected:
        issues.append(f"[编号] 编号不连续：现有 {sorted(ids)}，期望 {expected}")

    adj = {cid: [] for cid in couplets}
    actual_parents = {cid: set() for cid in couplets}
    range_pat = re.compile(r"(\d+(?:\.\d+)?)\s*[-–—~]\s*(\d+(?:\.\d+)?)")
    fuzzy_pat = re.compile(r"(其他情况|较长|较短|较大|较小|显著较大|otherwise|other characters)", re.I)

    # 2. 分支结构、死链、数值重叠与模糊词检测
    for cid, c in couplets.items():
        leads = c["leads"]
        if len(leads) != 2:
            issues.append(f"[结构] 项对 {cid} 含 {len(leads)} 条分支（标准二歧表应为 2 条）")

        ranges = []
        for idx, lead in enumerate(leads):
            text = lead["text"]
            m_range = range_pat.search(text)
            if m_range:
                ranges.append((float(m_range.group(1)), float(m_range.group(2))))
            m_fuzzy = fuzzy_pat.search(text)
            if m_fuzzy:
                issues.append(f"[语义] 项对 {cid} 第 {idx + 1} 条包含疑似模糊或消极表述: '{m_fuzzy.group(1)}'")

            if lead["target_type"] == "couplet":
                tgt = lead["target"]
                if tgt not in couplets:
                    issues.append(f"[死链] 项对 {cid} 指向不存在的编号 {tgt}")
                else:
                    adj[cid].append(tgt)
                    actual_parents[tgt].add(cid)

        if len(ranges) == 2:
            (a1, a2), (b1, b2) = ranges
            if max(a1, b1) <= min(a2, b2):
                issues.append(f"[语义] 项对 {cid} 数值范围 {a1}–{a2} 与 {b1}–{b2} 存在重叠或端点冲突")

    # 3. 回溯号核验
    for cid, c in couplets.items():
        p = c.get("parent")
        if p is not None and p not in actual_parents[cid]:
            issues.append(f"[回溯号] 项对 {cid} 标注来源 ({p})，实际指入节点为 {sorted(actual_parents[cid])}")

    # 4. BFS 孤立节点检测
    root = 1 if 1 in couplets else min(couplets)
    visited = {root}
    q = deque([root])
    while q:
        u = q.popleft()
        for v in adj[u]:
            if v not in visited:
                visited.add(v)
                q.append(v)
    for orphan in sorted(set(couplets) - visited):
        issues.append(f"[孤立节点] 项对 {orphan} 从根节点 {root} 不可达")

    # 5. 三色 DFS 环路检测
    color = {cid: 0 for cid in couplets}
    has_cycle = False

    def dfs_cycle(u, path):
        nonlocal has_cycle
        color[u] = 1
        for v in adj[u]:
            if color[v] == 1:
                has_cycle = True
                cycle = path[path.index(v):] + [v]
                issues.append(f"[环路] 检测到死循环: {' -> '.join(map(str, cycle))}")
            elif color[v] == 0:
                dfs_cycle(v, path + [v])
        color[u] = 2

    for cid in couplets:
        if color[cid] == 0:
            dfs_cycle(cid, [cid])

    # 6. 树形效率评估（仅在无环时计算）
    stats = {}
    if not has_cycle and root in couplets:
        depths = []

        def measure_depth(u, d):
            for lead in couplets[u]["leads"]:
                if lead["target_type"] == "taxon":
                    depths.append(d)
                elif lead["target_type"] == "couplet" and lead["target"] in couplets:
                    measure_depth(lead["target"], d + 1)

        measure_depth(root, 1)
        if depths:
            n_exits = len(depths)
            avg_steps = sum(depths) / n_exits
            ideal_steps = math.log2(n_exits) if n_exits > 1 else 1.0
            stats = {
                "exits": n_exits,
                "max_depth": max(depths),
                "avg_steps": round(avg_steps, 2),
                "ideal_min_steps": round(ideal_steps, 2),
                "efficiency_ratio": round(ideal_steps / avg_steps, 2),
            }

    return {"issues": issues, "stats": stats}


def renumber_key_dfs(key_data: dict, root_id: int = 1) -> dict:
    """对无环连通检索表按 DFS 先序重编号，并同步刷新跳转指针与回溯号"""
    couplets = {c["id"]: c for c in key_data["couplets"]}
    old_to_new = {}
    new_list = []

    def visit(old_id, new_parent):
        if old_id in old_to_new:
            return old_to_new[old_id]
        new_id = len(old_to_new) + 1
        old_to_new[old_id] = new_id
        node = {"id": new_id, "parent": new_parent, "leads": []}
        new_list.append(node)
        for lead in couplets[old_id]["leads"]:
            if lead["target_type"] == "couplet":
                child_id = visit(lead["target"], new_id)
                node["leads"].append({**lead, "target": child_id})
            else:
                node["leads"].append(dict(lead))
        return new_id

    visit(root_id, None)
    return {**key_data, "couplets": new_list}


def export_markdown_table(key_data: dict) -> str:
    """导出右端严格对齐的三列 Markdown 表格"""
    lines = [
        f"### {key_data['title']}",
        "",
        "| 项号 | 形态特征 | 跳转 / 类群 |",
        "| :--- | :--- | ---: |",
    ]
    for c in key_data["couplets"]:
        head = f"**{c['id']}({c['parent']}).**" if c.get("parent") else f"**{c['id']}.**"
        for idx, lead in enumerate(c["leads"]):
            num = head if idx == 0 else "**–**"
            if lead["target_type"] == "taxon":
                tgt = f"***{lead['target']}***"
                if lead.get("author"):
                    tgt += f" {lead['author']}"
                if lead.get("page") is not None:
                    tgt += f" (p. {lead['page']})"
            else:
                tgt = f"**{lead['target']}**"
            lines.append(f"| {num} | {lead['text']} | {tgt} |")
    return "\n".join(lines)


def export_typst_calls(key_data: dict) -> str:
    """将 JSON IR 编译为可直接嵌入前文 Typst 模板的 #couplet(...) 调用"""
    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', '\\"')

    def fmt_lead(lead: dict) -> str:
        parts = [f'text: "{esc(lead["text"])}"']
        if lead["target_type"] == "taxon":
            parts.append(f'target: "{esc(str(lead["target"]))}"')
            parts.append("taxon: true")
            if lead.get("author"):
                parts.append(f'author: "{esc(lead["author"])}"')
            if lead.get("page") is not None:
                parts.append(f'page: {lead["page"]}')
        else:
            parts.append(f'target: {lead["target"]}')
        return "(" + ", ".join(parts) + ")"

    blocks = []
    for c in key_data["couplets"]:
        parent_arg = f", parent: {c['parent']}" if c.get("parent") else ""
        a, b = c["leads"][0], c["leads"][1]
        blocks.append(
            f"#couplet(\n  {c['id']}{parent_arg},\n  {fmt_lead(a)},\n  {fmt_lead(b)},\n)"
        )
    return "\n\n".join(blocks)
```

### 4.4 Python 实战代码 2：从性状矩阵自动生成二分检索表

在自动建表算法（如 DELTA `KEY`、Xper3 `Ikey+`）中，数学核心是**带性状权重与多态性惩罚的决策树分裂**：
* **判别力（Discriminant Power）**：若两个类群 $i, j$ 在性状 $k$ 上的状态集合交集为空，则定义不相容度 $\mathrm{comp}_k(i, j) = 1$，否则为 $0$，总判别力为：
  $$PD(k) = \sum_{i < j} \mathrm{comp}_k(i, j)$$
* **平衡分裂与观察代价**：以香农熵衡量切分平衡度（理想二分树平均步数趋近 $\log_2 N$，极端梳形树则退化为 $\frac{N+1}{2}$），再乘以**性状可靠度/易观察权重**并惩罚多态性导致的物种重复出口。

```python
import math

# 性状定义：weight 越大表示越稳定、越容易观察（优先置于顶层）
characters = {
    "eyes": {"label": "口前叶眼点", "weight": 3.0},
    "cirri_pairs": {"label": "围口节触须对数", "weight": 2.2},
    "falciger_teeth": {"label": "镰状刚毛端片锯齿", "weight": 0.9},
}

# 性状矩阵：使用集合表示状态，原生支持种内多态性（如 Taxon D 的 eyes 为 {"有", "无"}）
taxa_matrix = {
    "Taxon A": {"eyes": {"有"}, "cirri_pairs": {"3对"}, "falciger_teeth": {"粗锯齿"}},
    "Taxon B": {"eyes": {"有"}, "cirri_pairs": {"4对"}, "falciger_teeth": {"细锯齿"}},
    "Taxon C": {"eyes": {"无"}, "cirri_pairs": {"3对"}, "falciger_teeth": {"粗锯齿"}},
    "Taxon D": {"eyes": {"有", "无"}, "cirri_pairs": {"4对"}, "falciger_teeth": {"粗锯齿"}},
}


def best_split(taxa_subset: list[str], char_key: str):
    all_states = sorted({s for t in taxa_subset for s in taxa_matrix[t][char_key]})
    if len(all_states) < 2:
        return (-1.0, [], [], [], [])

    best = (-1.0, [], [], [], [])
    n = len(taxa_subset)

    for state in all_states:
        left_states = {state}
        right_states = set(all_states) - left_states
        left_taxa = [t for t in taxa_subset if taxa_matrix[t][char_key] & left_states]
        right_taxa = [t for t in taxa_subset if taxa_matrix[t][char_key] & right_states]

        if len(left_taxa) == n or len(right_taxa) == n or not left_taxa or not right_taxa:
            continue

        # 1. 香农熵平衡分（50/50 切分时达到最大值 1.0）
        p = len(left_taxa) / (len(left_taxa) + len(right_taxa))
        balance = -(p * math.log2(p) + (1 - p) * math.log2(1 - p))

        # 2. 多态重复惩罚（减少不必要的网状出口）
        overlap = len(set(left_taxa) & set(right_taxa))
        poly_penalty = 1.0 / (1.0 + overlap)

        score = balance * characters[char_key]["weight"] * poly_penalty
        if score > best[0]:
            best = (score, sorted(left_states), sorted(right_states), left_taxa, right_taxa)
    return best


def generate_key_ir(taxa_subset: list[str], title: str = "Auto-generated Key") -> dict:
    couplets = []
    counter = [1]

    def build(sub_taxa, parent=None):
        cid = counter[0]
        counter[0] += 1

        best_char, best_res = None, (-1.0, [], [], [], [])
        for ckey in characters:
            res = best_split(sub_taxa, ckey)
            if res[0] > best_res[0]:
                best_char, best_res = ckey, res

        if best_char is None:
            return None

        _, ls, rs, lt, rt = best_res
        node = {"id": cid, "parent": parent, "leads": []}
        couplets.append(node)

        for states, branch_taxa in [(ls, lt), (rs, rt)]:
            desc = f"{characters[best_char]['label']}为{'或'.join(states)}"
            if len(branch_taxa) == 1:
                node["leads"].append({"text": desc, "target_type": "taxon", "target": branch_taxa[0]})
            else:
                child_id = build(branch_taxa, parent=cid)
                if child_id is None:
                    node["leads"].append({
                        "text": desc,
                        "target_type": "taxon",
                        "target": f"未完全区分({', '.join(branch_taxa)})",
                    })
                else:
                    node["leads"].append({"text": desc, "target_type": "couplet", "target": child_id})
        return cid

    build(taxa_subset)
    return {"title": title, "couplets": couplets}


if __name__ == "__main__":
    ir = generate_key_ir(list(taxa_matrix.keys()), "Hypothetical Taxa Key")
    print(export_markdown_table(ir))
```

---

## 五、 GitHub 开源项目、数据标准与核心文献资料

### 5.1 主流开源工具与框架

| 项目 / 工具 | 仓库 / 入口 | 技术栈 | 核心定位与特色 |
| :--- | :--- | :--- | :--- |
| **DKey** | `DrawWing/DKey` | C++ / 桌面端 (GPL-3.0) | 专攻传统二分检索表的开源编辑器。支持解析现有纯文本检索表、合并多表、移动/删改项对、**自动重编号**、自动关联插图，并导出出版格式或超链接 HTML。 |
| **Open-DELTA** | `AtlasOfLivingAustralia/open-delta` | Java (跨平台开源) | 经典 **DELTA（DEscription Language for TAxonomy）** 套件开源版，涵盖 `DELTA Editor`、`KEY`（生成二分表）、`Intkey`（多入口交互检索）与 `CONFOR`（自动生成物种描述）。 |
| **Clavis & clavis-pipeline** | `Artsdatabanken/Clavis`、`Artsdatabanken/clavis-pipeline` | JSON Schema / TypeScript / React | 挪威生物多样性信息中心主导的现代开源检索表 JSON 标准与工具链。支持用 0–1 频率表达多态性，且 `clavis-pipeline` 提供基于 LLM Agent **从扫描专著抽取带原文逐字引用溯源的结构化检索表**的完整脚手架。 |
| **dimoose** | `leipzig/dimoose` | R 包 | 支持从 CSV 性状矩阵或标本照片集构建二分检索表，附带交互向导与检索表统计检验工具。 |
| **monographaR** | CRAN: `monographaR` | R 包 | 面向分类学专著编制的 R 工具包，含 `DichoKey` 等函数用于辅助格式化检索表、分布图与描述段落。 |
| **KeyBase** | `rbgvictoria/keybase_model`、`rbgvictoria/keybase-redevelopment` | Web / JSON | 澳大利亚皇家植物园主导的开源二分检索表托管与播放系统，支持多级子表联动跳转（`to_key`）及 JSON 导出。 |
| **TaxonWorks** | `SpeciesFileGroup/taxonworks` | Ruby on Rails / Vue | 大型开源分类学综合工作台，内置性状观察矩阵（Observation Matrix）与检索表生成模块。 |
| **Library of Identification Resources** | GitHub 组织 `identification-resources`（含 `sdd-sdk`） | TypeScript / JS | 面向 FAIR 原则的开源检索表目录与 **SDD（Structure of Descriptive Data）** 标准 TypeScript SDK。 |
| **TSKey** | `mossnisse/TSKey` | TypeScript | 轻量级 Web 端二分检索表编辑器，代码精简，适合作为前端数据结构参考。 |
| **Xper3** | `xper3.fr`（含 `Mkey` / `Ikey+`） | Java / Web / SDD | 法国索邦大学团队维护的免费分类学知识库平台，支持协作编辑、数据一致性检查、判别力计算及单/多入口检索表导出。 |

### 5.2 核心文献与实战参考数据集

* **检索表实证审查与核查清单**：Packer, L. (2024). *A survey of keys for the identification of newly described insect genera*. **ZooKeys** 1215: 65–90 (`doi:10.3897/zookeys.1215.130416`).
* **检索表理论与交互演进**：Walter, D. E., & Winterton, S. (2007). *Keys and the Crisis in Taxonomy: Extinction or Reinvention?* **Annual Review of Entomology** 52: 193–208.
* **二分检索表解析与编辑工程**：Tofilski, A. (2018). *DKey software for editing and browsing dichotomous keys*. **ZooKeys** 735: 131–140 (`doi:10.3897/zookeys.735.21412`).
* **形式化描述与判别力模型**：Kerner et al. (2025). *An Xper3 reference guide for taxonomists*.
* **二分检索表数学基础**：Osborne, D. V. (1963). *Some aspects of the theory of dichotomous keys*. **New Phytologist** 62(2): 144–160.
* **多毛类 / 环节动物 DELTA 实战数据集**：
  * Glasby et al. (2025). *ANNiKEY Interactive* (`doi:10.5281/zenodo.13738485`).
  * Wilson, R. S., Glasby, C. J., & Bakken, T. (2023). *A Taxonomic Information System for Nereididae*.