# PaddleOCR 使用手册（本地笔记）

起草 2026-11-21。目的：为 Imajima 日文志书、德文变音符、检索表 OCR 评测提供参数与模型清单。
已有评测不在此重复，见 `docs/ocr_tool_survey.md`、`docs/ocr_hard_scans.md`、`docs/ocr_eval/LEDGER.tsv`。
标记：【文档】官方网页；【源码】本机 `/root/ocr_eval/venv_gpu/lib/python3.13/site-packages`（下称 SP）；【模型卡】`~/.paddlex/official_models/*/README.md`；【未确证】。
抓取注意：网页由小模型摘要后返回，数字可能有误；两处网页数字互相矛盾时一律标【未确证】，以源码或模型卡为准。

## 0. 本机环境（已核实）
- paddleocr 3.7.0、paddlex 3.7.2、paddlepaddle-gpu 3.3.1、Python 3.13、onnxruntime 1.25.1、transformers 5.6.2（pip show / dist-info）。
- GPU：GTX 1660 SUPER（`nvidia-smi -L`）。
- 已下载模型（`~/.paddlex/official_models`）：PP-OCRv6_medium_det/rec、PP-OCRv5_server_det/rec、PP-OCRv5_mobile_det/rec、latin_PP-OCRv5_mobile_rec、PP-LCNet_x1_0_textline_ori、PP-DocLayoutV3、PaddleOCR-VL-1.6-0.9B（1.8 GB，权重 bfloat16）。
- 文档站已迁至 http://www.paddleocr.ai/ （paddlepaddle.github.io 301 跳转）。

## 1. 模型清单

### 1.1 检测（文本行定位）
来源：http://www.paddleocr.ai/latest/en/version3.x/pipeline_usage/OCR.html 表 1（测试集：500 张自有中文图；T4）。
| 模型 | Hmean % | 大小 MB | 备注 |
|---|---|---|---|
| PP-OCRv6_medium_det | 86.2* | 59.4 | *v6 用内部多场景集，与 v5/v4 数字不可直接比；模型卡称 15.5M 参数 |
| PP-OCRv6_small_det | 84.1* | 9.6 | |
| PP-OCRv6_tiny_det | 80.6* | 1.9 | |
| PP-OCRv5_server_det | 83.8 | 84.3 | T4 GPU 89.55/70.19 ms（标准/高性能） |
| PP-OCRv5_mobile_det | 79.0 | 4.7 | GPU 10.67/6.36 ms |
| PP-OCRv4_server_det | 69.2（OCR 页）/ 82.56（Structure 页） | 109 | 两页矛盾，【未确证】 |
| PP-OCRv4_mobile_det | 63.8 | 4.7 | |
架构：检测均为 DB（DBPostProcess）系，CNN。v6 = LCNetV4 骨干（MetaFormer 式、结构重参数化）+ RepLKFPN 颈（SP 无；见模型卡 `~/.paddlex/official_models/PP-OCRv6_medium_det/README.md:48`）。

### 1.2 识别
表 2 同页。v6 精度为内部集 W-Avg；v5 分语种为各自内部集。
| 模型 | 精度 % | 大小 MB | 说明 |
|---|---|---|---|
| PP-OCRv6_medium_rec | 83.2* | 73.3（本机 74M） | 19M 参数，50 语种；LCNetV4 + EncoderWithLightSVTR 颈 + CTC+NRTR 多头（模型卡 `PP-OCRv6_medium_rec/README.md:61`） |
| PP-OCRv6_small_rec | 81.3* | 20.4 | |
| PP-OCRv6_tiny_rec | 73.5* | 4.4 | 49 语种 |
| PP-OCRv5_server_rec | 86.38（zh）/ 64.70（en）/ 93.29（繁）/ 60.35（ja） | 81 | 仅 CNN+SVTR 类 CTC，非 transformer 大模型 |
| PP-OCRv5_mobile_rec | 81.29 / 66.00 / 83.55 / 54.65 | 16（Structure 页写 136，矛盾，【未确证】） | |
| en_PP-OCRv5_mobile_rec | 85.25 | 7.5 | |
| PP-OCRv5 多语种 mobile | korean 88.0、latin 84.7、eslav 81.6、th 82.68、el 89.28、arabic 81.27、cyrillic 80.27、devanagari 84.96、te 87.65、ta 94.2 | 7.5–14 | 模型名 `{lang}_PP-OCRv5_mobile_rec` |
v6 rec 分项（模型卡表，`PP-OCRv6_medium_rec/README.md` 约 63 行）：JP 90.5（v5_server 73.7、v5_mobile 75.8）、Ancient 72.4（v5_server 60.4）、Printed EN 94.1（85.1）、Printed CN 91.5（90.1）、TC 78.6（74.7）。W-Avg 83.2 对 78.1（v5_server）。此为官方自测，【未经本库复现】。
v6 det 分项（`PP-OCRv6_medium_det/README.md:65` 表）含 Japanese、Ancient Text、Warp、Table 列；v5_server 均值 81.6。

