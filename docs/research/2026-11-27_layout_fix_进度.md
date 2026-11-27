# 2026-11-27 booklayout 五项修复进度

规则：每项先写失败测试，再改代码，再跑相关测试文件。工作树开工前已有他人未提交改动，未回退。

## 项 1 标题层级（完成）
- 改 booklayout/fontlevels.py：number_depth 接受裸 "1 Introduction"；新增 _bold_short_line（同字号粗体短行候选，排除句末标点、小写开头、引导点、行末页码）；新增 merge_levels；assign_levels 改用 merge_levels。
- 改 booklayout/ingest_native.py refine_levels：不再对有编号的书提前返回，编号深度与字号阶梯合并。
- 改 booklayout/profile.py（MAX_HEADING_LEVEL=6，heading_style 超 4 级回落到 4 级样式）、builder.py（define_heading_styles 1-6，去掉 min(level,4)）、htmlout.py（CSS 1-6）、restyle.py（Heading 5/6）。
- 新测试 tests/test_booklayout_heading_merge.py：test_same_size_bold_numbered_headings、test_bold_genus_paragraph_stays_one_body_block、test_bigger_unnumbered_title_not_below_numbered、test_fontlevels_number_regex_bare_number、test_merge_levels_unnumbered_between、test_deep_levels_get_styles（6 过）。
- 改旧测试：tests/test_booklayout_ingest_native.py 的 test_refine_levels_keeps_numbered_books 换成 test_refine_levels_merges_numbered_and_unnumbered（旧测试断言"有编号的书不动"，与本项要求相反，有意改）。
- 相关文件跑过：heading_merge、ingest_native、fontlevels、profile、restyle、structure 共 52 过。
- 未做：Heading 5/6 在非默认 builder 模板上的外观未逐一核对。

## 项 4 栏数（完成）
- 改 booklayout/ingest_native.py order_lines：分栏线两侧有一侧没有行时返回 1 栏并按单栏排序。builder 的 page["columns"] 处理未动。
- 新测试 tests/test_booklayout_order_lines_columns.py：test_one_sided_gutter_is_single_column、test_two_sided_gutter_stays_two_columns；与 test_booklayout_ingest_native.py 共 21 过。

## 项 5 publish_book 文档串（完成，选"加进 plan()"）
- 查：booklayout normalize --aligned X 默认原地改写，由 cli._locked_inplace 加锁；align-md 自身不调用 normalize（alignmd.py:12 写明二者分开）；docs/booklayout.md:116-122、184 把 normalize 列为必经确定性步骤。因此加进 plan() 安全。
- 改 scripts/publish_book.py：STAGES 在 align 后加 normalize 阶段，命令 booklayout normalize --aligned aligned.json --report normalize_report.json；文档串同步。
- 新测试 tests/test_publish_book.py::test_dry_plan_normalizes_after_align；该文件 4 过。

## 项 2 目录（完成，选"新增角色 toc_entry"）
- 查：profile.py ROLES 没有 toc_entry；docstruct 路径用 role=index（需 --layout-dir 与 meta.contents_in_place），离线路径没有目录输出，所以新增角色并补渲染。
- 改 booklayout/ingest_native.py：新增 toc_entries()（调 contents.contents_from_pdf_page 与 contents.parse_contents；三分之一行以引导点加页码结尾，或几何条目 >=5 且有 Contents 类标题/接在目录页之后）、apply_toc()（把碎块换成每条目一个 toc_entry 块：text=标题，printed=印刷页码，toc_level，style=Contents；"Contents"标题块保留），页 kind=toc；ingest() 在 refine_levels 之后调用。
- 改 booklayout/profile.py（NEW_ROLES 加 toc_entry）、gtranslate.py（ROLES 加 toc_entry，标题可译）、cli.py（空译文判定排除 toc_entry）、builder.py（新增 render_toc_entry：右对齐点引导制表位，按 toc_level 缩进；render_body 处理 role=toc_entry）。
- 新测试 tests/test_booklayout_toc_native.py：test_leader_contents_page_becomes_toc_entries、test_contents_without_leaders_needs_contents_title、test_builder_renders_toc_entry_with_dot_leader（3 过）；与 ingest_native、heading_merge、contents、contents_entries 共 39 过。
- 未做：目录页上的标题仍参与字号阶梯统计（在 refine_levels 前未剔除）；多栏目录的作者行可能并入标题。

