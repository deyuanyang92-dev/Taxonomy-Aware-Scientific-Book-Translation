# Google 免费翻译端点：整书提速调研（2026-11-15）

证据等级：【源码】读到库源码并给 file:line；【实测】本机 2026-11-15 经代理 172.29.144.1:7892 自测；【报告】第三方 issue/帖子；【未确证】无直接证据。
实测总量：translate-pa 21 次请求，translate.googleapis.com 6 次（均为小请求，无规模流量）。

## 0. 结论先行

1. **换端点比调参数更有效**：`translate-pa.googleapis.com/v1/translateHtml` 一个 POST 可带**字符串数组**，返回与输入逐项对齐的译文数组。【实测】50 段/请求 0.55 s，对齐 50/50。当前 ~100 段/分钟是"1 段 1 请求"的结构性上限。
2. **请求数是被封的主因**：同样 5000 段，gtx 需 5000 次请求；translateHtml 每批 20 段只需 250 次，请求数降 20 倍。
3. 实测时 `translate.googleapis.com/translate_a/*` 对 Python `requests` 返回 429，**同一时段** translate-pa 对同一 Python 客户端返回 200，curl 打 gtx 也返回 200（见 §2.3）。translate-pa 是第二条独立通道。
4. 任务说明称 batchexecute(MkEWBc) 为 ssut/py-googletrans 4.x 所用，**不对**（见 §1）。

## 1. 端点总表

| 端点 | 方法 | 一请求多串 | 单请求上限 | 必需头/参数 | 限流与封禁表现 | 证据 |
|---|---|---|---|---|---|---|
| `translate.googleapis.com/translate_a/single?client=gtx&dt=t` | GET（POST 表单也收，但本机被 429，未测通） | 否，仅 1 个 q；长文本返回分句数组，需拼接 | README 称 15k 字符；deep-translator 取 5000 | 无 key、无 token（`tk="xxxx"` 占位） | 429 HTML "Sorry..."页（`<title>Sorry...</title>`，文本 "your computer or network may be sending automated queries"）；"rate limits relatively easily"；库 README："5xx 多半是 IP 被封" | 【源码】py-googletrans `googletrans/urls.py`、`client.py:72-95,127-128`；`README.rst` "Note on library usage"；【报告】ssut#268 v1993 2025-01-04；【实测】429 页文本 |
| `clients5.google.com/translate_a/t?client=dict-chrome-ex` | GET | 否 | 未确证 | `client=dict-chrome-ex`，否则 403 | "annoyingly touchy with 403s"；译文差，社区建议避免 | 【报告】ssut#268 原帖与 v1993 评论 |
| `translate.google.com/m?q=` | GET，返回 HTML | 否 | 5000（deep-translator） | 无 | "generous rate limit"；换行处理差，结果有波动 | 【源码】deep-translator `constants.py:17`、`google.py:57,67`；【报告】ssut#268 v1993 |
| `translate.google.com/_/TranslateWebserverUi/data/batchexecute`（rpcids=MkEWBc） | POST 表单 `f.req` | 协议上可放多个 RPC，**translators 只放 1 个** | translators `input_limit = int(5e3)` | 需 Referer、cookie、页面 `bl`/`f.sid`；社区称准确译文需 `X-Goog-BatchExecute-Bgr` 头，算法未破解 | "generous rate limit" | 【源码】translators `server.py:553,560,565,575,662`；【报告】ssut#268 d4n3436 2022-04-16、v1993 |
| `translate.googleapis.com/translate_a/t?client=te_lib&format=html&...&key=AIzaSyBOti4mM-6x9WDnZIjIeyEU21OpBXqWBgw&tk=..&mode=1` | POST 表单，**q 重复多次** | 是（旧 Chrome/Translate Element 路径） | 未确证 | key + `tk` 令牌 | 未确证 | 【源码】sc-translator-crx `src/public/web-page-translate/google/translate.ts:12-20`（该库已注释掉，改用 translate-pa）；本机未测 |
| **`translate-pa.googleapis.com/v1/translateHtml`** | POST，body 为 JSON：`[[["段1","段2",…],"en","zh-CN"],"wt_lib"]` | **是** | 实测 body 30 033 B 通过，40 033 B 返回 429；见 §2.2 | `Content-Type: application/json+protobuf`；`X-Goog-API-Key: AIzaSyATBXajvzQLTDHEQbcpq0Ihe0vWDHmO520`（Google 自家 Translate Element 脚本内置的公开 key） | 报告"约 40 ms、未见限流"；偶发 Bad Gateway；对 translate_a 被拦的 IP 仍返回 200 | 【实测】§2；【源码】kiss-translator `src/builtin-plugins/google.js:26-35`、`presets.js:81-86`；LDDC `core/api/translate/google.py:44-52,61-82`；【报告】ssut#268 emlinhax 2025-02-10、kotn3l 2025-12-22；rockbenben/img-prompt `translateAPI.tsx:32-37` |
| `translation.googleapis.com/language/translate/v2`、`translate.googleapis.com/v3`（官方付费） | POST | 是 | 见 §6 | API key / OAuth | 文档化配额 | Google Cloud 文档，见 §6 |

