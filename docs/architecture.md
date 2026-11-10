# 组件架构与接口（v1，2026-11-10）

取代此前「脚本串联」的做法。原则：**每个组件只做一件事、有唯一主库、有自己的命令行与测试；组件之间只通过下文约定的接口交接，不引用彼此内部代码；书和领域的差异全部放配置，不写进代码。**

```
             ┌──────────── 用户、Claude、Codex、其他技能（yzz-compilation / yzz-review / yzz-zootaxa）
             ▼
 ┌─────────────────────┐   ┌──────────────┐   ┌──────────────┐
 │ docstore 本地资料库 │◄──│ taxadb 分类库 │   │ termbase 术语 │（yiku）
 │ 资料登记·文本·检索  │   │ 记述·名称·名录│   │ 定名·出处·等级│
 └─────────▲───────────┘   └──────▲───────┘   └──────▲───────┘
           │ 读页面/检索           │ 读记述            │ 查术语
 ┌─────────┴───────────────────────┴──────────────────┴───────┐
 │ translate 翻译与审校（每本书 book.toml）                      │
 │ 分段对齐 · 术语注入 · 初译 · 异模型核译 · 问题单 · 闸口        │
 └───────────┬──────────────────────────────┬─────────────────┘
             ▼                              ▼
     ┌──────────────┐              ┌──────────────┐
     │ qa 验证       │              │ publish 出版  │
     │ 通用 + 领域插件│              │ md → docx/pdf │
     └──────────────┘              └──────────────┘
```

依赖方向只向下：docstore、termbase 不知道上层存在；删掉 translate，资料库照样能用。

---

## 1. docstore 本地资料库（第一优先，独立产品）

**定位**：用户把任何 PDF（志书、名录、专著、论文、译本、原著）放进来，就能随时检索、取原文、引页码。服务翻译，也服务物种汇编、写新种稿、审稿、日常查资料。

**主库**：`<库根>/`（默认 `/mnt/p/翻译-译作/参考资料/_资料库/`，可配置）
```
_资料库/
  registry.tsv            资料登记（唯一进度来源）
  docstore.sqlite         页文本 + 全文索引（FTS5，中文 trigram）
  pages/<key>/pNNNN.json  逐页证据：文本、方法、质量、核对状态（sqlite 可由此重建）
  images/<key>/           按需渲染的页图缓存（可删）
```

**资料登记字段**：key、path、sha256、pages、kind（志书/名录/专著/学位论文/译本/英文原著/中文论著/论文）、lang、pair（对照书）、domain、tier（依据等级）、title、authors、year、page_offset（印刷页 − PDF 页）、status（各阶段）、note。

**页面核对等级**：`text_layer`（原生文本层）＞ `ocr_verified`（逐页核过）＞ `ocr_sampled`（抽查过）＞ `ocr_raw`（机器初识）＞ `blank`。

**命令**
| 命令 | 作用 |
|---|---|
| `docstore add <文件或目录>` | 登记（按 sha256 去重；改名不重登；内容变即新版本），初判 kind/lang/domain，标「待确认」 |
| `docstore text [<key>…\|--pending] [--workers N]` | 文本化：有文本层直取；扫描页 OCR（默认 RapidOCR 300 dpi，可换引擎）；断点续跑 |
| `docstore quality <key>` | 列低质量页（低置信、乱码、少字、生僻字缺失），生成抽查单 |
| `docstore verify <key> <页> --fix <file>` | 写入人工/模型对原页的校正，页面升级为 ocr_verified，留改动记录 |
| `docstore search "<词>" [--key K] [--kind 志书] [--domain D]` | 全文检索，返回 key、PDF 页、印刷页、片段、页面核对等级 |
| `docstore page <key> <页> [--image]` | 取一页文本（或渲染页图），用于引用和看图核对 |
| `docstore cite <key> <页>` | 生成规范引注（书目 + 印刷页 + PDF 页） |
| `docstore export <key> --txt\|--md` | 导出全文 |
| `docstore status` | 每份资料的页数、文本化进度、各核对等级页数 |

