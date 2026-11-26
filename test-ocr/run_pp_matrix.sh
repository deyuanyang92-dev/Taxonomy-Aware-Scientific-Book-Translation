#!/bin/bash
cd /mnt/p/翻译-译作/Taxonomy-Aware-Scientific-Book-Translation
PY=/root/ocr_eval/venv_gpu/bin/python
for cfg in "PP-OCRv5_mobile ppocrv5_mobile_200 200" "PP-OCRv6_medium ppocrv6_medium_200 200"; do
 set -- $cfg
 echo "== $2"; $PY scripts/bench/ocr_run.py $2 --model $1 --dpi $3 2>&1 | tail -30
done
echo ALLDONE
