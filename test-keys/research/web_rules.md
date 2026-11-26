# 二歧式检索表制作与排版规则：网络调研

调研日期 2026-11-23。方法：WebSearch + WebFetch 读取页面（WebFetch 返回的是模型摘录，不是逐字原文；带引号的短语为摘录中的引文，使用前请回原页核对）。
未能取得全文的重要来源：Winston《Describing Species》(1999) 检索表部分、Pankhurst《Biological Identification》(1978)、Williamson 1922 (Science)、《中国动物志》编写规则、《动物志编写规范》、科学出版社检索表版式细则。凡涉及这些的内容一律写「未确证」。

## 1. 结构：偶句与分支

| 规则 | 说明 | 出处 |
|---|---|---|
| 偶句(couplet)由两条对立的分支(lead)组成；一个决策点的全部分支合称 couplet | 每条分支或指向下一偶句，或终止于分类单元 | https://en.wikipedia.org/wiki/Single-access_key；https://herbarium.ncsu.edu/4H/fig6-3.pdf (Fig. 6.3, p.1) |
| 两条分支互斥，且覆盖该节点下全部变异 | 不能用两个类群共有的特征(如都「有斑点」)作区分 | 来源：https://employees.csbsju.edu/ssaupe/biol308/Lecture/keys.htm（'mutually exclusive'、'all of the potential variations'） |
| n 个终端单元的完整二歧检索表恰有 n-1 个偶句 | 可作自动检查：偶句数 = 终点数 - 1（无网状交叉时） | https://employees.csbsju.edu/ssaupe/biol308/Lecture/keys.htm |
| 平行对比：两条分支必须平行且对立(parallel and contrasting) | 两条分支比较同一特征 | NCSU 图 6.3 说明：https://herbarium.ncsu.edu/4H/fig6-3.pdf (Fig. 6.3, p.1) |
| 两条分支以同一名词/同一特征词起首 | 例：一条以 petals 起首，另一条也以 petals 起首；避免否定式，用 absent 对 present | 课程讲义 https://employees.csbsju.edu/ssaupe/biol308/Lecture/keys.htm（'start each couplet with a noun'、'avoid negatives'） |
| 两条分支中特征的出现次序应一致，且每个特征在另一条中都有对应 | Packer 调查：仅 2 个 key 次序不平行，19 个 key 有特征未被对比 | Packer 2024（Parallel Couplets 节）：Packer 2024, ZooKeys 1215:65-90, https://pmc.ncbi.nlm.nih.gov/articles/PMC11489712/ |
| 编号后缀：缩进式用 1 与 1'，或 1a 与 1b | 也有 1 与 -（Zootaxa 作者须知：第二条分支以连字符起首） | 缩进式 https://employees.csbsju.edu/ssaupe/biol308/Lecture/keys.htm；Zootaxa：https://www.mapress.com/zt/about/submissions (Preparation of manuscripts, keys 条) |
| 括号式必须编号；并应在偶句号后注明回指号，如 2a (1) | 回指号让用户在死胡同时能回溯 | 来源：https://employees.csbsju.edu/ssaupe/biol308/Lecture/keys.htm |
| 连续平行式：每对分支有两个号，其中一个括在括号内，如 1.(6) 与 6.(1) | 符合则顺序往下读；不符合则跳到括号里的号 | 中文：https://zh.wikipedia.org/zh-hans/生物检索表；https://www.cnblogs.com/impw/p/13955021.html |
| 去向：每条分支末尾给出下一偶句号，或分类单元名 | 号与正文之间用冒号或省略号（…）或点线分隔 | Wikipedia 举例 '1. ...: 2'；Zootaxa 示例用 '... 2' 与 '... Genus A'；https://en.wikipedia.org/wiki/Single-access_key；https://www.mapress.com/zt/about/submissions (Preparation of manuscripts, keys 条) |
| 第一条分支应带用户进入紧随其后的偶句；避免跳跃式(leapfrog)偶句 | Packer 建议 15 与 14（尽量扇形） | Packer 2024：Packer 2024, ZooKeys 1215:65-90, https://pmc.ncbi.nlm.nih.gov/articles/PMC11489712/ |
| 检索表中应有明确入口：标题说明适用范围（类群、地区、性别等） | Packer 建议 5、6、7 | Packer 2024：Packer 2024, ZooKeys 1215:65-90, https://pmc.ncbi.nlm.nih.gov/articles/PMC11489712/ |
| 不得有孤立号、重复号、缺号、循环、未达终点 | Packer：4 个 key 有编号重复/缺失/错误，1 个完全没有编号；校对成本为零却常被忽略 | Packer 2024（Numbering 节）；循环/孤立号属图论推论，Wikipedia 称 key 为树，网状(reticulation)才成有向无环图：https://en.wikipedia.org/wiki/Reticulation_(single-access_key) |
| 网状交叉(reticulation)：终端网状（同一分类单元在多处出现）兼容任何版式；内部网状在缩进式中需要特殊机制 | 故缩进式检索表中通常不允许内部交叉，需要交叉时用括号/平行式 | https://en.wikipedia.org/wiki/Reticulation_(single-access_key) |
| 较易判断、常见的类群放前面；需复杂操作(解剖)的放后面 | Packer 建议 17、18 | Packer 2024：Packer 2024, ZooKeys 1215:65-90, https://pmc.ncbi.nlm.nih.gov/articles/PMC11489712/ |
| 选稳定、易观察、避免含糊词的特征；定量；避免 vague terms | 课程讲义 'use fixed features'、'quantify'、'avoid trichotomies' | https://employees.csbsju.edu/ssaupe/biol308/Lecture/keys.htm |
| 多于两条的多分支(polytomy)应避免；必要时版式上要与二歧明显区分 | Packer 建议 16 | Packer 2024：Packer 2024, ZooKeys 1215:65-90, https://pmc.ncbi.nlm.nih.gov/articles/PMC11489712/ |
| 终端分类单元在最末偶句中常按字母序排列 | NCSU 说明 | NCSU 图 6.3：https://herbarium.ncsu.edu/4H/fig6-3.pdf (Fig. 6.3, p.1) |

