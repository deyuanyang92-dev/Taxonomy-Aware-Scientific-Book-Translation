# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

仓库规则（唯一主库、docstore 用法、脚本优先、改动规则、技能目录以仓库为准）写在 `AGENTS.md`，下面整段导入；本文件只补命令、坑和跨文件的整体结构。

@AGENTS.md

## 命令

```bash
python3 -m pytest -q tests yiku/tests            # 全套；在 /mnt/p 上很慢（实测超过 3 分钟），改动时先跑单文件
python3 -m pytest -q tests/test_apply_issues.py                       # 单个测试文件（约 0.5 秒）
python3 -m pytest -q tests/test_apply_issues.py::<测试名>             # 单个用例
ruff check <改动的文件或目录>                    # 根目录 line-length 120；yiku/ 自带配置 110
mypy <改动的文件或目录>                          # ignore_missing_imports
scripts/sync_skill.sh --dry                      # 改完 skill/、scripts/、transqa/ 后先看差异，再去掉 --dry 同步到技能目录
```

- 现有代码的 ruff 基线不干净（抽查 `scripts/apply_issues.py transqa booklayout` 有 3 条）；要求的是新增和改动的代码过 ruff、mypy，不是全仓库清零。
- 安装的命令：`docstore`、`taxadb`、`booklayout`（根 `pyproject.toml`）和 `yiku`（`yiku/pyproject.toml`，独立包，自带 `AGENTS.md` 与测试）。`scripts/` 不是包，每个脚本独立运行：`python3 scripts/run_batches.py <书目录> --mode ... `，各脚本顶部 docstring 写用法。

## 容易踩的坑

- **本机有两份检出**：本目录（`/mnt/p/翻译-译作/...`）和 `/root/github/Taxonomy-Aware-Scientific-Book-Translation`（两边都有对方没有的未合并改动，勿互相覆盖；DeepSeek 忙时窗口以 `/root/github` 份为准）。2026-11-19 的省 token 改动（`transqa/taxoblocks.risk()` 去误报、`claude -p` 预算上限，见 `docs/superpowers/specs/2026-11-19-token-optimization-design.md`）已提交到 `/root/github`（提交 2c25d44），并以相同代码移植到本目录工作区（未提交，因本目录这些文件还带别的未提交改动）。`pip install -e` 指向 `/root/github` 份，所以 PATH 上的 `docstore`/`booklayout`/`taxadb` 控制台命令，以及在本仓库外 `import docstore`，用的是后者。要运行本目录的代码，在仓库根目录用 `python3 -m booklayout ...`（已验证 `-m` 会优先取当前目录），或用 pytest。 `docstore keys extract|check`（检索表偶句重建，issue #38，提交 6331907）同样两边都有：`/root/github` 已提交，本目录为未提交的相同文件。
- `conftest.py` 负责让测试用本仓库的 `yiku/`、`docstore/`，并把 `scripts/`、`scripts/publish/`、`scripts/bench/` 追加到 `sys.path` 末尾，测试里直接 `import apply_issues` 这类顶层模块名。`scripts/` 里需要 `transqa` 的脚本自己把仓库根插进 `sys.path`。
- 仓库根的 `yiku/` 是项目目录，真正的包在 `yiku/yiku/`。在仓库根 `import yiku` 得到的是空的命名空间包，要靠 pytest（`conftest.py` 调了路径）或进入 `yiku/` 再用。
- 技能目录里 md 文件在根，仓库里在 `skill/` 下；`run_batches.py` 用 `SKD = SK if (SK / 'RULES.md').exists() else SK / 'skill'` 兼容两种布局，新增脚本读规则文件时照此办理。
- 书、译文、OCR、术语库和资料库数据都在仓库之外（资料库默认 `/mnt/p/翻译-译作/参考资料/_资料库/`，术语库 `~/.yiku/yiku.db`）；每本书的目录结构（`src_en/`、`译文/`、`核译/issues/*.jsonl`、`核译/direct/<章>/…`）在 `skill/SKILL.md` 第 3 节。DeepSeek 凭证走环境变量 `DEEPSEEK_API_KEY` 或 `DEEPSEEK_ENV_FILE`，不入库。

## 整体结构（需要读多个文件才能看清的部分）