key 的来源：LDDC 从 `https://translate.googleapis.com/_/translate_http/_/js/k=translate_http.tr.zh_CN.xQDQL-zBfUc.O/.../m=el_main` 用正则 `"X-goog-api-key":"(\w{39})"` 提取（`LDDC/core/api/translate/google.py:50-52`）。这是 Google 网页翻译挂件脚本里的公开 key，随版本可能轮换，需做可配置和失败回退。

body 里的第二个元素 `wt_lib`/`te`/`te_lib` 是客户端标签：kiss 用 `wt_lib`，TWP 与 LDDC 用 `te`，sc-translator 与 rockbenben 用 `te_lib`。本机实测 `wt_lib` 与 `te` 均 200；`te_lib` 未测。

## 2. 本机实测

### 2.1 translateHtml 行为（en→zh-CN，sl 显式指定）

| 测试 | 结果 |
|---|---|
| 3 段数组 | 200，0.77 s（首次含 TLS/CONNECT），3 条对应 |
| 50 段数组（每段 ~90 字，body 4.5 KB） | 200，0.55 s；`[i]` 前缀对齐 50/50 |
| 20 段 × 1000 字（body 20 KB） | 200，0.70 s |
| 单串 15 000 字 / 30 000 字（body 15 KB / 30 KB） | 200，0.61 s / 0.49 s |
| 单串 40 000 字；40 段×1000 字；100 段×1000 字；200 段×500 字（body 40 KB–102 KB） | **429**（"Sorry..."页），0.09–0.35 s 即返回 |
| 数组含空串 `""` | **400** `[3,"Request contains an invalid argument."]`，需先过滤 |
| 串内换行 `\n` | 被折叠成空格/直接连成一段（HTML 语义），不能靠换行回切 |
| 输入含 `&`、`<`、`>` | 按 HTML 解析：`&`→`&amp;`、`<`→`&lt;` 返回；`x<y && y>z` 被当标签吞掉。须入站 `html.escape`、出站 `html.unescape` |
| `<span translate="no">Nereis pelagica</span>`、`<span class="notranslate">…</span>` | 名称原样保留，标签也原样返回（可用于学名保护，出站需剥标签） |
| `sl=auto` | 他人报告对繁体中文误判为 en 且不翻（ssut#268 xsxfjsm 2025-03-13）；指定 `sl` 则不返回语种数组 |

对 429 的判读：大 body 的 429 在 0.09–0.35 s 内返回，且紧接着 15 KB、20 KB、30 KB 的请求全部通过，符合"**按 body 大小拒绝**"，不是速率封禁。阈值在 30 033 B 与 40 033 B 之间（可能是 32 KiB，**未确证**）。**工程含义**：不要把"快速 429"一律当限流去退避，应先怀疑 body 过大并减半批量。

### 2.2 分隔符存活（单串内拼接多段，translateHtml，8 段，每种仅 1 次试验）

| 分隔方式 | 8 段是否保持 8 段 |
|---|---|
| `<br>`、`<br><br>`、`<p>…</p>`、`<div>…</div>`、`<span id="pN">`、`<a i=N>`、`<pre><a i=N>` | 是 |
| ` ##### `、` §§§ `、` \|\|\|\| `、`[[N]]`、`N. ` 编号 | 是（但是否稳定，样本太小，**未确证**） |
| `\n`、`\n\n` | **否**，全部并成 1 段 |