## 2. 排版

| 规则 | 说明 | 出处 |
|---|---|---|
| 三种版式：嵌套/缩进式(nested/indented)、链接/平行/括号式(linked/bracketed)、连续平行式 | 嵌套式：每个偶句紧接在其分支之后；缩进随层级加深，但缩进本身不是嵌套式的本质特征；链接式：偶句两条分支相邻，各指向编号偶句 | https://en.wikipedia.org/wiki/Single-access_key；https://en.wikipedia.org/wiki/Identification_key |
| 缩进式：同一偶句的两条分支距左边界等距，下一偶句缩进在所选分支之下 | 中文称定距式，每深一层右移一个字格 | 英：https://employees.csbsju.edu/ssaupe/biol308/Lecture/keys.htm；中：https://www.cnblogs.com/impw/p/13955021.html |
| 平行/括号式：两条分支并排，不同号码之间不缩进，每条分支以下一号或名称收尾 | 节省版面，但回溯较难；缩进式占版面，但逻辑更易见 | 中：https://zh.wikipedia.org/zh-hans/生物检索表；英：https://employees.csbsju.edu/ssaupe/biol308/Lecture/keys.htm（teresas 讲义因 403 未读取） |
| 正文与去向之间用点线(leader dots)或省略号连接 | Saupe 图 1 括号式从每条分支拉点线到去向；缩进式用较短点线接分类单元名 | 来源：https://employees.csbsju.edu/ssaupe/biol308/Lecture/keys.htm；中文页面用「……」：https://zh.wikipedia.org/zh-hans/生物检索表 |
| Word/DOCX 实现：用真实制表位(w:tabs)，右对齐去向制表位，w:leader=dot；换行说明用悬挂缩进；不得用空格或手打点号模拟对齐 | 来自本项目的 issue（本仓库内部文档，非外部权威来源） | https://github.com/deyuanyang92-dev/Taxonomy-Aware-Scientific-Book-Translation/issues/11 |
| PDF：显式的去向列或等价制表布局；换行必须保留分支缩进，去向仍可见；用悬挂缩进 | 同上 | https://github.com/deyuanyang92-dev/Taxonomy-Aware-Scientific-Book-Translation/issues/11 |
| 正文过长换行：点线应接在最后一行正文之后，而不是第一行之后 | W3C 对 CSS 引导点线的说明：正文换行时，点线要落在最后一行，不在第一行；前提是点线之后的内容较短 | 来源：https://www.w3.org/Style/Examples/007/leaders.en.html（该页讲的是菜单，不是检索表；原理可类推，属推论） |
| edichokey(LaTeX) 的做法：连接分支与分类单元的点线可折成两行；所有分支(含其后点线)在距右边界 \\righttaxonskip(默认 2em) 处折行，只有终点分类单元可触及右边界 | 即：正文与点线在去向列左侧折行，去向右对齐在版心右缘；分类单元名默认 \\bfseries\\itshape | 来源：edichokey 文档 https://ctan.csail.mit.edu/macros/latex2e/contrib/edichokey/edichokey-doc-en.pdf p.1-2 |
| edichokey 示例：续行点线在下一行继续并以分类单元名收尾（如 '3. Fruits white . . . . .' 折行后接 '. . . P. leucocarpus'） | 说明点线可跨行；属名缩写用前缀 'P.' 统一 | 来源：edichokey 文档 https://ctan.csail.mit.edu/macros/latex2e/contrib/edichokey/edichokey-doc-en.pdf p.1-2 |
| 一个偶句不应跨页；同一偶句的两条分支尽量同页；标题与第一偶句同页；超长偶句用一致的续页规则 | 同上 | 来自 issue（内部）：https://github.com/deyuanyang92-dev/Taxonomy-Aware-Scientific-Book-Translation/issues/11；外部权威来源：未确证 |
| 图号：偶句中的图号放在分支正文末尾、去向之前，括在括号内，如 '(Figs 29; 33a) … 2' | Zootaxa 示例；Figs/Fig. 大写 F，范围用 en dash | Zootaxa Odonata 须知示例：https://www.mapress.com/zootaxa/files/ZOOTAXA_Requirements_Odonata.pdf (Keys 条, p.约4)；ZooKeys 图号规则：https://zookeys.pensoft.net/about#Submissions |
| 图应靠近相关偶句；或超链接到图；或所有图集中放置，便于对照 | Packer 建议 11、12；仅不到 12% 的 key 把图放在相关偶句旁 | Packer 2024：Packer 2024, ZooKeys 1215:65-90, https://pmc.ncbi.nlm.nih.gov/articles/PMC11489712/ |
| 学名斜体；作者名正体 | 通用规则：ZooKeys 须知写明属种学名应斜体；「作者名正体」未在所读摘录中确认 | ZooKeys 斜体：https://zookeys.pensoft.net/about#Submissions；作者正体：未确证 |
| 检索表要在版面上醒目：清晰标题和可见格式；避免多余空白或不可达偶句 | Packer 建议 23 | Packer 2024：Packer 2024, ZooKeys 1215:65-90, https://pmc.ncbi.nlm.nih.gov/articles/PMC11489712/ |
| Zootaxa：投稿时检索表只需简单输入，排版由出版社处理 | 每条分支作为一个段落；偶句第一条以编号起首，第二条以连字符 '-' 起首；去向前用省略号 | 来源：https://www.mapress.com/zt/about/submissions (Preparation of manuscripts, keys 条)；https://www.mapress.com/zootaxa/files/ZOOTAXA_Requirements_Odonata.pdf (Keys 条, p.约4) |

