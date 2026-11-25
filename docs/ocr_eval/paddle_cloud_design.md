# PaddleOCR 云 API 调用：顶层设计（2026-11-23）

依据：官方文档摘录 `docs/ocr_eval/paddle_aistudio_api_official.md`；实测原始 JSON `docs/ocr_eval/paddle_api_probe_raw/`（T1–T11）；实测汇总 `docs/ocr_eval/paddle_aistudio_api_probe.md`。

## 1. 已确证事实（实测，2026-11-23，模型 PaddleOCR-VL-1.6，异步 /api/v2/ocr/jobs）

| # | 事实 | 证据 |
|---|---|---|
| F1 | 提交成功：HTTP 200，`{"code":0,"data":{"jobId":…}}` | T1、T4、T7… submit |
| F2 | 错误模型名：HTTP 400，`code 10007 "模型传参错误"` | T3a |
| F3 | 非 PDF 字节：HTTP 400，`code 10004 "文件格式不支持"` | T3b |
| F4 | 错误 token：HTTP 401，`code 401 "Unauthorized"` | T3c |
| F5 | 任务失败：轮询 HTTP 200、`code 0`，`data.state="failed"`，`data.errorMsg="OCR服务请求失败，状态码 500"`；无 extractProgress | T2、T5×2 |
| F6 | 上述 500 失败是**随机的**：同内容 105 页 PDF，T5 两次失败（4 s 内），T10 成功 | T5、T10 |
| F7 | done 时有 `data.extractProgress.totalPages / extractedPages`（文档说只在 running 有效，实测 done 也有） | 全部 done 任务 |
| F8 | JSONL：每行 4 页（末行余数），每行有 `errorCode/errorMsg/logId/result`；`result.dataInfo.numPages` = 本行 `layoutParsingResults` 长度；页序与原 PDF 一致 | T7：25 行 100 页，页号 1..100 全对 |
| F9 | 101、105、150、250 页均完整解析（totalPages = extractedPages = 提交页数），**未观察到 100 页截断** | T8–T11 |
| F10 | 空白页：done，layoutParsingResults 1 项，markdown 为空串 | T4 |
| F11 | 经本机 Clash 代理（172.26.32.1:7892）上传 ≥2.4 MB 即 ProxyError / SSLError；直连（NO_PROXY 含 aistudio-app.com、bcebos.com）正常 | T1、T2 两轮 |
| F12 | jsonUrl 是 BOS 签名链接，有效期 604800 s（7 天） | jsonUrl 参数 |

## 2. 未定 / 与文档冲突

- 页数上限：文档三处说法（100 / 1000 / 英文旧版 100 + 日 3000）。实测 250 页正常。**按用户转述的官方要求取 ≤100 页/任务**——保守、且失败重试代价小（F6）。
- 文件大小上限：文档称无限制；76 MB 的 105 页扫描件失败一次（F5，可能是随机 500，未确证与大小有关）。设计加字节上限（默认 40 MB）再细分。
- 并发/QPS、配额用尽码（403/12001 或 429）：文档不一致，未实测（不故意耗尽额度）。

## 3. 设计 v2（2026-11-23，吸收 Codex 审查；v1 见本节末“修订记录”）

### 3.0 原则
- 每块 ≤100 页（用户转述的官方要求 + 英文配额页 2.3；实测 250 页可过，但不依赖）。
- **只有通过全部闸口的页才入库**；未通过的页走现有逐页降级，并在版本元数据里留下原因。
- 不建任何缓存目录（AGENTS.md:17）。批量识别在 textify **父进程**里做，结果直接经 `save()` 写 docstore。

### 3.1 分块（`paddle_vl.plan_chunks`）
- 输入：有序页码列表（可不连续）。按顺序切成 ≤ `MAX_PAGES`（默认 100，env `DOCSTORE_PADDLE_MAX_PAGES`，越界 [1,100] 报 ValueError）。
- 生成块 PDF 后检查字节 ≤ `MAX_BYTES`（默认 45 MB，官方本地上传上限 50 MB）；超了就对半拆，单页仍超 → 该页记失败（走本地降级）。

### 3.2 一个块的生命周期（`paddle_vl.run_chunk`）
1. **提交**：HTTP 200 且 body.code==0 且 data.jobId 非空。
2. **轮询**：每次 HTTP 200、code==0、data.jobId==提交的 jobId、state∈{pending,running,done,failed}；否则按 3.3 分类。轮询/下载的暂时错误只重试**同一 jobId**（不重复提交）。
3. **done 校验**（任一不过 = 块失败，不返回半成品）：
   a. extractProgress 存在时：totalPages、extractedPages 归一化为非负整数（接受数字字符串），都须等于提交页数；缺失只记警告（官方说仅 running 有效），以 JSONL 为准。
   b. jsonUrl 下载 HTTP 200；每行能解析为 JSON；每行 errorCode==0；logId 不重复。
   c. 每行 `len(layoutParsingResults) == dataInfo.numPages == len(dataInfo.pages)`；总和 == 提交页数。
   d. **页身份**：第 i 个结果的 dataInfo.pages[i] 宽高 == 第 i 个提交页 `page.rect` × 2（±2 px，实测 T6/T7 全部精确 2.0 倍）。不符即判乱序/错页。
   e. 每页 `markdown.text` 为 str。
