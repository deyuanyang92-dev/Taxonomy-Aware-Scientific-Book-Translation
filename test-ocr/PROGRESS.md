# 进度 2026-11-21
## 目标
三本中国动物志各随机 10 页做中文 OCR 测试，Datalab 作参照金标（用户 /goal）。
## 已完成
- 取样：多毛纲Ⅰ(z09)、第三十三卷(z33)、第五十四卷(z54) 各 10 页，固定种子。
- 金标：Datalab accurate；已去其自生成英文图片描述与页眉页码；3 页无正文剔除，n=27。
- 结果 cer_norm：PP-OCRv6 medium 0.0394（3.3 s/页）；v5 server 0.0490；v5 mobile 0.0542（1.1 s/页）；Tesseract chi_sim 0.1318。z33 最难，z33_p0047 各引擎约 0.32（原因未确证）。
- 已写 LEDGER.tsv（4 行）、REPORT.md（中文动物志一节）、tests/test_zh_gold.py（3 passed）；ruff(忽略 E702/E401)、mypy 通过。
- 已 git add 仅 OCR 相关文件：.gitignore scripts/bench/zh_*.py tests/test_zh_gold.py LEDGER REPORT。
## 未完成 / 下一步
- 提交并推送 main 被权限拦截：等用户允许，或用户自跑 `! git commit` / `! git push`。信息 “OCR eval: Chinese fauna test (3 books x 10 pages), Datalab reference gold, PP-OCR vs Tesseract”，末尾 Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>。
- 可选：补 RapidOCR/Tesseract 其他 psm；逐页核 z33_p0047；Datalab 金标人工抽核。
- 日文测试遗留（Surya 2.5、Datalab 日文、dots.ocr、kraken 全集等）仍未做。
## 关键决定
- Datalab 是参照非真值，分数=与 Datalab 差异；金标文本不入库。
## 文件位置
- 仓库：/mnt/p/翻译-译作/Taxonomy-Aware-Scientific-Book-Translation
- 脚本：scripts/bench/zh_sample.py zh_datalab.py zh_run.py（`zh_run.py <tag> --score-only` 重算）
- 数据：test-ocr/zh_fauna/（manifest、pages、datalab）；runs：test-ocr/runs/zh_*/（均 gitignore）
- key：test-ocr/.env.datalab（勿入库）
## 坑
- Datalab 关 caption 开关仍有英文描述残留，须 strip_gold_artifacts 过滤。
- PP-OCR 会读页眉页码，Datalab 不读，须两边 strip_header。
- 工作区有大量无关未提交改动，提交只 add OCR 文件。
## 仍在跑的任务
- 无
