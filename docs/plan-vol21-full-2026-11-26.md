# Vol.21 全卷（555 页）端到端译本排版：软件缺口与优化方案

日期：2026-11-26　规划：claude-opus（只读调研，未改代码、未调云 OCR、未调模型）
目标：Fauna Ibérica 第 21 卷（docstore key `Fauna_Iberica_Vol21`，西班牙语扫描本 555 页）由软件本体一条链生成 ES 底本 → EN（及 ZH）排版成品；每个暴露的不足都落成可复现的改进项 + 测试。

## 0. 现状（本次已核对的证据）

| 事实 | 证据 |
|---|---|
| docstore 555 页全部有文本，主版本 producer 均为 `consensus(paddle_vl)` 300 dpi，alternates 中 paddle_vl 570 条 | 逐页读 `_资料库/pages/Fauna_Iberica_Vol21/p*.json` 统计 |
| 页面文本保留了 VL 的块分隔（块间空行），页眉页脚已去掉，但无角色、无坐标 | p0100、p0301、p0540 文本抽查 |
| VL 版面（块框+标签）只落盘 49 页（p0001–p0050，缺 p5、p9）：`_资料库/layout/Fauna_Iberica_Vol21/pNNNN.json`；PP-OCR 行框缓存 `ppocr/` 只 50 页 | `ls` 计数 |
| 原因：全卷 VL 跑在 11-23，`paddle_vl.save_layout` 是 11-24 才加的（docstring 写明「2026-11-24 Vol21 教训」） | `docstore/engines/paddle_vl.py:400-420`，调用点 `docstore/textify.py:332`、`:488` |
| `scripts/vl_to_aligned.py` 只读版面文件，没有版面就无法生成 aligned | `scripts/vl_to_aligned.py:62`（layout_files）、`:96-126`（convert） |
| p1-50 EN/ZH 链路已跑通：translate-aligned → recover-top → make，gate PASS（DRAFT） | `docs/booklayout.md:422-458`；`yanjie/排版成品/Fauna_Iberica_Vol21_{EN,ZH}_p1-50.make.json` |
| p1-50 的西语底本有 111/368 块经人工校正（存于 `translation` 字段） | `docs/booklayout.md` key targets 段 |
| 现有 Vol21 图目录 `figr_v21`（106 图）与 `aligned_t21_prep.json` 都是每 11 页抽 1 页（页 14,25,…,549），按 yanjie/CLAUDE.md 禁用 | 读 `排版成品/work/figr_v21/source_figure_audit.json`、`aligned_t21_prep.json` 页号 |
| p0540 文本有 h→b 错（`Arcb. Naturgescb.`、`krobnii`），全卷未做西语校正 | p0540 文本 |
| 待办 issue：#46 页顶续段丢失、#47 译本 source-check 弱、#48 folio 假设页连续、#49 页脚斜体、#50 ZH 页脚/标点、#51 索引页码 | `gh issue list` |

结论：全卷不缺 OCR 文本，缺的是**版面结构**（块角色、y 坐标、图框）和**西语校正层**。不需要再付费跑 OCR 也能出全卷；VL 重跑只为拿回版面框，属于质量增强，须用户批准。

## 1. 软件缺口清单

