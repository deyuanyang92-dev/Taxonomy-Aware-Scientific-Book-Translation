# 候选引擎调研笔记（来源摘录）

日期：2026-11-11。执行：cursor。数字以链接页/论文为准；查不到写「未确证」。

## 公开榜 OmniDocBench（文档解析 Overall，越高越好）

来源：https://www.sota2.com/research/sota/document-recognition-on-omnidocbench （抓取 2026-11-11）

| 引擎 | Overall | TextEdit↓ | 备注 |
|---|---:|---:|---|
| PaddleOCR-VL 1.5 | 94.5 | 3.5 | 管线；本机 0.9B 级，6GB 未确证能否舒适跑 |
| MinerU2.5 | 90.67 | 4.7 | 解耦 VLM；显存需求未在本页列出 |
| MonkeyOCR-pro-3B | 88.85 | 7.5 | 3B；4060 8GB 可跑量化版（官方 README） |
| dots.ocr | 88.41 | 4.8 | ~3B；BF16 权重约 6.4GB（第三方汇总） |
| MonkeyOCR-pro-1.2B | 86.96 | 8.4 | FP16 约 3.2GB（第三方汇总） |
| Qwen3-VL-4B | 86.78 | 5.5 | 小尺寸 VL |
| PP-StructureV3 | 86.73 | 7.3 | 版面/表格管线 |
| olmOCR | 81.79 | 9.6 | 约 7B；第三方称约 12GB+ |
| Marker-1.8.2 | 71.3 | 20.6 | Surya 系 |

## OCR 纯识别 NED（越低越好）

来源：https://www.sota2.com/research/sota/ocr-text-recognition-on-omnidocbench ；PP-OCRv5 论文 https://arxiv.org/html/2603.24373

| 引擎 | NED ALL | NED ZH | 参数量 |
|---|---:|---:|---|
| Qwen3-VL-235B | 0.026 | 0.026 | 超大，不可本地 6GB |
| PP-OCRv5 | 0.067 | 0.076 | 5M（mobile） |
| GOT-OCR | 0.077 | 0.112 | 0.58B |
| Surya | 0.090 | 0.123 | — |
| Mathpix | 0.137 | 0.240 | 商用 API |
| Tesseract | 0.324 | 0.551 | — |

## PP-OCRv5 资源（官方文档）

来源：https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/algorithm/PP-OCRv5/PP-OCRv5.en.md  
测试机 Tesla V100；200 张图含读盘。

| 配置 | 峰值显存 | 均时/图 |
|---|---:|---:|
| v5_mobile GPU | 4190 MB | 0.62 s |
| v5_server GPU | 5402 MB | 0.74 s |

支持简繁中、拼音、英、日；宣称生僻字场景有升级（官方文案，未独立复现）。

## 许可证 / 离线（摘录）

| 引擎 | 许可（已确证来源） | 离线 |
|---|---|---|
| PaddleOCR / PP-OCR | Apache-2.0（项目常见声明；具体以仓库 LICENSE 为准） | 是 |
| RapidOCR | Apache-2.0（RapidAI/RapidOCR） | 是 |
| MinerU | 开源（Apache 系自定义，第三方综述） | 是 |
| MonkeyOCR | 开源（GitHub yuliang-liu/MonkeyOCR） | 是 |
| olmOCR | Apache-2.0（Ai2） | 是（显存大） |
| GOT-OCR2.0 | 代码 Apache-2.0；训练数据 CC-BY-NC（第三方） | 是 |
| Surya/Marker | 代码 Apache-2.0；权重 modified OpenRAIL-M（商业限制，$5M 门槛，GitHub datalab-to/surya） | 是 |
| Qwen2.5/3-VL | 见各模型卡（Qwen 许可） | 小尺寸可试，大模型否 |
| Tesseract | Apache-2.0 | 是 |
| 百度/腾讯/阿里 OCR | 专有；可私有化（官网） | API 默认在线；SDK/私有化另购 |
| ABBYY | 专有；FineReader 桌面约 $99/年（第三方价目 2026） | 桌面可离线 |
| Google Document AI | 专有；OCR ≈$1.50/千页（公开价目综述） | 否（云） |
| Azure Document Intelligence | 专有；Read ≈$1.50/千页 | 容器可本地（需许可） |
| Mathpix | 专有；公式强，中文 NED 弱于专用中文引擎（OmniDocBench） | 否 |

## 6GB（GTX 1660 SUPER）可行性（分层）

| 引擎 | 判断 | 依据层 |
|---|---|---|
| PP-OCRv5 mobile | 可跑 | 官方峰值 4.19GB < 6GB（已确证文档） |
| PP-OCRv5 server | 边界 | 官方峰值 5.40GB；本机尚余进程时可能 OOM（推测） |
| RapidOCR/ONNX | 可跑 | 本库生产已用（已确证） |
| MonkeyOCR-pro-1.2B | 可能 | 第三方称 FP16≈3.2GB；官方测过 4060 8GB（半确证） |
| dots.ocr BF16 | 紧 | 权重≈6.4GB，推理余量不足（第三方） |
| Qwen2.5-VL-3B | 紧/可能需量化 | 第三方称峰值 6.0–6.5GB |
| olmOCR 7B | 否 | 约 12GB+（第三方） |
| MinerU2.5 全量 VLM | 未确证 | 榜高但本机未测 |

## 商用 API（只调研，未注册未上传）

- 百度：通用宣称准确率 98%+；有离线 SDK/私有化。https://cloud.baidu.cn/product/ocr
- 腾讯：印刷体宣称 95%+。社区横评 https://cloud.tencent.com/developer/article/2743532
- 阿里：发票等专项宣称高；通用单价第三方摘录约 ¥0.08/次量级
- 价格第三方摘录（非官网实时价，**未确证**）：百度≈¥0.04/次、腾讯≈¥0.035/次
- 资料含未发表学位论文与本地扫描件 → **默认不上传云 API**（设计约束，非精度结论）
