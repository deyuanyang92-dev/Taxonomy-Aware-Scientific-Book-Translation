# PaddleOCR AI Studio 云端 API 官方说明要点

抓取日期：2026-11-23。方法：无头 Chromium 渲染官方文档页，文本原样存档（临时目录），下文引文为页面渲染文本。
入口页 https://aistudio.baidu.com/paddleocr 为 JS 渲染；其 API 按钮的说明页（https://aistudio.baidu.com/paddleocr/task）需登录，未能读取，标“文档未写明/未读到”处即此原因或文档确实没写。API 文档在 ai.baidu.com 帮助文档站「AI Studio > PaddleOCR专区」。

## 0. 文档页清单（来源 URL）
| 页面 | URL | 页面标注更新时间 |
|---|---|---|
| 异步API使用文档 | https://ai.baidu.com/ai-doc/AISTUDIO/fml7mozw5 | 2026-02-04 |
| 异步 API 英文版 | https://ai.baidu.com/ai-doc/AISTUDIO/Mml7n69e7 | 未核 |
| API 配额规则和错误码说明（中） | https://ai.baidu.com/ai-doc/AISTUDIO/Xmjclapam | 2026-09-08 |
| API Quota Rules and Error Code Description（英） | https://ai.baidu.com/ai-doc/AISTUDIO/pmjcld5qm | 2026-02-10 |
| PaddleOCR-VL-1.5_API（同页含 VL-1.6 简介） | https://ai.baidu.com/ai-doc/AISTUDIO/Cmkz2m0ma | 2026-06-16 |
| PaddleOCR-VL_API | https://ai.baidu.com/ai-doc/AISTUDIO/2mh4okm66 | 2025-12-29 |
| PP-OCRv5_API | https://ai.baidu.com/ai-doc/AISTUDIO/Kmfl2ycs0 | 未核 |
| PP-StructureV3_API | https://ai.baidu.com/ai-doc/AISTUDIO/Fmfz6oh2e | 未核 |
| PaddleOCR MCP | https://ai.baidu.com/ai-doc/AISTUDIO/bmfl1tnm4 | 未核 |

重要：上列 PaddleOCR-VL-1.5_API / VL_API / PP-OCRv5_API / PP-StructureV3_API 四页描述的是 **同步** 服务化接口（POST /layout-parsing，Authorization: token，file 为 Base64 或 URL，同步直接返回）。**异步任务接口** 只在「异步API使用文档」。两者的页数限制不同，不要混用。

## 1. 异步接口端点（来源 https://ai.baidu.com/ai-doc/AISTUDIO/fml7mozw5）
原文：
```
接口文档

Base URL：https://paddleocr.aistudio-app.com/

提交解析任务

Path: /api/v2/ocr/jobs

Method: POST

Header:

Authorization: Bearer {access_token}
Content-Type: application/json（传入文件链接时设置，示例代码中已自动适配）
Content-Type: multipart/form-data（上传文件时设置，示例代码中已自动适配）
Accept-Encoding: gzip, deflate, br
请求参数说明
参数	类型	是否必填	示例	描述
file	bytes	是（与 fileUrl 二选一）		二进制文件数据
fileUrl	string	是（与 file 二选一）		文件链接
model	string	是	PP-OCRv5
PP-StructureV3
PaddleOCR-VL
PaddleOCR-VL-1.5	OCR 模型名
optionalPayload	object	否	{"useDocOrientationClassify": false}	解析参数，不同模型类型不同，参考：
PP-OCRV5：文档
PP-StructureV3：文档
PaddleOCR-VL：文档
PaddleOCR-VL-1.5：文档
pageRanges	string	否	"2,4-6"：第2页，第4到第6页
"2--2"：第2页到倒数第2页	指定解析的页码范围
batchId	string	否	可唯一标识的字符串	批量ID，用于批量查询任务
响应参数说明
参数	类型	示例	说明
traceId	string	0b1eb3150f5bec03dab9e74b4264c615	请求 ID
code	int	10002	接口状态码，成功为 0，失败详情参考“错误码说明”
msg	string	文件 URL 无法识别	接口响应信息，失败详情参考“错误码说明”
data	object		
data.jobId	string	ocrjob-f4377241b695	任务 ID
获取解析结果

Path: /api/v2/ocr/jobs/{jobId}

Method: GET

Header:

Authorization: Bearer {access_token}
Content-Type: application/json
响应参数说明
参数	类型	示例	说明
traceId	string	0b1eb3150f5bec03dab9e74b4264c615	请求 ID
code	int	0	接口状态码，成功：0
msg	string	Success	接口处理信息，成功："Success"
data	object		
data.jobId	string	ocrjob-f4377241b695	任务 ID
data.state	string	done	任务处理状态
* done：完成
* pending：排队中
* running：正在解析中
* failed：解析失败（不存在部分页成功的情况）
data.errorMsg	string	文件格式不支持，请上传符合要求的文件类型	解析失败原因 state=failed 时该值有效
data.resultUrl	object	提供 BOS 短链
{ "jsonUrl": "https://***.com", "markdownUrl": "https://***.com"}	文档解析结果 state=done 时该值有效
data.extractProgress	object		文档解析进度 state=running 时该值有效
data.extractProgress.startTime	string	2026-01-01T12:00:00+08:00	文档解析开始时间
data.extractProgress.endTime	string	2026-01-01T12:00:00+08:00	文档解析结束时间
data.extractProgress.totalPages	string	10	文档总页数
data.extractProgress.extractedPages	string	1	文档已解析页数
批量获取任务结果

Path: /api/v2/ocr/jobs/batch/{batchId}

Method: GET

Header:

Authorization: Bearer {access_token}
Content-Type: application/json
Accept-Encoding: gzip, deflate, br

响应参数说明

参数	类型	示例	说明
traceId	string	0b1eb3150f5bec03dab9e74b4264c615	请求 ID
code	int	0	接口状态码，成功：0
msg	string	Success	接口处理信息，成功："Success"
data	object		
data.batchId	string	batchid-202601210000	批量任务 ID，用户自定义传入，形式自订。
data.extractResult	array		推理结果列表
data.extractResult.jobId	string	ocrjob-f4377241b695	任务 ID
data.extractResult.state	string	done	任务处理状态
* done：完成
* pending：排队中
* running：正在解析中
* failed：解析失败（不存在部分页成功的情况）
data.extractResult.errorMsg	string	文件格式不支持，请上传符合要求的文件类型	解析失败原因 state=failed 时该值有效
data.extractResult.resultUrl	object	提供 BOS 短链
{ "jsonUrl": "https://***.com", "markdownUrl": "https://***.com"}	文档解析结果 state=done 时该值有效
data.extractResult.extractProgress	object		文档解析进度 state=running 时该值有效
data.extractResult.extractProgress.startTime	string	2026-01-01T12:00:00+08:00	文档解析开始时间
data.extractResult.extractProgress.endTime	string	2026-01-01T12:00:00+08:00	文档解析结束时间
data.extractResult.extractProgress.totalPages	int	10	文档总页数
data.extractResult.extractProgress.extractedPages	int	1	文档已解析页数
错误码
错误码	错误码说明	解决建议
401	Token 无效	检查token，从链接中获取token：链接
500	系统错误	请联系官方，或稍后重试
10001	空文件（http status 对应为 400）	请检查文件
10002	文件 URL 无法识别（http status 对应为 400）	请检查URL
10003	文件大小超出限制（http status 对应为 400）	请检查文件
10004	文件格式不支持（http status 对应为 400）	请检查文件
10005	文件内容无法解析（http status 对应为 400）	请检查文件
10006	文件页数超过限制（http status 对应为 400）	请检查文件
10007	模型参数错误（http status 对应为 400）	模型不存在，请检查模型名
10008	请求参数错误（http status 对应为 400）	optionalPayload或extraFormats参数错误，请根据data.errorMsg提示修正
10009	同一 batchId 的任务仅允许创建 100 条（http status 对应为 400）	请更换batchId
10010	任务提交队列已满	请稍后重试
11001	jobId 不存在（http status 对应为 404）	请检查jobId
11002	job 已过期（http status 对应为 400）	请更换JobId
11003	job 解析失败（http status 对应为 200）	解析失败，具体原因见：data.errorMsg
12001	已达每日页数上限（http status 对应为 403）	超过上每日限额，如需提升请参看配额说明
12002	请求频率过高（http status 对应为 429）	请稍后重试
```
要点：
- Base URL：https://paddleocr.aistudio-app.com/ 。提交 POST /api/v2/ocr/jobs；查询（取结果）GET /api/v2/ocr/jobs/{jobId}；批量查询 GET /api/v2/ocr/jobs/batch/{batchId}。「取结果」没有单独端点：状态为 done 时 data.resultUrl.jsonUrl / markdownUrl 为下载短链，再 GET 该链接。
- 鉴权：Header `Authorization: Bearer {access_token}`（示例代码写作 `f"bearer {TOKEN}"`）。Token 获取位置：错误码表 401 行写“从链接中获取token：链接”，页面文本未给出具体 URL；同步页写“请访问 PaddleOCR 官网 https://aistudio.baidu.com/paddleocr/task 在 API 调用示例中获取”。
- model 取值（该页示例列）：PP-OCRv5、PP-StructureV3、PaddleOCR-VL、PaddleOCR-VL-1.5。**异步文档未列 PaddleOCR-VL-1.6**（首页 https://aistudio.baidu.com/paddleocr 已显示 “PaddleOCR-VL-1.6”“PP-OCRv6” 并写 “Announcing the Launch of PP-OCRv6 & PaddleOCR-VL-1.6”）；VL-1.6 在异步 API 的 model 字符串：文档未写明。
- 其他请求字段：pageRanges（"2,4-6"；"2--2" 表示第2页到倒数第2页）、batchId。示例还出现 extraFormats（仅见于 10008 错误码说明），其用法：文档未写明。
- optionalPayload：“解析参数，不同模型类型不同”，指向各模型同步页的请求参数表（见第 8 节）。异步页本身不列默认值。

