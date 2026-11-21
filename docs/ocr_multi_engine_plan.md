# OCR 多引擎兼容与评测计划（防遗忘）

记录日期：2026-11-21。来源：用户指令「测评要兼顾一些老的分类文献；软件设计兼容 kraken、paddleocr、tesseract 等；tesseract 各种参数也要测试」。

## 1. 要求
1. 评测必须覆盖**老的分类文献**（老铅印、历史印刷体、拉丁/德/法文、泛黄、双栏、检索表），不只日文 Imajima。
2. 软件设计（`docstore/engines/`）统一适配器，至少兼容：kraken、PaddleOCR（含 VL）、Tesseract；其他引擎（YomiToku、NDLOCR-Lite）同接口。
3. Tesseract 各参数都要测，不只 lang。
4. 每条结论写明基准名与页数；每次测试追加一行 `docs/ocr_eval/LEDGER.tsv`；G2（2007 PDF 1–12 页）为用户指定基准，不排除、不增页；G0 独立金标 14 页另列。
5. 扩大页集前先问用户；老分类文献评测集的页由用户确认来源，不自行扩范围。

## 2. kraken（https://github.com/mittagessen/kraken）
已确证（README）：`pip install kraken`；Linux/macOS；Python 3.10–3.13；Apache-2.0；
`kraken -i in.tif out.txt binarize segment ocr`；`kraken -i in.tif lines.json segment -bl`；`... segment -bl ocr -m <model>.mlmodel`；
`kraken get 10.5281/zenodo.10592716` 取默认模型，`kraken list` 列 Zenodo 模型库；输出 ALTO/PageXML/abbyyXML/hOCR；可训练版面、阅读顺序、识别。
未确证（需读 docs/user_guide 并实测）：GPU 支持、拉丁/古印本/日文竖排可用模型、逐行/逐字置信度、ketos 训练命令。
待办：独立 venv（`/root/ocr_eval/venv_kraken`）；读 docs；挑印刷体模型（如 catmus-print）；小样后再全量。

## 3. Tesseract 参数测试矩阵（本机 5.x，tessdata 有 jpn/deu/eng/fra/lat/chi_*）
| 维度 | 取值 |
|---|---|
| lang | jpn、jpn+eng、deu、lat、eng；fast/best 版 |
| --psm | 3、4、6、11、12、13；竖排 5、（jpn_vert 若有） |
| --oem | 1(LSTM)、3 |
| dpi | 150/200/300/400 |
| 预处理 | 无、灰度、Otsu、自适应二值、去倾斜、放大 |
| 配置变量 | preserve_interword_spaces=1、user_defined_dpi、textord_*、tessedit_char_whitelist（仅数字页）、load_system_dawg/load_freq_dawg=0 |
先前已测 27 组（G0 最好 jpn fast 0.170）；本轮补未测维度，查 LEDGER 避免重复。

## 4. 统一适配器设计（待做）
接口：`recognize(image, lang, **params) -> Page{lines[(poly,text,conf)], reading_order, engine, version, params_hash}`；
缓存键含参数哈希（沿用 ppocr.py）；输出统一进 docstore pages JSON（extra 存引擎原始字段）；评分一律 `scripts/bench/ocr_score.py`。

## 5. 进度
见 `.claude/tasks-*.md` 与 `docs/ocr_eval/LEDGER.tsv`。

## 实测记录（2026-11-21）

### Tesseract 5.3.4 参数网格（fast Japanese，psm3，dpi300 为基线）
基准：Imajima 日文评测集 G0（独立金标，n=14）与 G2（2007 PDF 第 1–12 页，Sonnet 辅助金标，n=12）；指标 cer_norm；明细见 `docs/ocr_eval/LEDGER.tsv`，原始输出 `test-ocr/runs/tg_*`。manifest 26 行、25 个唯一 id（一页同属 G0 与 G2），按 set 计数 14/12。

| 变体 | G0 (n=14) | G2 (n=12) | 结论 |
|---|---|---|---|
| 基线 psm3 | 0.1809 | 0.2178 | |
| psm1 / oem1 / 关词典 | 0.1809 | 0.2178 | 无变化 |
| preserve_interword_spaces=1 | 0.1805 | 0.2176 | 无实质变化 |
| textord_heavy_nr=1 | 0.1559 | 0.1896 | 本网格最优，两集同向 |
| dpi200 | 0.2401 | 0.2324 | 变差 |
| dpi400 | 0.1593 | 0.2806 | G0 好、G2 差，不稳 |
| jpn+eng | 0.3337 | 0.267 | 变差 |
| psm12 / psm13 / psm5 | 0.65 / 1.0 / 0.96 | 0.86 / 1.0 / 2.08 | 不可用（整页版面） |

对照：PaddleOCR v6 medium 0.0482 / 0.0483。Tesseract 最优变体仍约为其 3–4 倍 CER。
未覆盖：预处理（二值化、去倾斜、缩放）、jpn_vert、Fraktur/deu/lat（无对应金标，也无 Fraktur 模型）。

### kraken 7.2 安装
`/root/ocr_eval/venv_kraken`，Python 3.13，torch 2.14.0+cu130。GPU 不可用：驱动 CUDA 12.6 低于 cu130（报 "NVIDIA driver on your system is too old (found version 12060)"）。可改装 cu126 版 torch，或先用 CPU。模型清单、识别结果待测。

