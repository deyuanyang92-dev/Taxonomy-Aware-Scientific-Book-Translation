# OCR QC 进度

## 2026-11-11 19:42 · cursor

- 完成：读 brief、工作区 AGENTS（0/0b/3）、`docstore status`（41 份 / 16105 页，ocr_verified=278）、现有 `quality/consensus/verify` 与试点文档。
- 未动：`docs/ocr_consensus_pilot_metrics.json`（他人进行中）。
- 下一步：用 278 页 ocr_verified 作金标准，对 alternates 中各引擎 OCR 算 CER（总/拉丁/数字/CJK 扩展/漏行），写 `docs/ocr_accuracy_baseline.md` + json。

## 2026-11-11 19:50 · cursor

- 完成：基线 CER → `docs/ocr_accuracy_baseline.md` + `.json`。RapidOCR_300 CER=0.0144；RapidOCR_200 CER=0.0917。glm/Tesseract/生僻字 CER 因样本缺口未测。
- 下一步：写调研结论进基线文档；实现 `docstore qc` + `rules/qc.toml` + 测试；金标准标定查全率/误报率。

## 2026-11-11 20:10 · cursor

- 完成：`docstore qc`（评分/apply pass/redo/calibrate）、`rules/qc.toml`、测试、标定 json、调研写入 baseline、试点杨德渐2006+刘瑞玉2008名录（分流+563/158 次 pass 提升+2 页 redo 样本）、`docs/ocr_qc_pilot.md`。pytest 51 过；ruff/mypy 过。未动 `ocr_consensus_pilot_metrics.json`。全库未铺开。
- 下一步：用户确认后是否批量 `--apply --redo`。
