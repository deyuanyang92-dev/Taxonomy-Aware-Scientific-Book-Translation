# StructDoc 检索表金标

格式：`{"doc": "Imajima2007", "set": "p176-177", "pages": [176,177], "couplets": [{"page":176,"key":1,"lead":"3'","terminals":["Foo bar"]}]}`

- pages 是金标覆盖的 PDF 页；偶句必须列全这些页上**所有**偶句（否则查准率失真）。
- 必须由人对照原页图像写成。禁止用本流水线（keys extract / structdoc）或交付 aligned 的输出生成金标（用户 2026-11-22 否决 aligned 作参照）。
- 计分：`docstore struct score structdoc.json gold.json --ledger docs/ocr_eval/STRUCT_LEDGER.tsv --note ...`
- 指标：recall/precision 按 (page,key,lead) 匹配；terminal_acc 为匹配偶句中终点完全一致的比例；wrong_flagged = 终点错误的偶句中被标 uncertain 的数量/总数。
