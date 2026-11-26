#!/bin/bash
cd /mnt/p/翻译-译作/Taxonomy-Aware-Scientific-Book-Translation
echo "== yomitoku_lite"; python3 scripts/bench/ocr_run_ext.py yomitoku_lite_200 --adapter yomitoku --dpi 200 --args=--lite 2>&1 | tail -3
echo "== ndlocr"; python3 scripts/bench/ocr_run_ext.py ndlocr_200 --adapter ndlocr --dpi 200 2>&1 | tail -4
echo ALLDONE