| # | 现象 | 代码位置 | 为何不行 | 修法 |
|---|---|---|---|---|
| G1 | 全卷版面只存了 49 页，506 页的 VL 版面已丢 | `docstore/engines/paddle_vl.py:400-420`；`docstore/textify.py:330-332` | 存版面的功能晚于全卷 OCR 一天加入；`docstore status` 不报版面覆盖率，没人发现缺口 | `docstore status` 增加 layout 覆盖列（版面页数/文本页数）；`docstore text` 在 VL 页无版面时警告。测试 `tests/test_docstore_layout_coverage.py` |
| G2 | 没有「docstore 文本 → aligned」转换器，无版面就无法排版 | `scripts/vl_to_aligned.py:62,96-126`（只认版面文件） | 全卷 504 页只能靠版面文件进入 booklayout | 新增 `booklayout from-docstore`（模块 `booklayout/fromstore.py`）：按 VL 块空行切块；角色用确定性规则（复用 `vl_to_aligned.py` 的 FIGLABEL、KEYLINE、KEYHEAD、OPEN_LEADER；新增西语标题规则：`Familia/Subfamilia/Género/Clave …`、单独成块的「学名 + 作者, 年」、BIBLIOGRAFÍA 后为 ref、ÍNDICE 后为 index）；y0 由本地 Tesseract 行（source-check 已缓存的 TSV）回配；输出带 `lineage`。测试 `tests/test_booklayout_fromstore.py` |
| G3 | vl_to_aligned 是仓库脚本，不在 booklayout CLI，参数和 make 不一致 | `scripts/vl_to_aligned.py:289-298` | 两条入口各自演化，规则不共享 | 把 FIGLABEL/KEYLINE 等规则移到 `booklayout/blockrules.py`，脚本与 from-docstore 共用；脚本保留为薄包装。回归：`tests/test_vl_to_aligned*.py` 不变即通过 |
| G4 | `make --pages` 缺省写死 `1-50` | `booklayout/make.py:153` | 全卷 make 漏传参数时 source-check 只查前 50 页却报 PASS（H7 同类：闸口查了子集） | 缺省改为 aligned 实际页范围；make.json 记录实际检查页数，页数 < aligned 页数时 gate 判 incomplete。测试 `test_make_pages_default_from_aligned`（放进 `tests/test_booklayout_make.py`） |
| G5 | make.json 不记录输入（aligned/metadata/profile/figures 路径与 sha256） | `booklayout/make.py`（make.json 只有 ok/draft/problems/seconds/files/log/trace_db） | p1-50 成品无法从 make.json 复现，下次全卷跑无法确认用的是哪份 metadata | make.json 增加 `inputs`：路径 + sha256 + 软件 git commit。测试 `test_make_records_inputs` |
| G6 | 全卷西语底本无校正层；h→b、断词等 OCR 错直接进入 Google 翻译并影响学名遮蔽 | `booklayout/gtranslate.py`（--source-field 只在 p1-50 有人工校正值） | 504 页无人工校正，EN/ZH 里学名、引文缩写会错（如 krobnii） | 确定性链：`docstore postfix` → namefix/WoRMS 学名纠正 → `booklayout source-check --aligned` → `source-fix`（450 dpi 词框投票）→ `patch-blocks`，循环到无 output_error；结果写进 `translation` 字段。新增 `booklayout es-fix` 一键包装（或 make 子阶段）。测试 `tests/test_booklayout_esfix.py`（用 p0540 的 Arcb./krobnii 作夹具） |
| G7 | 全卷图目录不存在；现有 figr_v21 是禁用的抽样页 | `booklayout figures scan`（存在）；`booklayout/scanfigures.py:41` | 未对 1-555 跑过；图与「Fig. N」图注的配对没有全卷核对 | 跑 `figures scan --pages 1-555` + `figures map`；新增 qa `figure_caption_count`：文本中 Fig. N 编号集合 vs 裁图配对集合，缺失即失败。测试 `tests/test_booklayout_figure_caption_count.py` |
| G8 | translate-aligned 全卷规模未验证：单缓存文件、pause=0、8 并发 | `booklayout/gtranslate.py:123-125`；限流见 issue #6 | p1-50 为 85.5k 字符/82 s/312 请求；全卷约 10 倍，429 时整批失败无断点（未确证，未实测） | 按页段分块 + 每块写报告 + 429 指数退避 + 重跑只补未译块；报告列每块请求数/失败数。测试 `tests/test_booklayout_gtranslate.py::test_resume_after_429`（mock 端点） |
| G9 | 译本 source-check 只比数字和学名，p1-50 仍有 EN 85 / ZH 320 项待人工 | `booklayout/sourcecheck.py`（--translated，#47） | 线性外推全卷 EN ≈ 940 项、ZH ≈ 3,500 项，人工审不完 | 扩展不阻塞类别：图内标注、页眉、引文年份顺序差；ZH 先查 320 项的类别分布再定规则。验收看「每 50 页阻塞项」而不是总数。测试加到 `tests/test_booklayout_sourcecheck.py` |
| G10 | 页顶续段丢失（#46）在 from-docstore 路线下更突出（无 y0 时 recover-top 无法判上界） | `booklayout/recover_top.py:29,52,85` | recover_top 依赖块 y0 与 Tesseract 行比对 | from-docstore 必须给出 y0（G2）；新增全卷统计：每页源 Tesseract 行覆盖率，<0.95 的页列入报告。测试 `tests/test_booklayout_recover_top.py` 加无 y0 输入用例（应报错而非静默） |
| G11 | 索引/目录页码指向全书页（#51），页脚/标题/标点（#50），folio 假设页连续（#48），页脚斜体（#49） | 见各 issue | 全卷首次真正需要索引页码与 page_map 全对上 | 全卷跑后按 gate 结果逐条关 issue；`wrong_page_refs` 必须为 0 |
| G12 | make 在 555 页规模的耗时、内存未知（p1-50 约 20 s；source-check 70 s/50 页） | `booklayout/make.py` | 线性外推 build ≈ 1–2 min、source-check ≈ 13 min（Tesseract 首次），未确证；LibreOffice 转大 DOCX 可能更慢 | 先 1-150 试点量时长；make.json 已有分阶段秒数，增加峰值内存。超 30 min 再考虑分章 build |
| G13 | 全卷检索表结构未建：`docstore keys` 依赖 PP-OCR 行框缓存，只有 50 页 | `docstore/structauto.py:20`（keys_from_cache） | 检索表偶句/目标页码靠 from-docstore 的 KEYLINE 规则，无交叉验证 | 本地 PP-OCR（免费，`docstore text --engines ppocr` 只写 alternates）补检索表所在页的行框；key-report + `key_target_lost` 必须 0 |

