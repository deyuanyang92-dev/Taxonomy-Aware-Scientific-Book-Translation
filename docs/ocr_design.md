# 高精度 OCR 与「对看」方案设计

日期：2026-11-11。执行：cursor。任务书：`docs/tasks/ocr_design_brief.md`。  
约束：**只调研与设计**；未改 `docstore/` 代码；未写资料库。  
结论标记：**已确证** / **未定** / **推测**。数字均附来源或实测文件。

---

## 一页结论与推荐

**推荐（已确证 + 设计判断）**

1. **先做人工金标准 ~30 页**，再谈「高精度」数字。现有 278 页 `ocr_verified` 中 277 页是 glm 转录（`docs/ocr_accuracy_baseline.md`），CER 只是与 glm 一致率。
2. **批量默认仍用 RapidOCR @ 300 dpi**（本库基线 CER≈1.4% vs glm；本轮 20 页 glm 子集一致率≈8.95%）。DPI 200→300 收益已确证且大。
3. **加 PP-OCRv5 mobile 作第二引擎 / 难页通道**：本轮对「螠」召回 4/5，RapidOCR 0/5（`docs/ocr_eval/metrics_fair.json`）。整体与 glm 一致率略逊 Rapid，但生僻字是分类学刚需。
4. **Tesseract chi_sim 不作中文主引擎**（本轮 CER≈0.48）。
5. **不对云 API 上传本库扫描件**（学位论文、未发表材料、本地扫描；合规优先）。商用 API 仅作对照调研。
6. **对看**：现无并排 UI，仅有 `docstore page --image`。新做本地只读渲染 + 编辑写回 `docstore verify --by user` 的轻量页（设计见下）；不另建页面库。
7. **优化优先级**：300 dpi 强制 → 人工金标准 → PP-OCRv5 双引擎分歧高亮 → 版面（双栏/表）→ yiku/学名词典纠错 → VLM 只复核可疑行。

**不要立刻做的**：全库换引擎；上云 OCR；未标定前宣称「精度 xx%」。

---

## 1. 现状摘要（已确证，不重复展开）

| 项 | 状态 | 来源 |
|---|---|---|
| RapidOCR 300 dpi vs glm verified | CER ≈ 0.0144（63 页） | `docs/ocr_accuracy_baseline.md` |
| RapidOCR 200 dpi | CER ≈ 0.0917（220 页） | 同上 |
| Rapid+Tesseract 共识 | 动物志33 抽样无增益 | `docs/ocr_consensus_pilot.md` |
| 金标准生产者 | glm 277 / codex 1 | baseline |
| 生僻字 CER | 金标准扩展区长度 0；规则有「虫甸→𧍒」「罗因→螠」 | baseline；`docstore/rules/ocr_fix.toml` |
| 对看 UI | **无**；`docstore page [--image]` 取文/渲图 | `docs/architecture.md`；本轮 CLI 核对 |
| 硬件 | GTX 1660 SUPER 6GB，WSL2 | `nvidia-smi` |

---

## 2. 候选引擎调研表

详细摘录见 `docs/ocr_eval/survey_notes.md`。版本/分数以 2026-11-11 抓取的公开页为准。

### 2.1 开源

