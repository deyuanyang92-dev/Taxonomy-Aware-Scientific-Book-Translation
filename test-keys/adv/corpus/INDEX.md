| id | 格式 | 语种 | 要击穿什么 |
| --- | --- | --- | --- |
| [de_page_only](de_page_only.json) | dash | de | 德文 S. 引向记述页，两个页码均不参与图的可达性检查。 |
| [de_two_entry_join](de_two_entry_join.json) | ab | de | 两个声明入口共用叶部性状偶句 3，仅对汇合给出警告。 |
| [en_ascii_prime](en_ascii_prime.json) | prime | en | 直撇号标同号第二支。 |
| [en_backref_one](en_backref_one.json) | backref | en | 依 SPEC，1(3) 表示从 3 来；已声明以 3 为入口，核对实际边 3→1。 |
| [en_backref_wrong](en_backref_wrong.json) | backref | en | 实际由 1 进入 2，括号却写 4。 |
| [en_backwards_ok](en_backwards_ok.json) | ab | en | 路径 1→3→2 终止于页地址，3→2 合法且无环。 |
| [en_dangling_range](en_dangling_range.json) | ab | en | 范围取左端后表中无偶句 5。 |
| [en_diamond](en_diamond.json) | ab | en | 两条检索路径在 4 汇合，按 SPEC 仅提示 multi_parent；汇合后仍能到达终点。 |
| [en_duplicate_b](en_duplicate_b.json) | ab | en | 三行各有性状，但后两行都印成 1b；不能据行序改成 1c。 |
| [en_duplicate_prime](en_duplicate_prime.json) | prime | en | 直撇号和真撇号归一后重复，不能按原字形去重。 |
| [en_empty_cell](en_empty_cell.json) | table | en | 末行第三格为空；第二格的性状不能补作分类终点。 |
| [en_indent_siblings](en_indent_siblings.json) | indented | en | 纯缩进表按子树先后编号。 |
| [en_island_cycle](en_island_cycle.json) | ab | en | 2→3→2 构成独立子环。 |
| [en_letter_jump](en_letter_jump.json) | other | en | 字母 B 单独作去向，指第二偶句。 |
| [en_letters](en_letters.json) | indented | en | A/AA 与 B/BB 各成一对，子层为隐式跳转。 |
| [en_no_stop](en_no_stop.json) | prime | en | 数字和撇号之后直接留空格，没有句点。 |
| [en_prime_jump](en_prime_jump.json) | bullet | en | 依 SPEC，带撇号的数字去向归到偶句 2。 |
| [en_range](en_range.json) | ab | en | 依 SPEC 去向范围取左端 5，6 另由 5a 到达；未连续使用的号不在问题词表内。 |
| [en_running_head](en_running_head.json) | prime | en | 跨页后先遇页眉与印刷页码，再遇弯撇号备择。 |
| [en_same_terminal](en_same_terminal.json) | ab | en | 本批标本有两种束生针叶数，均归松属。 |
| [en_single_primary](en_single_primary.json) | ab | en | 主支和终点俱存，缺少与它配对的分支。 |
| [en_trichotomy](en_trichotomy.json) | polytomy | en | 三个互斥的叶序各有地址。 |
| [en_two_entries](en_two_entries.json) | ab | en | 开花与结果标本各有一个声明入口。 |
| [en_two_titles](en_two_titles.json) | ab | en | 同一物理页两个标题各自重启编号，分支按表的出现次序展平。 |
| [en_unreachable_chain](en_unreachable_chain.json) | ab | en | 入口 1 到不了 2 和 3。 |
| [es_bullet_page](es_bullet_page.json) | bullet | es | 项目点承接上一号。 |
| [es_crosspage_cycle](es_crosspage_cycle.json) | dash | es | 分页前后的两条实际跳转组成 1→2→1；每个偶句只有一个入边。 |
| [fr_backref_self](fr_backref_self.json) | backref | fr | 第二偶句把来路误记为自身，实际来路为 1；只有去向边才能构成环。 |
| [fr_empty_tail](fr_empty_tail.json) | dash | fr | 第一支的点线止于换行，下一行已有自己的支号与终点。 |
| [fr_prose_boundary](fr_prose_boundary.json) | dash | fr | 末支后紧接采集地正文，段末页号不属于末支。 |
| [fr_wrap](fr_wrap.json) | ab | fr | 第一支的形态描述在介词前折行，后一行的属名属于该支。 |
| [ja_figure_anchor](ja_figure_anchor.json) | dash | ja | 图号修饰终点，图号后的属名仍须提取。 |
| [ja_image_only](ja_image_only.json) | other | ja | 调用方声明入口 1，文本层只有标题和图版占位。 |
| [la_ab_caps](la_ab_caps.json) | ab | la | 拉丁文表以大写 A、B 作支号，规范化为小写。 |
| [pair_chinese_only](pair_chinese_only.json) | ab | en → zh | 第二支把拉丁双名全部替换为中文，即使读者能理解其所指，也丢失原书的学名地址。 |
| [pair_equivalent_pages](pair_equivalent_pages.json) | ab | en → zh | 页标由英文改为中文全角括号，分支、拉丁双名与页码数值逐一相符。 |
| [pair_extra_fourth](pair_extra_fourth.json) | polytomy | en → zh | 译文在合法的三歧后增添 d，额外去向也必须按分支身份识别。 |
| [pair_extra_third](pair_extra_third.json) | ab | en → zh | 原文二歧，译文凭空增添 c。 |
| [pair_genus_only](pair_genus_only.json) | ab | en → zh | 种加词丢失，只保留属名和正确页码。 |
| [pair_missing_fourth](pair_missing_fourth.json) | polytomy | en → zh | 四歧变三歧，d 消失。 |
| [pair_missing_last](pair_missing_last.json) | polytomy | en → zh | 译文漏掉三歧末支 c，余下 a、b 次序不变且仍成对。 |
| [pair_numeric](pair_numeric.json) | ab | en → zh | 译文 1a 将种名和所附页码换成表内已有的偶句号 2。 |
| [pair_order_three](pair_order_three.json) | polytomy | en → zh | 译文保留首支，把 c 排在 b 前；每个地址仍附于原标号。 |
| [pair_order_two](pair_order_two.json) | ab | en → zh | 译文将完整的 b 支提前。 |
| [pair_page_dropped](pair_page_dropped.json) | ab | en → zh | 第一支保留种名却漏掉其记述页；去向同时包含的页码也要比较。 |
| [pair_taxa_swapped](pair_taxa_swapped.json) | ab | en → zh | 两个种名互换，分支和页码均保留原序；比较全表名称集合会漏报。 |
| [pair_whole_key_added](pair_whole_key_added.json) | ab | en → zh | 译文增加一张完整且有独立标题的表。 |
| [pair_whole_key_lost](pair_whole_key_lost.json) | ab | en → zh | 原文第二表整张漏译。 |
| [ru_lost_glyphs](ru_lost_glyphs.json) | other | ru | 调用方声明入口 1，OCR 仅留下框线与缺字方框。 |
| [ru_prime_page](ru_prime_page.json) | prime | ru | 换页仍属同一偶句，俄文标题和真撇号均须保留其作用。 |
| [ru_single_prime](ru_single_prime.json) | prime | ru | 只有撇号支，同时满足单支和无主支两个定义。 |
| [zh_dangling_nextline](zh_dangling_nextline.json) | ab | zh | 第一支折下去的 19 没有页码标志，表内也无第 19 偶句。 |
| [zh_page_detached](zh_page_detached.json) | dash | zh | 中文译排中两个地址各占下一行，均归入紧邻的上一支。 |
| [zh_single_dash](zh_single_dash.json) | dash | zh | 第二偶句被明确跳入，只余标号 2b 的一支；同时报单支和孤立备择。 |
| [zh_three_columns](zh_three_columns.json) | table | zh | 三列表的单元格边界已划定去向，Markdown 分隔行没有分支。 |