## 3. 中文检索表惯例

本节来源薄弱：未能取得《中国动物志》编写规则、《动物志编写规范》、科学出版社检索表版式细则的原文。搜索结果只证实这些规则存在（中科院动物所 2023 年会议报道提到编研人员须遵循「中国动物志编写规则」，页面未列检索表条款），具体写法未确证。可核实的部分来自教学资料。

| 规则 | 说明 | 出处 |
|---|---|---|
| 分三式：定距式(退格式)、平行式(双项式)、连续平行式(单项式)；另有包孕式 | 包孕式只宜类群少时使用，不推荐类群多时用 | 中：https://www.cnblogs.com/impw/p/13955021.html；https://zh.wikipedia.org/zh-hans/生物检索表 |
| 定距式：相对应的两个分支起首距左端等距；下一级向右缩进一个字格；每项前写数字编号 | 「在编排时每两个相对应的分支的开头，都编在离左端同等距离的地方」属搜索摘要转述 | 中：https://www.cnblogs.com/impw/p/13955021.html（搜索摘要引述该意思） |
| 平行式：数字号码写在左侧第一格；相对的两条分支两两平行相邻；每条末尾指向下一号 | 同上 | https://www.cnblogs.com/impw/p/13955021.html；https://zh.wikipedia.org/zh-hans/生物检索表 |
| 连续平行式：每对分支有两个号，后一个括在括号内，如 1.(6) 与 6.(1)；行数约 2n-2，双项式约 n-1 个偶句 | 同上 | https://www.cnblogs.com/impw/p/13955021.html；https://zh.wikipedia.org/zh-hans/生物检索表 |
| 正文与名称/去向之间用「……」(中文省略号)连接 | 中文页面示例；未见规定点数或点线形式 | https://zh.wikipedia.org/zh-hans/生物检索表；https://www.cnblogs.com/impw/p/13955021.html |
| 最终条目要写出所到阶元的完整名称(科、属、种)；终点名称加粗 | 中文维基示例以粗体显示终点；「属名后接'属'」未在任何所读来源中确证 | https://www.cnblogs.com/impw/p/13955021.html；https://zh.wikipedia.org/zh-hans/生物检索表；「属名后接属」：未确证 |
| 编号后的标点：数字加句点，如 '1.'、'2.' | 示例所见；全角还是半角未确证 | https://zh.wikipedia.org/zh-hans/生物检索表 |
| 排序：先写显著易见的特征，按重要性排列；上部用一般形态特征，下部用较细特征 | 编制要点 | https://www.cnblogs.com/impw/p/13955021.html |
| 数字与量词、单位的写法 | 未确证：未读到相关规范原文 | 未确证 |
| 植物志数据规范：检索条目含锚点(顺序号)、跳转目标、学名和中文名 | 属数据结构，不涉及版式 | https://www.plantplus.cn/cn/standards/9（第 2.3、3.2.4 节） |

