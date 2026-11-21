# 全书结构化与按需翻译/排版：顶层方案（审定稿）

日期：2026-11-21。输入：Google 4 份稿（01_ocr / 02 / 03_json_ai / 04_pdf）；审查：主线程逐条对照仓库代码 + Codex 独立审查（`codex_review.md`）。

## 1. 结论

4 份稿方向对，但都按"新建一套"写，与仓库已有模块重复。审定原则：**扩展现有模块，不新建平行库**。

| 稿 | 取 | 弃/改 | 依据 |
|---|---|---|---|
| 01 OCR 预检 | 范围模式（全本/书签章/目录章/页段）；缓冲页；页级持久复用 | 不另建 `ocr_pages/`。落在 docstore 的页库，`ocr_plan.json` 只是一个"待办页集合" | `docstore/textify.py:152-160` 已按页跳过已有结果、支持 `pages` 参数 |
| 02 逻辑切分 | 块级边界 `[page, block]`；node_type 分流（chapter/key/taxon_entry/figure_plate/references）；覆盖完整性闸口 | 不新写 4 级路由。`chapter_split.py detect` 已有书签→印刷目录→标题三路 + `chapter_plan.json` + `confirmed`。只在计划里加块边界字段与 node_type | `scripts/chapter_split.py:1-25`；`split_check.py` 现只查图注混入，需新增覆盖检查（Codex） |
| 03 JSON IR | 唯一真相源 + 原子补丁 + 乐观锁(old_hash) + 单块守卫 + 脏标记 + 可回滚 | 不新建 `book_ir/`。**把现有对齐 JSON 升格为 IR**：已有 `page/chapter/kind/blocks[role,translation,y0]`、`patch-blocks`、`repair` | `booklayout/alignmd.py:94`、`booklayout/cli.py:12,1198`、`docs/booklayout.md:16-37` |
| 04 极速 PDF | 双轨（草稿预览 vs 终稿）；按单元哈希缓存；150 DPI 预览图 | Typst 先评测不先承诺；单章渲染后合卷的页码/目录/索引不可靠，终稿仍走两遍 | Typst 0.13.1 已装，但中文版式、分类志缩进、检索表未实测；`docs/booklayout.md:195` 两遍是现行硬流程 |

## 2. 必须先修的一个隐患（Codex 发现，已核实）

对齐 JSON 的 `block_id` 现为 `p{页}-b{页内序号}`（`booklayout/alignmd.py:94`）。重新切分或 OCR 重跑后，同一 id 可能指向另一段，旧补丁会**静默改错**。

处置：
1. 补丁必带 `old_hash`（块 `src` 内容哈希）。哈希不符 → 拒绝，不改。
2. 块 id 稳定化：`p{页}-b{序}` 之外加 `src_hash` 前缀指纹；重切时按指纹重映射，映射不到的块进人工队列。
3. 回归测试：重切后旧补丁不得命中错块。

### 2.1 小测结果（2026-11-21，Imajima v8 aligned_p1-12.json）

