#!/usr/bin/env bash
# 由正式版 PDF 生成传播版：彩色/灰度图降到 120 dpi，彩图重压成 JPEG 质量 72，字体仍全嵌入并子集化。
# （Rouse 2022 中译本 55 MB -> 12 MB，图文仍清晰。）
#
# 用法: share_pdf.sh <正式版.pdf> [传播版.pdf]
#   缺省输出 <正式版同目录>/<原名>_传播版.pdf
# 环境变量: GS=Ghostscript 命令名（Windows 用 gswin64c）；RES=图像分辨率，缺省 120；JPEGQ=JPEG 质量，缺省 72
set -euo pipefail

if [ $# -lt 1 ] || [ ! -f "$1" ]; then
    echo "用法: $0 <正式版.pdf> [传播版.pdf]" >&2
    exit 2
fi
SRC="$1"
DST="${2:-${SRC%.*}_传播版.pdf}"
GS="${GS:-gs}"
RES="${RES:-120}"
JPEGQ="${JPEGQ:-72}"

if ! command -v "$GS" >/dev/null 2>&1; then
    echo "找不到 Ghostscript（$GS）。Linux: apt-get install ghostscript；Windows: 设 GS=gswin64c" >&2
    exit 3
fi
if [ "$(readlink -f "$SRC")" = "$(readlink -f "$DST" 2>/dev/null || echo "$DST")" ]; then
    echo "传播版不能覆盖正式版：$SRC" >&2
    exit 2
fi

"$GS" -dNOPAUSE -dBATCH -dQUIET -sDEVICE=pdfwrite -dCompatibilityLevel=1.6 \
    -dDownsampleColorImages=true -dColorImageDownsampleType=/Bicubic \
    -dColorImageResolution="$RES" -dColorImageDownsampleThreshold=1.0 \
    -dDownsampleGrayImages=true -dGrayImageResolution="$RES" -dGrayImageDownsampleThreshold=1.0 \
    -dAutoFilterColorImages=false -dColorImageFilter=/DCTEncode -dJPEGQ="$JPEGQ" \
    -dEmbedAllFonts=true -dSubsetFonts=true \
    -sOutputFile="$DST" "$SRC"

size() { du -h "$1" | cut -f1; }
echo "正式版 $(size "$SRC") -> 传播版 $(size "$DST")：$DST"
