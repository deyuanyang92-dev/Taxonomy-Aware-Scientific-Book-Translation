# 任务：高精度 OCR 与「对看」方案调研（只调研、只设计，不实现）

执行者：Cursor。只用中文或英文写作。不得再派生子代理。每完成一节就写盘，并在 `docs/tasks/ocr_design_progress.md` 追加进度。

## 用户需求（原话）
「我要求 OCR 可以对看文献，也可以达到很高的识别精度。调查一下，看看是否有好用的 OCR，或者优化目前算法。」
- **对看**：页面原图与识别文本左右并排，逐行对应；可疑字高亮；点击即可改字，改动写回资料库。
- **高精度**：资料是中文扫描专著（动物志、名录、学位论文、教材，多为 1980–2010 年代印刷）和英文原著。最要紧的是拉丁学名、中文科属名、生僻字（CJK 扩展区，如「𧍒」U+27352、「螠」）、数字页码、双栏、表格、检索表。

## 现状（先读，不要重复已有工作）
- 仓库 `AGENTS.md`、`docs/architecture.md`、`docs/ocr_accuracy_baseline.md`、`docs/ocr_qc_pilot.md`、`docs/ocr_consensus_pilot.md`，以及 `docstore/qc.py`。
- 已有引擎：RapidOCR/PP-OCRv3（300 dpi 时 CER 约 1.4%，200 dpi 约 9.2%），glm-5.3-flash-local（视觉模型转录），Tesseract（共识试点中无增益）。
- **已知问题**：现有「金标准」的 278 页中，277 页是 glm 转录的，不是人工校对。因此 CER 只表示与 glm 的一致程度，不是真实精度。
- 硬件：GTX 1660 SUPER（6 GB 显存），WSL2。本地已有 bge-m3、PyMuPDF、rapidocr_onnxruntime。先查 docstore 有没有现成的页面查看或对看功能。

## 要回答的问题
1. **候选引擎调研**：每项写清楚，并附来源链接——公开基准成绩（优先 OmniDocBench、olmOCR-bench 及各引擎论文或官方报告）、对中文古旧扫描件和生僻字的支持、能否在 6 GB 显存上运行、速度、许可证、是否离线可用。至少覆盖：
   - 开源：PaddleOCR PP-OCRv5 / PP-StructureV3、MinerU、dots.ocr、MonkeyOCR、olmOCR、GOT-OCR2.0、Qwen2.5-VL / Qwen3-VL 小尺寸、Surya/Marker、Tesseract chi_sim；
   - 商用 API：百度、腾讯、阿里、ABBYY、Google Document AI、Azure Document Intelligence、Mathpix。只调研，不注册、不上传任何资料。
   版本与发布时间以官方页面为准；查不到的写「未确证」，不要凭记忆写数字。
2. **本地小规模实测**：只测能装、能在 6 GB 显存上运行的 2–3 个候选。装在独立环境 `/root/ocr_eval/`（venv 或 conda），不污染系统环境，也不写资料库。
   - 测试页：从 `docstore page` 取约 20 页，覆盖志书、名录、学位论文、教材、英文原著；含双栏页、表格页和含生僻字的页面。页图用 `docstore page --image` 或原 PDF 300 dpi 渲染。
   - 指标：与 glm 转录比较的 CER（注明这是一致率，不是真实精度），另外单独统计拉丁学名、数字和生僻字；再记录速度和显存占用。
   - 结果写入 `docs/ocr_eval/`，含原始输出。
3. **算法优化**：评估这些提精度手段的收益和代价——提高 DPI、版面分析（双栏排序、表格）、多引擎逐字投票、视觉大模型复核可疑行、用 yiku 术语库和学名库做词典纠错、生僻字专门处理（字形相似映射、扩展区字体渲染比对）。
4. **金标准方案**：设计一份约 30 页的人工校对金标准，写清楚怎么选页、校对规范、用户大约要花多少时间。以后所有精度数字都以它为准。
5. **对看界面设计**：基于 docstore 现有数据结构（页面 json、alternates、history、verify），设计本地对看页面——原图与文本并排逐行对齐、可疑字高亮、改字写回 `docstore verify --by user`。只出设计，不写代码。可以附 ASCII 草图。

## 交付
- `docs/ocr_design.md`：一页结论加推荐方案在前，正文依次为调研表、实测结果、优化手段评估、金标准方案、对看设计、分步实施计划（每步的时间和成本估计）、需要用户决定的事项。
- 结论分「已确证 / 未定 / 推测」三类，每个数字都要有来源或实测文件。
- 只 commit `docs/` 下的文件，不 push；不改 `docstore/` 代码，不写资料库。
- 最后输出 ≤300 字总结。