- 模拟重切（每页前插页眉块、位置重编号）：94 个 id 中 89 个改指别的文本。无锁时静默误改 89；带 `old_hash` 时拒绝 89、误改 0。
- 已实现（原型，未提交）：`booklayout/normalize.py` 新增 `block_src_hash()`；`apply_block_edits` 对带 `old_hash` 的补丁校验，不符计入返回值 `stale` 且不改。无 `old_hash` 的旧补丁行为不变。回归测试 `tests/test_block_old_hash.py`（3 例通过，ruff 通过）。
- Codex 第二轮审查（`codex_review2.md`，10 条）已处理：哈希只取原文 `text`、sha256 取 32 位，无原文块不可上锁（#2、#10）；删除也受锁，补丁 `"version":2` 强制带哈希（#3）；删除后清 `by_id`（#7）；`patch-blocks` 有 stale 时非零退出、不写回，`--allow-partial` 才写（#1）；旧测试期望补 `stale`（#6）。测试 7+7 例通过。
- 设计级待办（Codex #4 #5 #8 #9）：①重映射遇相同原文的多个块（重复标题/短段）须用源页+页内位置+邻块消歧，多候选进人工队列，P0 加此用例；②P1 的"应覆盖集合"由选定范围 + docstore 源块清单 + `skipped_pages` 登记确定，其余块须按序恰好一次，不允许带缺口通过；③P2 验收分"OCR 读取范围"与"译文输出范围"，加同页章界样例；④P3 验收含守卫拒绝、日志、revert 还原断言，P4 验收含预览内容与终稿一致（不只比耗时）。
- 第三步原型：`booklayout/blockid.py`（`fingerprint_table` / `remap` / `check_coverage`）+ `tests/test_blockid.py`（7 例通过，ruff/mypy 通过）。重复原文不按位置猜：唯一哈希须源页相同；重复哈希须新旧组大小相等且恰有一个候选前后邻块相同，否则列 ambiguous。Imajima v8 真数据：重切模拟后 94 块中 93 映射、0 歧义、1 孤儿（唯一的无原文块，须先回填原文）；覆盖检查登记第 7 页跳过后仅剩第 6 页 source_page≠page 需写明理由（正是预期的闸口行为）。
- Codex 第三轮已处理：`remap` 改为与表顺序无关（互为最优 + 源页必须相同，否则进 ambiguous，不按位置硬选；重复哈希组大小变化一律 ambiguous）；`check_coverage` 增 `expected_blocks`（源块序列：丢失/多出/乱序）、空理由、重复页、无原文块检查；v2 补丁 `missing` 也视为冲突不写回。测试 18 例通过。
- Codex 第四轮已处理（测试 27 例通过）：`remap` 重复组须同大小+邻块唯一，None 的 source_page 归一为页码，重复旧 id 全部 ambiguous，输出排序；`check_coverage` 用多重集比较、已登记跳过页不报 empty、跳过/放行理由分别校验空值；CLI 冲突时报告 `applied=[]`/`removed=[]`（原值存入 `not_written*`），`--report` 不得等于 `--aligned/--patch/--out`，写盘原子（临时文件+rename）；哈希先 strip。
- 已知限制：指纹表只存哈希不存原文，无法事后核对；`source_page_ok` 目前按页放行（P1 改块级）；`expected_blocks` 省略时不做块级核对，P1 须改为必填。
- Codex 第五轮已处理（测试 48 例通过，ruff 通过）：补丁校验——编辑项非 dict、id 非空串、未知键、`remove` 非布尔或与字段并用、无操作、字段值非字符串均记 `invalid`；`old_translation` 作为译文前置条件（后补丁不覆盖前补丁），不符记 `stale`；`data` 内重复 id 报错；v2 批次整体拒写（`--allow-partial` 是唯一例外）；CLI `--out` 不得等于 `--patch`，写盘用唯一临时文件+rename 且保留软链接。`blockid.py`：`check_coverage` 不给 `expected_blocks` 时 `ok` 恒为假（须显式 `pages_only=True` 才只验页级），已登记跳过页按**源页**在期望与实际两侧同口径排除，block_id 须为非空字符串；`remap` 拒绝新数据里重复/非法 id（列入 `invalid_new_ids`）。
- Codex 第六轮已处理（测试 65 例通过，ruff 通过，mypy 仅余旧错 `builder.py:238`）：补丁协议 v2 现为——整体须为 dict、`version`∈{1,2} 的整数、`edits` 为列表；每项必带整数 `page`，及每个被改字段（`translation`/`role`/`level`）对应的 `old_*`（删除须带 `old_translation`+`old_role`），任一不符记 `stale`；`role` 须在 `profile.ROLES` 白名单，`level` 为 ≥1 整数且非布尔；重复 id 用 `Counter`；CLI 对 `<aligned>.lock` 加 `flock`，数据先于报告写盘，拒绝时报告 `not_written*`、返回码 1，写盘保留原文件权限位。`blockid.py`：重复文本组大小按**全部**新块计，组内含不可寻址（非法/重复 id）候选则不自动确认；新旧 id 须为非空字符串，`1` 与 `"1"` 不合并，列表/字典 id 返回结构化错误而非抛 `TypeError`；`check_coverage` 的跳过页只从期望侧扣除，输出里出现已跳过源页的块一律报 `excluded_present`；跨页许可改为按 `(block_id, source_page, logical_page)` 绑定到具体块；`source_page: null` 统一由 `_sp()` 归一。
- Codex 第七轮已处理（测试、ruff 通过；mypy 仅余旧错 `builder.py:238`）：补丁协议 v2 现必带 `old_prev`/`old_next`（全书序邻块哈希）、移除须带 `old_level`；`old_*` 严格类型；`role` 改为 table/list 须带 rows/items；顶层未知键与非整数 `version` 记 `invalid`；非 str/不可哈希 id 用 `safe_key`，`remap` 对非法旧 id 按行键。CLI 的 `patch-blocks` 已用 `fcntl.flock` 锁定（共享目录 `tempfile.gettempdir()/booklayout-locks`，锁名为解析后路径的 sha256，同时锁 aligned 与 out 路径，按序加锁）；写盘用 O_EXCL 临时文件 + `os.replace`。不支持硬链接（软链接经 `resolve()` 跟随）。前置条件不符（`old_*` 值与现状不同）记 `stale`；缺少必需的 `old_*` 字段记 `invalid`，两者均整体拒写。
- Codex 第八轮已处理（测试 86 例通过，ruff 通过，mypy 仅余旧错 `builder.py:238`）：v2 补丁缺 `old_hash` 记 `invalid`（原为 `stale`）；移除须带 `old_struct`（`block_struct_digest`：rows/items/figures 的规范 JSON sha256 前 32 位），单元格被改过后再删记 `stale`；邻块哈希新增哨兵 `NOHASH="~"`（有邻块但无可用哈希），`""` 只表示全书首/尾；`role` 改动复用 `profile.validate_aligned` 校验；补丁 JSON 含重复键或不可解析时 `patch-blocks`/`repair` 打印 `error: bad patch file` 并返回 2，不写数据也不写报告。`check_coverage` 遇不可哈希 id/`source_page` 返回 `ok=False` 而非抛 `TypeError`；`remap` 新增逐行人工队列 `queue`（`row`、`raw_id`、`status`、`candidates`），与输入顺序无关。`_write_json` 先以 0600 建临时文件，改名前设为目标原权限（新文件为 `0666 & ~umask`，umask 读自 `/proc/self/status`，不改进程 umask）。锁目录固定为 `/tmp/booklayout-locks`（`BOOKLAYOUT_LOCK_DIR` 可覆盖，与 `TMPDIR` 无关），锁文件 0666 以便跨用户打开；`--aligned/--patch/--report/--out` 落在锁目录内一律拒绝（返回 2）；`repair` 与 `patch-blocks` 共用同一加锁事务。仍不支持硬链接。
- 第七轮残余风险（未修，需 P3 持久 docstore 块 id，不是靠哈希或邻块能解决）：①两个相同文本且相同邻居的块无法区分（发现 1）；②同文替换被 `check_coverage` 判为完整（发现 6）；③`remap` 会自动确认被污染的旧指纹（发现 11）。P0 只能缓解，不能消除。
- 补丁入口余下归 P3：日志、revert、脏标记、持久块 id；
- 仍未做：把稳定指纹 id 写入对齐 JSON；补丁入口自动先 remap；译文字段版本前置条件（防后补丁覆盖前补丁）；manifest `skipped_pages`。
- 真实数据发现 ①：第 7 页（参考文献续页）被有意略过，但全书任何文件都没记录。结论：manifest 必须写 `skipped_pages: [{page, reason}]`，覆盖检查才能区分"漏"与"有意略"。
- 发现 ②：第 6 页有 22 块 `source_page=5`。是否标错未确证。规则：块级 `source_page` 为准；`page≠source_page` 仅在 key 续页等有理由时放行，否则报警。
- 发现 ③：`apply_block_edits` 原先对不存在的 id 只记 `missing`，无 old_hash，也无漂移测试（现已补）。

