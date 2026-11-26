# 第 2 轮分类检索表解析审查

35 例均为合成转写，覆盖多毛类、昆虫、植物志及中日俄文版式。按 SPEC.md 核对表数、有序分支及问题码集合。下列样例名省略 r2_ 前缀和 .json 后缀。行号指本轮运行的 booklayout/keygraph.py。

P0 表示去向确已改变却通过原译对照，或整表、大段分支丢失。P1 表示局部结构、去向或告警错误。P2 表示仅影响终点的书写形式。

| 级别 | 源码位置 | 实测问题 | 样例 |
|---|---|---|---|
| P0 | booklayout/keygraph.py:57、649–652 | 双名后的第三词、subsp. 后的加词、cf. 后的种加词均能被替换而不触发 target_changed。 | trinomial、subspecies_rank、cf_epithet |
| P0 | booklayout/keygraph.py:507–514 | 无标点编号只能持平或加一。105 偶句的表在 82 明确跳往 86 时截断，210 支只读出 164 支。 | long_sparse |
| P0 | booklayout/keygraph.py:60–61、310 | 中日文编号后紧排正文，或俄文以西里尔 а、б 标支，均可令整表识别为零。全角数字本身可正常归一。 | compact_zh、compact_ja、ru_cyrillic |
| P1 | booklayout/keygraph.py:177、645–652 | 动物命名人及年份、植物作者缩写进入学名字段；略去 Linnaeus, 1758 还会误报去向改变。LIMITS 第 725 行已提示作者识别问题。 | authority、botanical_author |
| P1 | booklayout/keygraph.py:166–177 | 科或亚科后的 (part) 进入学名字段；亚科例中，另行改变页码仍能正确告警。 | part_family、part_subfamily |
| P1 | booklayout/keygraph.py:51、196–198 | 行末的末鳃刚节号和俄文图号被读作跳转，缺去向被报成悬空跳转。 | count_range、count_fig |
| P1 | booklayout/keygraph.py:237–244、507–514 | 横线后的触角节数使整支漏读；续行开头的 2 aciculae 则凭空生成分支 2a。 | dash_count、wrap_count |
| P1 | booklayout/keygraph.py:60–64、135–139 | OCR 把撇号读成 1 或 l 后，规范化分别产生 11a 和 1l。配对清稿提供期望读法，孤立字形不足以确定原号。 | ocr_one、ocr_ell |
| P1 | booklayout/keygraph.py:26、193–199 | 两个居中三点符不足匹配门槛；点线完全消失时，单空格后的缩写学名也丢失。后一情形已列于 LIMITS 第 724 行。 | double_ellipsis、lost_dots |
| P1 | booklayout/keygraph.py:190–195 | 先截页码再检测宽空格，导致带页码的科名终点退化为单独页码。 | gap_page |
| P1 | booklayout/keygraph.py:202–203、538–541 | 编号式检索表的种或亚种加词折到下一行时被丢弃，同一偶句拆成两张表。LIMITS 第 722 行仅提缩进式折行。 | wrapped_genus、wrapped_subspecies |
| P1 | booklayout/keygraph.py:47–48 | 日文「１２ページ」被解释为跳偶句 12，继而误报悬空。 | jp_page |
| P1 | booklayout/keygraph.py:67–68、166–170 | 页码与分图或图号列表并列时，Fig. 4A 残留在学名中；中文页码终点凭空产生类群「、4)」。 | plate_panel、page_figure_list |
| P1 | booklayout/keygraph.py:481–488 | 续行写回原单元格，学名中残留页码；独立页码列排在科名列之后时，两支科名都消失。 | table_cont、table_split_columns |
| P1 | booklayout/keygraph.py:458–463 | 页尾单列跳号被作印刷页码丢弃。底稿将同一目标内联，可核对下一页实际接到的偶句。 | detached_pageend |
| P1 | booklayout/keygraph.py:305–310 | 页标后同行紧接分支时，整行丢弃，只剩备择支。 | inline_marker |
| P1 | booklayout/keygraph.py:139、589 | 去掉了偶句号的前导零，却用原字符串 01 查回指来源，误报 backref_mismatch。 | padded_backref |
| P2 | booklayout/keygraph.py:149–150 | sp. 和 spp. 的缩写点被剥去。两例按保留开放命名原写法断言；SPEC 未单列缩写标点规则。 | sp_terminal、spp_terminal |

通过的对照为 abbr_control（六个连续点、缩写属名、换种告警）、prime_control（全角数字、直撇号及空格分隔点线）、fig_page_control（简单俄文图号与页码并存，仅改页码即可告警）。

运行命令为 PYTHONDONTWRITEBYTECODE=1 python3 test-keys/adv/run_corpus.py。退出码 1；逐例差异见同目录 corpus_report.json。
全量 90 例，58 例通过，32 例失败。第 1 轮 55 例全部通过；第 2 轮 35 例中 3 例通过，32 例失败。
