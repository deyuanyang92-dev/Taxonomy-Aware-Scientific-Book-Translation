# 版面评测结果：Rouse2022 原生 PDF 作 GT，对 Greg_Annelida_2022 扫描页（2026-11-26）

## 结论（16 页，配准全部 ok）

扫描书版面识别：**PaddleOCR-VL 云端 API 最好**。角色（正文/图注/标题/页眉页脚）判对率 1.00，标题检出 1.00，全页文字 CER 0.086，字袋 F1 0.997。本机 PP-DocLayoutV3 仅出框，角色 0.973，标题检出 1.00，但文字靠 tesseract 填，CER 0.249（框内顺序/裁切所致，推测，未逐页核）。Tesseract 单独用文字最准（CER 0.037）但分不出图注（召回 0.0）和标题（检出 0.126）。

**标题层级所有引擎都不可靠**：Paddle 只有 doc_title（=1 级）带层级，paragraph_title 无层级。按字高聚类推 2-4 级（"+h"），严格准确率最高 0.434。需要靠原生 PDF 字体或后处理规则定级，不能指望 OCR 引擎。

| 引擎 | 页数(配准ok) | block_f1 | role_acc | cover | caption_recall | body_recall | role_macro_f1 | heading_recall | heading_level_acc | heading_level_strict | order_tau | col_interleave | cer | bag_f1 | italic_f1 | seconds |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| tesseract | 16 | 0.791 | 0.831 | 1.0 | 0.0 | 1.0 | 0.365 | 0.126 | None | 0.0 | 0.971 | 0.071 | 0.037 | 0.982 | 0.0 | 1.717 |
| tesseract+h | 16 | 0.791 | 0.831 | 1.0 | 0.0 | 1.0 | 0.365 | 0.126 | 0.75 | 0.115 | 0.971 | 0.071 | 0.037 | 0.982 | 0.0 | 2.226 |
| doclayout | 16 | 0.803 | 0.973 | 0.973 | 1.0 | 0.965 | 0.75 | 1.0 | 1.0 | 0.308 | 0.87 | 0.079 | 0.249 | 0.967 | 0.0 | 0.199 |
| doclayout+h | 16 | 0.803 | 0.973 | 0.973 | 1.0 | 0.965 | 0.75 | 1.0 | 0.434 | 0.434 | 0.87 | 0.079 | 0.249 | 0.967 | 0.0 | 0.199 |
| paddle-cloud | 16 | 0.746 | 1.0 | 1.0 | 1.0 | 0.998 | 0.718 | 1.0 | 1.0 | 0.308 | 0.845 | 0.078 | 0.086 | 0.997 | 0.0 | 3.819 |
| paddle-cloud+h | 16 | 0.746 | 1.0 | 1.0 | 1.0 | 0.998 | 0.718 | 1.0 | 0.434 | 0.434 | 0.845 | 0.078 | 0.086 | 0.997 | 0.0 | 3.819 |
指标说明：role_acc/cover/caption_recall/body_recall 为按交叠面积的角色评分（与块粒度无关）；heading_recall 只按文字匹配；heading_level_acc 只在已找到且引擎给了层级的标题上计；heading_level_strict 漏找或无层级都算错；order_tau 为配上块的 Kendall tau；col_interleave 0 最好；italic_f1 全为 0，无引擎输出斜体。seconds：tesseract 为整页；paddle-cloud 为云端块级耗时；doclayout 的 0.199 不可靠（一次加载多页的批处理计时）。

## 方法
- 样本：docs/ocr_eval/layout_sample.tsv，16 对页（原生 Rouse 页 ↔ Greg 扫描页，Jaccard 页配对 16/16 ok）。
- GT：scripts/bench/layout_gt.py，PyMuPDF span 按字体字号规则分角色（标题 1-4、正文、条目、图注、参考文献、页眉页脚），再用 tesseract 词与原生词的唯一词对做 RANSAC 仿射配准到扫描页，中位残差 0.6-0.9 px（150 dpi）。
- 打分：scripts/bench/layout_score.py；批跑：scripts/bench/layout_run.py（gt / eval / table）；适配器：layout_adapters.py；本机 Paddle：layout_paddle_local.py。
- 结果文件：docs/ocr_eval/layout_gt/、docs/ocr_eval/layout_runs/<引擎>/。

## 限制与未确证
- GT 是规则生成（gt_status=rule），非人工标注；规则分错的块会冤枉引擎。只抽看了 1 页叠框（s56），未逐页人工核。
- block_f1 受粒度影响（GT 按原生文本块，引擎按段），仅供参考，排名以 role_acc/cover/heading 指标为准。
- 踩坑：pdftoppm 默认 mediabox，fitz 与云端用 cropbox。Greg mediabox 高 842 pt，cropbox 792.8 pt，不加 -cropbox 则坐标整体错位。已加 check_aspect 报错闸口和测试。
- 本机 PaddleOCR-VL 单页 280 秒无结果被终止（失败）；PP-StructureV3 本机模型未缓存且无网络，未试。均未下载新模型。
- 云端部分文本块返回内容为空（如 p22 块 11、p56 块 8），原因未查。
- paddle-cloud 阅读序 tau 0.845 低于 tesseract 0.971，未查原因（可能为图版页、图注页）。
- 未测其他引擎（GPU 引擎、Sonnet 视觉）。