## 3. 目标架构（五层，向下依赖）

```
L0 页库   docstore（pages/pNNNN.json：块、bbox、layout_type、页码、qc）  ← 唯一页级真相源
L1 结构   chapter_plan.json v2（节点 = 章/检索表/条目/图版/文献；起止 = [页,块]；confirmed）
L2 内容   对齐 JSON（= IR）：块级 src/translation/role/style_override/locked + 单元哈希
L3 补丁   patch-blocks 升级：原子操作 + old_hash + 单块守卫 + 日志 + revert
L4 渲染   DOCX 管线（终稿）+ 单元级预览（草稿）；两遍排版仍为终稿路径
```

## 4. 用户场景如何走通

- **指定页码翻译**：`docstore` 只 OCR 所选页(+缓冲)→ 取这些页的块 → 直接进翻译批（不需要先有章结构）。
- **指定章节翻译**：`chapter_split detect` → 人工确认 `chapter_plan.json` → 按节点的 `[页,块]` 取块 → 翻译；node_type 决定策略（references/index 默认跳过；key 走 `keys.py` 严格模式）。
- **全书数据化**：OCR 全页 → `detect` → 确认 → 全部块入对齐 JSON，带目录与页码映射。
- **改错/改排版**：`bookir`-式查询（按文本/页/图号返回 1–3 块+邻居）→ 生成补丁 → 单块守卫(`italic_check`、`transqa/zh_typo`、yiku) → 仅标脏该单元 → 单元预览。不读整章、不重跑全书。

