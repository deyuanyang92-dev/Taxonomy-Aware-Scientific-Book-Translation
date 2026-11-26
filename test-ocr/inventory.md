# 步骤1 盘点 (2026-11-21)
- tesseract: 系统 5.3.4 (leptonica 1.82.0, AVX2/FMA/OpenMP)；/opt/tess 不存在
- tessdata(/usr/share/tesseract-ocr/5/tessdata): 仅标准 jpn、eng、lat、osd 等；无 jpn_vert、Japanese、fast/best(仅 deu_fast)
- 编译工具: cmake gcc g++ pkg-config 有；autoconf/libtool/libleptonica-dev 缺(未确证需要，装前查)
- GPU: GTX 1660 SUPER 6144MiB，盘点时已占 5857MiB、util 100%，WSL 内无进程 → 占用来自 Windows 侧，GPU 测试前必须释放(基线>1800MiB 中止)
- venvs(/root/ocr_eval): datalab docling doctr gpu marker mineru olmocr rapid vlm yt；ext/ndlocr-lite 已有
- 磁盘 / 剩余 53G；内存 62G；16 核