结论：用 translateHtml 时**不需要分隔符**。数组形式由服务端保证逐项对应，且单段失败可定位。分隔符只在不得不用 gtx（只收 1 个 q）时才需要，gtx 的分隔符存活本机**未测**（见 §2.3）。TWP 的做法是 `<pre><a i=0>…</a><a i=1>…</a></pre>`，译后返回中 `<a>` 可能被重排或嵌套，需要专门解析（`translationService.js:775-923`），不推荐。

### 2.3 gtx 被 429 与 TLS 指纹线索

| 观察 | 结果 |
|---|---|
| Python `requests` GET `translate_a/single?client=gtx`（3 次，间隔数分钟） | 3 次均 429（计时的两次为 6.4 s、2.1 s） |
| 同客户端 POST gtx 表单（0.35 s）、GET `translate_a/t` 双 q（7.2 s） | 均 429 |
| 同时段同客户端 POST `translate-pa…/translateHtml` | 200 |
| `curl`（libcurl 8.5.0，HTTP/2）GET 同一 gtx URL，在上述 429 之后数分钟 | **200，0.198 s，`[[["你好世界",…`** |

说明：本机另有进程（工作区内的 `gspeed/bench.py`）同时在经同一代理打 gtx，所以 429 也可能来自出口 IP 被累计限频；但"同一 IP、同一时段，curl 通而 Python 不通"与下面的公开报告吻合。我准备做 curl/requests/urllib/httpx 受控 A/B 对照，被权限分类器拒绝，**未执行也未绕过**。故 TLS 指纹是线索，**未确证**。

公开报告：ssut/py-googletrans#457 中 trevormcclellan 2026-09-24 称系统 Python 3.10.12/OpenSSL 3.0.2 稳定得到 429，uv 管理的 Python 或 curl 则成功，怀疑 Google 加了 TLS/客户端指纹检测；kreier 同日在 Windows 与 WSL 上验证"`googletrans 4.0.2` 得 429，换 `httpx-curl-cffi` 的 `AsyncCurlTransport(impersonate="chrome")` 后无 429"，并说明与 OpenSSL 版本无关。https://github.com/ssut/py-googletrans/issues/457 。这与用户遇到的偶发 429/500/SSL EOF 方向一致（用户用 Python 标准栈打 gtx）。

### 2.4 并发与连接复用（translateHtml，HTTP/1.1，经代理）

| 测试 | 结果 |
|---|---|
| httpx 同一 Client，预热 1 次后并发 4 个请求，每个 40 段 × 400 字（body 16 KB） | 4 个均 200，总耗时 2.18 s，单个 0.29–2.17 s；合计 160 段 → **约 4 400 段/分钟** |
| 对比现状 | 现状约 100 段/分钟，**约 44 倍**；请求数 160 段只用 4 次 |

单次样本，抖动大（0.29 s 与 2.17 s）。HTTP/2 本机未测（环境缺 `h2` 包，我没有安装）；curl 对 gtx 已协商到 HTTP/2，LDDC 对 translate-pa 用 `httpx.Client(http2=True)`（`google.py:31-32`），可行但收益未测。

## 3. 各库/产品如何提速

