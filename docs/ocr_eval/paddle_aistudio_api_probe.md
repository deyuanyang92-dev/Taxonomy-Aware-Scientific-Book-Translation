# PaddleOCR 云 API 实测（2026-11-23，PaddleOCR-VL-1.6，异步 jobs 接口）

脚本：会话临时目录 probe.py（逻辑：提交→轮询状态变化全量记录→下载 JSONL→统计）。原始 JSON 在 `paddle_api_probe_raw/`（不含 token）。

| 测试 | 输入 | 结果 |
|---|---|---|
| T1 | 扫描件 3 页（2.4 MB） | 经代理 2 次 ProxyError；直连 done，131 s，totalPages=extractedPages=3，JSONL 1 行 3 页 |
| T2 | 扫描件 105 页（76 MB） | 经代理 SSLError；直连 state=failed "OCR服务请求失败，状态码 500"（53 s） |
| T3a | model=NoSuchModel | HTTP 400 code 10007 "模型传参错误" |
| T3b | 随机字节 bad.pdf | HTTP 400 code 10004 "文件格式不支持" |
| T3c | token=invalid | HTTP 401 code 401 "Unauthorized" |
| T4 | 1 页空白 | done，1 行 1 页，markdown 空串 |
| T5 | 合成文字 105 页 | 两次均 failed "状态码 500"（4 s） |
| T6 | 扫描件 30 页 | done 112 s，JSONL 8 行（每行 4 页），共 30 页 |
| T7 | 合成 100 页 | done，25 行，100 页，页号 1..100 顺序全对 |
| T8 | 合成 101 页 | done，totalPages=extractedPages=101，101 页全有 |
| T9 | 合成 150 页 | done，150/150 |
| T10 | 合成 105 页（与 T5 同内容） | done，105/105 → T5 的失败是随机的 |
| T11 | 合成 250 页 | done，250/250 |

结论见 `paddle_cloud_design.md` 第 1–2 节。