## 项 3 图锚点（完成）
- 3a 向量簇过滤：booklayout/pdffigures.py 新增 _is_furniture_or_table（整体落在页面上/下 15% 带内的簇、文字面积占比 >35% 的簇、全是轴向直线或矩形且无填充、文字占比 >=5% 的网格表，均不算图；带填充或曲线的绘图保留）和 _text_spans；image_placements(vector=True) 调用它。测试 tests/test_booklayout_vector_filter.py：test_table_grid_is_not_a_figure、test_header_and_footer_rules_are_not_figures、test_real_vector_drawing_is_kept（3 过）。
- 3b ingest：booklayout/ingest_native.py 新增 add_figure_blocks（image_placements(vector=True) + page_captions + figures.link_figures），按阅读序插入 role=figure 块：bbox（src.bbox）、crop（与 figures extract 同名 source_figure_crops/fig_source_pNNN_II.png）、label、与图注块互指（figure 块 caption_block_id，图注块 figure_id）。
- profile.py NEW_ROLES 加 figure（text 置空以过校验）。builder.py：place_figure 先按 figure_id 取图（取不到不猜），无 figure_id 走旧的标签/首个未放图；新增 render_figure_block 打印无图注的 figure 块；render_body 处理 role=figure，cap_first 的 first_y 不计 figure 块。
- run.py、sample.py 抽图命令加 --vector，使裁图编号与 ingest 一致。
- 测试 tests/test_booklayout_figure_blocks.py：test_ingest_emits_figure_block_paired_with_caption、test_place_figure_prefers_figure_id_over_label、test_place_figure_without_figure_id_keeps_label_matching、test_unpaired_figure_block_is_rendered_in_place（4 过）；pdffigures、multilevel、run、sample 等共 57 过。
- 未做/限制：figure 块在双栏页的插入位置按 y 与 x 粗估；figures extract 的 furniture（重复页的页眉图）不在 audit 输出里，builder 对其块静默跳过。

## profilegen 回归（本批新发现，已修）
- 现象：项 1 把 heading_styles 校验上限设为 6 后，profile --from-pdf 在量到 7 级字号阶梯的书（Rouse 2022、Hartmann-Schröder）上抛 ValueError: heading_styles key '7'。
- 修：booklayout/profilegen.py 新增 fit_heading_styles（>6 级折叠丢弃，不足 4 级补齐），测试 tests/test_booklayout_profilegen_levels.py（2 过）；profile.py 重复的 MAX_HEADING_LEVEL 行已删。
- 对比公平性：before 副本（项 1 改动撤回）同样套用此 profilegen，使两边都能出 profile。
- 另补：docstore/structdoc.py EXTRA_TYPES 加 toc_entry（test_types_superset_of_aligned_roles 因新角色而败，已修）。

## 多书验证（--no-translate，--no-source-check，无云端；输出 排版/_试点_booklayout/fix1127/<书>/{before,after}）
| 书 | 页 | likeness A 档 | 标题级数(after) | figure 块/图注 | toc_entry |
|---|---|---|---|---|---|
| Handbook Vol3（Springer 系） | 13-40 | 5/7 → 5/7 | 3 | 0→13 / 13 | 0 |
| Rouse 2022 | 5-24 | 2/7 → 4/7 | 6（原书 7） | 0→9 / 9 | 0 |
| Hartmann-Schröder 1996（扫描+OCR） | 8-27 | 2/7 → 3/7 | 4（原书 10） | 0→40 / 0 | 0 |
- 以 Hartmann-Schröder 代替 Greg 2022（Greg 无文本层、未做 OCR，已跳过）。
- 退步：Rouse roles 序列比 0.56 → 0.26（新增 figure 块进入角色序列；源侧同样含 figure，但顺序与输出不一致，未查清）。
- 未达成：三本 toc_entry 均为 0。Handbook/Rouse 所选页段不含印刷目录页；Hartmann 目录页是德文标题"Inhaltsübersicht"、OCR 引导点碎成多块（每页 159-281 块），toc_entries 未触发——离线目录检测对此类 OCR 扫描页无效。
- Hartmann figure 块每页 2 个、共 40 个而图注 0：疑为整页扫描底图/半页图被当作图，属误检，未处理。
- 标题级数：Handbook 3 级未超过原书；Rouse 6 对 7、Hartmann 4 对 10，层级仍有缺口。
- furniture.type 三本都不通过（页眉文字/折叠类型），本批未涉及。

## 全量 pytest（无 -x）
- 修后 2459 过 / 6 败 / 1 跳（基线：301 过 1 败 为 -x 提前停）。
- 本批引起并已修：test_types_superset_of_aligned_roles（toc_entry）。
- 非本批改动：test_wrapped_name_line_gets_leader_from_left_margin（基线已败）；test_figure_no_order_flags_outlier_with_hint（测纯 structdoc 函数，该文件我只加一个类型名）；test_chapter_split::...unconfirmed_plan（ModuleNotFoundError test_translate_corpus）；test_usage_monitor 2 个。后四者未逐个对照 HEAD 复现，归因为"未确证"。
