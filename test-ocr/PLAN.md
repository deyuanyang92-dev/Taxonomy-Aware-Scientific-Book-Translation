# OCR 选型测评计划（Tesseract vs PaddleOCR）· 2026-11-22
规划：主会话。执行：子代理/脚本（sonnet 或 haiku；禁止再派子代理；每步写盘）。

## 目标
为分类学文献选出日常可用的最佳 OCR：Tesseract（含语言包）与 PaddleOCR（本地各版本 + 云 API 各版本），覆盖 ru/fr/de/ja/zh（+la）。可选：输出带分类学章节标签，便于整理。

## 结案（2026-11-22，用户定：不做德文，P1 取消，评测到此为止）
推荐：ru Tesseract rus+eng；fr 本地 PP-OCRv6 medium 默认；la 云 PaddleOCR-VL-1.6（本地备选 PP-OCRv6 medium）；zh、ja 用 PP-OCRv6 medium；de 未测，沿用 deu。依据见下表与 bench/summary_150.md。

## 现状（已完成，见 bench/summary_150.md、docs/ocr_eval/LEDGER.tsv）
| 语种 | n | 最优 | 备注 |
|---|---|---|---|
| ru | 50 | Tesseract rus+eng 0.130 | v6 medium 无西里尔识别 |
| fr | 50 | 本地 Paddle P0≈P8 0.106 | |
| la | 50 | 云 VL-1.6 0.118 | 本地备选 P0 0.139 |
| zh | 27 | PP-OCRv6 medium 0.039 | Tesseract chi_sim 0.132 |
| ja | 14 | PP-OCRv6 medium 0.048 | n 偏小 |
| de | 0 | 未测 | 库内 de 175 本，未测是最大缺口 |
金标一律 Datalab（非人工真值）。

## 阶段（串行；每阶段先 5 页小样，过了再 50 页）
P1 de：从库内 de 书取 50 页，覆盖年代（1920s–1990s）与字体（Antiqua/疑似 Fraktur），按 bench/samples_*.csv 格式登记。Tesseract deu、deu+eng、deu_fast、frk（需先装 Fraktur 包）；Paddle P0（v6m）、P1（latin 识别）、云 VL-1.6。脚本：scripts/bench/multi_ocr.py、ocr_matrix.py。
P2 ja 扩样：库内 ja 仅 3 本，扩到 n≥30 页；对比 jpn、jpn+eng、jpn_vert 与 Paddle。n<10 不宣称最优。
P3 金标不确定度（零成本，纯脚本）：(a) 多引擎一致性分层，统计"仅 Datalab 与其余全不同"的比例；(b) hunspell 词典未登录词率作独立指标（学名会误报，需排除斜体学名）；(c) 检索公开的人工校对真值集（需核实，未确证）。
P3b 多引擎融合（零成本）：用已有逐页输出试三种：(1) 逐页择优的上界（oracle）；(2) 行级多数投票（ROVER 式，可用 docstore/consensus.py）；(3) 只在分歧处标记待核。以"最优单引擎"为对照，配对 Δ 与 CI 决定是否值得。
P4 分类学章节标签（可选）：先用规则（前言、检索表、Diagnosis、Description、Material examined、Distribution、Etymology、Remarks/Discussion）在 OCR 文本上打标，规则放 docstore/rules 或 taxadb/rules，不新建库；与 PP-StructureV3/VL 的版面输出对比，看谁更省事。
P5 汇总：语种 × 版面类型的推荐表（带 CI 与 n），追加 LEDGER，更新记忆 ocr-test-plan。

## 提升精度的探索结果（2026-11-22，金标=Datalab，n=50）
1. CER 约一半不是识别错误：fr P0 的 cer_norm 0.1065，bag_err（不看读序）0.0493，order_gap 0.057；ru T16 0.1299/0.0706；la VL-1.6 0.1178/0.0741。50 页中 fr 有 18 页 order_gap>0.05。
2. 引擎漏字：len_ratio 0.91–0.95（漏掉 5–9% 的字符，疑似页眉、脚注、图中标注）。
3. 融合收益小：逐页择优上界仅降 0.001（fr）、0.013（ru）、0.006（la）；2:1 字符投票 fr -0.001、ru -0.0065、la 无效。原因：各引擎错误高度相关，不是互补。结论：多引擎融合不值得作为主路线。
4. 确定性后处理更有效：去连字符换行 + 去页眉页码，fr 0.1065→0.0949（-11%），ru -3%，la 0。注意金标（Datalab）本身已去页眉和连字符，这部分是口径对齐。
5. 剩余主因是版面与读序（多栏、图中字母、脚注）。下一步方向：用版面模型（PP-StructureV3/VL）取读序，对比普通 OCR，只在版面复杂页启用。
未确证：order_gap 中有多少来自 Datalab 金标自身的读序差异（需看更多页）。

## 硬规则
- 金标只用 Datalab；禁 Sonnet 当金标；不擅自加金标。结论必须标集名 + n。
- 评测串行；单引擎 30 页超 2.5 h 直接排除，记入 bench/EXCLUDED.md。
- 产物只放 test-ocr/、bench/；入库写 --by <模型名>。
- 每次新测试追加一行 docs/ocr_eval/LEDGER.tsv。
- 新脚本配 pytest，过 ruff 和 mypy。
- PaddleOCR 本地与云全部免费，不问价。DeepSeek 仅非高峰期；本计划不需要。

## 待决
- Datalab 为 de 50 页（+ja 扩样）生成金标的额度/费用：先确认。
- 先 commit 工作区约 30 个未提交文件。