## 2. 限制与配额
### 2.1 异步页（https://ai.baidu.com/ai-doc/AISTUDIO/fml7mozw5，更新 2026-02-04）原文
- 单次请求最大支持 1000 页 pdf
- 支持传入文件链接。文件大小不能超过 200 MB
- 支持上传本地文件。文件大小不能超过 50 MB
- 错误码 10006：文件页数超过限制（http status 对应为 400）；10003：文件大小超出限制。是否对超 1000 页直接报 10006 还是截断：该页未写明（与配额页“仅解析前 1000 页”表述存在张力，需实测）。

### 2.2 配额页（中文，https://ai.baidu.com/ai-doc/AISTUDIO/Xmjclapam，更新 2026-09-08）原文
- 总量限制：每个用户针对每个模型，每日可解析的页面总数上限为 20000 页。
- 超额反馈：当当日解析量超过 20000 页时，后续请求将无法处理，系统会返回 429 (Too Many Requests) 错误码。
- 页数建议：为避免处理时间过长导致网关超时，建议单个文件的页数 不超过 1000 页。
- 超页处理：如果上传的文件超过 1000 页，API 将仅解析前 1000 页的内容，后续页面将被忽略。
- 如果您有更高的页面解析需求，请填写 问卷 免费申请提升配额。

### 2.3 配额页（英文，https://ai.baidu.com/ai-doc/AISTUDIO/pmjcld5qm，更新 2026-02-10，旧版）原文
- Total Limit: Each user can parse up to 3,000 pages per model per day.
- Page Suggestion: To avoid gateway timeout due to long processing times, it is recommended that a single file does not exceed 100 pages.
- Over-page Handling: If the uploaded file exceeds 100 pages, the API will only parse the first 100 pages; subsequent pages will be ignored.
（英文页比中文页旧：3000 页/日、100 页 → 中文新版 20000 页/日、1000 页。用户已知引文“每次单个文件大小无限制，但为避免处理超时请控制在100页内，超出部分将被忽略不解析”与此英文旧版语义一致，但逐字原文在我读到的所有官方文档页中未出现；很可能来自需登录的 https://aistudio.baidu.com/paddleocr/task 页面或旧版文档，已不是最新口径。）

### 2.4 同步接口页数默认值（各页 file 参数行原文）
- PaddleOCR-VL-1.5_API（https://ai.baidu.com/ai-doc/AISTUDIO/Cmkz2m0ma）：「默认对于超过100页的PDF文件，只有前100页的内容会被处理。要解除页数限制，请在产线配置文件中添加以下配置：Serving: extra: max_num_input_imgs: null」
- PaddleOCR-VL_API（https://ai.baidu.com/ai-doc/AISTUDIO/2mh4okm66）：「默认对于超过10页的PDF文件，只有前10页的内容会被处理。」同上解除方法。
- PP-OCRv5_API（https://ai.baidu.com/ai-doc/AISTUDIO/Kmfl2ycs0）：「默认对于超过10页的PDF文件，只有前10页的内容会被处理。」
- PP-StructureV3_API（https://ai.baidu.com/ai-doc/AISTUDIO/Fmfz6oh2e）：「默认对于超过10页的PDF文件，只有前10页的内容会被处理。」
（“产线配置文件”是自部署 PaddleX 服务的配置，云端用户无法修改；云端同步接口实际是否沿用该默认值：文档未写明。）

### 2.5 网站首页（https://aistudio.baidu.com/paddleocr，网页上传 UI）原文
- 「Single file ≤ 200MB/1000 pages · Single image ≤ 10MB」
- 「Unregistered users can enjoy 3 free trials per day, while registered users can use it unlimited times!」
- 首页另有 PaddleOCR-VL-1.5 弹窗，无限额信息。