### kraken 模型清单核查（2026-11-21，kraken 7.2，`kraken list` 结果）
- 日文标签的模型只有 Kuzushiji（くずし字手写，DOI 10.5281/zenodo.13942714），不适合现代日文印刷体；因此在 Imajima 的 G0（n=14）、G2（n=12）上跑 kraken 预期没有参考价值，暂不跑。
- 清单中另有 PP-OCRv6（medium）多语种识别模型（DOI 10.5281/zenodo.21788410），可作为 kraken 内部加载 PaddleOCR 识别头的入口，未验证。
- kraken 的价值在老欧文印刷：CATMuS-Print（DOI 10.5281/zenodo.10592716）、德文 Fraktur/antiqua、拉丁摇篮本。要评测必须先有老德文、拉丁文、英文分类文献的金标页，由用户提供；未提供前不增加金标页。

### kraken 日文页试点（2026-11-21，仅 G0 的 j2001_p0073，n=1，不能代表全集）
- 命令形式：`kraken -d cpu -i 页图 输出 segment -bl ocr -m 模型`。必须加 `-d cpu`：不加时默认走 CUDA，因驱动 12.6 低于 torch cu130 要求，报 "Failed processing" 且无具体原因。
- PP-OCRv6 medium 模型（kraken 内加载）：cer_norm 0.7363，假名、汉字召回均为 0，数字和拉丁召回约 0.96；基本只识别出数字与拉丁字符，CJK 输出缺失。原因未确证（可能是该 kraken 模型包的字符集或 blla 对竖排日文分行失败），未继续全量。
- CATMuS-Print：cer_norm 0.9345，假名、汉字召回 0，符合其欧文印刷训练范围。
- 结论（仅此一页）：kraken 当前不能处理 Imajima 日文页；需要用老德文/拉丁页验证其本职能力。

### kraken 日文零输出的原因（2026-11-21 已确证）
- PP-OCRv6 medium（zenodo.21788410）模型卡的语言列表为 ara、cat、ces、deu、eng、fra、grc、heb、lat、rus 等 40 余种，文字体系为 Arab、Armn、Cyrl、Ethi、Geor、Grek、Hebr、Latn、Mlym、Syrc，不含日文（Jpan）和汉字（Hani）。CATMuS-Print 的 metadata.json 中 script 仅为 Latn，字符表为拉丁字符。所以这两个模型输出里没有假名、汉字是字符表所限，不是调用方式错误；日文页输出的是拉丁字符与乱码。
- 结论：kraken 不用于 Imajima 日文页，所以不在 G0/G2 全量上跑（理由已由模型卡证实，而不是未经检验的假设）。其适用范围是老欧文印刷与手稿，须用德文、拉丁文、英文金标页评测，该金标页须由用户提供。

### Tesseract 预处理与旧英文页（2026-11-21 补）
- 预处理（Japanese fast psm3 dpi300 +textord_heavy_nr=1，cer_norm，G0 n=14 / G2 n=12，基线 0.1559 / 0.1896）：otsu 0.1518/0.2067；adaptive 0.1468/0.2116；deskew 0.1504/0.2034；scale2 0.1594/0.4910；denoise 0.1411/0.2028；deskew+otsu 0.1557/0.2087。G2 无一优于基线；全部远差于 PP-OCRv6 medium（0.0482/0.0483）。
- 旧英文页（docs/ocr_eval/manifest.json，cursor 旧金标，n=4，只是一致率）：见 PROGRESS.md 和 LEDGER。kraken（两模型）与 Tesseract（eng、lat）不可区分；Mayr 金标来自 PDF 文本层，Greg 金标不可靠。
- 未完成：德文（含 Fraktur）、拉丁文老文献评测，缺金标页。候选来源（仅为候选，未经用户同意不入评测集）：资料库中 Hartmann-Schröder 1962/1979/1982 德文多毛类论文。需用户选页并同意后，再由独立核对生成金标，然后 kraken（德文/Fraktur/CATMuS）、PaddleOCR（deu/latin）、Tesseract（deu、lat，缺 Fraktur 数据）同台评测。
- 与另一任务（`yanjie/work/jp_bench/jp_result.md`）的合并：仅文档层面，结论一致处与差异处见 PROGRESS.md「合并说明」；两任务数值不混排。

## 合并：与 jp_bench（yanjie/work/jp_bench/jp_result.md）对照（2026-11-21）
三个评测集互不相同，数值不混排，只比较排名。jp_bench = 14 页分层样本（金标 Sonnet 转录 + 人工核 2 页）；G0 = 独立金标 n=14；G2 = 2007 PDF 1–12 页 n=12。引擎设置均为 200dpi（Tesseract psm3，jp_bench 为 300dpi，G0/G2 基线为 psm3 300dpi）。
| 引擎 | jp_bench CER（n=14） | G0 cer_norm（n=14） | G2 cer_norm（n=12） |
|---|---|---|---|
| PP-OCRv6 medium | 0.057（1） | 0.0482（1） | 0.0483（2） |
| PP-OCRv5 mobile | 0.065（2.5） | 0.0551（2） | 0.0525（3） |
| PP-OCRv5 server | 0.065（2.5） | 0.0602（3） | 0.026（1） |
| YomiToku std | 0.085（4） | 0.0812（4） | 0.2112（4） |
| Tesseract psm3 | 0.266（5） | 0.1809（5） | 0.2178（5） |
括号内为该集内排名。
- 一致：三个集都是 PP-OCRv5/v6 三者 < YomiToku < Tesseract；jp_bench 与 G0 的完整排名相同。
- 不一致：G2（n=12）上 v5 server 第一（0.026），与另两集不同，原因未确证，不下结论。
- 因此日文首选 v6 medium@200 有两个独立评测集支持（jp_bench、G0），G2 不反对（0.0483，仍属第一梯队）。
- jp_bench 的组合上限（v6 主 + server/YomiToku 分歧复核）未在 G0/G2 复现，LLM 复核未实跑。
- kraken 部分已用 grep 逐节核对本文件（未重跑 `kraken --version`）：模型清单、`-d cpu`、零输出原因、n=1 试点、n=4 英文页，前后一致，无需改。