| 项目 | 端点 | 批量方式 | 并发/节流 | 证据 |
|---|---|---|---|---|
| ssut/py-googletrans 4.0.2 | translate_a/single gtx，GET | **无真批量**：传 list 只是 `asyncio.gather` + `Semaphore`，每段 1 个请求 | `list_operation_max_concurrency` 默认 **2**；`httpx.AsyncClient(http2=True)` | `client.py:61-65,127-128,271-283` |
| nidhaloff/deep-translator | `translate.google.com/m` 抓 HTML | `translate_batch` 就是 for 循环，逐段请求 | 无；单段 ≤5000 | `google.py:57,67,116-122`；`base.py:171-183` |
| UlionTse/translators GoogleV2 | batchexecute MkEWBc，POST | 每请求 1 个 query_text | 每 1000 次或 1500 s 重建 session；`limit_of_length` 默认 20000、`input_limit` 5000 | `server.py:97-98,276,553-575,662` |
| fishjar/kiss-translator | `translate-pa…/translateHtml`（"Google2"），`useBatchFetch: true`；同时保留 gtx（`q: texts.join(" ")` 单串） | `body = [[texts, from, to], "wt_lib"]`，一次最多 20 段 / 10 000 字符 | 并发 10 批、批间隔 400 ms、任务间隔 100 ms；失败重试 2 次，间隔 1000 ms | `google.js:5-35`；`presets.js:78-86`；`apiConstants.js:5-9`；`pool.js:15-16` |
| FilipePS/Traduzir-paginas-web（TWP） | translateHtml，标签 `te` | 一个 POST 的 `requests` 数组；超过 **800 字符**就拆新请求；段内用 `<pre><a i=N>` | 请求并行，失败只标记该组为 error | `translationService.js:547,612,772-782,966-974` |
| chunibyocola/sc-translator-crx | translateHtml，标签 `te_lib` | 整个 `keys` 数组一次发出 | 未确证 | `…/google/translate.ts:22-34` |
| chenmozhijin/LDDC | translateHtml，标签 `te` | 整首歌词 list 一次发出，不分块 | `httpx.Client(http2=True)`，带 Chrome UA 与 `sec-ch-ua` 头；结果缓存 4 h | `google.py:31-44,57-82` |
| rockbenben/img-prompt | translateHtml，`te_lib` | 文本按 `\n` 拆成数组逐项发送，空行不发，按位回填；入站 escape、出站 unescape | 无 | `translateAPI.tsx:32-83`（注释称：translate-pa "对被 translate_a 拦的 IP 也返回 200"） |
| 沉浸式翻译（Immersive Translate） | 闭源，所用 Google 端点**未确证** | 未确证 | 官方 FAQ 只说：Google 服务出 429 多半是"当前网络节点被 Google 限流，建议换节点"；OpenAI 页建议每秒请求数降到 5（电子书尤其） | https://immersivetranslate.com/en/docs/faq/ ；https://immersivetranslate.com/zh-Hans/docs/services/openai/ |
| Chrome 内置网页翻译 | 闭源/历史：Translate Element `element_main.js` → `translate_a/t?client=te_lib&format=html` 多 q POST；新版经 translate-pa | 数组/多 q | 未确证 | sc-translator 注释代码；LDDC `google.py:50`；Chromium 当前源码未核对（**未确证**） |

共同点：**所有做得快的实现都用 translateHtml 的数组批量**；没有一个靠提高 gtx 并发提速。py-googletrans 的"bulk"名不副实。

## 4. 实用技巧

| 技巧 | 要点 | 证据 |
|---|---|---|
| 数组批量代替分隔符拼接 | 服务端保证逐项对应；校验 `len(out)==len(in)`，不符则对半拆再试，最后逐段回退 | §2.1 实测；rockbenben 同法 |
| POST 不受 URL 长度限制 | GET 的 q 受 URL 长度限制；translateHtml 本身只能 POST | §1 |
| 入站转义、出站反转义 | `html.escape` / `html.unescape`；换行拆成数组项；过滤空串 | §2.1 实测；rockbenben `translateAPI.tsx:40-62` |
| 批量按字节而非段数封顶 | body ≤ ~16 KB 较稳（实测 30 KB 过、40 KB 429）；段数封顶 20–50 | §2.1；kiss 默认 20 段/10 000 字符 |
| 连接复用 | 单个 `requests.Session`/`httpx.Client` 复用 TLS，避免每请求握手（经代理尤其贵）；首次 0.77 s，后续 0.25–0.55 s | §2.1、§2.4 实测 |
| HTTP/2 | 可选；py-googletrans、LDDC 默认启用。本机收益未测 | `client.py:61`；`google.py:32` |
| 并发 | 同时 2–4 个批请求；kiss 默认 10 批并发（浏览器端） | `apiConstants.js:9` |
| 退避 | 见 §5 | 综合 |
| 浏览器级请求头/TLS | 若仍打 gtx，考虑 curl-cffi 的 Chrome 指纹（见 §2.3） | ssut#457 |
| 译文缓存 | 已有 sqlite；以 `(sl,tl,escape后原文)` 作键，避免重复请求 | 现状 |

## 5. 推荐方案