依赖方向只向下：资料与知识底座 → 翻译与审校 → 质检与出版。删掉上层，下层照样能用（`docs/architecture.md` 开头的图）。

**知识底座，各自唯一主库、各有 CLI 和测试**
- `docstore/`：本地资料库。`registry.tsv`（登记）+ `pages/<key>/pNNNN.json`（逐页证据：主版本、alternates、history、核对等级）是主库，`docstore.sqlite`（FTS5 检索）可由 pages 完全重建。同一页允许多个模型/引擎的版本并存，按核对等级和 dpi 选主版本。OCR 引擎在 `docstore/engines/`，多引擎共识在 `consensus.py`，校正在 `proofread.py`，OCR 修正与质检规则在 `docstore/rules/*.toml`。
- `yiku/yiku/`：术语库。译名带出处和依据等级（已核/暂定）。`yiku table` 把一章原文需要的术语分成 HARD（必用）和 SOFT（多译名，由译者按语境取舍），注入翻译提示词；`yiku check` 事后查一致性。
- `taxadb/`：物种记述、名称用法的结构化库，来源类型的切分规则在 `taxadb/rules/*.toml`。

**翻译与审校（`scripts/`）**
- `llm_engines.call(engine, system, user)` 是调模型的唯一入口：`deepseek-flash`/`deepseek-v4-pro`（Anthropic 兼容端点；调用前 `deepseek_offpeak.wait_offpeak()` 避开忙时）、`claude-sonnet`/`claude-opus`（`claude -p`）、`codex`（`codex exec`）。用量追加到 `usage.tsv`，预算与 `max_tokens` 档位在 `token_economy.py`。
- `run_batches.py` 是调度器，两种模式：智能体模式（`--engine codex|claude`，按 `核译/batches.json` 渲染 `skill/PROMPTS.md` 模板，模型自己读写文件）；直调模式（`--engine deepseek-*|claude-*`，`direct_mode.py` 把原文切成约 9000 字符的块，每块注入 `yiku table`，产物按块写盘并可续跑）。续跑靠每块旁的 `cNN.meta.json`（引擎、系统提示词、术语表的 sha256）：设置变了就报错停下，除非 `--force`。直调下初译与核译必须是不同模型（`--same-engine-ok` 才放行）。
- 一章的顺序：`split_check`/`split_figures`（图注分离）→ `translate` → `fidelity_check`（确定性，拉丁名、人名、数字）→ `review`（核译，输出 JSONL 问题单）→ **`apply_issues.py` 闸口**（`old` 必须恰好匹配一次；数字和斜体学名不得丢；可重复应用）→ `species` → `final` → `polish`（`polish_guard.py` 指纹闸口 + 另一次请求的语义核验，规则运行时读自 `skill/STYLE.md` 第 6 节）→ `cite`。**所有对译文的修改只能经问题单和闸口进入。**
- `skill/` 里的 md 不只是文档：`RULES.md`、`STYLE.md`、`PROMPTS.md`、`domains/*.md` 会被脚本在运行时读进提示词，改它们就改变了流水线行为。新领域复制 `skill/domains/_模板.md`。

**质检与出版**
- `transqa/`：共用 QA 层。`check_all(src_md, tgt_md, sl, tl, domain)` 返回 `Issue(code, severity, …)`，`critical`/`major` 为阻断；通用检查在 `core.py`，领域插件注册在 `transqa/__init__.py` 的 `PLUGINS`（现有 `taxonomy`），语种表在 `languages.py`。调用方是 `scripts/auto_translate.py` 和 `scripts/apply_issues.py`。
- `booklayout/`：确定性排版 CLI（对齐 JSON → DOCX/PDF）。两遍：`build` 出 PDF → `map-pages` 量页 → `build --map` 重排 → `check`/`qa`/`gate`。细则见 `docs/booklayout.md`。
- `scripts/publish/`：成品阶段工具（`patch_release.py` 定点替换已出版的 docx/pdf、`word_render.py`、`share_pdf.sh`、索引与图注抽取）。在 Windows 上调用要加 `-X utf8`。

阅读次序：`docs/design.md`（原则与分层）→ `docs/architecture.md`（组件与接口）→ `docs/workflow.md`（每章命令和质量门）→ `skill/SKILL.md`（给模型的流程）。