### 2.6 未写明项
- 并发 / QPS 限制：文档未写明数值；仅有错误码 12002「请求频率过高（http status 对应为 429）请稍后重试」、10010「任务提交队列已满」。
- 任务超时：文档未写明（仅 504 网关超时、建议控制页数）。
- 结果保存期限：文档未写明具体时长；11002「job 已过期」，resultUrl 为 “BOS 短链”，有效期未写。
- 计费：配额页与异步页均未出现价格；首页称注册用户“无限次”，配额页给 20000 页/模型/日。付费：文档未写明。

## 3. 任务状态值与失败字段（来源 https://ai.baidu.com/ai-doc/AISTUDIO/fml7mozw5）
- data.state：done（完成）、pending（排队中）、running（正在解析中）、failed（解析失败，**原文：“不存在部分页成功的情况”**）。共 4 个值，页面未列其他值（如 canceled）。
- data.errorMsg：解析失败原因，state=failed 时有效（示例“文件格式不支持，请上传符合要求的文件类型”）。
- 顶层 code / msg / traceId：成功 code=0，msg="Success"。11003「job 解析失败（http status 对应为 200）」：即 failed 任务 HTTP 仍为 200，必须读 data.state 与 data.errorMsg。

## 4. 错误码表
异步错误码（https://ai.baidu.com/ai-doc/AISTUDIO/fml7mozw5 原文）：
| 码 | 说明 | 建议 |
|---|---|---|
| 401 | Token 无效 | 检查token，从链接中获取token：链接 |
| 500 | 系统错误 | 请联系官方，或稍后重试 |
| 10001 | 空文件（http status 对应为 400） | 请检查文件 |
| 10002 | 文件 URL 无法识别（400） | 请检查URL |
| 10003 | 文件大小超出限制（400） | 请检查文件 |
| 10004 | 文件格式不支持（400） | 请检查文件 |
| 10005 | 文件内容无法解析（400） | 请检查文件 |
| 10006 | 文件页数超过限制（400） | 请检查文件 |
| 10007 | 模型参数错误（400） | 模型不存在，请检查模型名 |
| 10008 | 请求参数错误（400） | optionalPayload或extraFormats参数错误，请根据data.errorMsg提示修正 |
| 10009 | 同一 batchId 的任务仅允许创建 100 条（400） | 请更换batchId |
| 10010 | 任务提交队列已满 | 请稍后重试 |
| 11001 | jobId 不存在（404） | 请检查jobId |
| 11002 | job 已过期（400） | 请更换JobId |
| 11003 | job 解析失败（200） | 解析失败，具体原因见：data.errorMsg |
| 12001 | 已达每日页数上限（403） | 超过上每日限额，如需提升请参看配额说明 |
| 12002 | 请求频率过高（429） | 请稍后重试 |

HTTP 层错误码（配额页 https://ai.baidu.com/ai-doc/AISTUDIO/Xmjclapam 原文）：
| 码 | 说明 | 建议 |
|---|---|---|
| 403 | Token 错误 | 检查 Token 是否正确，或 URL 是否与 Token 匹配 |
| 413 | 请求体过大 | 请减少 PDF 文件的页数或文件大小 |
| 422 | 参数无效 | 请参考 errorMsg 进行解决 |
| 429 | 超出单日解析最大页数 | 请使用其他模型或稍后再试 |
| 500 | 服务器内部错误 | 如果频繁遇到 500 问题，请联系 PaddleOCR 官方人员 |
| 503 | 当前请求过多 | 请稍后再试 |
| 504 | 网关超时 | 请稍后再试 |
（异步页 12001 写 403，配额页写 429，两处对“日额度用尽”的状态码不一致，需实测。）

## 5. 结果格式与页数校验（最关键）
来源 https://ai.baidu.com/ai-doc/AISTUDIO/fml7mozw5，原文字段：
- data.resultUrl：「提供 BOS 短链 { "jsonUrl": "https://***.com", "markdownUrl": "https://***.com"}，文档解析结果 state=done 时该值有效」
- data.extractProgress（「文档解析进度 state=running 时该值有效」）：
  - startTime（例 2026-01-01T12:00:00+08:00）、endTime
  - totalPages「文档总页数」（单任务查询表类型写 string 示例"10"；批量表写 int）
  - extractedPages「文档已解析页数」（同上 string / int）
- 示例代码在 state=done 时也读取 extractProgress.extractedPages / startTime / endTime，打印“Job completed, successfully extracted pages: …”。即 **结果中有页数字段**：running 时有 totalPages 与 extractedPages；done 时示例代码读 extractedPages（表格说明写“state=running 时有效”，但代码在 done 读取，两处表述略有出入，建议实测 done 时 totalPages 是否存在）。
- 校验“是否全部页都解析”：可比较 done 时 extractProgress.extractedPages 与自己已知的 PDF 页数；同时 JSONL 逐行 result.layoutParsingResults 数组长度之和（示例代码按此累加 page_num）也等于实际处理页数。同步页原文：「layoutParsingResults … 数组长度为1（对于图像输入）或实际处理的文档页数（对于PDF输入）。对于PDF输入，数组中的每个元素依次表示PDF文件中实际处理的每一页的结果。」
- 超页被忽略时是否有显式标志（如 truncated 字段）：文档未写明。因此必须自行核对页数。
- JSONL 每行结构：文档无专门字段表；由示例代码可知，每行是一个 JSON，含 `result`；PaddleOCR-VL/PP-StructureV3 的 result 含 `layoutParsingResults` 数组，每元素含 `markdown.text`、`markdown.images`（相对路径 → 图片 URL）、`outputImages`（名 → URL）；PP-OCRv5 的 result 含 `ocrResults` 数组，每元素含 `ocrImage`（URL）。一行 = 一个分块（通常多页），而非必然一页，故按 layoutParsingResults 累加页数，不要按行数。（“一行对应几页”文档未写明，此为由代码结构得出的推断。）
- 同步页 layoutParsingResults 元素字段（VL/SV3 页）：prunedResult、markdown{text, images, isStart, isEnd}、outputImages、inputImage；响应顶层 logId、errorCode（成功固定 0）、errorMsg（成功固定 "Success"）、result{layoutParsingResults, dataInfo}。

