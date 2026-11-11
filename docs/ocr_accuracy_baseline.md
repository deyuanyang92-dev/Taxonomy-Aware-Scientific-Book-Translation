# OCR 准确性基线（相对 ocr_verified 金标准）

日期：2026-11-11。写入者：cursor。原始数据：`docs/ocr_accuracy_baseline.json`。

## 方法（已确证）

- 金标准：`verify_level=ocr_verified` 的主版本文本，共 **278** 页。
- 金标准生产者：`glm-5.3-flash-local` 277 页，`codex` 1 页（已确证，来自 `docstore` 索引）。
- 假设文本：同页 `alternates`（及非 verified 主版本）中可归类的 OCR 版本；每页每引擎标签取最长文本一份。
- CER：去空白后编辑距离 / 金标准字符数。另计拉丁学名串、数字串、CJK 扩展区字符、漏行率（金标准行与假设行 SequenceMatcher 比 <0.6 计漏）。

## 引擎 CER（已确证）

| 引擎标签 | 页数 | CER | 拉丁 CER | 数字 CER | 漏行率 | 生僻字 CER |
|---|---:|---:|---:|---:|---:|---|
| RapidOCR_300 | 63 | **0.0144** | 0.0277 | 0.0051 | 0.0092 | 无样本 |
| RapidOCR_unk_dpi | 7 | 0.0147 | 0.0094 | 0.0000 | 0.0167 | 无样本 |
| RapidOCR_200 | 220 | **0.0917** | 0.0307 | 0.0654 | 0.0165 | 无样本 |
| ocr_cache | 232 | 0.0909 | 0.0305 | 0.0646 | 0.0167 | 无样本 |

要点：

1. **DPI 效应大（已确证）**：同引擎 RapidOCR，300 dpi CER≈1.4%，200 dpi≈9.2%。
2. **ocr_cache 与 RapidOCR_200 几乎同量级（已确证）**：多数缓存来自旧 200 dpi 流水线。
3. **glm / 视觉模型：无独立 OCR 假设可测（已确证缺口）**：金标准本身即 glm 看页后的 verified 文本，库内无「glm 初识 ≠ verified」的平行版本，故**不能**报告 glm 引擎 CER。
4. **Tesseract：金标准页无 alt（已确证缺口）**：本轮无法报 Tesseract CER。先前试点 `docs/ocr_consensus_pilot.md` 在动物志33 上 RapidOCR+Tesseract 共识未优于单 RapidOCR（CER 0.050433）。
5. **生僻字（CJK Ext A/B 等）：金标准串长度为 0（已确证缺口）**：verified 文本中未检出扩展区字符（可能已写为 BMP 近形或样本不含）。规则文件 `docstore/rules/ocr_fix.toml` 仍有「虫甸→𧍒」「罗因→螠」等替换，说明问题存在于生产路径，但**本金标准无法标定生僻字 CER**。

## 按资料类型（RapidOCR，已确证）

| 标签 | kind | 页 | CER |
|---|---|---:|---:|
| RapidOCR_300 | 名录 | 39 | 0.0127 |
| RapidOCR_300 | 志书 | 18 | 0.0283 |
| RapidOCR_300 | 学位论文/英文原著/译本 | 6 | ≈0（样本极少） |
| RapidOCR_200 | 志书 | 209 | 0.0921 |
| RapidOCR_200 | 专著 | 11 | 0.0773 |
| RapidOCR_unk_dpi | 中文论著 | 5 | 0.0239 |

## 覆盖不足（已确证）

- kind 无任何 ocr_verified：**教材**、**本项目译稿**。
- 金标准页无 RapidOCR alt：7 页（杨德渐2006×6、杨德渐2013×1），仅有 ocr_cache。
- 双栏串行、整页漏识：未做版面级标注，漏行率仅为行对齐启发式（推测有效、未人工复核）。

## 试点目标书在基线上的位置

| key | 引擎 | 页 | CER |
|---|---|---:|---:|
| 刘瑞玉2008名录 | RapidOCR_300 | 39 | 0.0127 |
| 杨德渐2006 | RapidOCR_unk_dpi | 5 | 0.0239 |
| 杨德渐2006 | ocr_cache | 11 | 0.0283 |

杨德渐2006 金标准仅 11 页，且多数无明确 300 dpi RapidOCR alt（未定：全书面 CER 可能高于这 11 页）。

## 提准手段调研（依据分层）

| 手段 | 结论 | 依据 |
|---|---|---|
| 提高 DPI 200→300 | **优先采用** | 本库金标准：CER 0.0917→0.0144（已确证，`ocr_accuracy_baseline.json`） |
| 多引擎共识 RapidOCR+Tesseract | 本库样本收益弱 | 试点动物志33：双引擎 CER 与单 RapidOCR 同为 0.050433（`docs/ocr_consensus_pilot.md`，已确证）；Tesseract 在金标准页无 alt |
| 规则+学名表纠错 | 小幅降 CER | 同试点：0.050433→0.048851（已确证） |
| 视觉模型转录 | 作金标准/难页，不作默认识别 | 278 页 verified 中 277 页 producer=glm（已确证）；独立 glm CER 未测 |
| 去噪/二值化 | 未在本库实测 | 经典预处理；对扫描底噪有效为文献通识（推测）。需单独 A/B |
| 版面分析（双栏） | 未实测 | 漏行率启发式 0.9–1.6%（已确证数字）；是否双栏串行导致未人工标注（未定） |
| 低置信/乱码/未知学名信号 | 纳入 `docstore qc` | 与用途（抽术语）对齐；阈值见 `docstore/rules/qc.toml`，金标准标定见 `docs/ocr_qc_calibration.json` |
| 页码连续性、目录交叉 | 部分 | qc 检查 `page_offset` 是否可解析；目录交叉核对未实现（未定） |

参考（外部）：

- RapidOCR / PP-OCR：https://github.com/RapidAI/RapidOCR 、PaddleOCR 文档（引擎说明）
- OCR 评估常用 CER/WER：ITU / OCR 评测惯例（编辑距离比）
