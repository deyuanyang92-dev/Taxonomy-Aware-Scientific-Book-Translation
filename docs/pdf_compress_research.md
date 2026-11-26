# 扫描版 PDF 切块压缩调研（面向 Google 文档处理，≤10 MB/块）

日期：2026-11-26。调研对象：Imajima 2009/2001/2007 三本日文扫描志书（`/mnt/p/翻译-译作/日本-imajima/`）。
实验文件全部在 scratchpad（会话临时目录），未写入项目目录。

## 1. Google 官方限制（WebFetch 于 2026-11-26 读取官方页面）

| 服务 | 大小 | 页数 | 扫描件 PDF | 出处 |
|---|---|---|---|---|
| Google 翻译网页版「文档」 | ≤10 MB（.docx/.pdf/.pptx/.xlsx） | PDF ≤300 页 | **不翻译**：官方原文 "You can find text in images and scanned .pdf pages in the output document but they aren't translated." | https://support.google.com/translate/answer/2534559 |
| Cloud Translation API 文档翻译（同步） | PDF ≤20 MB | 原生 PDF ≤300 页（需 isTranslateNativePdfOnly=true）；**扫描 PDF ≤20 页**；开 enableShadowRemovalNativePdf 时 20 页 | 支持，但 "Translating scanned PDF files results in some formatting loss"；扫描+原生混合时扫描部分不翻译；扫描件不能与 PDF→DOCX 转换同用 | https://docs.cloud.google.com/translate/docs/advanced/translate-documents |
| Cloud Translation API 批量 | 一次最多 100 个文件，总量 ≤1 GB 或 1 亿 Unicode 码点 | 官方页未写单 PDF 页数上限（未确证） | 同上 | 同上 |
| Google Drive「用 Google 文档打开」OCR | "The file should be 2 MB or smaller." | 官方页未写页数上限（第三方博客称只取前 10 页，**未确证**） | 支持（这就是 OCR 功能）；"Text should be at least 10 pixels high." | https://support.google.com/drive/answer/176692 |

已确证要点：
- 用户说的「每文件 10 MB」与 Google 翻译网页版一致；但**该入口对扫描页不做 OCR、不翻译**。本项目三本书无文本层，直接上传扫描块到 Google 翻译网页版，得到的是原图，不会有译文。
- 若改用 Cloud Translation API：扫描 PDF 同步请求每份 ≤20 页、≤20 MB；50 页一块超出 20 页限制。
- 若用 Drive OCR：每份建议/限制 2 MB（官方措辞 "should be"）。


## 2. 源 PDF 图像结构（pdfimages -list，未解码整本）

已确证（`pdfimages -list`/`pdfinfo`，2026-11-26）：
- 三本都是 **每页 1 张整页灰度 JPEG（8 bpc），400 ppi**（2001 卷有 1 页 RGB JPEG、1 页 300 ppi）。无文本层。2009 卷：361 页，2551×4002 px，页面 459.18×720.36 pt，Adobe Acrobat 7.0 Image Conversion。
- 每页中位 1.13–1.27 MB，最大 1.6–2.1 MB。按 50 页切块的原始体积（MiB，图像流合计）：
  - 2009：53.9 58.9 59.5 65.3 64.2 60.8 64.0 10.0
  - 2001：55.2 55.5 53.1 54.2 54.2 58.0 52.6 58.2 6.7
  - 2007：55.4 57.1 56.1 54.9 55.9 57.6 56.4 15.0
- 结论：`docstore split`（pdfsplit.py 用 pypdf 原样抄页，不重编码）切出的 50 页块约 53–65 MiB，是 10 MB 的 5–6.5 倍。实测 2009 p1–50 块 53.99 MiB。

## 3. 本机可用工具（which / pip list）

有：gs（Ghostscript）、pdfimages/pdfinfo/pdftoppm（poppler）、ImageMagick convert、tesseract；系统 python3：PyMuPDF 1.27.2.3、pypdf 6.8.0、Pillow 12.1.1（含 libtiff→CCITT G4、OpenJPEG 2.5.4）、opencv-headless 4.13；GPU venv：PyMuPDF 2.1、paddleocr 3.7.0。
缺（未安装）：qpdf、mutool、img2pdf、jbig2enc、ocrmypdf、pdfcpu、pikepdf。因此 JBIG2 与 MRC 分层未实测。

## 4. 实验（2009 卷 p1–50 一块；OCR 质量另测两张金标页）