## 6. 各模型差异与用途（各页原文摘录）
- PaddleOCR-VL-1.5（https://ai.baidu.com/ai-doc/AISTUDIO/Cmkz2m0ma）：「2026年1月29日，我们在PaddleOCR-VL的基础上发布了PaddleOCR-VL-1.5。PaddleOCR-VL-1.5不仅以94.5%精度大幅刷新了评测集OmniDocBench v1.5，更创新性地支持了异形框定位，使得PaddleOCR-VL-1.5 在扫描、倾斜、弯折、屏幕拍摄及复杂光照等真实场景中均表现优异。此外，模型还新增了印章识别与文本检测识别能力」
- PaddleOCR-VL-1.6（同页）：「在文档解析基准 OmniDocBench v1.6 上取得 96.33% 的最新 SOTA … 强化多元素识别能力：… 进一步大幅度增强了对复杂表格，古籍 和 生僻字的识别能力 … 0.9B紧凑架构：沿用 PaddleOCR-VL系列的 0.9B 紧凑构架，零成本适配，即换即用。」
- PaddleOCR-VL（https://ai.baidu.com/ai-doc/AISTUDIO/2mh4okm66）：「PaddleOCR-VL-0.9B …（NaViT 风格动态分辨率视觉编码器 + ERNIE-4.5-0.3B）… 支持 109 种语言，并在识别复杂元素（如文本、表格、公式和图表）方面表现出色」
- PP-StructureV3（https://ai.baidu.com/ai-doc/AISTUDIO/Fmfz6oh2e）：多子产线可开关（印章、表格、公式、图表、区域检测等，见第 8.3 节参数），输出版面解析 layoutParsingResults + Markdown。
- PP-OCRv5（https://ai.baidu.com/ai-doc/AISTUDIO/Kmfl2ycs0）：纯文字检测识别，输出 ocrResults（无 Markdown/版面）；参数见 8.2。
- 官方“推荐用途”的专门文字：文档未写明；上为各页简介。