## 2. 两条路线

### 路线 A（默认，零云 OCR、零模型）：docstore 文本 + 版面规则
1. `booklayout from-docstore Fauna_Iberica_Vol21 --pages 1-555` → ES aligned（G2，y0 用 Tesseract 行回配）。
2. `booklayout figures scan` + `figures map`（G7）。
3. 西语确定性校正（G6），写入 `translation`。
4. ES make（同语种 source-check，最强闸口）。
5. `translate-aligned --source-field translation --tl en`（再 zh-CN）→ `recover-top` → `make --translated`。

质量预期：文本精度 = 现有 VL 共识文本（与 p1-50 同源）。结构弱于 VL 版面：标题层级、图注与正文分界、双栏图注靠规则，预计 p1-50 对照下角色一致率 ≥ 0.90（M1 实测后填写，未确证）。图框由连通域检测，复杂图版可能被拆或并。

### 路线 B（已作废，2026-11-26 用户决定：不云端重跑）：重跑 PaddleOCR-VL 取回版面
- 范围：p52–555 共 504 页，用 `docstore text --redo` 路径（只加 alternates、不改主版本，并自动 `save_layout`，见 `textify.py:470-488`）。耗云额度；须用户批准后执行。
- 之后 `vl_to_aligned.py` 全卷转换，与 p1-50 同一流程。
- 质量预期：结构与 p1-50 相同（VL 块标签 + 块框 + VL 图框），gate 通过率预期与 p1-50 相同。也可只对路线 A 判为低置信的页（角色冲突、图注未配对）重跑，降低额度消耗。

## 3. 分阶段里程碑与验收

约定：`R=/mnt/p/翻译-译作/Taxonomy-Aware-Scientific-Book-Translation`，`Y=/mnt/p/翻译-译作/yanjie`，中间文件放 `$Y/排版成品/work/`，新文件名带 `_full`；成品写 `$Y/排版成品/Fauna_Iberica_Vol21_{ES,EN,ZH}_full.*`。不覆盖已有 p1-50 文件。

| 阶段 | 内容 | 验收命令 | 通过标准 |
|---|---|---|---|
| M0 基线 | 记录测试与 lint 基线 | `cd $R && python3 -m pytest -q tests yiku/tests && ruff check booklayout docstore && mypy booklayout` | 全过；失败项先登记，不混入本方案改动 |
| M1 转换器 | G2、G3、G4、G5、G1 | `booklayout from-docstore Fauna_Iberica_Vol21 --pages 1-50 --out $Y/排版成品/work/aligned_v21_full_fromstore_p1-50.json` 后与 `vl_to_aligned`（用已有 49 页版面）结果对比：`pytest -q tests/test_booklayout_fromstore.py` | 字符覆盖 100%（每页源文本字符全在块中）；角色一致率 ≥ 0.90；caption/key 召回 ≥ 0.95；每块有 y0 |
| M2 ES 全卷试点 | 1-150 页：转换 + 图 + make | `booklayout make --aligned …_p1-150.json --figures … --pages 1-150 --source-pdf "$Y/FAUNA IBERICA（Vol.21）.pdf" --name Fauna_Iberica_Vol21_ES_full_p1-150 …` | make 完成；记录各阶段秒数；gate 结果与阻塞项数写入 make.json |
| M3 ES 校正 | G6；全卷 1-555 | `booklayout source-check --aligned … --pages 1-555`；`pytest -q tests/test_booklayout_esfix.py` | output_error = 0；阻塞项每 50 页 ≤ 35（Vol.25 p1-50 基准，`docs/booklayout.md` 404-420 行）；Arcb./krobnii 类 h→b 不再出现 |
| M4 ES 全卷成品 | 全卷 make | `booklayout make … --pages 1-555 --name Fauna_Iberica_Vol21_ES_full` 后 `python3 /mnt/p/yzz-分类工作流/yzz.py zh check <pdf>` 不适用（纯西语），改跑 `booklayout gate` | gate PASS；`figure_caption_count` 0 缺失；key_target_lost 0；p1、p100、p301、p540 与原 PDF 并排（`pdftoppm -cropbox`）人工核对无丢段 |
| M5 EN | G8、G9、G10、G11 | `booklayout translate-aligned --aligned …ES_full.json --sl es --tl en --source-field translation --out …EN_full.json --report …`；`booklayout recover-top …`；`booklayout make --translated --source-pdf … --pages 1-555 --name Fauna_Iberica_Vol21_EN_full` | 翻译报告失败块 0；gate PASS；wrong_page_refs 0；key_target_lost 0；译本 source-check 阻塞项每 50 页 ≤ 10；p1/p540 并排核对 |
| M6 ZH | 同 M5，`--tl zh-CN` | 同上 + `python3 /mnt/p/yzz-分类工作流/yzz.py zh check <docx/pdf>` | gate PASS（含 footer_not_flush 0，#50）；zh check OK |
| M7 收尾 | 文档与 issue | `docs/booklayout.md` 增「Vol.21 全卷」记录（命令、秒数、阻塞项）；关闭或更新 #46–#51；`scripts/sync_skill.sh --dry` | 测试全过；每个已修缺口有测试名；未修项写在 issue 中 |