方法：脚本 `compress.py` / `compress2.py`（scratchpad），OCR 用 docstore 原样流程：`ppocr_rows(pdf, p, 200)`（PP-OCRv5_server，v2 自适应，GPU）→ `rows_to_text` → `prep_ja.page_paras` → `split_glued` → `bench/cer.py::cer`，与 `bench/eval.py` 相同。缓存指向 scratchpad（`DOCSTORE_PPOCR_CACHE`），未写 ~/.cache。
- 金标 CER：`bench/gold/Imajima2009_p0066.txt`、`Imajima2001_p0061.txt`（各自对该页单页 PDF 施加同一压缩）。
- 一致性 CER：2009 p6/12/20/30/40/47 六页，压缩后 OCR 文本对原图 OCR 文本的 CER（字符数加权）。0 = 与原图逐字相同。
- 重复性对照：原图跑两遍（orig/origB）结果逐字相同，一致性 CER 0，说明 OCR 在本机是确定性的，下表差异来自图像改动而非随机性。
- 体积单位 MiB；「≤10 MB」按 10,000,000 字节判（Google 未说明 MB 是 10^6 还是 2^20，**未确证**，故取严）。

| 方法 | 做法 | 50 页体积 MiB | ≤10 MB | 金标 CER 2009 p66 | 金标 CER 2001 p61 | 对原图一致性 CER（6 页） |
|---|---|---|---|---|---|---|
| orig | 原图（pypdf/fitz 抽页，400 ppi 灰度 JPEG 不动） | 53.99 | 否 | 0.0008 | 0.0061 | 0 |
| r200_png | MuPDF 按 200 dpi 渲染灰度（= docstore page_pixmap）→ PNG/Flate 无损 | 19.73 | 否 | 0.0008 | 0.0061 | 0 |
| r200_q90 | 同上 → JPEG q90 | 19.78 | 否 | 0 | 0.0138 | 0.0099 |
| r200_q75 | 同上 → JPEG q75 | 14.09 | 否 | 0.0017 | 0.0184 | 0.0141 |
| r200_q60 | 同上 → JPEG q60 | 11.51 | 否 | 0.0034 | 0.0199 | 0.0117 |
| r200_q40 | 同上 → JPEG q40 | 9.30 | 是 | 0.0008 | 0.023 | 0.0126 |
| r200_g4 | 同上 → Otsu 二值化 → CCITT G4 | 1.94 | 是 | 0.0008 | 0.0291 | 0.018 |
| j200_q90 | 原 JPEG 解码 → Lanczos 降到 200 ppi → JPEG q90 | 20.63 | 否 | 0.0017 | 0.0306 | 0.0129 |
| j200_q75 | 同上 q75 | 14.79 | 否 | 0.0008 | 0.0214 | 0.014 |
| j200_q60 | 同上 q60 | 12.12 | 否 | 0.0008 | 0.023 | 0.0137 |
| j200_q40 | 同上 q40 | 9.77 | 否 | 0.0008 | 0.026 | 0.0141 |
| j300_q50 | Lanczos 降到 300 ppi → JPEG q50 | 20.71 | 否 | 0.0017 | 0.0291 | 0.0122 |
| gs_200_q75 | Ghostscript pdfwrite 降采样 200 ppi（Bicubic）+ DCT QFactor 0.4 | 16.05 | 否 | 0.0025 | 0.0322 | 0.0144 |
| bin400_g4 | 400 ppi Otsu 二值化 → CCITT G4 | 3.83 | 是 | 0.0025 | 0.0153 | 0.006 |
| bin300_g4 | 300 ppi 二值化 → G4 | 2.94 | 是 | 0.0017 | 0.0168 | 0.008 |
| bin200_g4 | 200 ppi 二值化 → G4 | 2.01 | 是 | 0.0008 | 0.026 | 0.0123 |

（原始数据：scratchpad `compress_exp/ocr_result_run1.json`、`ocr_result.json`、`sizes.tsv`、`chunkstats.json`。）

补充：
- JPEG 2000 无损（r200_jpx）：26.5 MiB，比 PNG/Flate 大，不取。
- 无损 r200_png 在最重的块（2009 p151–200，原 65.4 MiB）上为 24.5 MiB。逐页 Flate 大小：p1–50 中位 430 KB、最大 601 KB；p151–200 中位 515 KB、最大 583 KB。任意连续 N 页的最大体积：N=18 → 7.87 / 9.04 MiB；N=20 → 8.74 / **10.05** MiB；N=25 → 10.80 / 12.61 MiB。
- 肉眼对比：未做（只做了数值比较）。

### 实验结论

