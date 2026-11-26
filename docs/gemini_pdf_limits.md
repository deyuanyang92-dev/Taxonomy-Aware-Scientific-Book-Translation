# Gemini 处理扫描版 PDF 的官方限制与 docstore split「目标服务 profile」设计

日期：2026-11-26（全部官方页面于 2026-11-26 用 WebFetch 读取）。只读调研，未改代码。
对象：Imajima 三卷日文扫描 PDF（无文本层，每页 400 ppi 灰度 JPEG）。
标记：**已确证** = 官方页面原文；**未确证** = 官方未写或仅论坛/推测；**推测** = 本文计算。

注：ai.google.dev/gemini-api/docs/* 现已 301 跳转到 aistudio.google.com/docs/*，下表 URL 为跳转后的实际读取地址。
WebFetch 返回的是页面摘录，引文为摘录中的原句；个别表格被工具改写成列表（已注明）。

## 1. Gemini API（AI Studio / Developer API）

| 项 | 值 | 原文引用 | 出处 | 状态 |
|---|---|---|---|---|
| inline 请求总大小 | 100 MB/请求；PDF 50 MB | "100 MB per request or payload" ("50 MB for PDFs") | https://aistudio.google.com/docs/file-input-methods | 已确证 |
| 何时必须用 Files API | 请求总大小 >100 MB；PDF 限 50 MB | "Always use the Files API when the total request size" … "larger than 100 MB."；"For PDF files, the limit is 50 MB." | https://aistudio.google.com/docs/files | 已确证 |
| Files API 单文件 / 项目总量 | 2 GB/文件，20 GB/项目（通用）；PDF 仍 50 MB | "with a per-file maximum size of 2 GB."；"lets you store up to 20 GB of files per project" | 同上 | 已确证 |
| Files API 保留 | 48 小时 | "Files are stored for 48 hours."；"Files are automatically deleted after 48 hours." | 同上 | 已确证 |
| 外部 URL | 15 MB/文件 | "15 MB per file" | https://aistudio.google.com/docs/file-input-methods | 已确证 |
| Cloud Storage 注册 | 2 GB/文件；注册最长 30 天 | "2 GB per file, no overall storage limits"；"One time registration can give access for up to 30 days." | 同上 | 已确证 |
| 文档处理总限 | 50 MB/文件，1000 页/PDF；对 inline 与 Files API 都适用，切片（page_options）时仍按整份文件计 | "Up to 50 MB per file, 1,000 pages per PDF, or 2,000 pages or slides per Office or OpenDocument file." | https://aistudio.google.com/docs/document-processing | 已确证 |
| 页面切片 | 可用 page_options 只送部分页，按切片计费 | "Use `processing.page_options` to slice PDFs, documents, and presentations." | 同上 | 已确证 |
| 每页 token（Gemini 4/3） | low 280，medium 560（默认），high 1120 | 页面：Gemini 4/3 "about 280 tokens per page at low, 560 at medium (default), and 1,120 at high"（工具摘录） | 同上 | 已确证（摘录） |
| 每页 token（Gemini 2.5） | 固定 258 | "Gemini 2.5: a flat 258 tokens per page"（工具摘录） | 同上 | 已确证（摘录） |
| media_resolution 表（Gemini 4/3） | PDF：unspecified 560；low 280+Native Text；medium 560+Native Text；high 1120+Native Text；ultra_high N/A（仅图像 2240） | 原页为表格，工具改写 | https://aistudio.google.com/docs/media-resolution | 已确证（摘录） |
| PDF 推荐分辨率 | medium；OCR 标准文档上 high 很少有提升 | "Optimal for document understanding; quality typically saturates at `medium`."；"rarely improves OCR results for standard documents" | 同上 | 已确证 |
| 像素尺寸与 token | 输入像素尺寸不影响 token；页面渲染为约 2 MP（288 DPI） | "Input pixel dimensions do not change token cost; use `resolution` to control token budget and detail."；"renders PDF and Office pages to 2-megapixel images (288 DPI)" | https://aistudio.google.com/docs/document-processing | 已确证 |
| 扫描页是否靠视觉处理 | 每页都渲染为图像；有嵌入文本则额外抽取（不另计费）。官方未单独区分扫描/原生 | "embedded PDF text is extracted alongside page images at no extra token charge" | 同上 | 已确证（扫描件无文本层 → 只有页图像，推测） |
| 扫描件最佳实践 | 先转正方向；避免模糊、低对比 | 摘录："Rotate pages to the correct orientation before uploading."；"Avoid blurry scans or low-contrast pages." | 同上 | 已确证 |
| 图像 token 规则（2.5 及旧模型） | ≤384 px 258 token；更大按 768×768 切片，每片 258 | "Images ≤384 pixels in both dimensions count as 258 tokens."；"Larger images are tiled into 768x768 pixel tiles, each counting as 258 tokens." | https://aistudio.google.com/docs/tokens | 已确证 |

模型上下文与输出上限（各模型详情页）：

| 模型 | 输入上限 | 输出上限 | 出处 | 状态 |
|---|---|---|---|---|
| gemini-3-flash-preview | 1,048,576 | 65,536 | https://aistudio.google.com/docs/models/gemini-3-flash-preview | 已确证 |
| gemini-3.8-flash | 1,048,576 | 65,536 | https://aistudio.google.com/docs/models/gemini-3.8-flash | 已确证 |
| gemini-3.1-pro-preview | 1,048,576 | 65,536 | https://aistudio.google.com/docs/models/gemini-3.1-pro-preview | 已确证 |
| gemini-2.5-flash-lite | 1,048,576 | 65,536 | https://aistudio.google.com/docs/models/gemini-2.5-flash-lite | 已确证 |

模型状态（https://aistudio.google.com/docs/models）：gemini-2.5-flash、gemini-2.5-pro 已 deprecated，2026-12-01 起分别路由到 gemini-3.5-flash-lite、gemini-3.8-flash。
价格（https://aistudio.google.com/docs/pricing，每 1M token）：gemini-3-flash-preview 输入 $0.50 / 输出 $3.00（含思考 token），batch 减半，有免费档；gemini-3.8-flash 输入 $0.75 / 输出 $3.75（至 2026-12-31，2027-01-01 起翻倍）；gemini-2.5-flash-lite 输入 $0.10 / 输出 $0.40。

## 2. Gemini 应用（gemini.google.com）与 AI Studio 网页

| 项 | 值 | 原文引用 | 出处 | 状态 |
|---|---|---|---|---|
| 每次提示文件数 | 最多 10 个 | "Up to 10 files (subject to availability) can be attached in the same prompt." | https://support.google.com/gemini/answer/14903178 | 已确证 |
| 每文件大小 | 非视频文件 100 MB | "All other supported file types can be up to 100 MB." | 同上 | 已确证 |
| 每文件页数 | 官方未写 | 页面无页数上限 | 同上 | 未确证 |
| 上下文（按订阅） | 免费 32k；AI Plus 128k；AI Pro/Ultra 1M | "32k tokens"；"128k tokens"；"1 million tokens" | https://support.google.com/gemini/answer/16275805 | 已确证 |
| 1M 上下文可容纳 | 约 1500 页文本 | "up to 1,500 pages of text or 30,000 lines of code" | 同上 | 已确证（指文本页，不是扫描页） |
| 应用内每页扫描件 token | 官方未写 | — | — | 未确证（推测与 API medium 相近，560/页） |
| AI Studio 网页上传 | 未找到官方帮助页；论坛有人报 .txt 被限 1 MB、PDF 不受影响 | 论坛：https://discuss.ai.google.dev/t/why-is-google-ai-studio-limiting-txt-uploads-to-1mb-now/111863 | 论坛（非官方） | 未确证；按 API 限制（50 MB/1000 页）设 profile |

推测：免费版 32k 上下文 = 输入 + 输出 + 对话历史。20 页 × 560 = 11,200 输入 token，再加 20 页译文（见第 3 节约 15–30k），已接近 32k。免费版建议 ≤10 页/块，AI Pro 版可用 20 页。

## 3. 输出 token 上限与单次建议页数

- 官方：所有上表模型输出上限 65,536 token（已确证）。思考 token 计入输出计费（定价页 "Output price (including thinking tokens)"，已确证）；是否同时占用 maxOutputTokens 配额，本次未读到原文（**未确证**）。
- 官方对「单次多少页」的转写/翻译建议：document-processing 页未给（工具摘录明言 "The page does not give this recommendation"），**未确证**。
- 本项目实测译文长度（`work/<卷>/{en,zh}/checked.md` 按 `<!-- PDF p.N -->` 分页统计，2026-11-26）：

| 稿 | 每页字符中位 | p90 | 最大 |
|---|---|---|---|
| 日文源（去空白） | 604–646 | 995–1413 | 2937–3960 |
| 英文稿 | 1737–1763 | 2094–2873 | 4770–4865 |
| 中文稿 | 532–593 | 982–1253 | 3388–4586 |

- 推测换算（Gemini 分词比例本次未查官方，按英文约 4 字符/token、中文约 1 字符/token 粗估）：英文 p90 约 0.7k token/页、最大约 1.2k；中文 p90 约 1.3k、最大约 4.6k。
  - 20 页一块：英文约 15–25k token，中文 p90 约 26k、全部取最大页的极端情况约 92k（超 65,536）。
  - 若开思考模式，思考 token 还要占份额。结论（推测）：**20 页是安全上限，中文稿按 15–20 页；英文稿可到 30–40 页但不建议**（单次输出越长，模型中途截断或漏页的风险越大，属经验判断，未确证）。
- 建议在 profile 里留 `max_output_pages`，并在调用端设置 `maxOutputTokens=65536`、关闭或限制思考；检测 finishReason=MAX_TOKENS 时自动二分重切。

## 4. Vertex AI（与 API 不同之处）

| 项 | 值 | 原文引用 | 出处 | 状态 |
|---|---|---|---|---|
| 每提示文件数 | 3000 个文档（与图像共享）；含纯文本可到 6500 | "Maximum number of files per prompt: 3,000 documents (shared with images" | https://docs.cloud.google.com/vertex-ai/generative-ai/docs/multimodal/document-understanding | 已确证 |
| 每文件页数 | Gemini 4 Hydrogen/Carbon 3000；2.5 Pro/Flash 3000，未迁移端点 1000 | "Maximum number of pages per file: 3,000" | 同上 | 已确证 |
| inline | 256 MB | "Maximum inline part size (GenerateContent API): 256 MB" | 同上 | 已确证 |
| Cloud Storage | 2 GiB − 500 KiB | "Maximum file size per file from Cloud Storage: 2 GiB minus 500 KiB" | 同上 | 已确证 |
| 控制台本地上传 | 7 MiB | "Maximum file size per file for direct local uploads in the console: 7 MiB inline" | 同上 | 已确证 |
| 公网 URL | 15 MiB | （工具摘录）"capped at 15 MiB per file" | 同上 | 已确证（摘录） |
| 每页 token（Gemini 3） | HIGH 1120；MEDIUM 560；LOW 280；UNSPECIFIED 560（默认） | "MEDIA_RESOLUTION_LOW: 280 tokens per page for PDFs"；"MEDIA_RESOLUTION_UNSPECIFIED: 560 for PDFs (default)" | 同上 | 已确证 |
| 模型输出上限 | 本次未读 Vertex 模型页 | — | — | 未确证（推测同 API，65,536） |

## 5. 可直接做成配置的 profile 表

`max_mb` 按 10^6 字节取严（官方 MB/MiB 混用：API 写 MB，Vertex 写 MiB）；`max_pages` = 官方硬上限；`rec_pages` = 本文建议的单次页数（推测，依据第 3 节）。

| profile | max_mb | max_pages | rec_pages | 说明 | 出处 |
|---|---|---|---|---|---|
| gemini-api-inline | 50（PDF）；整请求 100 | 1000 | 20（zh 15–20） | 扫描页按图像处理；medium 560 token/页 | file-input-methods；document-processing |
| gemini-api-files | 50（PDF；通用 2 GB） | 1000 | 20 | 48 h 过期；可用 page_options 切片，但大小/页数仍按整文件计 | files；document-processing |
| gemini-api-url | 15 | 1000 | 20 | 外部 URL | file-input-methods |
| gemini-app-free | 100/文件，10 文件/提示 | 未确证 | 10（推测，受 32k 上下文） | gemini.google.com 免费版 | support 14903178、16275805 |
| gemini-app-pro | 100/文件，10 文件/提示 | 未确证 | 20 | AI Pro/Ultra，1M 上下文 | 同上 |
| aistudio-web | 50（按 API，未确证） | 1000（按 API，未确证） | 20 | 无官方网页上传帮助页 | — |
| vertex-inline | 256 | 3000（未迁移端点 1000） | 20 | GenerateContent inline | Vertex document-understanding |
| vertex-console | 7 MiB ≈ 7.34（取 7.0） | 3000 | 10（受体积限制，见第 6 节） | 控制台本地上传 | 同上 |
| vertex-gcs | 2 GiB − 500 KiB | 3000 | 20 | | 同上 |
| google-translate-web | 10 | 300 | — | **扫描页不翻译**（见 pdf_compress_research.md §1） | support.google.com/translate/answer/2534559 |
| cloud-translate-scanned | 20 | 20 | 18 | 扫描 PDF 同步翻译 | docs.cloud.google.com/translate/docs/advanced/translate-documents |
| drive-ocr | 2 | 未确证 | — | 只适合 G4 二值化等有损方案 | support.google.com/drive/answer/176692 |

建议 TOML 形状（只是设计，未写入代码）：

```toml
[profiles.gemini-api-inline]
max_bytes = 50_000_000
max_pages = 1000
rec_pages = 20
render_dpi = 200          # 与 docstore OCR 一致；Gemini 自己按 ~2 MP 重渲染
encode = "flate"          # 无损
source = "https://aistudio.google.com/docs/document-processing"
checked = "2026-11-26"
```

CLI 设想：`docstore split <key> --profile gemini-api-inline --pages 20 [--max-mb N]`；显式参数覆盖 profile；切块时同时检查 `max_bytes`（体积）、`max_pages`（硬上限）与 `--pages`（单次输出预算），取最严者，超限即提前封块。

## 6. 与「无损 200 dpi Flate」方案的兼容性（依据 pdf_compress_research.md §4–5）

已有实测（§4）：200 dpi 灰度 + Flate，逐页中位 430–515 KB、最大 601 KB；连续 18 页最坏 9.04 MiB、20 页最坏 10.05 MiB、50 页 19.7–24.5 MiB。OCR 结果与原图逐字相同。

| profile | 体积约束是否起作用 | 建议页数/块 | 理由 |
|---|---|---|---|
| gemini-api-inline / files | 否（50 页 ≤24.5 MiB ≪ 50 MB） | 20（输出预算决定） | 体积可容约 80 页（50 MB ÷ 0.6 MB，推测）；瓶颈是 65,536 输出 token |
| gemini-app-free / pro | 否（100 MB） | 10 / 20 | 瓶颈是上下文（免费 32k） |
| vertex-inline / gcs | 否 | 20 | 同 API |
| vertex-console | 是（7 MiB） | 按体积装块，约 11–12 页（推测：7 MiB ÷ 0.6 MB） | 用 §5 提议的 `max_bytes` 贪心装块 |
| cloud-translate-scanned | 页数先到（20） | 18 | §5 实测 18 页最坏 9.04 MiB |
| google-translate-web | 10 MB | 18（体积） | 但扫描页不翻译，此路无用 |
| drive-ocr | 是（2 MB） | 无损不可行 | 只能 G4 有损 |

要点：
1. **对 Gemini，压缩不是瓶颈**：50 MB 上限下 20 页无损块约 9–10 MiB，余量 5 倍；不需要任何有损压缩。默认 profile 可直接用无损 Flate（或干脆不重编码、原 400 ppi JPEG：50 页 54 MiB 会超 50 MB，但 20 页约 22 MiB 仍可，推测按 §4 orig 体积线性折算）。
2. **分辨率**：Gemini 按约 2 MP（288 DPI）自行渲染，且"Input pixel dimensions do not change token cost"。本书 200 dpi 页为 1276×2001 ≈ 2.55 MP，已高于 2 MP，因此 400 ppi 原图给 Gemini 没有额外信息（推测；官方「2 MP」与「288 DPI」对本书页面尺寸给出的像素数不一致，以哪个为准**未确证**）。
3. **页数应由输出预算决定**：profile 里把 `rec_pages` 和 `max_pages` 分开；默认 20 页（用户提的 1–20 页）；中文目标语可设 15。
4. **方向与对比度**：官方建议先转正、避免低对比。docstore v2 已有整页旋转判断与自适应二值化（AGENTS.md），重编码时可复用旋转结果（建议，未测）；二值化是有损，不默认开。
5. **media_resolution**：日文扫描页字小且密，官方说 medium 通常饱和、"dense document comprehension" 可能要更高。建议在 2 张金标页上试 medium vs high 再定（未测，未确证）。

## 7. 未确证清单

- Gemini 应用 / AI Studio 网页的 PDF 页数上限。
- 思考 token 是否占用 maxOutputTokens 配额。
- Gemini 对日文、中文的每 token 字符数。
- 单次转写/翻译的官方建议页数（官方未给）。
- Vertex 各模型输出上限。
- 官方「2 MP」与「288 DPI」哪个决定实际渲染像素。