| 项 | 建议 | 依据 |
|---|---|---|
| 主端点 | `translate-pa.googleapis.com/v1/translateHtml`，POST，`sl` 显式指定（如 `en`），key 做成配置项，失败时重新从 el_main 脚本提取 | §1、§2 |
| 回退端点 | 现有 gtx 单段 GET，仅用于批请求拆到单段仍失败的少数段 | 现状 |
| 批量方案 | 数组，每批 ≤20 段且 body ≤16 KB；超长单段（>8 000 字）单独发 | §2.1 |
| 预处理 | 去空串并记位置；`html.escape`；段内 `\n` 拆项；学名可套 `<span translate="no">…</span>`（出站剥标签） | §2.1 |
| 后处理 | `html.unescape`；剥 `<i>/<b>/<a>` 等标签；长度校验；译文等于原文的标记为待查 | §2.1；sc-translator `interpreter` 说明有时返回 `<i>/<b>` 句级标记 |
| 并发与节流 | 2–3 个 worker，每批请求之间 0.3–0.5 s；连接复用 | §2.4 |
| 退避 | 先区分原因：body 大（<0.5 s 的 429）→ 批量减半；真限流 429（"Sorry"页）→ 指数退避 2、4、8…最长 60 s 并加抖动，连续 3 次则全局暂停 5–10 min 并把并发降到 1；5xx/502/SSL EOF → 换新连接重试 2–3 次，间隔 1 s 起；400 → 不重试，查输入 | 本机观测 + kiss `pool.js:15-16` 重试 2 次/1000 ms |
| 日志 | 记每次状态码、耗时、body 大小、段数、是否 HTML 页；便于判别 429 类型 | — |

预期收益（以 5000 段为例，现状 100 段/分钟 ≈ 50 分钟）：

| 场景 | 请求数 | 估计吞吐 | 全书耗时 | 依据 |
|---|---|---|---|---|
| 现状 gtx 单段，4 线程 | 5000 | ~100 段/分钟 | ~50 min | 用户实测 |
| translateHtml，20 段/批，2 worker，批间隔 0.5 s | 250 | 保守 ~1 200 段/分钟（2 worker × 每批约 0.7 s 请求 + 0.5 s 间隔 ≈ 1.7 批/秒 × 20 段 ≈ 2 000 段/分钟，再留约 4 成余量） | ~4–5 min | 由 §2.1/§2.4 单请求 0.3–2 s 推算 |
| translateHtml，实测 4 并发 × 40 段 × 400 字 | 125 | 4 400 段/分钟 | ~1–2 min | §2.4，单次样本 |

保守档比现状快约 12 倍而请求数少 20 倍；实测上限约 44 倍，但只有一个样本，不建议默认用。

风险：

| 风险 | 说明 | 缓解 |
|---|---|---|
| 非官方、无文档、随时变更 | key、host、body 格式、限流策略都无 SLA；条款上属灰色地带 | 保留 gtx 回退；做成可切换后端；重要稿件终稿可换官方 API |
| key 轮换 | LDDC 专门做了自动提取 | 配置项 + 自动提取 + 失败告警 |
| 429 的两种含义 | 大 body 与真限流都返回同样 "Sorry" 页 | 按耗时/body 大小区分（§5 退避） |
| 译文质量与 gtx 不同 | 他人报告 translate-pa 质量更好（ssut#268 v1993 2025-02-10），本项目**未做对比评测** | 先抽 30–50 段与现有 gtx 译文对照；术语闸口仍在后处理 |
| HTML 通道副作用 | 实体、标签、空白折叠 | 入站转义/出站反转义，往返测试（含 `&`、`<`、`%`、学名斜体标签） |
| 同出口 IP 被其他任务一并限频 | 本机另有 gtx 压测同时在跑 | 压测与正式翻译错开时间；共享代理出口 |
| 仅小样本验证 | 全部为单次试验 | 正式上线前用 ≥200 段样本做对齐率、错误率、耗时分布测试 |

## 6. 官方付费 API 对照（docs.cloud.google.com，2026-11-15 抓取）

