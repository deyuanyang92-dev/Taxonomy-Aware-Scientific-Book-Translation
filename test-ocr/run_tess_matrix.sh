#!/bin/bash
# 串行跑 Tesseract 版本 × 模型档 × 语言矩阵（psm3, 300dpi）
cd /mnt/p/翻译-译作/Taxonomy-Aware-Scientific-Book-Translation
declare -A BIN=( [411]=/opt/tess/4.1.1/bin/tesseract [534]=tesseract [551]=/opt/tess/5.5.1/bin/tesseract )
for v in 411 534 551; do for q in std fast best; do for l in jpn jpn_vert Japanese; do
  tag=tess${v}_${q}_${l}_psm3_dpi300
  [ -f test-ocr/runs/$tag/metrics.json ] && continue
  [ $v = 534 ] && [ $q = std ] && [ $l = jpn ] && continue
  echo "== $tag"; python3 scripts/bench/ocr_run_tess.py $tag --bin ${BIN[$v]} --tessdata /opt/tess/tessdata/$q --lang $l --psm 3 --dpi 300 2>&1 | grep -E "MEAN|Error|error" 
done; done; done
echo ALLDONE
