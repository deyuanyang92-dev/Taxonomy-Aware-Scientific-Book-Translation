# OCR 评测报告：日文老旧分类学文献（Imajima 2001/2007/2009）

日期 2026-11-21。硬件 GTX1660S 6GB。严格串行。逐条数据见 `LEDGER.tsv`。

## 指标与金标
- 指标 cer_norm（越低越好）。G0 = 独立金标 14 页（n=14）；G2 = 循环金标 12 页（n=12），偏向 PP-OCR 系，**不作排名依据**，只作参照。
- 金标文本含书籍内容，不入库（`test-ocr/gold/` 在本机）。

## 结果（均值）
| 引擎 | G0 | G2 | 速度 | 备注 |
|---|---|---|---|---|
| PP-OCRv6 medium 200dpi | **0.0482** | 0.0483 | 1.84 s/页 | G0 最佳 |
| PP-OCRv5 mobile | 0.0551 | 0.0525 | | |
| PP-OCRv5 server | 0.0602 | 0.026 | | |
| YomiToku std / lite | 0.0812 / 0.0828 | 0.2112 / 0.2136 | | |
| NDLOCR-Lite 1.4.0 | 0.1055 | 0.1994 | 3.1 s/页 | |
| PaddleOCR-VL-1.6 | 0.1666 | 2.13 | 136 s/页 | 全书太慢；难页 j2001_p0150 0.921（PP-OCR 0.324）。G2 cer>3 的页疑金标近空白 |
| Tesseract（27 组最好：Japanese fast psm3 +denoise） | 0.1411 | 0.2028 | | jpn_vert 横排页不可用（G0 0.95） |
| kraken 7.2 | 0.74–0.93（n=1 试点） | | | 不可用 |

## 推荐
1. **主引擎：PP-OCRv6 medium，200dpi。** G0 最低、速度 1.84 s/页，docstore 已有适配器（`docstore/engines/ppocr.py`）。
2. **备选/第二意见：PP-OCRv5 mobile 或 YomiToku**（G0 0.055 / 0.081）。与主引擎不同架构，用于多引擎共识，不单独用。
3. **不推荐：** PaddleOCR-VL（慢、难页也不优）、NDLOCR-Lite（G0 0.106）、Tesseract（最好 0.141，仅作免费兜底）、kraken、jpn_vert。
4. 难页（如 j2001_p0150）仍 0.32：交页面图像人工/强模型校正（`docstore verify`），不靠换引擎。

## 未测（结论的限制）
Surya 2.5、Datalab API、dots.ocr、引擎组合与 LLM 复核层、劣化变体、G1、盲测集 B 均未测。G0 仅 14 页，三本书覆盖有限；推荐是在已测引擎范围内的，不代表未测引擎更差。

## 中文动物志测试（2026-11-21）
测试集：中国动物志 环节动物门 多毛纲Ⅰ、第三十三卷、第五十四卷，各随机 10 页（种子固定，`scripts/bench/zh_sample.py`），其中 3 页金标无正文剔除，n=27。
金标：Datalab `/convert` accurate 模式，已去其自生成的英文图片描述段与页眉页码（`zh_run.strip_gold_artifacts`）。**Datalab 是参照，不是人工真值；分数 = 与 Datalab 的差异。**

| 引擎 | cer_norm | bag_err | 分书 z09/z33/z54 | 速度 |
|---|---|---|---|---|
| PP-OCRv6 medium | 0.0394 | 0.0214 | .040/.069/.010 | 3.3 s/页 |
| PP-OCRv5 server | 0.0490 | 0.0252 | .043/.084/.019 | 3.4 s/页 |
| PP-OCRv5 mobile | 0.0542 | 0.0292 | .055/.088/.020 | 1.1 s/页 |
| Tesseract chi_sim psm3 | 0.1318 | 0.0911 | .164/.164/.077 | 1.9 s/页 |

结论（限于已测引擎）：PP-OCRv6 medium 最近 Datalab，与日文测试结论一致。z33 最难（含图版/表）。最差页 z33_p0047 各引擎都约 0.32，疑为版面/金标问题，未逐页核。
限制：金标未经人工核；Datalab 偶有漏读或版面重排，会同时抬高所有引擎的差异。