## 7. 官方示例代码（Python，原样）
### 7.1 异步，PaddleOCR-VL-1.5 / PaddleOCR-VL / PP-StructureV3（https://ai.baidu.com/ai-doc/AISTUDIO/fml7mozw5）
```python
# Please make sure the requests library is installed
# pip install requests
import json
import os
import requests
import sys
import time

JOB_URL = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
TOKEN = ""
# 可选模型: "PaddleOCR-VL-1.5", "PaddleOCR-VL", "PP-StructureV3"
MODEL = "PaddleOCR-VL-1.5"

file_path = "<local file path or file url>"

headers = {
    "Authorization": f"bearer {TOKEN}",
}

optional_payload = {
    "useDocOrientationClassify": False,
    "useDocUnwarping": False,
    "useChartRecognition": False,
}

print(f"Processing file: {file_path}")

if file_path.startswith("http"):
    # URL Mode
    headers["Content-Type"] = "application/json"
    payload = {
        "fileUrl": file_path,
        "model": MODEL,
        "optionalPayload": optional_payload
    }
    job_response = requests.post(JOB_URL, json=payload, headers=headers)
else:
    # Local File Mode
    if not os.path.exists(file_path):
        print(f"Error: File not found at {file_path}")
        sys.exit(1)
        
    data = {
        "model": MODEL,
        "optionalPayload": json.dumps(optional_payload)
    }
    
    with open(file_path, "rb") as f:
        files = {"file": f}
        job_response = requests.post(JOB_URL, headers=headers, data=data, files=files)

print(f"Response status: {job_response.status_code}")
if job_response.status_code != 200:
    print(f"Response content: {job_response.text}")

assert job_response.status_code == 200
jobId = job_response.json()["data"]["jobId"]
print(f"Job submitted successfully. job id: {jobId}")
print("Start polling for results")

jsonl_url = ""
while True:
    job_result_response = requests.get(f"{JOB_URL}/{jobId}", headers=headers)
    assert job_result_response.status_code == 200
    state = job_result_response.json()["data"]["state"]
    if state == 'pending':
        print("The current status of the job is pending")
    elif state == 'running':
        try:
            total_pages = job_result_response.json()['data']['extractProgress']['totalPages']
            extracted_pages = job_result_response.json()['data']['extractProgress']['extractedPages']
            print(f"The current status of the job is running, total pages: {total_pages}, extracted pages: {extracted_pages}")
        except KeyError:
             print("The current status of the job is running...")
    elif state == 'done':
        extracted_pages = job_result_response.json()['data']['extractProgress']['extractedPages']
        start_time = job_result_response.json()['data']['extractProgress']['startTime']
        end_time = job_result_response.json()['data']['extractProgress']['endTime']
        print(f"Job completed, successfully extracted pages: {extracted_pages}, start time: {start_time}, end time: {end_time}")
        jsonl_url = job_result_response.json()['data']['resultUrl']['jsonUrl']
        break
    elif state == "failed":
        error_msg = job_result_response.json()['data']['errorMsg']
        print(f"Job failed, failure reason：{error_msg}")
        sys.exit()

    time.sleep(5)

if jsonl_url:
    jsonl_response = requests.get(jsonl_url)
    jsonl_response.raise_for_status()
    lines = jsonl_response.text.strip().split('\n')
    output_dir = "output"
    os.makedirs(output_dir, exist_ok=True)
    page_num = 0
    for line_num, line in enumerate(lines, start=1):
        line = line.strip()
        if not line:
            continue
        result = json.loads(line)["result"]
        # 注意：此处使用的是 layoutParsingResults 字段
        for i, res in enumerate(result["layoutParsingResults"]):
            md_filename = os.path.join(output_dir, f"doc_{page_num}.md")
            with open(md_filename, "w", encoding="utf-8") as md_file:
                md_file.write(res["markdown"]["text"])
            print(f"Markdown document saved at {md_filename}")
            for img_path, img in res["markdown"]["images"].items():
                full_img_path = os.path.join(output_dir, img_path)
                os.makedirs(os.path.dirname(full_img_path), exist_ok=True)
                img_bytes = requests.get(img).content
                with open(full_img_path, "wb") as img_file:
                    img_file.write(img_bytes)
                print(f"Image saved to: {full_img_path}")
            for img_name, img in res["outputImages"].items():
                img_response = requests.get(img)
                if img_response.status_code == 200:
                    # Save image to local
                    filename = os.path.join(output_dir, f"{img_name}_{page_num}.jpg")
                    with open(filename, "wb") as f:
                        f.write(img_response.content)
                    print(f"Image saved to: {filename}")
                else:
                    print(f"Failed to download image, status code: {img_response.status_code}")
            page_num += 1
2. PP-OCRv5 调用示例

```
### 7.2 异步，PP-OCRv5（同页）
```python
# Please make sure the requests library is installed
# pip install requests
import json
import os
import requests
import sys
import time

JOB_URL = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
TOKEN = ""
MODEL = "PP-OCRv5"

file_path = "<local file path or file url>"

headers = {
    "Authorization": f"bearer {TOKEN}",
}

optional_payload = {
    "useDocOrientationClassify": False,
    "useDocUnwarping": False,
    "useTextlineOrientation": False,
}

print(f"Processing file: {file_path}")

if file_path.startswith("http"):
    # URL Mode
    headers["Content-Type"] = "application/json"
    payload = {
        "fileUrl": file_path,
        "model": MODEL,
        "optionalPayload": optional_payload
    }
    job_response = requests.post(JOB_URL, json=payload, headers=headers)
else:
    # Local File Mode
    if not os.path.exists(file_path):
        print(f"Error: File not found at {file_path}")
        sys.exit(1)
        
    data = {
        "model": MODEL,
        "optionalPayload": json.dumps(optional_payload)
    }
    
    with open(file_path, "rb") as f:
        files = {"file": f}
        job_response = requests.post(JOB_URL, headers=headers, data=data, files=files)

print(f"Response status: {job_response.status_code}")

if job_response.status_code != 200:
    print(f"Response content: {job_response.text}")

assert job_response.status_code == 200
jobId = job_response.json()["data"]["jobId"]
print(f"Job submitted successfully. job id: {jobId}")
print("Start polling for results")

jsonl_url = ""
while True:
    job_result_response = requests.get(f"{JOB_URL}/{jobId}", headers=headers)
    assert job_result_response.status_code == 200
    state = job_result_response.json()["data"]["state"]
    if state == 'pending':
        print("The current status of the job is pending")
    elif state == 'running':
        try:
            total_pages = job_result_response.json()['data']['extractProgress']['totalPages']
            extracted_pages = job_result_response.json()['data']['extractProgress']['extractedPages']
            print(f"The current status of the job is running, total pages: {total_pages}, extracted pages: {extracted_pages}")
        except KeyError:
             print("The current status of the job is running...")
    elif state == 'done':
        extracted_pages = job_result_response.json()['data']['extractProgress']['extractedPages']
        start_time = job_result_response.json()['data']['extractProgress']['startTime']
        end_time = job_result_response.json()['data']['extractProgress']['endTime']
        print(f"Job completed, successfully extracted pages: {extracted_pages}, start time: {start_time}, end time: {end_time}")
        jsonl_url = job_result_response.json()['data']['resultUrl']['jsonUrl']
        break
    elif state == "failed":
        error_msg = job_result_response.json()['data']['errorMsg']
        print(f"Job failed, failure reason：{error_msg}")
        sys.exit()

    time.sleep(5)

if jsonl_url:
    jsonl_response = requests.get(jsonl_url)
    jsonl_response.raise_for_status()
    lines = jsonl_response.text.strip().split('\n')
    output_dir = "output"
    os.makedirs(output_dir, exist_ok=True)
    page_num = 0
    for line_num, line in enumerate(lines, start=1):
        line = line.strip()
        if not line:
            continue
        result = json.loads(line)["result"]
        # 注意：PP-OCRv5 使用 ocrResults 字段
        for i, res in enumerate(result["ocrResults"]):
            image_url = res["ocrImage"]
            img_response = requests.get(image_url)
            if img_response.status_code == 200:
                # Save image to local
                filename = f"output/img_output_{page_num}.jpg"
                with open(filename, "wb") as f:
                    f.write(img_response.content)
                print(f"Image saved to: {filename}")
            else:
                print(f"Failed to download image, status code: {img_response.status_code}")
            page_num += 1
```
### 7.3 同步，PaddleOCR-VL-1.5（https://ai.baidu.com/ai-doc/AISTUDIO/Cmkz2m0ma）
```python
# Please make sure the requests library is installed
# pip install requests
import base64
import os
import requests

# API_URL 及 TOKEN 请访问 [PaddleOCR 官网](https://aistudio.baidu.com/paddleocr/task) 在 API 调用示例中获取。
API_URL = "<your url>"
TOKEN = "<access token>"

file_path = "<local file path>"

with open(file_path, "rb") as file:
    file_bytes = file.read()
    file_data = base64.b64encode(file_bytes).decode("ascii")

headers = {
    "Authorization": f"token {TOKEN}",
    "Content-Type": "application/json"
}

required_payload = {
    "file": file_data,
    "fileType": <file type>,  # For PDF documents, set `fileType` to 0; for images, set `fileType` to 1
}

optional_payload = {
    "useDocOrientationClassify": False,
    "useDocUnwarping": False,
    "useChartRecognition": False,
}

payload = {**required_payload, **optional_payload}

response = requests.post(API_URL, json=payload, headers=headers)
print(response.status_code)
assert response.status_code == 200
result = response.json()["result"]

output_dir = "output"
os.makedirs(output_dir, exist_ok=True)

for i, res in enumerate(result["layoutParsingResults"]):
    md_filename = os.path.join(output_dir, f"doc_{i}.md")
    with open(md_filename, "w", encoding="utf-8") as md_file:
        md_file.write(res["markdown"]["text"])
    print(f"Markdown document saved at {md_filename}")
    for img_path, img in res["markdown"]["images"].items():
        full_img_path = os.path.join(output_dir, img_path)
        os.makedirs(os.path.dirname(full_img_path), exist_ok=True)
        img_bytes = requests.get(img).content
        with open(full_img_path, "wb") as img_file:
            img_file.write(img_bytes)
        print(f"Image saved to: {full_img_path}")
    for img_name, img in res["outputImages"].items():
        img_response = requests.get(img)
        if img_response.status_code == 200:
            # Save image to local
            filename = os.path.join(output_dir, f"{img_name}_{i}.jpg")
            with open(filename, "wb") as f:
                f.write(img_response.content)
            print(f"Image saved to: {filename}")
        else:
            print(f"Failed to download image, status code: {img_response.status_code}")

```