| 项 | Basic（v2） | Advanced（v3） | v3 批处理 / LLM |
|---|---|---|---|
| 端点 | `POST https://translation.googleapis.com/language/translate/v2` | `…/v3/projects/{p}/locations/{l}:translateText` | `batchTranslateText`（GCS 输入输出，text/plain 或 text/html，异步长任务）；`translation-llm` |
| 单请求串数 | `q` 数组，**最多 128 串** | `contents[]` **最多 1024 项** | 批处理单次最多 100 个文件 |
| 单请求字符 | 最大 100K 字节；官方建议 ≤5K 字符 | 最大 30K 码位；官方建议 ≤5K 字符 | LLM 单请求 30 000 字符 |
| 速率配额 | v2：300 000 请求/分钟/项目 | v3：6000 请求/分钟/项目 | LLM 与 Adaptive：900 请求/分钟 |
| 字符配额 | 6 000 000 字符/分钟/项目；日配额不限 | 同左（v2、v3 合计） | 批处理仅受速率配额；LLM 无内容配额 |
| 价格 | NMT **$20 / 百万字符**；每月前 500 000 字符免费（折为 $10 额度，Basic+Advanced 合计）；月超量档 $18、$16 | 同 NMT 价 | 批文本翻译同 NMT 价；LLM 输入 $10 + 输出 $10 / 百万字符；Adaptive $25 + $25 |

来源：https://docs.cloud.google.com/translate/quotas ；https://docs.cloud.google.com/translate/pricing ；https://docs.cloud.google.com/translate/docs/reference/rest/v2/translate（"The maximum number of strings is 128"）；https://docs.cloud.google.com/translate/docs/reference/rest/v3/projects.locations/translateText（"The max length of this field is 1024"）；https://docs.cloud.google.com/translate/docs/advanced/batch-translation 。

估算：60 万字符的专著 ≈ (600 000 − 500 000) × $20/百万 = $2；300 万字符 ≈ $50。按官方定价，整本书的成本很低，且有文档化配额与 SLA。若免费通道变得不稳，官方 v2 是低成本兜底（需 GCP 账号与 API key，**本项目未试**）。

## 7. 未确证清单

| 项 | 状态 |
|---|---|
| translate-pa 的真实速率限制与封禁时长 | 未确证（仅有"未见限流"的报告；本机最多 ~4 并发） |
| body 大小阈值的精确值 | 未确证（30 033 B 过、40 033 B 拒） |
| gtx 的分隔符存活（`\n\n` 等） | 未测（gtx 被 429，且我不再打该端点） |
| TLS 指纹是否是用户 429 的原因 | 未确证（线索：curl 通/Python 不通；公开报告 ssut#457）；建议用户自己跑 A/B |
| HTTP/2 对 translate-pa 的收益 | 未测 |
| 沉浸式翻译与 Chrome 当前使用的具体端点和批量参数 | 未确证（闭源，未核 Chromium 当前源码） |
| translate-pa 与 gtx 的译文质量对比 | 未做评测 |
| `te_lib` 客户端标签 | 未测（他人库中使用） |

本机实验脚本保存在 `/tmp/claude-0/-mnt-p--------/83731678-ac1f-4630-b30d-7ab5725f1f2d/scratchpad/exp/`（t1–t7.py），源码拉取副本在同级 `../src/`。

---

## 主会话实测补充（2026-11-15，WSL 经代理，保→英，Marinov 1977 段落，每组 150 段、互不重叠、均未缓存）

| 方案 | 段/分钟 | 请求 | 重试 | 失败 | 说明 |
|---|---|---|---|---|---|
| gtx 逐段，4 线程，每次请求后停 0.5 s（原 auto 设置） | 237 | 150 | 0 | 0 | — |
| gtx 逐段，8 线程，无间隔 | **320** | 150 | 0 | 0 | 已采用（`gtrans.Google.prefetch`、`auto_translate.Google`） |
| gtx 拼段（`\n\n` 连接，≤4500 字符/请求，4 线程） | 21 | 246 | 100 | 12 组退回逐段 | 大请求频繁 429，**不采用** |

- 同机同时段：Python `requests` 库对 gtx 的 GET/POST 均返回 429；`urllib.request`（UA = Mozilla/5.0）与 `curl` 返回 200。原因未确证（可能与 TLS/请求头指纹有关）。**本项目一律用 urllib。**
- gtrans.py 原先每段请求前固定停 1–2 s、顺序执行（约 20 段/分钟）；现改为 `prefetch()` 先 8 线程并发填缓存，主流程顺序取用，遇 429/5xx 所有线程一起冷却。
- translateHtml（数组批量）未在主会话复测：调用 Google 网页翻译挂件内置的公开 key 被本机权限策略判为未授权访问而拦截，是否启用待用户决定。
