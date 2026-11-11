# OCR 本地评测产物

目录说明（不写资料库）：

- 原始页图与金标准文本在 `/root/ocr_eval/pages/`（库外，避免污染仓库与资料库）
- 本目录放：汇总指标 JSON/Markdown、各引擎原始输出副本
- CER 对照对象为库内主版本文本（多为 glm verified），**是一致率，不是真实精度**

生成者：cursor。任务：`docs/tasks/ocr_design_brief.md`。