## 5. 落地顺序（每步可独立验收，先小样）

| 步 | 内容 | 验收 |
|---|---|---|
| P0 | `old_hash` 乐观锁 + 稳定块指纹（第 2 节） | 重切回归测试通过；v2 补丁 missing/stale 整体拒写（`--allow-partial` 是唯一例外，且报告 applied 仍为实际写入数）；重复删除第二次记 missing；补丁入口已有 CLI 测试；真实入口按补丁协议 v2（见上文“Codex 第六轮已处理”）要求 `page` 与全部被改字段的 `old_*` 前置值，借此拒绝多数"同文本错位"；邻块指纹与 flock 锁已在 P0 落地；彻底消除相同文本相同邻居等残余风险需持久块身份（docstore 源块 id），未完成，归 P3；新补丁必带哈希，无哈希旧补丁仅在非 v2 下兼容 |
| P1 | `chapter_plan` 增加块边界与 node_type；`split_check.py` 增"块覆盖单调无重漏" | 应覆盖集合（定义一次，各处引用）= 选定范围内的 docstore 源块清单，减去已登记 `skipped_pages`（理由非空）与块区间排除，两侧按源页同口径；`expected_blocks` 必填；每块按序恰好一次，有缺口即失败，不允许带缺口通过。Imajima 实测 |
| P2 | 按页/按章选择入口：`docstore` pages + 章计划 → 批次 | 指定 3 页翻译：OCR 读取范围（含缓冲页）与译文输出范围分别断言，输出只含这 3 页；含同页章界样例；章界块的首/末块文本断言；节点内可跳过块段（清单用块区间，不只整页 `skipped_pages`） |
| P3 | 补丁协议升级（日志、revert、单块守卫、脏标记 `build_state.json`） | 改一个词：只有 1 个单元标脏；守卫拒绝非法补丁、写日志、revert 后与原文件逐字节一致（断言）；守卫拒绝时文件与脏标记均不变；补丁带邻块指纹，上下文不符拒绝；译文字段带版本前置条件；默认拒写与 `--allow-partial` 例外以 P0 定义为准，邻块指纹与 flock 已在 P0 落地，此处验收日志、revert，并补持久块 id（消除第七轮残余风险 ①②③）；耗时与 token 实测记录 |
| P4 | 单元级 DOCX 预览 `--unit`；终稿保持 build→map-pages→build | 预览内容与终稿同单元文本一致（断言），斜体学名与缩进保留（断言）；草稿 vs 全书时间对比 |
| P5 | Typst 评测（独立实验，记 `docs/ocr_eval` 式台账）：中文、斜体学名、检索表前导点、分类志缩进 | 通过线：中文无方框、斜体学名保留、检索表前导点对齐、分类志缩进一致，且单章预览耗时 ≤ DOCX 路径的 1/3（基线先在 Imajima 同章实测记入台账）；不通过则放弃，不影响 P0–P4 |

## 6. 风险

