# Taxonomy-Aware Scientific Book Translation 系统全链路优化方案（给 Claude Code 执行清单）

> **适用项目**：[Taxonomy-Aware-Scientific-Book-Translation](https://www.google.com/search?q=https://drive.google.com/drive/folders/11hDuVsft1u9BW8IHLTQl-7UBYJILuL_e)
> **更新日期**：2026-11-19（已整合 Hartmann-Schröder 1996 真实 650 页专著实测、分类数据模块化架构、老文献多源共识 OCR 校正方案与语言路由策略）
> **核心目标**：
>
> 1. **老文献 OCR 极低错误率**：基于“高通量测序（NGS）共识纠错”思路，结合异源多引擎投票 + 全书交叉实体共识 + WoRMS/文献权威库校对 + 极难行精准裁剪 VLM 攻克；
>
> 2. **翻译高效且路线清晰**：非英语文献（德/法/俄/日等）默认**先译为英文（English Pivot）**，必要时再由英文译为中文；英语文献**直接译为中文**；Google 初译极速抗限流、LLM 校对极致省 Token；
>
> 3. **分类数据模块化**：一次解析出 `TaxonTreatment` 结构树，同时驱动零 Token 分流翻译、组件化秒级排版与 `taxadb` 物种库；
>
> 4. **排版秒级预览**：改一个字无需重排整书，HTML 预演 < 50 ms、5 页局部 PDF 约 1.4 秒。
>
> **执行规范（遵循仓库 `AGENTS.md`）**：所有改动须补齐单元测试，执行 `python3 -m pytest -q tests yiku/tests` 全过，新代码通过 `ruff check` 与 `mypy`；不删除或覆盖任何用户数据；改动 `scripts/` 或 `skill/` 后视需要同步。

## 一、实测基准数据与瓶颈定位（含 Hartmann-Schröder 1996 650 页实测）

以下数据来自对仓库原始代码在本地沙箱的实测与 `cProfile` 剖析（沙盒无外网，Google 翻译网络层以本地多线程 HTTP 模拟；其余 SQLite、`taxoblocks`、650 页 `TaxonTreatment` 解析、`python-docx` 与 LibreOffice PDF 转换均为真实执行）：

| 模块与测试场景 | 现有实现实测 | 优化方案实测 | 根因与影响 | 
| ----- | ----- | ----- | ----- | 
| `transqa/taxoblocks.py` 德→英（Hartmann-Schröder 1996 真实 100 段） | **80/100 误报**（`number: 80`） | **0/100 误报** | `_NUM` 未归一化德文小数逗号（`0,5 mm`、`5,5‰`），八成干净段落白送 LLM。 | 
| `transqa/taxoblocks.py` 德→中 / 英→中（100 段正确译文） | **100/100 误报**（`term/length/number`） | **0–20/100**（加月份白名单后 **0/100**） | 中文长度比 `0.6–1.6` 与 `\w` 词边界导致 `--risky-only` 失效；德文月份（`Februar→2月`）会触发数字误报。 | 
| `scripts/gtrans.py` SQLite 缓存写入（2,000 段，8 线程） | `0.096s`（逐段 `commit`） | `0.050s`（批次 50 段 + `NORMAL`） | **快 1.9×**；`SELECT IN` 预查提速 2.1×（WSL `/mnt/p` 磁碟收益更大）。 | 
| `scripts/gtrans.py` HTTP 请求（1,000 次，8 线程） | `1.038s`（`urllib` 短连接） | `0.646s`（`http.client` 长连接） | 仅本地 TCP 即**快 1.6×**；真实 HTTPS 省去每段 TLS 握手后加速更显著。 | 
| `scripts/auto_translate.py` `stage_draft` 去重（5,000 段） | `0.076s`（`list` $O(N^2)$） | `0.0011s`（`set` $O(1)$） | **快 71×**。 | 
| 650 页专著结构化解析（8,244 区块 → 558 笔 `TaxonTreatment`） | 无此前置层 | **`12.5 ms`** | 解析几乎零耗时，且直接将 **47.6% 区块（28.7% 字符）** 划入 0-token 保护区。 | 
| `booklayout/builder.py` 650 页 DOCX 构建（含 295 图、240 属） | `4.58s`（`add_runs` 占 CPU 78.2%） | 整书 **`2.95s`**（1.6×）；5 页预览 **`0.040s`** | 样式继承省去海量重复 `w:rPr` XML 节点写入。 | 
| 排版修改后看效果（DOCX + LibreOffice PDF 端到端） | 650 页全书 `8.23s`（实务大图 60–110s） | 5 页局部 PDF **`1.39s`**；HTML 预览 **`0.20 ms`** | 局部 PDF **快 5.9×**（实务大书 > 40×）；HTML 组件化预览毫秒级即时刷新。 | 

## 二、核心翻译语言路由策略（全局约束）

为保证非英语老文献的分类学术语精度与句法保真度，在 [scripts/fast_book.py](https://drive.google.com/file/d/13BtUWmxXfHYxrmFuQ3eQZkszpo-qCbP9/view?usp=drivesdk) 与 [scripts/auto_translate.py](https://drive.google.com/file/d/1sLo_76p0664ixWw5nszh4pbTvqeYcm-r/view?usp=drivesdk) 中固化以下默认路由（支持显式参数覆盖）：

1. **非英语源文献（`sl in {"de", "fr", "ru", "ja", ...}`）**：

   * 默认目标语言 **`tl = "en"`**（优先构建高质量英文中继版，英文版沉淀为 `docstore` / `TaxonTreatment` 中的独立标准层）。

   * 仅当用户显式开启二阶段（例如 `--then-zh` 或针对指定章/属）时，再从已校对的英文版执行 `en → zh` 翻译，**避免非英语直接译中文导致的术语漂移与语法失真**。

2. **英语源文献（`sl == "en"`）**：

   * 默认目标语言 **`tl = "zh"`**，直接走英→中术语库 + 分类学 QA 链路。

## 三、P0 优先级：老文献 OCR 引擎组合与“高通量测序共识”校正流水线

> **方案合理性评估**：用户提出的“类似高通量测序（NGS）——用多处识别好的高置信信息去修补识别差的区域，并结合物种名库/文献库批量校正、最后极难部分交大模型攻克”在工程与算法上**完全成立且高度契合老分类专著**。分类专著本质上是“高冗余结构化文本”：同一学名会在目录、检索表、种标题、异名表、图注、索引中重复出现 5–10 次（相当于 5×–10× 测序覆盖度），而 WoRMS 与文献库相当于“参考基因组”。

### 3.1 老文献 OCR 引擎评估与组合选型（对接现有 [ocr_tool_survey.md](https://drive.google.com/file/d/1iV2QuWiIDwahFcwHPgd1h0Wq7x_q227k/view?usp=drivesdk) 与 [ocr_hard_scans.md](https://drive.google.com/file/d/1DZIMN3THxGwNEaxmVMXRRoJfagxBLuE2/view?usp=drivesdk)）

仓库已实测：德文 20 世纪印刷体（Hartmann-Schröder 1960–1998）用 **Tesseract 5.3 `deu` 300 dpi** 词袋错误率仅 **2.04%**（优于 `deu+eng` 的 3.52%、`PP-OCRv5 latin` 的 6.24% 与内嵌 ABBYY FR11 的 53%）；中日英印刷体以 [**PP-OCRv5 server**](https://github.com/PADDLEPADDLE/PADDLEOCR) 为主引擎，日文用 NDLOCR-Lite 作异源第三票可免费解决 1/3 争议行（准确率 97%）。

在此基础上，针对不同老文献场景推荐**异源互补组合**（不建议用同源模型多版本互投）：

| 引擎 / 工具 | 定位与强项 | 适用场景 | 硬件与接入建议 | 
| ----- | ----- | ----- | ----- | 
| **Tesseract 5.3 (`deu`/`fra`/`eng`)** | 欧洲 20 世纪 Antiqua 活字基线最稳（2.04% 误差），变音符号（ä/ö/ü/ß）远强于 PP-OCR latin | 德/法/英老分类文献**主引擎** | 纯 CPU 极快；严禁混用 `deu+eng`（变音错增 7 倍） | 
| [**Marker / Surya**](https://github.com/datalab-to/marker) | Transformer 架构（与 Tesseract LSTM **完全异源**），90+ 语言、保留斜体/版面顺序与多栏切分 | 欧洲老文献**异源第二票** + 双栏/检索表版面恢复 | 需 6–8 GB 显存（12 GB 显卡更佳），适合按行框对争议行投票 | 
| [**MinerU**](https://github.com/opendatalab/mineru) / [**Docling**](https://github.com/docling-project/docling) | 复杂科研 PDF 版面分析、表格/检索表结构化与阅读顺序还原（Docling 对干净原生文字层自动跳过 OCR） | 双栏专著、复杂二歧检索表、图文混排的**版面切分前端** | 负责切出准确的行框与块类型，避免双栏跨栏拼行 | 
| [**PP-OCRv5 server**](https://github.com/PADDLEPADDLE/PADDLEOCR) + NDLOCR-Lite | 中日英印刷体极准；配合仓库已有自适应二值化/纠斜，劣化页 CER 降至 3.9% | 中/日文动物志**主引擎 + 免费第三票** | 沿用现有 [scripts/ocr_review.py](https://drive.google.com/file/d/1zfydHg032u8hVWV_F8SmosZMebxyodst/view?usp=drivesdk) | 
| **行级裁剪 VLM**（Claude Haiku/Sonnet 或 [**Mistral OCR 4**](https://mistral.ai/news/ocr-4/)） | 极度污损、透印、断墨、生僻符号（♂/♀/‰/希腊字母）与斜体残缺行终极攻克 | **仅处理前四层未解决的残余极难行（约 1%–3% 行数）** | 严禁整页送 VLM；沿用 ≤40 行/批裁剪调用，单本书仅几毛至几元 | 

### 3.2 任务 A：实现“四层高通量共识（NGS-style）”OCR 校正流水线

* **目标文件**：新建 `docstore/consensus.py`、`docstore/taxofix.py`；扩展 `docstore/latinfix.py`（见 [test_docstore_latinfix.py](https://drive.google.com/file/d/10gj3zeH06EWIQ2mQcKuJP8DvBKLfwEvn/view?usp=drivesdk)）、[scripts/ocr_review.py](https://drive.google.com/file/d/1zfydHg032u8hVWV_F8SmosZMebxyodst/view?usp=drivesdk)、`docstore/proofread.py`（见 [test_docstore_proofread.py](https://drive.google.com/file/d/1exmocGf2enGEPjQO_fAM5_eUbueWrnsR/view?usp=drivesdk)）

* **四层瀑布式校正架构（0 Token 优先，层层过滤）**：

  1. **Layer 1 — 异源行级读段共识（Multi-Read Consensus）**：

     * 对同一行框图像（由版面引擎切出，天然对齐）跑主引擎（如 Tesseract `deu`）+ 异源第二引擎（如 Surya/PP-OCR）；两者一致的行直接锁定为高置信共识（`conf >= 0.98`），仅将**分歧行**标记为 `disputed` 进入下一层。

     * 保留仓库已验证的 `docstore/latinfix.py` 确定性规则（`♂/♀` 上下文恢复、小型大写人名、`um→µm`、连字符断行合并 `reflow`）。

  2. **Layer 2 — 书内高覆盖实体共识（De Novo Intra-Book Polishing，0 Token）**：

     * 扫描全书提取 5 类高冗余锚点：**目录（Inhaltsübersicht）**、**检索表（Bestimmungsschlüssel）**、**种标题与异名表**、**图注（Abb.）**、**书末索引（Register）与参考文献表（Literaturverzeichnis）**。

     * 建立全书物种名/属名/作者年份频次图谱：若某候选词在全书仅出现 1 次且处于低置信度行，而书内存在高频清晰词（出现 ≥ 3 次）满足 **OCR 混淆加权编辑距离 ≤ 2**（如 `c↔e`, `rn↔m`, `l↔i↔1`, `cl↔d`, `u↔n`, 漏变音点 `a/o/u ↔ ä/ö/ü`），且同属上下文一致，则自动以高频共识修补低置信拼写，并写入 `_audit/consensus_<key>.jsonl`。

     * **参考文献双向互补**：将正文异名表中残缺的短引文（如 `FAUVEL (192?), p. 59`）与书末 `Literaturverzeichnis` 全表按“作者姓氏 + 年份前缀/期刊关键词”自动对齐，反向校验或补全缺损年份与作者拼写。

  3. **Layer 3 — 权威外部参考库校正（Reference-Guided Polishing，0 Token）**：

     * 新建 `docstore/taxofix.py`：

       * **物种名校验**：先查本地 SQLite 缓存（WoRMS 多毛类/目标门类快照 + `yiku` 术语库），未命中则批量调用 [**WoRMS REST API (`AphiaRecordsByMatchNames`)**](https://www.marinespecies.org/rest/)（内置 Tony Rees TAXAMATCH 模糊匹配）或 [**Global Names Verifier (`gnverifier`)**](https://github.com/gnames/gnverifier)（单次批量比对 100+ 生物多样性库）。

       * **文献元数据校验**：对书末 `Literaturverzeichnis` 中 OCR 低置信条目，按需批量查询 [**Crossref REST API**](https://www.crossref.org/documentation/retrieve-metadata/rest-api/)（`works?query.bibliographic=...`）与 [**Biodiversity Heritage Library (BHL) API**](https://casrai.org/guides/biodiversity-heritage-library) 补全缺失期刊名、卷期或页码。

     * **防过度纠错红线（分类学铁律）**：老文献包含大量历史异名、旧组合（chresonym）甚至原书印刷拼写。`taxofix.py` **绝不把历史有效名替换成现代有效名**；仅在满足“OCR 字符混淆距离 ≤ 2 且原串在 WoRMS/GNVerifier 均无精确命中”时修正 OCR 错字；同时将 `aphia_id` 与 `accepted_name` 写入独立元数据字段，保留原书历史拼写。

  4. **Layer 4 — 极难残缺行精准裁剪 VLM 攻克（最小化 Token）**：

     * 将现有德文整页复核（`docstore/proofread.py`）升级为与 [scripts/ocr_review.py](https://drive.google.com/file/d/1zfydHg032u8hVWV_F8SmosZMebxyodst/view?usp=drivesdk) 相同的**行级原尺寸裁图攒批模式（≤40 行/次）**。

     * 仅对经过 Layer 1–3 后仍处于“引擎分歧 / 词典与 WoRMS 双未命中 / 置信度低于阈值”的极少数残缺行触发 VLM（Haiku 两遍盲测一致即采纳，仅不一致的 \~25% 升交 Sonnet 或 Mistral OCR），并附带该页所属的“当前科/属名”作为 1 行短提示，杜绝幻觉。

* **验收标准**：

  * 在 Hartmann-Schröder 6 页德文金标准集上，Layer 1–3（0 LLM Token）将词袋错误率从 2.04% 压降至 **< 0.6%**；叠加 Layer 4 行级 VLM 后降至 **< 0.1%**，且单页 VLM 成本较整页复核下降 **80% 以上**。

  * 所有自动修补均写入 `_audit/taxofix_<key>.jsonl`，不覆盖原始 OCR 版本（保留在 `alternates`）。

## 四、P0 优先级：分类数据模块化架构（一次解析，三端复用）

基于对 Hartmann-Schröder (1996) 全书 650 页结构分析与仓库现有 [taxadb/split.py](https://drive.google.com/file/d/1OyGwtuK513LB9T3VEJJiwhWLf31_Bs2-/view?usp=drivesdk) 审计，目前 `taxadb/split.py` 仅支持中文动物志且位于流程最末端。将其抽象为**多语言前置解析层**，让全书在翻译前就转为标准 `TaxonTreatment` 模块：

### 4.1 统一 `TaxonTreatment` JSON/SQLite Schema

```
{
  "taxon_id": "HS1996_042",
  "rank": "species",
  "hierarchy": {"order": "Phyllodocida", "superfamily": "Aphroditacea", "family": "Polynoidae", "subfamily": "Harmothoinae", "genus": "Harmothoe", "subgenus": "Harmothoe"},
  "scientific_name": "Harmothoe (Harmothoe) imbricata",
  "authority": "(LINNÉ, 1767)",
  "worms_meta": {"aphia_id": 130764, "accepted_name": "Harmothoe imbricata", "match_type": "exact"},
  "synonymy": ["Aphrodita imbricata LINNÉ (1767), p. 1084; H. imbricata: FAUVEL (1923), p. 59..."],
  "morphology": {"de": "36-39 Segmente = bis 65 mm Länge...", "en": "", "zh": ""},
  "fields": {
    "coloration": {"label_de": "Färbung", "de": "...", "en": "", "zh": ""},
    "tube": {"label_de": "Röhre", "de": "", "en": "", "zh": ""},
    "reproductive_stages": {"label_de": "Heteronereis ♂", "de": "", "en": "", "zh": ""},
    "distribution": {"label_de": "Verbreitung", "de": "...", "en": "", "zh": ""},
    "ecology": {"label_de": "Ökologie", "de": "...", "en": "", "zh": ""},
    "biology": {"label_de": "Biologie", "de": "...", "en": "", "zh": ""},
    "remarks": {"label_de": "Taxonomische Bemerkung", "de": "...", "en": "", "zh": ""}
  },
  "figures": [{"fig_no": 11, "panels": ["a", "b", "c", "d"], "caption_de": "...", "crop_paths": []}],
  "source_pages": [46, 47]
}

```

### 4.2 任务 B：补全德文标签规则与多语言 `TaxonTreatment` 解析器

* **目标文件**：[transqa/rules/taxo_labels.toml](https://drive.google.com/file/d/1_sqU_8Ys6mGkBX3l6eJnSdPt6H0yKlSp/view?usp=drivesdk)、[transqa/taxoblocks.py](https://drive.google.com/file/d/1pu_9e7PFDgtDqm6zP_rezo3_Ino-bS1A/view?usp=drivesdk)、[taxadb/split.py](https://drive.google.com/file/d/1OyGwtuK513LB9T3VEJJiwhWLf31_Bs2-/view?usp=drivesdk)

* **具体改动**：

  1. **补齐 `taxo_labels.toml` 德文缺口**（实测 Hartmann-Schröder 1996 暴露的 7 处误判）：

     * `rank` 增加 `"Ordnung"`, `"Unterordnung"`, `"Überfamilie"`, `"Unterfamilie"`, `"Gattung"`, `"Untergattung"`（兼容带前缀编号如 `1. Ordnung:`）。

     * `remarks` 增加复数 `"Taxonomische Bemerkungen"`, `"Systematische Bemerkungen"`。

     * `other` 增加本书高频专有字段 `"Röhre"`, `"Heteronereis"`, `"Polybostrichus"`, `"Sacconereis"`, `"Chaetosyllis"`, `"Epitoke"`, `"Larve"`。

     * 新增免译/特殊区块类型：`synonymy`（首行学名+年份+`p.`/`Abb.`/`fig.` 引用块，修复目前误判为 `heading` 的问题）、`key_header`（`Bestimmungsschlüssel`）、`zoogeography`、`index_entry`（`Register` 书末索引）。

  2. **多语言分流路由（650 页实测效益）**：

     * **0 Token 保护（47.6% 区块 / 28.7% 字符）**：种标题、异名表、21 页 `Literaturverzeichnis`、9 页动物地理名录、18 页 `Register`。

     * **模板直出（3.2% 区块）**：目/超科/科/属标题查表映射。

     * **Google 翻译 + 术语库（30.3% 区块 / 40.7% 字符）**：电报体形态描述、`Färbung`、`Röhre`、`Verbreitung`、检索表与图注。

     * **仅需 LLM 润色（18.8% 区块 / 29.5% 字符）**：`I. Allgemeiner Teil`、`Ökologie`、`Biologie`、`Taxonomische Bemerkung`。

  3. **模块化直接驱动排版**：

     * 支持从 `TaxonTreatment` 树直接渲染 DOCX/HTML：自动给 `scientific_name` + `synonymy` 中的学名套斜体（告别脆弱正则猜属名）、自动统一 `Colour:`/`Distribution:`/`Ecology:`（或中文 `体色：`、`分布：`、`生态：`）粗体引导头与缩进、**由结构树与实际排版页码自动生成全书目录与 18 页 `Register` 索引**。

## 五、P0 优先级：排版秒级预览与 DOCX 构建提速

### 任务 1：新增 `booklayout` 局部快排预览（`--pages` / `--taxon` / `--chapter`）与即时 HTML 预览

* **目标文件**：[booklayout/cli.py](https://drive.google.com/file/d/1alzv9gopI9cc597XDhTfGjb6QvptVrwp/view?usp=drivesdk)、[booklayout/builder.py](https://drive.google.com/file/d/1w7HpAdnPBnpJ3PeF12I9rX9MLVz_mFjD/view?usp=drivesdk)

* **具体改动**：

  1. 在 `booklayout build` 新增 `--pages <SPEC>`（支持 `277`、`275-280`、`12,45-48`）、`--taxon <ID_OR_NAME>`、`--chapter <NAME>` 与 `--preview`（自动跳过 `front_matter`、目录与 `render_index`，默认前后各带 1 页检查跨页接缝）。

  2. 新增 `booklayout preview` 子命令：

     * 默认 `--format html`：直接读取 `TaxonTreatment` 或 `aligned.json` + 对应 `source_figure_crops/`，套用 `@page { size: 170mm 240mm; }`、版心 `134mm`、右对齐点线检索表与图注样式，耗時 **< 50 ms**（实测 5 物种仅 **0.20 ms**），支持 `--watch` 自动刷新。

     * 加 `--pdf` 时走局部 DOCX + LibreOffice 转档，约 **1.4–2 秒** 核对真实断行与词距。

  3. 完整交付维持既有两遍 `build -> map-pages -> build -> qa -> check`。

### 任务 2：精简 `builder.py` 的 `add_runs()` 冗余 XML 写入

* **目标文件**：[booklayout/builder.py](https://drive.google.com/file/d/1w7HpAdnPBnpJ3PeF12I9rX9MLVz_mFjD/view?usp=drivesdk)

* **具体改动**：

  * 默认值（`size == 10.5`、`bold is False`、`ital is False`、`color is None` 且不含汉字）直接继承 `Normal` 样式，不重复写入 `w:rPr` 子节点（650 页实测 DOCX 生成提速 **1.6×**，且文件体积减小 10%）。

  * 仅在非默认字号、粗体、斜体、自定义颜色或 `_CJK.search(chunk)` 命中时写入对应属性；属名正则按 `genera` 集合 ID 缓存。

  * 若输入为 `TaxonTreatment` 结构化数据，优先使用结构字段中的学名列表做精确斜体标注，跳过全表正则扫描。

### 任务 C：标准分类学检索表（Dichotomous Key）确定性排版引擎与拓扑 QA

* **目标文件**：新建 `booklayout/key_renderer.py`、`transqa/key_qa.py`；修改 [booklayout/builder.py](https://drive.google.com/file/d/1w7HpAdnPBnpJ3PeF12I9rX9MLVz_mFjD/view?usp=drivesdk)（取代脆弱的 `key_para()` / `tabbed()` 正则切分）

* **根因诊断（为何 Cursor / DeepSeek 总是排不好检索表）**：
  1. 现有 `builder.py` 的 `key_para()` 依赖正則 `LEADER_RE`（`....`/`……`）和仅匹配英文 `(p. 136)` 的 `_TARGET_SUFFIX` 从自由文本里“猜”左右两半；大模型翻译或微调时只要漏掉点线、改写页码（如德文 `S. 42` 或中文 `第 42 页`），整行就退化为普通段落，右对齐点线和目标彻底丢失。
  2. `tabbed()` 硬编码了西班牙志书版式（仅首行缩进 4mm、折行顶回左页边距），不符合 *Die Tierwelt Deutschlands*、*Zootaxa*、*中国动物志* 通行的**悬挂缩进（Hanging Indent）**标准，导致序号被淹没在多行文字里。
  3. 缺少“项对（Couplet）”概念：未设成对防拆页（`keep_with_next`）与项对间留白，也未在第二遍排版时自动重映射检索表目标里的页码。

* **核心思路：剥夺大模型的“排版控制权”，改为“结构化数据契约 + 确定性引擎渲染”**：
  1. **强结构化 `DichotomousKey` JSON 契约**（翻译/OCR 阶段只填字段，**严禁大模型手打点线、空格或制表符**）：
     ```json
     {
       "key_id": "key_polynoidae_genera",
       "title": "Key to the genera of Polynoidae",
       "style": "bracketed_hanging",
       "couplets": [
         {
           "id": "1",
           "backref": "2",
           "leads": [
             {"label": "1 (2)", "diagnosis": "15 pairs of elytra; prostomium with distinct cephalic peaks", "target_type": "taxon", "target_label": "Harmothoe", "target_taxon_id": "HS1996_G012", "source_page": 42},
             {"label": "2 (1)", "diagnosis": "12 pairs of elytra; prostomium without cephalic peaks", "target_type": "couplet", "target_id": "3"}
           ]
         }
       ]
     }
     ```
  2. **确定性 DOCX / HTML 渲染引擎（`booklayout/key_renderer.py`）**：
     * **支持 3 种出版级预设模板（可在 `BookMeta` / CLI 切换）**：
       * `bracketed_hanging`（平行式悬挂缩进，最推荐，适配 *Die Tierwelt Deutschlands* / *Zootaxa* / *中国动物志*）：序号列固定左缩进（如 `13 mm`），段落 `left_indent = 13 mm`、`first_line_indent = -13 mm`，`13 mm` 处设左对齐 Tab 承接特征文本，版心右缘（`134 mm`）设右对齐点线 Tab（`WD_TAB_LEADER.DOTS`）承接目标编号或斜体学名+页码。
       * `indented`（阶梯缩进式，适配老英美志书）：按树深度自动递增 `left_indent = depth * 6 mm`。
       * `table_3col`（无边框三列表格保底模式，彻底杜绝极长特征描述在 Word/LibreOffice 中点线折行错位）：左列序号（`13 mm`）、中列特征描述（自动换行不侵入两侧）、右列右对齐目标（`28 mm`）。
     * **成对排版护栏**：同一 `couplet` 内的第一条（`a`）强制 `keep_with_next = True` 且 `space_after = 0pt`（防止一对二歧项被拆到两页）；最后一条（`b`）设 `space_after = 3.5pt` 拉开项对呼吸感；目标端整体设为不可断词（`_atomic_target`）。
     * **页码自动重映射**：第二遍构建时，根据 `target_taxon_id` 或 `source_page` 查 `page_map` 自动替换为新排版页码（如 `(p. 42)` → `(p. 58)`），不再沿用旧原书页码。
  3. **检索表拓扑与版式自动 QA（`transqa/key_qa.py`，构建前硬拦截）**：
     * 校验每对 `couplet` 均含 ≥ 2 条 lead、序号连续无跳跃；
     * 校验所有 `target_type == "couplet"` 的目标编号存在且无自环/死循环（图论可达性检查，确保从 `1` 出发可达所有终结物种）；
     * 校验所有 `target_type == "taxon"` 的学名与 `TaxonTreatment` / WoRMS 匹配且斜体正确；
     * 若上游仍传入旧格式纯文本检索表，先经专用解析器归一化为 `DichotomousKey` JSON 并跑通拓扑 QA，失败直接报错指出具体项号，不再静默退化为普通段落。

* **验收标准**：
  * Cursor / DeepSeek 仅需输出/编辑标准 `DichotomousKey` JSON（或在 Markdown 中用极简 3 列语法 `序号 | 特征 | 目标`），无需操心任何点线与缩进；
  * 渲染出的 DOCX/PDF 中，长多行特征描述严格垂直对齐在序号右侧，项对不被跨页拆分，所有目标右对齐且页码自动更新为新书页码；`transqa/key_qa.py` 能 100% 拦下断链、漏号与退化段落。

## 六、P0 优先级：校对极省 Token 优化

### 任务 3：修复 `transqa/taxoblocks.py` 的 `risk()` 误报

* **目标文件**：[transqa/taxoblocks.py](https://drive.google.com/file/d/1pu_9e7PFDgtDqm6zP_rezo3_Ino-bS1A/view?usp=drivesdk)、[transqa/terms.py](https://drive.google.com/file/d/18eVa9B1QarkODhD12WZBB2nY2mgy1xh4/view?usp=drivesdk)

* **具体改动**：

  1. **数字归一化**：改用 `transqa.core.numbers()` 统一处理德文小数逗号（`0,5` ↔ `0.5`）与千分位；新增多语言月份映射白名单（`Januar–Dezember` / `January–December` ↔ `1–12月`），消除最后 20% 德→中/英→中月份数字误报。

  2. **目标语自适应长度比**：短于 40 字符不做长度比检查；`tl.startswith("zh")` 用 `(0.18, 0.70)`，拉丁语系间用 `(0.55, 1.70)`。

  3. **CJK 术语匹配修复**：检测含 CJK 术语时去掉 `(?<!\w)...(?!\w)` 词边界。

  4. **收紧 `_EPITHET` 误报**：排除常见英文形态学首词（`Dorsal`, `Ventral`, `Lateral`, `Anterior`, `Posterior`, `Median`, `Body`, `Prostomium` 等）。

### 任务 4：校对改为“跨页紧凑打包 + 局部窗口 Judge + 精简输出”

* **目标文件**：[scripts/auto_translate.py](https://drive.google.com/file/d/1sLo_76p0664ixWw5nszh4pbTvqeYcm-r/view?usp=drivesdk)、[scripts/fast_book.py](https://drive.google.com/file/d/13BtUWmxXfHYxrmFuQ3eQZkszpo-qCbP9/view?usp=drivesdk)、[scripts/gtrans.py](https://drive.google.com/file/d/13Ay36MQEW44c5IvHEtKJ6Krb19hKVAQt/view?usp=drivesdk)

* **具体改动**：

  1. **跨页紧凑打包**：`stage_revise()`（Lean）与 `stage_check()`（`--risky-only`）先全书分流，再将待检段落带 `⟦pN_sM⟧` ID 按 `3,000–4,000` 字符动态打包，杜绝 1 句话发一次 API。

  2. **局部窗口 Judge**：`--lean` 默认 `--verify-mode judge`（第一模型 `edits=[]` 则 **0 token 跳过第二模型**）；触发复核时仅传候选 edit 所在段前后各 1 段，再省 70%–85% 复核 Token。

  3. **分层异模型复核**：仅对 `negation_risk` 页、检索表页与 `critical` 候选启用异模型复核。

  4. **关闭冗余辅助调用与压缩输出**：`--lean` 默认 `--no-entities`；省 Token 场景走 `--llm-mode edits`（差量 JSON 改动），`max_tokens` 统一接入 `token_economy.out_budget("json")`，前置接入 `transqa.terms.normalize()` 做 0-token 清理。

## 七、P1 优先级：Google 翻译极速与稳定优化

### 任务 5：升级 `gtrans.py` 连接池、批次缓存与术语预取

* **目标文件**：[scripts/gtrans.py](https://drive.google.com/file/d/13Ay36MQEW44c5IvHEtKJ6Krb19hKVAQt/view?usp=drivesdk)、[scripts/auto_translate.py](https://drive.google.com/file/d/1sLo_76p0664ixWw5nszh4pbTvqeYcm-r/view?usp=drivesdk)

* **具体改动**：

  1. **标准库 Keep-Alive 连接池**：以 `threading.local()` 维护 `http.client.HTTPSConnection` 长连接（支持 `gzip` 解压与断线自动重建重试一次）。

  2. **SQLite 缓存批次化**：`PRAGMA synchronous=NORMAL`、`Cache.missing_keys()` 每批 500 键 `SELECT IN` 预查、`Cache.put_many()` 每 30–50 笔或 2 秒批次 `commit`。

  3. **术语探测并入并发预取**：将所有 `HARD` 术语并入 `g.prefetch()`，消除主循环中同步慢等。

  4. **双端点分流与自适应并发**：分摊至 `translate.googleapis.com` 与 `clients5.google.com`，单端点 429 独立冷却；短段支持 `clients5` 多 `q=` 批次查询。

  5. **修复 `stage_draft()`** $O(N^2)$ **去重**：改为 `send_set = set(send)`。

## 八、P2 优先级：多进程并发安全与分类学 QA 补完

### 任务 6：修复多进程 `usage.tsv` 写锁、跨进程预算与 API Client 复用

* **目标文件**：[scripts/llm_engines.py](https://drive.google.com/file/d/1npnThJRT4S28Nw83NYQLKwlKiEcOgatG/view?usp=drivesdk)、[scripts/token_economy.py](https://drive.google.com/file/d/1opOJ4fZfjP5n9dG7GhO4rNv1_e1nlNHw/view?usp=drivesdk)、[scripts/auto_translate.py](https://drive.google.com/file/d/1sLo_76p0664ixWw5nszh4pbTvqeYcm-r/view?usp=drivesdk)、[scripts/fast_book.py](https://drive.google.com/file/d/13BtUWmxXfHYxrmFuQ3eQZkszpo-qCbP9/view?usp=drivesdk)

* **具体改动**：

  1. `log_usage()` 加跨进程文件锁（`fcntl.flock` / `msvcrt.locking`）。

  2. `_deepseek()` 复用 thread-local `anthropic.Anthropic` Client，以显式参数 `thinking: bool | None = None` 取代多线程改 `os.environ`。

  3. `_ask_json()` 区分 JSON 解析失败（立即重试）与 API 429/5xx（指数退避 + jitter）。

  4. `apply_edits()` 改为按页字典替换再重组；`fast_book.py chapters` 结束后自动汇总各章 `report.md`、`usage.tsv` 与 `human_review_queue.csv`。

### 任务 7：补齐 `transqa/taxonomy.py` 动物学三名法与检索表兼容性

* **目标文件**：[transqa/taxonomy.py](https://drive.google.com/file/d/10Ybr-ve0ICdufn2pi9fqdkt1chdcwXYy/view?usp=drivesdk)

* **具体改动**：

  1. `latin_names()` 支持 ICZN 动物学三名法及 `cf.`、`aff.`、`s.l.`、`s.str.`。

  2. `key_edges()` 与 `key_structure()` 统一兼容无粗体 `1(2)` 与 `1a.`/`1b.` 检索表格式。

  3. 并发改写前注入只读的“上页末段 + 最近上级分类标题（科/属名）”作为 `CONTEXT (do not translate)`。

## 九、建议给 Claude Code 的分批执行顺序

1. **第一批（立即可见排版与翻译提速）**：任务 1（`booklayout` 局部预览 + HTML 即时预览）+ 任务 2（`add_runs` 样式继承）+ 任务 C（标准检索表确定性引擎与拓扑 QA）+ 全局语言路由默认策略（非英先转英，英直转中）。

2. **第二批（立刻省下大部分校对 Token）**：任务 3（`taxoblocks.risk()` 零误报 + 月份白名单）+ 任务 4（跨页打包 + 局部窗口 Judge）+ 任务 B（`taxo_labels.toml` 德文补丁与 `TaxonTreatment` 模块化分流）。

3. **第三批（老文献 OCR 共识校正）**：任务 A（`docstore/consensus.py` 书内高覆盖实体共识 + `docstore/taxofix.py` WoRMS/GNVerifier/Crossref 零 Token 校对 + 行级 VLM 精准裁剪升级）。

4. **第四批（Google 翻译极限提速与多进程加固）**：任务 5（`gtrans.py` 长连接 + 批次缓存 + 术语预取）+ 任务 6 & 7（并发锁与分类学 QA 补完）。

每批完成后执行 `python3 -m pytest -q tests yiku/tests`、`ruff check`、`mypy`，确认全绿后再进入下一批。