| 引擎 | 公开成绩（来源） | 中文/古旧/生僻字 | 6GB 显存 | 速度量级 | 许可 | 离线 |
|---|---|---|---|---|---|---|
| **PP-OCRv5** | OmniDocBench OCR NED 0.067（ZH 0.076）；[论文](https://arxiv.org/html/2603.24373)；[官方文档](https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/algorithm/PP-OCRv5/PP-OCRv5.en.md) | 简繁+日英；官方称生僻字场景升级（**未在 OmniDoc 生僻子集独立验证**） | mobile 峰值 4.19GB（官方 V100 测）→ **可跑** | 官方 mobile GPU ~0.62s/图；本机 CPU ~5–8s/页 | Apache-2.0（项目惯用；以仓库 LICENSE 为准） | 是 |
| **PP-StructureV3** | OmniDocBench Overall 86.73；[sota2](https://www.sota2.com/research/sota/document-recognition-on-omnidocbench) | 版面/表强于纯 OCR | 未确证本机 | 管线更重 | 同 Paddle | 是 |
| **RapidOCR**（现用，多基于 PP-OCRv3/v4 ONNX） | 本库实测见 baseline | 中英可用；本轮 **螠 0/5** | 可跑（生产已用） | 本轮 ~5.5s/页 CPU | Apache-2.0 | 是 |
| **MinerU2.5** | Overall 90.67 | 文档解析强；古旧扫描**未确证** | 全量 VLM 路径未确证 | 中–慢 | 开源（Apache 系，第三方综述） | 是 |
| **MonkeyOCR-pro-1.2B / 3B** | 86.96 / 88.85 | 中英；生僻字未确证 | 1.2B 第三方称 FP16≈3.2GB；官方测过 8GB 卡 | 中 | 开源（GitHub） | 是 |
| **dots.ocr** | 88.41 | 多语；生僻字未确证 | BF16 权重约 6.4GB → **紧** | 中 | MIT + 补充协议（第三方读卡） | 是 |
| **olmOCR** | 81.79；olmOCR-bench 系 | 偏英文语料（综述） | ~12GB+ → **否** | 慢 | Apache-2.0 | 是 |
| **GOT-OCR2.0** | NED 0.077（ZH 0.112） | 中文弱于 PP-OCRv5 | 第三方称 ≥6GB | 中 | 代码 Apache；数据 CC-BY-NC（第三方） | 是 |
| **Qwen2.5-VL / Qwen3-VL 小尺寸** | Qwen3-VL-4B Overall 86.78；2B 80.58 | 通用 VL，OCR 非专项 | 3B 峰值或 6.0–6.5GB（第三方）→ **边界** | 慢于专用 OCR | 见模型卡 | 小尺寸可 |
| **Surya / Marker** | Surya NED 0.090；Marker Overall 71.3 | 多语；权重商业限制 | 相对 7B 轻，仍未本机测 | 中 | 代码 Apache；权重 OpenRAIL-M 变体 | 是 |
| **Tesseract chi_sim** | NED 0.324（ZH 0.551） | 中文扫描弱 | 可跑 | 本轮 ~3s/页 | Apache-2.0 | 是 |

### 2.2 商用 API（只调研，未注册、未上传）

| 服务 | 公开宣称/价目（来源分层） | 中文 | 离线 | 对本库 |
|---|---|---|---|---|
| 百度 OCR | 通用准确率宣称 98%+；有私有化/离线 SDK。[官网](https://cloud.baidu.cn/product/ocr) | 强 | SDK/私有化另购 | 默认可在线；**不上传本库件** |
| 腾讯 OCR | 印刷体宣称 95%+。[社区横评](https://cloud.tencent.com/developer/article/2743532) | 强 | 私有化 | 同上 |
| 阿里 OCR | 票据等专项宣称高；单价第三方摘录 | 强 | 私有化 | 同上 |
| ABBYY FineReader | 多语桌面；约 $99/年（第三方 2026 价目） | 中等–强（排版） | 桌面可 | 可作人工对看辅助，非管线 |
| Google Document AI | OCR ≈$1.50/千页（公开价目综述） | 可用 | 云 | 不上传 |
| Azure Document Intelligence | Read ≈$1.50/千页；可容器 | 可用 | 容器需许可 | 不上传 |
| Mathpix | OmniDoc NED ZH 0.240（弱于专用中文） | 公式强、中文文档弱 | 云 | 不优先 |

**价格数字**：第三方博客摘录百度≈¥0.04/次等 → **未确证**（非官网实时价）。

---

## 3. 本地实测（2–3 引擎）

环境：`/root/ocr_eval/`（venv + venv_rapid）。页图 300 dpi 自 PDF 渲出，**不写资料库**。  
交付：`docs/ocr_eval/`（`results.md`、`metrics_*.json`、`raw/`）。

### 3.1 样本

20 页，覆盖志书/名录/论著/专著/教材/学位论文/英文原著；含「螠」页、名录密排、疑难版面。见 `docs/ocr_eval/manifest.json`。

### 3.2 主结果（已确证）

| 引擎 | vs glm 金标准 CER（11 页） | 螠召回 | 备注 |
|---|---:|---:|---|
| RapidOCR | **0.0895** | 0/5 | 全量 0.063 含 Rapid 自金标准页，偏乐观 |
| PP-OCRv5 mobile | 0.1046 | **4/5** | 长边>4000 被缩放；CPU 轮 |
| Tesseract | 0.463 | 0/5 | 中文不可用 |

详见 `docs/ocr_eval/results.md`。

### 3.3 解读分层

| 判断 | 层 |
|---|---|
| Rapid 默认批量仍合理 | 已确证（基线 + 本轮 glm 子集） |
| PP-OCRv5 对生僻字/特殊汉字更有价值 | 已确证（螠）；扩展区「𧍒」样本仍缺（库内无「虫甸/𧍒」命中） |
| 近海1988 类旧扫描需版面分析，非单换引擎 | 已确证高 CER；根因（双栏串行 vs glm 改写）**未定** |
| PP-OCRv5 整体已全面超过 Rapid | **否**（本轮数据不支持） |
| server 模型 / 关 max_side_limit 能再降 CER | **未测** |

---

## 4. 算法优化：收益与代价

| 手段 | 预期收益 | 代价 | 依据 | 建议 |
|---|---|---|---|---|
| 强制 300 dpi | 大（CER 9%→1.4% 量级 vs glm） | 存图/时间 | baseline **已确证** | **立刻作为默认** |
| 版面分析（双栏、表、检索表） | 中–大（近海类页） | 接入 Structure/版面模型；调试读序 | 本轮近海 CER 高；Structure 榜面成绩 | 金标准后针对版面子集测 |
| 多引擎逐字投票（Rapid+PP-OCRv5） | 中（分歧处）；生僻字互补 | 2×算力；对齐 bbox | 共识试点 Tesseract 无增益，但 PP-v5 与 Rapid 错误谱不同（**推测**互补） | 先做「分歧高亮」供人对看，再自动投票 |
| VLM 复核可疑行 | 中（难字、乱码） | 慢；6GB 仅小模型/量化 | glm 已作 verified 生产者 | 只跑 qc human/redo 队列 |
| yiku + 学名库词典纠错 | 小–中（拉丁、科属中文） | 误纠风险 | consensus 试点 0.0504→0.0489 **已确证小幅** | 保留；收紧到低置信命中 |
| 生僻字专路径（近形映射、扩展区字体渲染比对） | 对分类学关键 | 字表维护；渲染比对开发 | 规则已有；本轮 PP-v5 認得螠 | 维护替换表 + 对看时扩展区字体 |

---

## 5. 金标准方案（约 30 页人工校对）

**目的**：以后一切精度数字只对这份人工金标准报；glm 一致率降级为「代理指标」。

### 5.1 选页（设计）

| 层 | 页数 | 抽法 |
|---|---:|---|
| 志书记述（动物志 09/33/54） | 8 | 含学名段 + 至少 2 页含「螠」或规则生僻字目标 |
| 名录（刘瑞玉2008） | 6 | 密排学名 + 1 页疑表 |
| 旧扫描专著（近海1988 / 杨德渐） | 6 | 强制含双栏或插图混排 |
| 教材（刘凌云） | 2 | 图注+正文 |
| 学位论文扫描 | 4 | 蔡文倩等 |
| 英文原著扫描（Greg） | 4 | 非 text_layer |
| **合计** | **30** | 固定种子；清单写入 `docs/ocr_gold/manifest.json`（实施时） |

回避：纯 text_layer 页（Mayr 等）不进「扫描 OCR」金标准。

### 5.2 校对规范

1. 对照 **300 dpi 原图**；读序：先左栏后右栏，表按行。
2. 保留印刷错误为原文；OCR 错才改。
3. 拉丁学名大小写、空格按原书；中文标点按原书（全角/半角不统一时从原图）。
4. 生僻字：能确认则用真实码位（如 螠、𧍒）；不确定标 `〔?U+xxxx〕` 不硬猜。
5. 页眉页脚、页码：纳入金标准全文（与现库页文本口径一致）。
6. 写回：`docstore verify <key> <页> --fix <txt> --level ocr_verified --by user`；history 必留。

### 5.3 时间估计

| 页类型 | 估计 | 30 页合计 |
|---|---|---|
| 疏朗记述 | 8–12 分钟/页 | |
| 密排名录 | 15–25 分钟/页 | |
| 双栏旧扫描 | 20–30 分钟/页 | |
| **加权平均** | **≈15–18 分钟/页** | **约 7.5–9 小时** 纯校对 |

另加：选页与清单 1h；抽查互检 1–2h。**用户侧约 1.5–2 个工作日**（推测，按专注校对计）。

---

## 6. 对看界面设计（只设计，不写代码）

### 6.1 目标交互

- 左：页图（可缩放、滚轮同步）。
- 右：可编辑文本；**按行**与检测框对齐（有 bbox 用引擎框；无则按行高均匀映射并标「弱对齐」）。
- 可疑字高亮：低置信、双引擎不一致、qc 信号、扩展区/PUA、未知学名。
- 单击高亮 → 焦点到行；改字后「写入校正」→ 调现有 `store.verify` / CLI `docstore verify --by user`。
- 只读浏览不写库；显式保存才写。

### 6.2 数据（沿用 docstore，不另库）

```
pages/<key>/pNNNN.json   主版本 + alternates + history
images/<key>/            渲图缓存（可删）
quality/qc/<key>_human.tsv  人工队列入口
```

对看启动参数建议：`key`、`page`、可选 `engine_a/engine_b` 只读 alternates 做分歧。  
**不**新建「对看专用页库」。

### 6.3 ASCII 草图

```
+------------------+-------------------------------+
| [key] p0123  dpi |  等级:ocr_sampled  引擎:Rapid |
| 300  [开PDF]     |  [PP-v5对照] [qc信号]         |
+------------------+-------------------------------+
|                  |  1  ...text line...           |
|   [ page image ] |  2  ...text line...  <<focus  |
|   with boxes     |  3  ...疑...                  |
|                  |                               |
|                  |  [保存 verify] [下一页 human]  |
+------------------+-------------------------------+
| 历史: verify by user 12:01  +3/-1                |
+--------------------------------------------------+
```

### 6.4 实现选型（建议，待用户定）

| 方案 | 优点 | 缺点 |
|---|---|---|
| A. 本地 Flask/FastAPI + 单页 HTML | 与 Python docstore 同进程；易调 verify | 需起服务 |
| B. 桌面（PyQt） | 离线强 | 与现仓库工具链略远 |
| C. 仅增强 CLI（diff+外部看图） | 最快 | 达不到「逐行点改」 |

**推荐 A**（推测最贴工作流）。工作量估计：可点改 MVP **2–4 人日**；含双引擎高亮 **+1–2 人日**。

---

## 7. 分步实施计划（时间 / 成本）

| 步 | 内容 | 时间 | 成本（算力/人） |
|---|---|---|---|
| 0 | 冻结：默认 OCR 300 dpi；qc 继续 | 0.5 d | 低 |
| 1 | 金标准 30 页人工 | 1.5–2 d 用户 | 人时为主 |
| 2 | 在金标准上重测 Rapid / PP-OCRv5（及可选 mobile vs server） | 0.5–1 d | GPU/CPU 小时级 |
| 3 | 接入 PP-OCRv5 为 alternates；分歧写入 qc | 2–3 d 开发 | 中 |
| 4 | 对看 MVP（图文+verify） | 2–4 d | 低算力 |
| 5 | 版面分析试点（近海/名录表） | 2–3 d | 中 |
| 6 | 词典纠错收紧 + 生僻字表扩展 | 1–2 d | 低 |
| 7 | （可选）小 VLM 只审 human 队列 | 2+ d | 显存紧，或 API 政策另议 |

**总建议路径**：1 → 2 → 4 与 3 可并行 → 5/6。云 API 默认跳过。

---

## 8. 需要用户决定的事项

1. **金标准 30 页**：是否按 §5 配比开做？谁校对（用户本人 / 分派）？
2. **对看载体**：Web 本地服务（荐）还是桌面 / 先 CLI？
3. **PP-OCRv5**：只作难页第二引擎，还是逐步替换 Rapid 默认？
4. **是否允许任何页上传国内云 OCR 做盲测**（默认否）？
5. **显存策略**：继续 CPU/ONNX，还是装 GPU 版 Paddle（server 峰值官方 5.4GB，本机紧）？
6. **「𧍒」等扩展区**：优先找真实书页加入金标准（库内现无该字形文本命中）。

---

## 附录：文件索引

| 路径 | 内容 |
|---|---|
| `docs/ocr_eval/survey_notes.md` | 调研摘录与链接 |
| `docs/ocr_eval/results.md` | 实测解读 |
| `docs/ocr_eval/metrics_fair.json` | 分层 CER |
| `docs/ocr_eval/raw/` | 三引擎原始文本 |
| `docs/tasks/ocr_design_progress.md` | 进度日志 |
| `/root/ocr_eval/` | 页图、venv、跑数脚本（库外） |