### 1.3 语种到模型的映射（以本机源码为准）
`SP/paddleocr/_pipelines/ocr.py` `_get_ocr_model_names`（行 318 起）：
- `lang=None, ocr_version=None` -> `PP-OCRv6_medium_det/rec`（行 330-331）。
- `lang` 属于 v6 集合 `{ch, chinese_cht, en, japan}` + LATIN_LANGS（去掉 `pi`）时，默认 v6（行 54-56，337-338）；其余语种 v5。
- v6 只有 medium 档被映射（行 355-358）；small/tiny 须手写 `text_detection_model_name` / `text_recognition_model_name`。
- v5：`ch/chinese_cht/japan` -> `PP-OCRv5_server_det` + `PP-OCRv5_server_rec`（行 362-363）；`en` -> `en_PP-OCRv5_mobile_rec`；Latin 系（含德文 `de`）-> `latin_PP-OCRv5_mobile_rec` + server_det（行 366-367、391-395）。
- 日文：v6 路线 `lang='japan'` -> v6_medium_rec；v5 路线 `ocr_version='PP-OCRv5', lang='japan'` -> v5_server_rec（共用中文识别模型，字典含日文假名）。
- 德文：`lang='de'` 在 LATIN_LANGS（`SP/paddleocr/_utils/langs.py:17`；是否含 `de` 须运行时查，本笔记未逐项确证）；v6 默认走 v6_medium_rec，v5 走 latin mobile。
- 中文：`lang='ch'` v6 或 v5_server。
- 本库曾测 `lang='de'` + latin mobile rec CER 6.2%（ocr_tool_survey.md），丢变音；v6 对德文未测。

### 1.4 非 CNN/SVTR 的大模型
- **PaddleOCR-VL（VLM）**：版本 v1（0.9B）、v1.5（2026-01-29，OmniDocBench v1.5 94.5%）、v1.6（2026-05-28，OmniDocBench v1.6 96.3%），架构 1.6 与 1.5 一致（【文档】PaddleOCR-VL.html）。VLM 部分 = NaViT 式动态分辨率视觉编码器 + ERNIE-4.5-0.3B 语言模型，名称 `PaddleOCR-VL-1.6-0.9B`；版面检测另用 `PP-DocLayoutV3`（本机 126 MB）。支持 109 种语言（【文档】）。
- 本机 `PaddleOCR-VL-1.6-0.9B/config.json`：`PaddleOCRVLForConditionalGeneration`，语言侧 18 层、hidden 1024、16 头、kv 头 2、`max_position_embeddings` 131072、`torch_dtype: bfloat16`；视觉侧 hidden 1152、`image_size` 384。权重 `model.safetensors` 约 1.8 GB（bf16 约 0.9B 参数）。1.5/1.6 的参数量文档未再声明（【文档】），以 0.9B 命名与文件大小为据。
- PP-StructureV3：版面 `PP-DocLayout_plus-L`（RT-DETR 类 transformer 检测器，126 MB）+ OCR + 表格（SLANeXt）+ 公式（PP-FormulaNet/UniMERNet）+ 可选 `PP-Chart2Table`（0.58B VLM，1.4 GB）。核心识别仍是 PP-OCRv5 CNN（本机 `SP/paddlex/configs/pipelines/PP-StructureV3.yaml:110,125`）。
- PP-ChatOCR（v3/v4）：OCR + 大语言模型信息抽取，需外部 LLM API；本机 yaml 有 `PP-ChatOCRv3-doc.yaml`、`PP-ChatOCRv4-doc.yaml`。本库不需要（【文档】细节未读）。

## 2. 可调参数（默认值以本机源码/yaml 为准）

路径缩写 SP = `/root/ocr_eval/venv_gpu/lib/python3.13/site-packages`。