| 风险 | 对策 |
|---|---|
| 块 id 漂移致补丁误改（最大） | P0 |
| 单章预览页码与终稿不同 | 预览明确标"草稿，页码无效"；目录/索引只在终稿两遍生成 |
| 缓冲页不能确定同页章界 | 以块级标题检测为准；缓冲只是 OCR 范围，不是边界 |
| 书签偏移/半页起章 | 在 ±2 页窗口按标题相似度锁定块（02 策略 A 的合理部分，并入 `detect`） |
| 重复建库 | 本方案禁止新增页库/IR 库；违者回到第 1 节表 |

## 7. 未确证项

- Typst 预览速度与 CJK 版式质量（Google 稿称"秒级"，无实测）。
- 现有 `chapter_split.py` 对"半页起章"的实际失败率（需在真实书上量）。
- 单元级 DOCX 渲染能否在 Word/LibreOffice 下真正缩短到可交互时长。

附：Codex 审查原文 `codex_review.md`。

## Codex 第九轮已处理

九项均已修并配回归测试：页补丁先整体校验再写（页值须为数组，`[]` 仍表示清页）；删除前置条件绑定整块规范 JSON 摘要（含 `couplet.target`）；`repair --out` 与 `--patch` 同路径（含软链接）拒绝；锁目录和锁文件只在自己独占创建时改权限，已有对象先 lstat/O_NOFOLLOW 核验并省略 `O_CREAT` 打开；remap 人工队列候选按行保存；`check_coverage` 对数组型 `source_page` 记入 `bad_source_page` 而不抛异常；repair 只给新块写整数 `source_page`，数字字符串统一归一；表格单元格 `colspan` 须为正整数。残余风险（需持久块 ID）仍记在第七轮条目。

**Codex 第十轮已处理（11 项）**：`normalize`/`key-align`/`backfill-source` 与 `patch-blocks`/`repair` 共用同一把锁，持锁后才读稿（`_locked_inplace`）；对齐稿读取一律严格拒绝重复 JSON 键（`builder.load_aligned`），失败时原件不动；整页补丁新增 `old_page_digests` 前置条件、规范化页号去重、全书块 ID 唯一、新块字段白名单并整页校验、必须显式含 `pages`；`old_struct` 在更新时也比较；`source_page` 拒绝 bool/float；remap 人工队列按行保存状态与候选；`col_widths_mm` 长度须与实际列数一致。已知局限（需持久块 ID，留给 docstore 阶段）：第 7 轮 1、6、11 项。

**Codex 第十一轮已处理**：补丁/锁协议 4 项已修，各有回归测试（`test_round11_*`）：(a) 锁按文件身份（dev:inode）取键，大小写别名和软链接共用一把锁；(b) `patch-blocks`/`repair` 的 `--report/--out` 与输入文件用 `samefile` 判重，别名也拒绝；(c) `normalize`/`key-align`/`backfill-source` 同样拒绝 `--report/--out` 覆盖输入；(d) `repair` 对已有块提交结构字段（rows/items/figures/text 等）且与现值不同时报错，不再接受后忽略。
**已知局限（第十一轮，非补丁协议范围，未修）**：① retable 脚注并入会覆盖下一标题译文；② `legend` 角色无 render_body 分支，`figure_group` 图被跳过；③ backfill-source 仅按页和位置序号绑定，需持久块 id；④ 同页正文合并丢第二块来源；⑤ 短引文如 `Smith, 1900` 可能被当图版噪声删除；⑥ key-align 遗留的 `_drop` 标记会让 normalize 删掉后来由 patch-blocks 补回的块。

**Codex 第十二轮已处理（6 条）**：加锁后重核文件身份（写入换 inode 会使旧锁键失效，重试至稳定）；patch-blocks/repair 写 report 前再查一次 report 与 out/aligned/patch 是否同文件；repair 拒绝对齐稿含重复页号、页内重复 block_id、把别页已有 id 当新块（跨页移动）；v1 补丁显式 `page` 与块所在页不符判 stale。回归测试 `test_round12_*`（219 通过，ruff 通过）。Codex 复审到此为止，不再循环；已知限制见上列 6 条（均需持久 block id，属 P3）。
