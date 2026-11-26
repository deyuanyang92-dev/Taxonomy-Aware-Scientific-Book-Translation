# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

`test-keys/` 是检索表（dichotomous key）工具的独立沙盒，位于上层仓库 `Taxonomy-Aware-Scientific-Book-Translation` 内。上层规则（单一主库、脚本优先、只用中英文、不入库书籍文本）见 `../CLAUDE.md` 与 `../AGENTS.md`，同样适用。本目录目前没有自己的 AGENTS.md。

## 边界

- **只改 `keykit/`，不改 `../booklayout/`。** keykit 是从 booklayout 复制出来反复优化的副本，稳定后再集成回去（`keykit/README.md`）。
- `keykit/builder.py`（约 2100 行）是整份复制的旧排版代码，只为其中 `italicize_key_address / split_key_target / tabbed / key_*` 几个函数；新流程（ir/layout/verify）不依赖它，待拆出后删除。
- 根目录的 `key.txt`、`key2.txt`、`code_artifact*.md`、`codex_audit*`、`adv/`、`research/`、`imajima_keys/`、`keycheck_结果/` 是调研与语料材料，不是代码。

## 命令

均在 `test-keys/` 下运行（`keykit` 以包方式调用）：

```bash
python3 -m pytest -q keykit/tests                         # 全部测试
python3 -m pytest -q keykit/tests/test_fix.py::<用例>     # 单个用例
ruff check --line-length 120 keykit/<改动文件>             # 新代码需过 ruff 与 mypy
mypy --ignore-missing-imports keykit/<改动文件>
python3 -m keykit {parse|check|fix|render|verify|make} ...
python3 -m keykit make imajima_keys/keys_2001.json --lang zh --source-style dash -o OUT.docx
python3 -m keykit make key.md --lang en --source-style dash -o OUT.docx
```

- `make` 一条龙：解析 → 修正 → 检查 → DOCX 排版 → soffice 转 PDF → 验版；同名 `.report.json` 记结果，有 critical/major 退出码 1。`--profile p.toml` 覆盖体例参数。
- PDF 转换依赖 `soffice`；验版依赖 PyMuPDF。没有 soffice 时 layout 相关测试应 skip。
- 中文 .docx 交付前按全局规则跑 `python3 /mnt/p/yzz-分类工作流/yzz.py zh check <文件>`。

## 结构（要读多个文件才能看清的部分）

数据流：**输入 → IR → fix/check → layout(DOCX) → PDF → verify**。

- `ir.py`：`KeyIR / Couplet / Lead` 是新流程的统一中间表示。三种读入：`from_markdown`（走 `keygraph.parse_text`）、`from_imajima_json`（`imajima_keys/keys_*.json`，pages[].blocks[]）、`load_irs`（已存的 IR JSON）。
- `keygraph.py` / `keymodel.py` / `keymarkers.py` / `keycheck.py` / `keyfix.py` / `keyalign.py` / `keyrender.py`：从 booklayout 带来的旧层——markdown 偶句解析、去向图与闭合检查、原文译文对齐、PDF 渲染后检查 KR1–KR7。新流程只经 `ir.from_keygraph` 使用其解析结果。
- `profile.py`：体例参数（second_lead / overflow / figref / dest_zh_name）。**随语言与原书取默认，用户可用 toml 覆盖，不做全书二选一。** `for_lang(lang, source_style)` 在原书体例未确证时抛 ValueError，不静默猜。
- `fix.py`：全部确定性修正，不调模型（全角数字、U+3000、点线前空格、学名 NBSP、重编号、yiku 已核中文名）；`check` 给 S1/S2/S3/L7/T2 等结构问题。
- `layout.py`：DOCX 为**两列无框固定宽表**（`tblLayout fixed`、`tblCellMar` 全 0、`tblInd 0`、`tblGrid`、行 `cantSplit`）。这是 2026-11-23 样张验证的方案：段落加越界制表位在 LibreOffice 里会失败，改动前读 `RULES.md` 第六节 2。`overflow=wrap` 与 `fill` 两种排法；fill 需两遍排版，跨页偶句由 make 第三遍在其前拆表分页（LibreOffice 不认表格行间 keep_with_next）。
- `verify.py`：对 PDF 查 L3/L5/L6/L8/L9（去向右对齐、无空白尾巴、偶句同页、右边界统一、点线长度）。按字符位置而非按页找分支。
- 规则文档：`RULES.md` 是规则表（S 结构 / L 版式 / T 字体），每条标「可自动查」与依据状态，第四节体例已由用户审定为 profile 参数；`SPEC_tool.md` 是工具规格；`README.md` 含任务队列与旧 booklayout 的已知缺陷。新增检查要同步到 RULES.md 的编号。

## 进行中的设计

`survey/PLAN.md`（v2）设计「性状矩阵 → 多阶元混合检索表」制作软件和检索表审计，放 keykit 内；`survey/PLAN_v1.md` 与 `PLAN_review.md`（Codex 对抗审查原文）是历史。进度见 `PROGRESS.md`。已定的约束：

- 审计结论必须附具体对句/种对证据；步数、树形效率只作「鉴定效率」，不作分类证据。
- dimoose / monographaR 为 GPL，只借思路；open-delta 为 MPL，公式自行实现，不抄代码。
- `fix.check` 会把合法 DAG（菱形）误报 S3；做 M2 前要换成 `keygraph` 的 `check_graph`。

## 坑

- 工作区未提交改动很多（bench/、test-ocr/、survey/repos/ 等），提交时按路径精确 add，别 `git add -A`。
- `key2.txt` 里引用的 DKey 仓库路径、"联网核验无误"各条未复核，不要当事实引用。