| 参数 | 含义 | 本机默认 | 出处 |
|---|---|---|---|
| text_det_limit_side_len / limit_type | 检测前缩放：min 表示短边不足则放大到该值；max 表示长边超过则缩小；resize_long 强制长边等于该值 | 本机 OCR.yaml：64 / min；传参为空时，PP-OCRv3/4/5/6 det 改用 960 / max | SP/paddlex/configs/pipelines/OCR.yaml:28-29；processors.py:126-165 |
| max_side_limit | 缩放后任一边超过则再压回 | 4000 | OCR.yaml:30；processors.py:168 |
| text_det_thresh | DB 概率图二值化阈值 | 0.3 | OCR.yaml:31 |
| text_det_box_thresh | 文本框平均得分下限，低于则丢弃 | 0.6 | OCR.yaml:32 |
| text_det_unclip_ratio | 文本框外扩比例（对密排小字、竖排易粘连时可降） | 1.5（官方文档页写 2.0，以本机 yaml 为准） | OCR.yaml:33 |
| DB 其余项（max_candidates / use_dilation / score_mode / box_type） | 候选框上限 / 是否膨胀 / fast 或 slow 打分 / quad 四边形 | 1000 / False / fast / quad；min_size 固定 3 | processors.py:288-302 |
| text_rec_score_thresh | 识别置信度低于则丢弃 | 0.0 | OCR.yaml:45 |
| text_recognition_batch_size | 识别批大小 | 6（文档页写 1） | OCR.yaml:43；ocr.py:80 |
| use_doc_orientation_classify | 整页 0/90/180/270 方向分类 | 默认由 yaml 决定；开启与 unwarping 任一即启用预处理子管线 | ocr.py（use_doc_preprocessor 由二者 or 得出） |
| use_doc_unwarping | UVDoc 去弯曲 | 同上 | OCR.yaml:20-22 |
| use_textline_orientation | 文本行 0/180 度分类（PP-LCNet_x1_0_textline_ori，批 6） | 见 yaml；只分两类，不能判竖排 | OCR.yaml:34-38 |
| return_word_box | 返回单字框 | None（关） | ocr.py:91 |
| lang / ocr_version | 语种与版本，决定 det/rec 模型 | 本机默认 v6 medium | ocr.py:318 起 |
| device | gpu:0 / cpu | 自动 | _common_args.py:40 |
| precision | 仅 fp32 / fp16，且只在启用 TensorRT 时生效（内部转为 pptrt_precision） | fp32 | _common_args.py:45,66-85 |
| enable_mkldnn / cpu_threads | CPU 加速 | 见 _constants.py | _common_args.py:46-48,91-95 |
| enable_hpi | 高性能推理（自动选后端） | 未确证（本次未读该分支） | 未确证 |
| text_det_input_shape | 固定检测输入形状（静态图/TRT 用） | None | ocr.py:89 |

旧参数名映射：det_db_thresh、det_db_box_thresh、det_db_unclip_ratio、rec_batch_num 均自动转为新名（ocr.py:48-52）。

## 3. GTX 1660 Super 6 GB（Turing，CC 7.5）

- fp16：OCR 管线里 `precision=fp16` 只通过 TensorRT 路径生效（_common_args.py:72-85）；不装 TensorRT 则等同 fp32。是否可用 Paddle 原生 fp16：未确证。
- bf16：Turing 无 bf16 硬件。PaddleOCR-VL 预测器用 `is_bfloat16_available(device)`，不可用则退回 fp32（doc_vlm/predictor.py:63-64，已读；退回分支具体为 fp32 见 Section 0 摘要）。无 fp16 分支。
- 算力门槛：Paddle/Transformers 后端 CC 不低于 7.0，vLLM 不低于 8.0，SGLang/FastDeploy 8.0 至 12.0 以下（文档，网页摘要，未逐字核）。1660S 为 7.5，只能走 Paddle 或 Transformers 后端，不能走 vLLM。
- 显存：PP-OCRv5/v6 mobile、medium、server 的检测加识别均为 CNN 类小模型，本机实测见 LEDGER（基线要求 nvidia-smi 低于 1800 MiB）。官方未给出 1660S 的显存数字：未确证。
- PaddleOCR-VL 0.9B 能否在 6 GB 加载：权重 bf16 约 1.8 GB，fp32 约 3.6 GB，加 PP-DocLayoutV3 与激活、KV cache 后是否放得下：未确证，需本机实测（正在跑 paddlevl_200）。
- 量化：官方文档未见 int8/int4 量化说明（未确证）。llama.cpp/GGUF 路线存在传闻但未核：未确证。

