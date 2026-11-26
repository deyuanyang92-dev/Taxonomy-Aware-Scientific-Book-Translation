# 第 3 轮裁定（主会话，2026-11-23）

## 解析（交执行员 A：只改 booklayout/keygraph.py、tests/test_keygraph.py）
接受并修：
- r3_count_fallthrough：无点线、紧跟计数名词（antennae/segments/pairs/chaetigers/節/对 等）的裸尾数不算跳转；正反条式下仍走隐式 +1。
- r3_indent_wrapped：悬挂缩进的续行并入上一支，不新开偶句。
- r3_rank_zh：去向剥离「属/科/亚科/种」及命名人，与 Genus/Род 同等处理。
- r3_restart_plain：正反条式已全部闭合后编号回到 1，切成新表。
- r3_serial_page_noleader / serial_species_noleader / serial_year_noleader：无点线时，句末「N. [阶元词] 学名 命名人[, 年份][ (p. N)]」判 taxon（页码另记 page）。
- r3_short_binomial：二字母种加词（Ia io）保留；对照签名含完整学名，改动要报 target_changed。
- r3_wrap_full_genus：完整属名后另起一行的单个小写种加词并入去向，不拆表。
- 有标题但 0 有效分支的表：保留为空表并报 error 新码 empty_key（SPEC 已加），不再丢弃。

驳回或改期望（主会话改样例）：
- r3_indent_no_heading：无标题、无编号的纯缩进文本与普通列表不可区分；调用方声明有表时报 no_keys 阻断，这就是正确的安全失败。期望改为 keys 0 + no_keys，保留为 LIMITS。
- r3_ocr_nonadjacent：非相邻 11→1′ 无条件改号会误伤；现在能报 single_branch/unreachable 阻断，属正确的安全失败。期望改为当前报错集合。Codex 自注「未确证」。

## 接入（交执行员 B：booklayout/keymodel.py、booklayout/cli.py、booklayout/keyrender.py、scripts/publish_book.py、tests/test_keygraph_wiring.py、test-keys/adv/run_corpus.py）
接受并修：
- P0 publish_book.py:44/215/221/230：任一必需检查子命令非零必须令最终 rc 非零、releasable=False；运行前删除本轮要写的旧报告（或比对报告内的产物路径与 mtime），旧报告不得冒充本轮结果。
- P0 keyrender.py:261/291 + cli.py:1778：keyrender 报告写出识别到的分支总数；gate 在 key-model 的 graph.source_keys>0 而 keyrender 分支数为 0（或明显少于 key-model 分支数的一半）时判不通过。
- P1 cli.py:1769/1778：gate 校验报告必需字段与类型；ok=true 而 graph.errors>0 视为不通过；keyrender 空对象（缺 summary）视为不通过。
- P1 keymodel.py:353：传 --entries 即视为预期有表；声明的入口号在表中不存在报 error（code dangling_jump，detail 写 entry）。
- P1 run_corpus.py:30：译文也跑 check；空字符串译文也对照（应报 key_count / missing_branch）。
- P2：gate 的 files 记入两份新报告路径；no_keys 的 detail 标明 source/translation；key-model 文件缺失给结构化报告并 rc=1，不抛栈。
不修（写进 docs 的已知限制）：
- cli.py:1765 旧调用不传两份报告返回 0：保持兼容，但 gate 输出里标明 key_model/keyrender 未检查（coverage 字段）。
- keymodel.py:354 按表清单核对局部整表丢失：需要原书表清单，留作以后。