4. **逐页文本判定**（`clean_md` 之后）：
   - 非空 → 通过。
   - 空，且原始 markdown 含图片块（`![` 或 `<img`）→ 通过，标 `empty_reason="image_only"`。
   - 空，且本地判定为空白页（无文本层、30 dpi 灰度渲染非白像素 <0.5%）→ 通过，标 `blank`。
   - 其余 → 该页判失败（疑似漏识），走逐页降级。

### 3.3 错误分类（同时看 HTTP 与业务码，按官方错误码表 §4）
| 类 | 条件 | 处理 |
|---|---|---|
| 配置错 `PaddleConfigError(ValueError)` | 401；403 且 code≠12001；code 10007/10008/10009/11001 | 立即上抛，**不降级**（textify 对 ValueError 本就不降级） |
| 配额 `PaddleQuotaError` | code 12001；HTTP 429 且 code≠12002 | 父进程停止所有云提交；剩余页只用 fallback 引擎，日志写明 |
| 缩块 | code 10003/10006；HTTP 413 | 对半拆再提交 |
| 文件问题 | code 10001/10002/10004/10005 | 块失败，页走本地降级 |
| 暂时性 `PaddleJobError` | 网络异常、5xx、503/504、10010、12002、11003、state=failed、3.2.3 校验不过 | 退避（10/30/90 s）最多 3 次；仍失败且块 >1 页则对半拆一轮；再失败 → 页走降级 |
| 未知组合 | 以上皆非 | 当暂时性处理，但日志打印原始 code/msg/traceId |

### 3.4 与 textify 集成
- `textify` 在 `need_ocr` 非空、且 engines 首位为 `paddle_vl` 时，先调 `paddle_vl.run_pages(path, need_ocr, log=log)`（父进程，线程并发 `DOCSTORE_PADDLE_CONCURRENCY` 默认 4 块）。返回 `ok: {页: (文本, 元数据)}`、`failed: {页: 原因}`、`quota_hit: bool`。
- ok 页：`save(n, [("paddle_vl", 文本, None, 秒)])`，版本 extra 记 jobId、traceId、块号、empty_reason。
- failed 页：进入现有逐页路径；若 quota_hit，engines 去掉 paddle_vl（只用 fallback），否则保留逐页 paddle_vl（单页任务，同一闸口）+ fallback。
- 返回值增加 `cloud_ok / cloud_failed / cloud_failed_reasons`；日志末行汇总。
- 单页 `paddle_vl_run` 复用 `run_chunk`（1 页块），同样过 3.2 全部闸口；空文本漏识 → 抛 `PaddleJobError` → `_run_with_fallback` 降级。

### 3.5 网络
- `requests.Session`，`trust_env=False`（直连，F11）；env `PADDLEOCR_USE_PROXY=1` 走系统代理。
- 超时：上传 300 s，轮询 60 s，块总等待 `DOCSTORE_PADDLE_JOB_TIMEOUT` 默认 1800 s。

### 3.6 测试（离线，假 Session）
分块（250→100/100/50，非连续页，越界 env）；超字节对半拆、单页超限；闸口 a–e 各一条反例（少一页、errorCode≠0、重复 logId、两行互换导致尺寸不符、extractProgress 字符串/缺失）；空页三态；错误分类（401/10007 上抛 ValueError 不降级，12001 停云，10006 拆块，failed→重试成功）；轮询错误不重复提交；textify 集成：云 ok 页入库、failed 页走降级、quota 后不再调云；Session.trust_env 默认 False；clean_md 原测试保留。

### 3.7 不在本次范围（Codex 指出，属 textify 既有行为，另立项）
- 内嵌 OCR 层的书：`text_done` 按“有任何版本的页数”判定，`--pending` 会漏选（docstore/textify.py:329、docstore/cli.py:46–48）。本次不改，记入 PROGRESS。

### 3.7 残余风险
- 同尺寸页互换无法由客户端识别：服务端不返回源页标识，页身份校验只比对宽高。依赖官方同步页文档“数组中的每个元素依次表示PDF文件中实际处理的每一页的结果”的顺序保证与 T7 实测（100 页顺序全对）。拆成单页任务可消除该风险但使分块失去意义，故不做（审查 r2 第 6 条，主线程裁定）。

### 修订记录
- v1→v2：去掉磁盘缓存（违反 AGENTS.md:17）；加页身份校验 3.2.3d；空页三态；错误按业务码分类，配置错不降级、配额停云；上传字节上限 45 MB；轮询错误不重复提交。

## 4. 不做
- 不改路由表语种分配、不改 UI、不做 18:00–09:00 批量 OCR 调度（N 盘另一项目）。