## 4. 老旧日文植物志、竖横混排、德文变音符、检索表

- 官方只有通用声明：PP-OCRv5 覆盖简体、繁体、拼音、英文、日文，并强化手写、竖排、生僻字（PP-OCRv5 介绍页）。**无专门针对老旧扫描日文植物志、检索表的官方建议：未确证。**
- 竖排：PP-OCRv5 server 识别竖排加权准确率 0.9314（v4 为 0.5455），日文 0.7372（v4 0.4623）；检测日文 0.772。测试集为官方内部集，未公开细节（见第 5 节）。textline orientation 只有 0/180 度两类，不判竖排（3.0.1 文档，网页摘要）。竖横混排的版面级处理：官方未给参数，需靠 PP-StructureV3 / VL 的版面检测，未确证。
- 德文变音符：`de` 属于 Latin 语系组（SP/paddleocr/_utils/langs.py:25）；v6 只映射 medium 档；v5 用 latin mobile rec。该字典是否完整覆盖 ä ö ü ß：未确证，需用本机德文页验证 rec 字典。
- 检索表（偶句、缩进、点线）：官方无文字说明，未确证。
- 可调旋钮（从原理推断，非官方建议）：低对比老扫描试降 text_det_thresh 与 box_thresh；竖排窄行粘连试降 unclip_ratio；小字密排试提高 limit_side_len 并用 limit_type=min。均需本机扫描验证。

## 5. 官方基准（PP-OCRv5 介绍页，网页摘要，数字未逐项核）

- 测试集：200 张通用与文档场景图像；硬件主测 Intel Xeon Gold 6271C + Tesla V100，PaddlePaddle 3.0.0；管线测速另用 3.1.0、CUDA 11.8、cuDNN 8.9，覆盖 A100、H20、A10、T4、V100。
- 识别加权准确率 v5 server 对 v4 server：整体 0.8401 对 0.5735（mobile 0.8015 对 0.5301）；竖排 0.9314 对 0.5455；日文 0.7372 对 0.4623；繁体 0.7472 对 0.4097；古文 0.6039 对 0.3080。mobile 通用场景识别 v5 反低于 v4（0.7703 对 0.8106）。
- 检测（server）日文 0.772 对 0.685，平均 0.827 对 0.662。
- 速度：GPU 每图 v5 mobile 0.62 s，v5 server 0.74 s；CPU v5 server 4.34 s。
- PaddleOCR-VL：OmniDocBench v1.5 94.5%（v1.5），v1.6 为 96.3%（OmniDocBench v1.6），为文档页所述。有第三方论文（arXiv 2511.15059）称 PaddleOCR-VL 在竖排日文上退化小于 DeepSeek-OCR（搜索摘要，未读全文）。
- 官方数字全部来自其内部集，与本项目 Imajima 扫描页不可比；以本机 LEDGER 为准。
- PP-OCRv6 的官方基准：本次未取得完整表，仅有 Section 1.2 的分类数字，其余未确证。

## 待本机实测的参数清单

| 参数 | 默认 | 建议扫描范围 |
|---|---|---|
| text_det_limit_side_len（limit_type=min） | 64 / min（本机 yaml）；960 / max（空参时） | 960、1280、1600、2048，对比 min 与 max |
| text_det_thresh | 0.3 | 0.15、0.2、0.3、0.4 |
| text_det_box_thresh | 0.6 | 0.3、0.4、0.5、0.6、0.7 |
| text_det_unclip_ratio | 1.5 | 1.0、1.3、1.5、2.0、2.5 |
| text_rec_score_thresh | 0.0 | 0.0、0.3、0.5（看漏字与噪声） |
| text_recognition_batch_size | 6 | 1、6、16（只影响速度与显存） |
| use_doc_orientation_classify | 见 yaml | 开、关 |
| use_doc_unwarping | 见 yaml | 开、关（扫描平整页预期无益） |
| use_textline_orientation | 见 yaml | 开、关（竖排页重点看） |
| return_word_box | 关 | 开（需字级对齐时） |
| lang / ocr_version | 默认 v6 medium | japan、ch、latin(de)；v5 mobile、server、v6 medium |
| 渲染 dpi（输入） | 200 | 150、200、300、400 |
| precision / TensorRT | fp32 | fp16 + TRT（若环境允许，未确证可用） |
| PaddleOCR-VL 加载 | fp32（无 bf16） | 能否在 6 GB 加载；max_new_tokens 与图像边长 |