## 4. 改进项 → 测试对照

| 缺口 | 测试文件 / 用例 | 回归检查 |
|---|---|---|
| G1 | `tests/test_docstore_layout_coverage.py` | 构造文本 555 页、版面 49 页的临时库，`docstore status` 报覆盖 49/555 |
| G2 | `tests/test_booklayout_fromstore.py` | 用 p1-50 已有 49 页版面生成的 aligned 作金标；字符覆盖、角色一致率、y0 存在三项断言 |
| G3 | 现有 `tests/test_vl_to_aligned*.py`（不改） | 规则搬家后输出逐字节不变 |
| G4 | `tests/test_booklayout_make.py::test_make_pages_default_from_aligned` | aligned 页 1-120、未给 --pages 时 source-check 收到 1-120 |
| G5 | `tests/test_booklayout_make.py::test_make_records_inputs` | make.json 含 inputs.aligned.sha256 |
| G6 | `tests/test_booklayout_esfix.py` | p0540 夹具：Arcb.→Arch.、Naturgescb.→Naturgesch.、krobnii→krohnii；重音差异不自动改（accent_unsafe） |
| G7 | `tests/test_booklayout_figure_caption_count.py` | 删一张裁图，qa 必须报 figure_caption_count |
| G8 | `tests/test_booklayout_gtranslate.py::test_resume_after_429` | mock 第 N 次请求返回 429：重跑后只补未译块，缓存不重复请求 |
| G9 | `tests/test_booklayout_sourcecheck.py` 新增用例 | 图内标注、页眉在译本模式下归不阻塞 |
| G10 | `tests/test_booklayout_recover_top.py` 新增用例 | 块无 y0 时报错退出码 1，不静默 |
| G11 | 现有 `test_booklayout_folio.py`、`test_booklayout_contents.py` 增全卷页码用例 | wrong_page_refs = 0 |
| G13 | `tests/test_keygraph_wiring.py` 增全卷检索表用例 | key_target_lost = 0 |

按仓库规则，每项改动另须 `ruff check`、`mypy` 通过，并以 GitHub issue 记录复现材料。

## 5. 用户已决定（2026-11-26）

1. 不云端重跑 VL。版面只用本地来源（路线 A：docstore 文本 + 本地 PP-OCR 行框；VL 已存的 49 页照用）。路线 B 作废。
2. 不用模型校正。规则改不了的疑点只记入问题清单（issues），不改译文、不调用任何模型。
3. EN 与 ZH 同时做。
4. 不做人工审核。质量核对：Tesseract 独立 OCR 对照（booklayout source-check），再随机抽取若干页交 haiku 校对；发现的问题写入问题清单，不阻塞交付。
5. 成品文件名：`yanjie/排版成品/Fauna_Iberica_Vol21_{ES,EN,ZH}_full.*`。

## 6. 未确证事项
- 路线 A 的角色一致率、全卷 make 耗时、Google 端点在约 95 万字符规模下的限流情况：均为外推，待 M1/M2 实测。
- 文本中块间空行数是否反映纵向间距：未确证，不作为 y0 来源。
