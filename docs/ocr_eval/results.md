# 本地 OCR 实测结果（20 页）

日期：2026-11-11。环境：`/root/ocr_eval/`（独立 venv）。GPU：GTX 1660 SUPER 6GB。  
**对照文本 = 库内主版本**（glm verified / rapidocr raw / text_layer），故 CER 是**一致率，不是真实精度**。  
原始输出：`docs/ocr_eval/raw/<engine>/`。清单：`manifest.json`。

## 引擎

| 引擎 | 安装 | 后端 | 峰值显存 |
|---|---|---|---|
| RapidOCR（rapidocr_onnxruntime 1.2.3） | venv_rapid | ONNX CPU | 未单独占 GPU（本轮） |
| PP-OCRv5 mobile（paddleocr 3.7.0 + paddlepaddle 3.0.0 CPU） | venv | CPU；模型 `PP-OCRv5_mobile_det/rec` | 约 2046–2049 MB（进程旁已有占用；Paddle 为 CPU 轮，此数为整卡占用观测） |
| Tesseract 5 `chi_sim+eng` PSM6 | 系统包 | CPU | 可忽略 |

未测（装得动但本轮未跑完整）：MonkeyOCR-pro-1.2B、Surya、GOT-OCR、dots.ocr（依赖重或显存紧）。olmOCR 7B 判定不适配 6GB。

## 汇总 CER（已确证，本机文件）

来源：`metrics_fair.json`、`metrics_*.json`。

| 引擎 | CER 全 20 页 | CER 排除 Rapid 自金标准页 | CER 仅 glm 金标准（11 页） | 螠 召回（金标准含螠的页） | 均时/页（约） |
|---|---:|---:|---:|---:|---:|
| RapidOCR | 0.0634 | 0.0773 | **0.0895** | **0/5** | ~5.5 s |
| PP-OCRv5 mobile | 0.0944 | 0.0890 | 0.1046 | **4/5** | ~5–8 s（CPU；时钟偶发负值已忽略） |
| Tesseract | 0.477 | 0.480 | 0.463 | 0/5 | ~3 s |

说明：

1. 刘凌云 / Greg 等主版本本身是 RapidOCR → Rapid 全量 CER 被拉低；看「排除自金标准」或「仅 glm」更公道。
2. 近海1988 两页两边 CER 都 >0.25（版面/读序相对 glm 差大）。
3. PP-OCRv5 对「螠」明显更好；整体与 glm 一致率略逊于 RapidOCR。
4. 300 dpi 页长边常 >4000，Paddle 默认 `max_side_limit=4000` 会缩放（日志已见），可能吃掉部分精度（未定；可再测关限幅）。

## 分层结论（已确证）

- **默认批量**：继续 RapidOCR @ 300 dpi 合理（本库基线 + 本轮一致率）。
- **生僻字/难页**：加 PP-OCRv5（或双引擎对照）值得做。
- **Tesseract chi_sim**：中文扫描专著不可作主引擎。