## 4. 期刊规范：Zootaxa、ZooKeys

| 规则 | 说明 | 出处 |
|---|---|---|
| Zootaxa：'Keys are not easy to typeset'，请用简单形式输入 | 每条分支一个段落；第一条以偶句号起首，第二条以 '-' 起首；去向（分类单元名或下一号）前用省略号；出版社排版 | 来源：https://www.mapress.com/zt/about/submissions (Preparation of manuscripts, keys 条) |
| Zootaxa（蜻蜓类附加须知）：偶句描述部分与分类单元或号之间用省略号(… )连接 | 示例：'1. ... (Figs 29; 33a) … 2' 与 '1’. ... (Figs 30-32a, b) ... 3'；分支以 1. 与 1’. 编号 | 来源：https://www.mapress.com/zootaxa/files/ZOOTAXA_Requirements_Odonata.pdf (Keys 条, p.约4) |
| Zootaxa：尽量少用格式；斜体、粗体只在必要时用 | 个别符号以 m# f# 代替 ♂ ♀ | 来源：https://www.mapress.com/zt/about/submissions (Preparation of manuscripts, keys 条) |
| ZooKeys：含检索表的稿件优先；以检索表为主的稿件亦可发表 | 单独的物种记述（非修订）中，检索表在多数情形下为强制 | 来源：https://zookeys.pensoft.net/about#Submissions；来自搜索摘要的引文，未在 about 页摘录中逐字复核 |
| ZooKeys：学名(属、种)应斜体；图引用 Fig./Figs 大写 F，范围用 en dash | 如 'Figs 1–3'、'Fig. 2A–E' | 来源：https://zookeys.pensoft.net/about#Submissions |
| ZooKeys 作者须知中未见检索表具体版式条款 | about 页摘录中未找到 | 未确证 |

## 5. 各来源相互冲突之处

| 议题 | 冲突 | 说明 |
|---|---|---|
| 术语：indented / nested / linked / bracketed / parallel | 不同来源给出的名称不同 | Wikipedia 以 nested(嵌套) 与 linked(链接) 为准；Saupe 讲义分 indented 与 bracketed；edichokey 把「缩进式」(各层同一缩进、分支用不同号) 与「嵌套式」(越深越缩进、分支同号) 区分开。中文「定距式/退格式」对应 edichokey 的 nested，而不是它的 indented。 |
| 缩进是否本质 | 讲义称缩进是缩进式检索表的定义；Wikipedia 称缩进非本质 | 实现检索表时以结构(分支紧随)为本质，缩进为呈现方式。 |
| 第二条分支的编号 | 1 与 1' / 1a 与 1b / 1 与 - / 连续式 1.(6) 与 6.(1) | Zootaxa 示例用 '-' 或 1’ 并存（须知用 '-'，蜻蜓附加须知用 1'）；中文连续式用括号回指号。要选一种并全书一致。 |
| 去向分隔符 | 冒号 / 省略号(…) / 点线 / 中文「……」 | Wikipedia 举例用冒号或省略号；Zootaxa 用省略号；Saupe 用点线。 |
| 回指号 | Saupe 括号式要求 '2a (1)' | 缩进式与 Zootaxa 示例都不要求；Packer 建议允许回溯，但不指定写法。 |
| 偶句不跨页、点线接末行等细节 | 只有本项目 issue 与 W3C(菜单示例) 讲到 | 无期刊或出版社的明文条款；属于排版实践与推论。 |
| 作者名正体 | 未读到任何来源明说 | 保持「未确证」。 |
| 中文规范 | 《中国动物志》编写规则未取得 | 以教学资料为准，须用本地已出版志书核对。 |
