# 第 3 轮检索表审查

30 例合成转写，正反条的依据见 SPEC.md 和 corpus/real_marinov_thesis.json。样例简称省略 r3_ 和 .json。以下区分 CLI 实测、语料实测和发布路径静态审查。P0 为错误结果可通过质量检查，P1 为漏表、误阻断或检查覆盖不足，P2 为报告可追溯性问题。

## 发布接入

| 级别 | 位置 | 发现 |
|---|---|---|
| P0 | scripts/publish_book.py:44、215、221、230 | 静态审查。qa 阶段包含 keyrender，任一子命令非零只令本阶段 ok=False，失败状态未带入最终 rc。若本轮读取 PDF 或写报告失败，复用工作目录的旧合格报告仍可能令 releasable=True。应把本轮各必需检查的完成状态带入最终判定，并核对报告所属产物。 |
| P0 | booklayout/keyrender.py:261、291；booklayout/cli.py:1778 | PDF 中整张表消失或一个分支也没识别时，keyrender 跳过该页；全书零分支与全部检查通过可生成同样的全零汇总。源码推断：即使 key-model 已识别表，gate 也无法比较 PDF 实际覆盖数。本轮未运行完整 PDF 发布。 |
| P1 | booklayout/cli.py:1765、1775；tests/test_keygraph_wiring.py:64 | 实测旧调用省略两份报告返回 0；测试明确保留该兼容行为。发布计划第 121–124 行会传两份报告。若独立 gate 也作为交付凭据，应在报告标明实际检查覆盖。 |
| P1 | booklayout/cli.py:1769、1778 | 实测模型报告 ok=true 与 graph.errors=1 矛盾，同时 keyrender 为合法 JSON 空对象，gate 返回 0。应检查报告必需字段、类型及汇总一致性。 |
| P1 | booklayout/keymodel.py:353；booklayout/keygraph.py:742；scripts/publish_book.py:104 | 实测无标题零表加 --entries 1,5 返回 0，加 --expect-keys 才返回 1。已有一表时两项合用并声明不存在的入口 99 又返回 0，入口被过滤后默认取最小号。发布脚本未传这两个选项。 |
| P1 | booklayout/keymodel.py:354、358；booklayout/keygraph.py:837 | 预期表数是全书布尔值。second_title_empty 第一张可读，第二张仅余标题与图像占位，文档级规则通过。需要按标题或原书表清单核对才能发现局部整表丢失。 |
| P1 | booklayout/keygraph.py:859；test-keys/adv/run_corpus.py:30 | 独立 CLI 与语料运行器仅对译文做 align，未做 check；运行器还会略过空字符串译文。发布用 key-model 第 364 行确有译侧图检查。语料通过数不代表三个入口等价。 |
| P2 | booklayout/cli.py:1788；booklayout/keymodel.py:367、380 | gate 的 files 漏记两份新报告路径；双侧同时缺表时两个 no_keys 没有侧别。implicit_next 实测旧 keys=0、graph_keys=1、rc=0；顶层 blocks 来自旧解析器，读报告时须区分两个字段。 |
| P2 | booklayout/keymodel.py:377、383；booklayout/cli.py:1756、1760 | key-model 显式译文文件缺失实测 rc=1，抛 FileNotFoundError，未生成新报告。必需 qa/check/key-report 的读取也在异常处理之外；与两份新报告的结构化失败格式不同。 |

**已核验的拦截路径。** gate 明确指定缺失的模型或渲染报告，分别返回 1 并给出路径。keyrender 的 summary 单项非零或仅 findings 非空，分别足以令 gate 返回 1。原文无表、译文多一整表时，key-model 实测返回 1，语料对照命中 key_count。tests/test_keygraph_wiring.py:75 已覆盖两字段同时异常与缺文件；本轮额外分别核验两个字段。检查采用内存文件调用实际 CLI。

## 图解析与原译对照

| 级别 | 位置（booklayout/keygraph.py） | 语料实测 |
|---|---|---|
| P0 | 180、215、803 | short_binomial 中 Ia io 与日译误录 Ia xx 均丢失种加词，未报 target_changed。应保留终点中的二字母加词，并检查对照签名是否确实包含学名。 |
| P1 | 356、668 | restart_plain 同页两组正反条分别闭合，第二组从 1 重启。分表时旧条号尚未配对，两个表被合并，随即全表退回回指解析；有独立标题的对照能分表。 |
| P1 | 275、367 | count_fallthrough 中 Number of antennae 1 被判作跳 1，遮蔽应有的隐式跳 2，凭空出现环和不可达偶句。正常无去向接下一条、跨页续表和末条缺终点的对照均通过。 |
| P1 | 82、266、272 | serial_year_noleader 的作者年份使编号属名整体漏识；serial_page_noleader 只留下页码；serial_species_noleader 中编号、缩写种名加括号作者也漏识。有点线的编号属名及年份对照通过。 |
| P1 | 76、194 | rank_zh 的「属」和命名人原样进入终点字段，rank_ru 中 Род 能正确剥离。 |
| P1 | 400、524 | indent_no_heading 的六支整表漏识；indent_wrapped 仅折了一行性状便凭空多出一级偶句，后续子树也改号。 |
| P1 | 179、689 | wrap_full_genus 中 Nereis 后另行的 pelagica 丢失，一个偶句被拆成两张表。 |
| P1 | 159 | ocr_nonadjacent 中清稿 1′ 在子偶句之后，OCR 的 11 被保留为偶句 11；源文单独判读未确证，不宜无条件改号。 |

**成对与回指。** mixed_two_headings 在同页分别识别两种括号式；mixed_hints 中带撇号备择的互指未被误并。partial_nested 缺内层对立条，实测整表按 SPEC 回退，连外层完整对也报错；incomplete_reciprocal 报单支。中译改跳号、改页码，日译改一般属名、漏支，俄译调序及等值页码对照均通过。

**LIMITS 成本判断。** 当前 booklayout/keygraph.py:872 实列八项。前四项中，缩进折行可对有标号或明确悬挂缩进的续行低成本合并；无标题纯缩进宜先验证完整兄弟子树，避免把普通列表当表。无点线终点可先支持显式序号加阶元、作者、页码；普通性状后的裸词仍有歧义。作者和学名宜共用已解析的终点字段，短加词可局部修复，复杂命名仍需对照。

后四项中，裸尾数量可先处理明确数量词；非相邻 OCR 撇号须结合清稿或结构提出待核候选；成对不全宜在全表回退时标出缺哪一条，保留 SPEC 判别；折行加词可先支持已有点线、完整属名后单独成行的情形。上述均为修复范围判断，尚未改动实现。

运行命令：`cd /mnt/p/翻译-译作/Taxonomy-Aware-Scientific-Book-Translation && python3 test-keys/adv/run_corpus.py`
通过 **111/122**，退出码 **1**。前两轮 **92/92**；第 3 轮 **19/30**，失败 **11**。逐例差异见 corpus_report.json。