已确证（本机、上述样本）：
1. **只有「按 OCR 分辨率渲染后无损存储」（r200_png）的 OCR 结果与原图逐字相同**：两张金标页 CER 相同（0.0008 / 0.0061），6 页一致性 CER 0，行框数相同。原因：docstore 本来就用 MuPDF `get_pixmap(dpi=200)` 把 400 ppi 页面渲染到 200 dpi 再 OCR；把这张 200 dpi 位图原样（无损）存进 PDF，重新渲染 200 dpi 时像素不变。体积为原图的 37%。
2. **任何有损方案都会改变 OCR 结果**，包括 JPEG q90（6 页约 1% 字符不同）与 Lanczos/Bicubic 降采样（不同于 MuPDF 的重采样滤波，即使 q90 也有 1.3% 差异）。两张金标页上，所有 15 个有损方案的合计 CER 都高于原图（原图 0.0069；有损方案 0.0138–0.0347）。2001 p61 单页 CER 从 0.0061 升到 0.0138–0.0322。
3. 能把 50 页压到 ≤10 MB 的只有：二值化 G4（1.9–3.8 MiB）与 JPEG q40 @200（9.30 MiB，余量极小，且重的块必超）。它们的 OCR 一致性 CER 0.6%–1.8%，金标 CER 上升 2.5–4.8 倍（2001 p61）。二值化还会把照片、网点图变成黑白点，图版细节损失。

未定：
- 有损方案在更大样本上是否「系统性更差」还是只是「不同」：金标只有 2 页（n=2），差异方向一致但样本太小。
- Google 自己的 OCR 对这些压缩方式的敏感度：本实验只用 PP-OCRv5 作代理，没有测 Google。

## 5. 结论与推荐

**「50 页一块、每块 ≤10 MB、CER 不变」做不到**（已确证）。CER 不变要求无损；无损最小方案（200 dpi 渲染 + Flate）50 页为 19.7–24.5 MiB。

**推荐方案**：200 dpi 灰度渲染 + 无损 Flate，**每块 18 页**（实测最坏连续 18 页 9.04 MiB；20 页会出现 10.05 MiB 超限）。更稳的做法是按体积装块：逐页累加，到 9.5 MB 前封块（页数随内容变化，约 18–22 页）。三本 1130 页约 63 块（推测，按 18 页/块估算）。

与 Google 限制的匹配（已确证限制 + 推测适用）：
- Google 翻译网页版：10 MB/300 页可满足，**但扫描页不翻译**（官方原文见第 1 节）。上传扫描块只能拿回原图，这条路走不通，除非先加文本层（例如把本项目 OCR 结果做成隐形文本层），此做法本次未测，Google 翻译是否会翻译隐形文本层、版面如何，**未确证**。
- Cloud Translation API 扫描 PDF：同步每份 ≤20 页、≤20 MB。18 页无损块两项都满足。
- Drive OCR：官方建议 ≤2 MB；无损 18 页约 8–9 MB 超出；只有 G4 二值化能接近（50 页：bin200 2.01 MiB、bin400 3.83 MiB；要 ≤2 MB 需约 25–50 页一块），但 OCR 有损。

**实现要点**（函数级，未改代码，供在 docstore 里实现）：
1. 在 `docstore/pdfsplit.py` 增加可选重编码：`split_pdf(..., render_dpi: int | None = None, max_bytes: int | None = None)`。
2. 每页：`pix = doc[p].get_pixmap(dpi=render_dpi, colorspace=fitz.csGRAY)` → `Image.frombytes('L', ...)` → `save(bio, 'PNG', optimize=True)` → 新页 `new_page(width=原页宽, height=原页高)` + `insert_image(rect, stream=png)`（MuPDF 存为 Flate，1276×2001，标 200 ppi）。页面尺寸必须与原页一致，否则重新渲染 200 dpi 时像素对不上。渲染必须用 MuPDF（与 docstore 的 `page_pixmap` 同一引擎）；改用 Pillow/Ghostscript 重采样就不再无损。
3. 装块：先算每页 PNG 字节数，贪心累加到 `max_bytes`（建议 9.5e6，留 PDF 结构开销）就封块；文件名仍带原页码范围，manifest 记原 PDF 页码，便于回映。
4. 回归测试：取 2 页样本，断言重编码块的 `ppocr_rows` 与原 PDF 逐字相同（本实验即此法）；体积断言每块 ≤ max_bytes。
5. 若接受有损（Drive OCR 2 MB 路线）：用 400 ppi Otsu + G4（Pillow `save('PDF', save_all=True)` 对 mode '1' 自动写 CCITT G4，pdfimages 验证 enc=ccitt），50 页 3.8 MiB，一致性 CER 0.6%，是有损方案里改动最小的；但图版照片会被毁，须另存图。

**风险**：
- Google 翻译网页版不翻译扫描页（已确证，最大风险）。用户的目的若是「让 Google 翻译」，压缩之前要先决定走哪条 Google 路线。
- 「10 MB」是 10^6 还是 2^20 字节未确证；按 10^6 取严。
- 无损结论只对 docstore 的 200 dpi 流程成立；若将来改 OCR dpi（如 300），需按新 dpi 渲染，体积约 ×2.25（推测，按像素比）。
- 原始 400 ppi 信息在 200 dpi 块中丢失；原 PDF 仍是母本，不可删除。
- 样本：体积测了 2009 卷 2 个块；2001 卷部分页尺寸更大（2607×4013），其块体积未实测（未定）。
