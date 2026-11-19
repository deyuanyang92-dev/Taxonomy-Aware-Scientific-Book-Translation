# OCR 工具调研清单（新语言或新材料动手前必查）

起因（2026-11-15）：Imajima 日文志书的 OCR 方案先在通用引擎（PaddleOCR / RapidOCR / Tesseract）里比较，
直到用户要求调研才发现日本国立国会图书馆的 NDLOCR-Lite——它在日文争议行上一致时 97% 正确、免费，
本该第一个评测。根因：从手头工具出发，没有先按「语言 × 材料」做现状调研。

## 规则

1. 新语言或新材料（古籍、手写、竖排、表格、检索表）开工前，先按下表逐格调研：国家图书馆或学术机构
   的专用 OCR、该语言社区常用工具、最新开源文档视觉模型。每个候选记下许可、硬件要求、有无公开评测数字、来源链接。
2. 评测用 `bench/`（金标准 + 争议行），判定标准：免费方案在争议行上的「全对率」不低于两遍 Haiku 一致（97–99%）
   才能替代模型调用。
3. 结论写回本文件（已测/未测、数字、日期）。

## 候选（「已测」有本库数字；其余未确证，只记来源）

| 语言/材料 | 工具 | 状态 | 说明 |
|---|---|---|---|
| 中日英印刷体 | PP-OCRv5 server | 已测（主引擎） | 见 docs/ocr_hard_scans.md |
| 日文近现代活字 | NDLOCR-Lite（NDL Lab，CC BY 4.0） | 已测（第三票，不作主引擎） | 日文争议行与 PaddleOCR 一致时 97%；中文 83%，不用。整页当主引擎：Imajima 金标准 2 页 11.0%/11.3%（PaddleOCR 0.61%/0.08%），丢斜体拉丁学名、「疣」读作「疵/坑/先」 |
| 日文古典籍（江户以前） | NDL古典籍OCR-Lite（ndl-lab/ndlkotenocr-lite） | 未测 | NDLOCR-Lite README 提及；古籍时再测 |
| 日文 | manga-ocr | 未测 | 漫画行识别器，对印刷体书籍效果未知 |
| 多语种文档 | PaddleOCR-VL 0.9B | 未测 | 官方建议显存 ≥8 GB；待 12 GB 显卡电脑 |
| 多语种 | qwen2.5vl:3b（Ollama） | 部分测 | 9 页劣于 Haiku，本机只能 CPU；待 12 GB 显卡复测 |
| 多语种 | RapidOCR / Tesseract / PP-OCRv5 mobile | 已测 | 弱于 server 或同源，投票无收益 |
| 中文古籍、繁体竖排 | （待调研） | — | 遇到时按规则 1 先查 |
| 德文 20 世纪印刷（Antiqua，1960–1998） | Tesseract 5.3 `deu`（tessdata_best 同版），300 dpi，psm 3 | **已测（主引擎）** | 6 页金标准词袋错误率 2.0%；见下「德文」节 |
| 德文 | Tesseract `deu+eng` / 400 dpi | 已测 | 3.5%（变音错 74/229）/ 2.3%，均不如单 `deu` 300 dpi |
| 德文 | PP-OCRv5 latin（`lang='de'`，mobile rec） | 已测 | 6.2%：丢变音（Oresund）、字距撑开的小标题拆词（Fun dorte）、双栏横向拼行；只有 ♀ 比 Tesseract 好 |
| 德文 | PDF 内嵌 ABBYY FineReader 11 层 | 已测 | 53%：字母隔开、变音全丢（kiirzer）、双栏乱序；不用 |
| 德文旧体（Fraktur） | OCR-D / Tesseract `deu_latf`、Calamari | 未测 | 本批无 Fraktur；遇到时再测 |
| 多语种 | Surya、docTR、olmOCR、dots.ocr、MinerU 2.5 | 未测 | 本机 6 GB 显存；德文 Tesseract 已 2%，剩余错误脚本可修，暂不需要 |

## 德文（2026-11-15，Hartmann-Schröder 论文 17 份）

金标准：6 页（1960 老扫描、1980/1985 复印对开页、1989、1992、1996），Sonnet 对照放大裁图逐行转录、两种 OCR 分歧处逐一看图
（`[?]` 0 处）。指标：词袋错误率（漏词+多词）/2/金标准词数，不受读序影响；另计变音词、♂♀、数字。

| 引擎 | 词袋错误 | 变音词错 | 数字错 |
|---|---|---|---|
| Tesseract deu 300 dpi | **2.04%** | 10/229 | 5/301 |
| Tesseract deu 400 dpi | 2.34% | 10/229 | 8/301 |
| Tesseract deu+eng 300 dpi | 3.52% | 74/229 | 4/301 |
| PP-OCRv5 latin（de） | 6.24% | 39/229 | 16/301 |
| ABBYY FR11 内嵌层 | 53% | 149/149 | 19/191 |

Tesseract 剩余错误与脚本修正（`docstore/latinfix.py`，零 token）：♂→`&`/`c&`、♀→`9`/`@`（上下文规则，D1985p6 13 处修 11）；
小型大写人名 `KoTT`→`KOTT`；`um`→`µm`；1960 老印刷变音点丢失与 c/e 混淆（`Zahne`、`stcht`）用全库词频纠正。
语言自动：`docstore text` 按登记表 `lang` 选 Tesseract 模型（`textify.TESS_LANG`），登记语言由 `docstore lang`（纯脚本）判定。

## German OCR proofreading (2026-11-16)

The supplied Codex pilot (gpt-6.1-sol, page image + Tesseract text) reduced bag-of-words error
from 1.74% to 0.08% on six gold pages; this is a pilot result, not validation of all 17 German documents.
Run `docstore --by codex proofread KEY --below 0.92 --pages 1-30 --limit 10 --dry` to preview
low-confidence pages (at least 300 non-whitespace characters); remove `--dry` to process them.
KEY is an exact registered key (e.g. a HartmannSchroder key); default concurrency is `--workers 3`.
Missing confidence falls back to OCR alternates; otherwise pages are skipped unless `--include-unknown`.
Each Codex call uses a fresh empty directory, the pilot prompt, read-only sandbox, and a 900-second timeout;
empty output is retried once. Word/line counts, new capitalised words, numbers, and chatter guard promotion.
Accepted output becomes primary without upgrading verification level; rejected output remains an alternate.
Both outcomes prevent repeat processing. `_audit/proofread_KEY.jsonl` records decisions, author, metadata,
and up to 200 word-diff spans; rejections also go to `_audit/proofread_rejects_KEY.jsonl`.
Failures remain retryable, and each completed attempt prints a flushed progress line.