## 8. optionalPayload / 同步请求参数表（原样，制表符分隔：名称 参数 类型 含义 是否必填）
说明：异步 optionalPayload 指向这些页的参数（官方原话“不同模型类型不同，参考：…文档”）；其中 file、fileType 为同步专用，异步用 file/fileUrl + model。默认值以各条含义中“默认初始化为…”为准，未写默认值的为“文档未写明”。
### 8.1 PaddleOCR-VL-1.5（https://ai.baidu.com/ai-doc/AISTUDIO/Cmkz2m0ma）
```
输入文件	file	string	服务器可访问的图像文件或PDF文件的URL，或上述类型文件内容的Base64编码结果。默认对于超过100页的PDF文件，只有前100页的内容会被处理。
要解除页数限制，请在产线配置文件中添加以下配置：
Serving:
  extra:
    max_num_input_imgs: null

	是
文件类型	fileType	integer｜null	文件类型。0表示PDF文件，1表示图像文件。若请求体无此属性，则将根据URL推断文件类型。	否
图片方向矫正	useDocOrientationClassify	boolean | null	是否在推理时使用文本图像方向矫正模块，开启后，可以自动识别并矫正 0°、90°、180°、270°的图片。	否
图片扭曲矫正	useDocUnwarping	boolean | null	是否在推理时使用文本图像矫正模块，开启后，可以自动矫正扭曲图片，例如褶皱、倾斜等情况。	否
版面分析	useLayoutDetection	boolean | null	是否在推理时使用版面区域检测排序模块，开启后，可以自动检测文档中不同区域并排序。	否
图表识别	useChartRecognition	boolean | null	是否在推理时使用图表解析模块，开启后，可以自动解析文档中的图表（如柱状图、饼图等）并转换为表格形式，方便查看和编辑数据。	否
版面区域过滤强度	layoutThreshold	number | object | null	版面模型得分阈值。0-1 之间的任意浮点数。如果不设置，将使用产线初始化的该参数值，默认初始化为 0.5。	否
NMS后处理	layoutNms	boolean | null	版面检测是否使用后处理NMS，开启后，会自动移除重复或高度重叠的区域框。	否
扩张系数	layoutUnclipRatio	number | array | object | null	版面区域检测模型检测框的扩张系数。 任意大于 0 浮点数。如果不设置，将使用产线初始化的该参数值，默认初始化为 1.0。	否
版面区域检测的重叠框过滤方式	layoutMergeBboxesMode	string | object | null	
large，设置为large时，表示在模型输出的检测框中，对于互相重叠包含的检测框，只保留外部最大的框，删除重叠的内部框；
small，设置为small，表示在模型输出的检测框中，对于互相重叠包含的检测框，只保留内部被包含的小框，删除重叠的外部框；
union，不进行框的过滤处理，内外框都保留；
如果不设置，将使用产线初始化的该参数值，默认初始化为large。	否
版面检测结果的几何形状	layoutShapeMode	string | null	用于指定版面检测结果的几何形状表示模式，该参数决定了检测区域（如文本块、图片、表格等）边界的计算方式及展示形态。可填写参数为 rect (矩形)、quad (四边形)、poly (多边形) 和 auto (自动)，默认初始化为auto。	否
prompt类型设置	promptLabel	string | null	VL模型的 prompt 类型设置，当且仅当 useLayoutDetection=False 时生效。可填写参数为 ocr、formula、table 和 chart，默认初始化为ocr。	否
重复抑制强度	repetitionPenalty	number | null	结果中出现重复文字、重复表格内容时，可适当调高。	否
识别稳定性	temperature	number | null	结果不稳定或出现明显幻觉时调低，漏识别或者重复较多时可略微调高。	否
结果可信范围	topP	number | null	结果发散、不够可信时可适当调低，让模型更保守。	否
最小图像尺寸	minPixels	number | null	输入图片太小、文字看不清时可适当调高，一般无需调整。	否
最大图像尺寸	maxPixels	number | null	输入图片特别大、处理变慢或显存压力较大时可适当调低。	否
公式编号展示	showFormulaNumber	boolean	输出的 Markdown 文本中是否包含公式编号。	否
重构多页结果	restructurePages	boolean	对多页 pdf 解析结果进行重构，用于适配跨页表格合并和段落标题级别识别，默认初始化为False。	否
跨页表格合并	mergeTables	boolean	开启后，会识别跨页表格，将其合并为一个，当且仅当 useLayoutDetection=False 时生效，默认初始化为True。	否
段落标题级别识别	relevelTitles	boolean	开启后，会识别段落标题级别，当且仅当 useLayoutDetection=False 时生效，默认初始化为True。	否
Markdown 美化	prettifyMarkdown	boolean	是否输出美化后的 Markdown 文本。	否
可视化	visualize	boolean | null	支持返回可视化结果图及处理过程中的中间图像。开启此功能后，将增加结果返回时间。
传入 true：返回图像。
传入 false：不返回图像。
若请求体中未提供该参数或传入 null：遵循产线配置文件Serving.visualize 的设置。

例如，在产线配置文件中添加如下字段：

Serving:
  visualize: False

将默认不返回图像，通过请求体中的visualize参数可以覆盖默认行为。如果请求体和配置文件中均未设置（或请求体传入null、配置文件中未设置），则默认返回图像。	否
```
### 8.2 PP-OCRv5（https://ai.baidu.com/ai-doc/AISTUDIO/Kmfl2ycs0）
```
输入文件	file	string	服务器可访问的图像文件或PDF文件的URL，或上述类型文件内容的Base64编码结果。默认对于超过10页的PDF文件，只有前10页的内容会被处理。
要解除页数限制，请在产线配置文件中添加以下配置：
Serving:
  extra:
    max_num_input_imgs: null

	是
文件类型	fileType	integer | null	文件类型。0表示PDF文件，1表示图像文件。若请求体无此属性，则将根据URL推断文件类型。	否
图片方向矫正	useDocOrientationClassify	boolean | null	是否在推理时使用文档方向分类模块，开启后，可以自动识别并矫正 0°、90°、180°、270°的图片，默认初始化为 False。	否
图片扭曲矫正	useDocUnwarping	boolean | null	是否在推理时使用文本图像矫正模块，开启后，可以自动矫正扭曲图片，例如褶皱、倾斜等情况，默认初始化为 False。	否
文本行方向矫正	useTextlineOrientation	boolean | null	是否在推理时使用文本行方向分类模块，开启后，可以自动识别和矫正 0° 和 180° 的文本行，默认初始化为 False。	否
图像边长限制	textDetLimitSideLen	integer | null	文本检测的图像边长限制。 大于0 的任意整数。如果不设置，将使用产线初始化的该参数值，默认初始化为 64。	否
图像边长限制类型	textDetLimitType	string | null	文本检测的边长度限制类型。支持 min 和 max，min 表示保证图像最短边不小于 textDetLimitSideLen，max 表示保证图像最长边不大于 textDetLimitSideLen。如果不设置，将使用产线初始化的该参数值，默认初始化为 min。	否
文本检测像素阈值	textDetThresh	number | null	文本检测像素阈值，输出的概率图中，得分大于该阈值的像素点才会被认为是文字像素点。 大于 0 的任意浮点数。如果不设置，将使用产线初始化的该参数值（默认为 0.3）。	否
文本检测框阈值	textDetBoxThresh	number | null	文本检测框阈值，检测结果边框内，所有像素点的平均得分大于该阈值时，该结果会被认为是文字区域。 大于 0 的任意浮点数。如果不设置，将使用产线初始化的该参数值（默认为 0.6）。	否
扩张系数	textDetUnclipRatio	number | null	文本检测扩张系数，使用该方法对文字区域进行扩张，该值越大，扩张的面积越大。大于 0 的任意浮点数。如果不设置，将使用产线初始化的该参数值（默认为 1.5）。	否
文本识别阈值	textRecScoreThresh	number | null	文本识别阈值，得分大于该阈值的文本结果会被保留。 大于 0 的任意浮点数。如果不设置，将使用产线初始化的该参数值（默认为 0.0，即不设阈值）。	否
可视化	visualize	boolean | null	支持返回可视化结果图及处理过程中的中间图像。开启此功能后，将增加结果返回时间。
传入 true：返回图像。
传入 false：不返回图像。
若请求体中未提供该参数或传入 null：遵循产线配置文件Serving.visualize 的设置。

例如，在产线配置文件中添加如下字段：

Serving:
  visualize: False

将默认不返回图像，通过请求体中的visualize参数可以覆盖默认行为。如果请求体和配置文件中均未设置（或请求体传入null、配置文件中未设置），则默认返回图像。	否
```
### 8.3 PP-StructureV3（https://ai.baidu.com/ai-doc/AISTUDIO/Fmfz6oh2e）
```
输入文件	file	string	服务器可访问的图像文件或PDF文件的URL，或上述类型文件内容的Base64编码结果。默认对于超过10页的PDF文件，只有前10页的内容会被处理。
要解除页数限制，请在产线配置文件中添加以下配置：
Serving:
  extra:
    max_num_input_imgs: null

	是
文件类型	fileType	integer｜null	文件类型。0表示PDF文件，1表示图像文件。若请求体无此属性，则将根据URL推断文件类型。	否
图片方向矫正	useDocOrientationClassify	boolean | null	是否在推理时使用文档方向分类模块，开启后，可以自动识别并矫正 0°、90°、180°、270°的图片，默认初始化为 False。	否
图片扭曲矫正	useDocUnwarping	boolean | null	是否在推理时使用文本图像矫正模块，开启后，可以自动矫正扭曲图片，例如褶皱、倾斜等情况，默认初始化为 False。	否
文本行方向矫正	useTextlineOrientation	boolean | null	是否在推理时使用文本行方向分类模块，开启后，可以自动识别和矫正 0° 和 180° 的文本行，默认初始化为 False。	否
印章识别	useSealRecognition	boolean | null	是否在推理时使用印章文本识别子产线，开启后，可以识别文档中的印章内容，默认初始化为 False。	否
表格识别	useTableRecognition	boolean | null	是否在推理时使用表格识别子产线，开启后，可以将文档中的表格转换为HTML或Markdown的结构化格式；若不开启，表格会保留为图片形式，默认初始化为 True。	否
公式识别	useFormulaRecognition	boolean | null	是否在推理时使用公式识别子产线，开启后，可以将数学公式转换为LaTeX代码；若不开启，公式会按普通文本识别，默认初始化为 True。	否
图表转表格	useChartRecognition	boolean | null	是否在推理时使用图表解析模块，开启后，可以自动解析文档中的图表（如柱状图、饼图等）并转换为表格形式，方便查看和编辑数据，默认初始化为 False。	否
复杂版面处理	useRegionDetection	boolean | null	是否在推理时使用文档区域检测模块，开启后，可以更好地识别报纸、杂志等排版复杂的文档内容，提高识别准确性，默认初始化为 True。	否
版面区域过滤强度	layoutThreshold	number | object | null	版面模型得分阈值。0-1 之间的任意浮点数。如果不设置，将使用产线初始化的该参数值，默认初始化为 0.5。	否
NMS后处理	layoutNms	boolean | null	开启后，会自动移除重复或高度重叠的区域框	否
扩张系数	layoutUnclipRatio	number | array | object | null	版面区域检测模型检测框的扩张系数。 任意大于 0 浮点数。如果不设置，将使用产线初始化的该参数值，默认初始化为 1.0。	否
版面区域检测的重叠框过滤方式	layoutMergeBboxesMode	string | object | null	
large，设置为large时，表示在模型输出的检测框中，对于互相重叠包含的检测框，只保留外部最大的框，删除重叠的内部框；
small，设置为small，表示在模型输出的检测框中，对于互相重叠包含的检测框，只保留内部被包含的小框，删除重叠的外部框；
union，不进行框的过滤处理，内外框都保留；
如果不设置，将使用产线初始化的该参数值，默认初始化为large。	否
文本检测图像边长限制	textDetLimitSideLen	integer | null	文本检测的图像边长限制。 大于 0 的任意整数。如果不设置，将使用产线初始化的该参数值，默认初始化为 736。	否
文本检测图像边长限制类型	textDetLimitType	string | null	文本检测的边长度限制类型。支持 min 和 max，min 表示保证图像最短边不小于 textDetLimitSideLen，max 表示保证图像最长边不大于 textDetLimitSideLen。如果不设置，将使用产线初始化的该参数值，默认初始化为 min。	否
文本检测像素阈值	textDetThresh	number | null	文本检测像素阈值，输出的概率图中，得分大于该阈值的像素点才会被认为是文字像素点。 大于 0 的任意浮点数。如果不设置，将使用产线初始化的该参数值（默认为 0.3）。	否
文本检测框阈值	textDetBoxThresh	number | null	文本检测框阈值，检测结果边框内，所有像素点的平均得分大于该阈值时，该结果会被认为是文字区域。 大于 0 的任意浮点数。如果不设置，将使用产线初始化的该参数值（默认为 0.6）。	否
扩张系数	textDetUnclipRatio	number | null	文本检测扩张系数，使用该方法对文字区域进行扩张，该值越大，扩张的面积越大。大于 0 的任意浮点数。如果不设置，将使用产线初始化的该参数值（默认为 1.5）。	否
文本识别阈值	textRecScoreThresh	number | null	文本识别阈值，得分大于该阈值的文本结果会被保留。 大于 0 的任意浮点数。如果不设置，将使用产线初始化的该参数值（默认为 0.0，即不设阈值）。	否
印章检测图像边长限制	sealDetLimitSideLen	integer | null	印章文本检测的图像边长限制。 大于 0 的任意整数。如果不设置，将使用产线初始化的该参数值，默认初始化为 736。	否
印章检测图像边长限制类型	sealDetLimitType	string | null	印章文本检测的图像边长限制类型。支持 min 和 max，min 表示保证图像最短边不小于 sealDetLimitSideLen 表示保证图像最长边不大于 sealDetLimitSideLen。如果不设置，将使用产线初始化的该参数值，默认初始化为 min。	否
印章检测文本检测像素阈值	sealDetThresh	number | null	检测像素阈值。输出的概率图中，得分大于该阈值的像素点才会被认为是文字像素点。 大于 0 的任意浮点数 。如果不设置，将默认使用产线初始化的该参数值 0.2。	否
印章文本检测框阈值	sealDetBoxThresh	number | null	检测框阈值，检测结果边框内，所有像素点的平均得分大于该阈值时，该结果会被认为是文字区域。 大于 0 的任意浮点数 。如果不设置，将默认使用产线初始化的该参数值 0.6。	否
印章检测扩张系数	sealDetUnclipRatio	number | null	印章文本检测扩张系数，使用该方法对文字区域进行扩张，该值越大，扩张的面积越大。 大于 0 的任意浮点数 。如果不设置，将默认使用产线初始化的该参数值 0.5。	否
印章文本识别阈值	sealRecScoreThresh	number | null	印章文本识别阈值，得分大于该阈值的文本结果会被保留。 大于 0 的任意浮点数 。如果不设置，将默认使用产线初始化的该参数值 0.0。即不设阈值。	否
有线表转HTML	useWiredTableCellsTransToHtml	boolean	是否启用有线表单元格检测结果直转HTML，启用则直接基于有线表单元格检测结果的几何关系构建HTML。	否
无线表转HTML	useWirelessTableCellsTransToHtml	boolean	是否启用无线表单元格检测结果直转HTML，启用则直接基于无线表单元格检测结果的几何关系构建HTML。	否
表格方向矫正	useTableOrientationClassify	boolean	是否启用表格使用表格方向分类，启用时当图像中的表格存在90°、180°、270°旋转时，能够将方向校正并正确完成表格识别。	否
单元格识别模式	useOcrResultsWithTableCells	boolean	是否启用单元格切分OCR，启用时会基于单元格预测结果对OCR检测结果进行切分和重识别，避免出现文字缺失情况。	否
有线表格端到端预测	useE2eWiredTableRecModel	boolean	是否启用有线表端到端表格识别模式，启用则不使用单元格检测模型，只使用表格结构识别模型。	否
无线表格端到端预测	useE2eWirelessTableRecModel	boolean	是否启用无线表端到端表格识别模式，启用则不使用单元格检测模型，只使用表格结构识别模型。	否
可视化	visualize	boolean | null	支持返回可视化结果图及处理过程中的中间图像。开启此功能后，将增加结果返回时间。
传入 true：返回图像。
传入 false：不返回图像。
若请求体中未提供该参数或传入 null：遵循产线配置文件Serving.visualize 的设置。

例如，在产线配置文件中添加如下字段：

Serving:
  visualize: False

将默认不返回图像，通过请求体中的visualize参数可以覆盖默认行为。如果请求体和配置文件中均未设置（或请求体传入null、配置文件中未设置），则默认返回图像。	否
```
### 8.4 PaddleOCR-VL（https://ai.baidu.com/ai-doc/AISTUDIO/2mh4okm66，与 1.5 的差别：无 restructurePages/mergeTables/relevelTitles/layoutShapeMode，promptLabel 无枚举说明）
```
输入文件	file	string	服务器可访问的图像文件或PDF文件的URL，或上述类型文件内容的Base64编码结果。默认对于超过10页的PDF文件，只有前10页的内容会被处理。
要解除页数限制，请在产线配置文件中添加以下配置：
Serving:
  extra:
    max_num_input_imgs: null

	是
文件类型	fileType	integer｜null	文件类型。0表示PDF文件，1表示图像文件。若请求体无此属性，则将根据URL推断文件类型。	否
图片方向矫正	useDocOrientationClassify	boolean | null	是否在推理时使用文本图像方向矫正模块，开启后，可以自动识别并矫正 0°、90°、180°、270°的图片。	否
图片扭曲矫正	useDocUnwarping	boolean | null	是否在推理时使用文本图像矫正模块，开启后，可以自动矫正扭曲图片，例如褶皱、倾斜等情况。	否
版面分析	useLayoutDetection	boolean | null	是否在推理时使用版面区域检测排序模块，开启后，可以自动检测文档中不同区域并排序。	否
图表识别	useChartRecognition	boolean | null	是否在推理时使用图表解析模块，开启后，可以自动解析文档中的图表（如柱状图、饼图等）并转换为表格形式，方便查看和编辑数据。	否
版面区域过滤强度	layoutThreshold	number | object | null	版面模型得分阈值。0-1 之间的任意浮点数。如果不设置，将使用产线初始化的该参数值，默认初始化为 0.5。	否
NMS后处理	layoutNms	boolean | null	版面检测是否使用后处理NMS，开启后，会自动移除重复或高度重叠的区域框。	否
扩张系数	layoutUnclipRatio	number | array | object | null	版面区域检测模型检测框的扩张系数。 任意大于 0 浮点数。如果不设置，将使用产线初始化的该参数值，默认初始化为 1.0。	否
版面区域检测的重叠框过滤方式	layoutMergeBboxesMode	string | object | null	
large，设置为large时，表示在模型输出的检测框中，对于互相重叠包含的检测框，只保留外部最大的框，删除重叠的内部框；
small，设置为small，表示在模型输出的检测框中，对于互相重叠包含的检测框，只保留内部被包含的小框，删除重叠的外部框；
union，不进行框的过滤处理，内外框都保留；
如果不设置，将使用产线初始化的该参数值，默认初始化为large。	否
prompt类型设置	promptLabel	string | null	VL模型的 prompt 类型设置，当且仅当 useLayoutDetection=False 时生效。	否
重复抑制强度	repetitionPenalty	number | null	结果中出现重复文字、重复表格内容时，可适当调高。	否
识别稳定性	temperature	number | null	结果不稳定或出现明显幻觉时调低，漏识别或者重复较多时可略微调高。	否
结果可信范围	topP	number | null	结果发散、不够可信时可适当调低，让模型更保守。	否
最小图像尺寸	minPixels	number | null	输入图片太小、文字看不清时可适当调高，一般无需调整。	否
最大图像尺寸	maxPixels	number | null	输入图片特别大、处理变慢或显存压力较大时可适当调低。	否
公式编号展示	showFormulaNumber	boolean	输出的 Markdown 文本中是否包含公式编号。	否
Markdown 美化	prettifyMarkdown	boolean	是否输出美化后的 Markdown 文本。	否
可视化	visualize	boolean | null	支持返回可视化结果图及处理过程中的中间图像。开启此功能后，将增加结果返回时间。
传入 true：返回图像。
传入 false：不返回图像。
若请求体中未提供该参数或传入 null：遵循产线配置文件Serving.visualize 的设置。

例如，在产线配置文件中添加如下字段：

Serving:
  visualize: False

将默认不返回图像，通过请求体中的visualize参数可以覆盖默认行为。如果请求体和配置文件中均未设置（或请求体传入null、配置文件中未设置），则默认返回图像。	否
```

## 9. 总结（供核对 OCR 流水线）
1. 页数上限：异步接口页 = 单次请求最大 1000 页 PDF；配额中文页（2026-09-08）= 超过 1000 页只解析前 1000 页；英文旧页 = 100 页。同步 VL-1.5 页默认 100 页，其余同步页默认 10 页。用户引文“100页内”最近似英文旧版配额页。适用模型：配额页写“每个模型”，未区分模型。
2. 页数字段：有。extractProgress.totalPages / extractedPages；done 时示例代码读取 extractedPages。另可用 JSONL 中 layoutParsingResults 长度总和交叉核对。无显式“被截断”标志。
3. 失败：state=failed，data.errorMsg；整任务失败，无部分页成功。HTTP 仍为 200（11003）。