**库接口（Python）**：`open_store(root)`、`store.search(q, **filters)`、`store.page(key, n)`、`store.pages(key)`、`store.doc(key)`。其他组件和技能只用这几个函数。

**迁移**：现有三处页文本——`参考资料/_本地知识库/`（Codex：OCR、校正规则、已核页）、`一些经典译作/知识库/`、`Rouse2022_Annelida/术语库/OCR/`——迁入 docstore。迁移只搬数据、保留各页的方法与核对状态，不重做 OCR；Codex 的 `confirmed_fixes / approved_pages` 转成 `ocr_verified`。迁完后旧目录标「只读，已迁移」。

---

## 2. termbase 术语库（yiku）

**主库**：`yiku.db`。skill 的 `terms/*.tsv` 改为 `yiku export` 生成的只读视图。

**接口**：`yiku lookup / table / check / import / review / export`（已有）；新增 `yiku from-docstore <key>`：对 docstore 中的资料做 `paren`（中文论著）或 `pair`（对照书），产出候选。
**不做**：不存页文本（只存 key + 页码，回 docstore 取原文）。

---

## 3. taxadb 分类数据库

**主库**：`taxa.sqlite`（表 `work / treatment / name_usage`，与 yzz-compilation 对齐）。
**输入**：docstore 的页面；分卷切分规则在配置里（标题格式、小标题词）。
**命令**：`taxadb split <key> --rules <规则.toml>`、`taxadb verify <key>`（列关键字段待看图核对）、`taxadb export --family X --format tsv`（名录）、`taxadb worms`（经 oworms 对照有效名）。
**约束**：用于名录和描述的记录，学名、命名人、年份、数字须为「关键字段已核」。

---

## 4. translate 翻译与审校

**每本书一个 `book.toml`**：书目、领域、类群范围、原文与译文目录、页码范围（参考文献、索引、图版）、模型分配。现在写死在脚本里的值全部移到这里。
**命令**：`translate align | terms | examples | draft | review | issues | apply | status | next`。
**依赖**：docstore（原书页、志书例句）、termbase（术语表）、taxadb（可选，取物种记述作参照）。
**主库**：`<书>/核译/`（段对齐、问题单、裁定、变更日志）、`<书>/状态.json`。

## 5. qa 验证

通用检查：数字、引文、图号、结构计数、残留英文、全角空格。
领域插件：`qa.taxonomy`（学名、命名人年份、检索表编号与跳转、陷阱表回归）。插件接口：`check(src_segments, tgt_segments, config) -> issues`。

## 6. publish 出版

输入：译文 md + `book.toml` + 图库。输出：docx / PDF / 传播版。
步骤：标注（类群中文名、暂定名、英文括注，按规则与 termbase 生成）→ 排版 → 插图浮动 → 量页 → 目录、参考文献、索引 → 检查。
渲染后端可选：Windows Word（默认，版式最好）或 LibreOffice（无 Word 时）。前言、联系方式等放 `book.toml` 指向的文件。

---

## 7. 重构顺序与验收

| 步 | 内容 | 验收 |
|---|---|---|
| 1 | **docstore**：实现命令与库接口；迁入现有三处页文本；登记用户新加的书 | `docstore search` 能检到所有已入库资料；迁移前后页文本逐页一致；新书完成文本化 |
| 2 | termbase：`terms/*.tsv` 改为导出视图；`from-docstore` | 脚本不再直接读 tsv |
| 3 | translate + `book.toml`：把 Rouse 的写死值移到配置 | 用配置重排 Rouse，与当前成品逐字一致 |
| 4 | qa 拆出通用与分类学插件；陷阱表回归 | 已知 9 个陷阱均能自动检出 |
| 5 | publish 配置化；LibreOffice 后端 | 同上逐字一致；无 Word 也能出 PDF |
| 6 | taxadb 改读 docstore；卷33 修切分规则后推广 | 试点 20 条关键字段错误率达标 |

每步一个提交、配测试；不新建任何「临时的第 N 个库」。
