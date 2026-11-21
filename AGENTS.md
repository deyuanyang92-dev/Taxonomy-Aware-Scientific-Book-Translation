# AGENTS.md · 给所有模型（Codex、Claude、DeepSeek 及其他）

本仓库是一个面向分类学的专业书籍翻译系统：术语有出处、原文可追溯、异模型审校、分类学专用验证。

## 先读

| 文件 | 内容 |
|---|---|
| `docs/design.md` | 顶层设计：原则、架构、数据与状态 |
| `docs/architecture.md` | 组件与接口：docstore、termbase(yiku)、taxadb、translate、qa、publish |
| `docs/workflow.md` | 工作流细则 |
| `skill/` | 模型技能：SKILL.md、RULES、PROMPTS、TERMS、STYLE、领域包 |

## 共用一个本地资料库（docstore）

- 任何资料的登记、文本化、OCR、校正、检索，**只通过 `docstore`**（`docstore --help`；库接口 `from docstore import open_store`）。
- **不得另建**页面库、知识库、OCR 缓存目录或「临时的第 N 个库」。
- 写入一律带 `--by <模型名>`（如 `codex`、`claude-opus`、`claude-haiku`、`deepseek`），或先设环境变量 `DOCSTORE_AGENT`。未带时命令会提醒，写入者记为 `unknown`。
- 多个模型可同时写：同一页的不同版本并存（按核对等级、dpi 选主版本），校正走 `docstore verify`，不覆盖他人结果。
- 发现库外已有的页面数据（pNNNN.json / pNNNN.txt / 含 pages 表的 sqlite），先 `docstore detect <目录>`，再 `docstore import <目录> --adapter <名>` 收编；不要另起炉灶。
- 找原件 PDF 要同时搜 `/mnt/n` 和 `/mnt/p` 两个盘（不少原件在 `/mnt/n/Sandisk/`、OneDrive、微信/QQ 目录）；找到后先比 sha256，再用 `docstore attach <key> <pdf> --check` 绑定到已登记资料（不复制、不移动原件），不要另登记一份。
- 库根默认 `/mnt/p/翻译-译作/参考资料/_资料库/`，可用 `--root` 或 `DOCSTORE_ROOT` 覆盖。

- OCR 引擎或参数评测前，先读 `docs/ocr_tool_survey.md`、`docs/ocr_hard_scans.md`、`docs/ocr_eval/LEDGER.tsv`，已测的不重复；每次新测试必须追加一行到 `LEDGER.tsv`（日期、引擎/参数、测试集、指标、结果、费用、出处）。子代理做 OCR 调研，提示词必须带这三个文件。

## 技能目录与仓库的关系（以仓库为准）

- `skill/*.md`、`skill/domains/`、`scripts/` 以**本仓库为准**；`~/.claude/skills/yzz-translate/`（Codex 端 `~/.codex/skills/yzz-translate` 指向同一目录）只是副本，不是软链接。
- 改规则、提示词、脚本：先改仓库，提交，再运行 `scripts/sync_skill.sh` 同步到技能目录（复制前逐文件比对并打印差异；`--dry` 只看差异不复制；`SKILL_DIR=` 可指定别的目标）。
- 技能目录里有、仓库里没有的文件（如 `terms/` 导出视图）不动；同步脚本末尾会列出，确认该并入仓库就并入。
- 不要直接在技能目录里改文件：下次同步会被仓库版本覆盖。急用已改了的，先把改动搬回仓库再同步。

## 单一主库

| 数据 | 唯一主库 |
|---|---|
| 页面文本、OCR、校正 | docstore |
| 术语、类群中文名 | yiku（`yiku.db`） |
| 物种记述、名称用法 | taxadb |

其他地方的同类数据都只是导出视图，不得反向当主库改。

## 脚本优先：交付同时改进软件

- 书籍任务同时服务于翻译交付和软件改进。OCR/文本化、切章、翻译调度、审校、术语/结构 QA、图表处理、排版和导出，优先使用本仓库的 CLI 与脚本；不得长期用大模型手工代做可自动化步骤。
- 运行前先核对脚本的帮助、适用输入、产物与限制；先做可检查的小样，再扩大运行。记录执行命令、软件版本、日志和校验结果，保证过程可复现。
- 脚本不存在、失败，或无法保留原始结构（如分类学检索表、图注与插图对应关系）时，先报 GitHub issue 并附复现材料/验收标准，再诊断并修复或实现脚本能力。临时手工结果只能标记为中间稿，不能冒充正式交付。
- 模型主要承担语言理解任务（翻译、核译、疑难裁定）；重复、结构化和可确定的处理交给脚本。新增脚本按下方规则配测试、lint 和类型检查，并把成功流程补入文档或技能。

## 改动规则

- 代码改动必须配测试：`python3 -m pytest -q tests yiku/tests` 全过；新代码过 `ruff check` 和 `mypy`。
- 不删除、不覆盖用户数据（原书、译文、术语库、资料库页面）。
- 不把书籍原文、译文、OCR 文本、数据库文件、个人联系方式提交进仓库（见 `.gitignore`）。
- 子任务不得再派生子任务；每完成一步写盘，中断不丢进度。
- 只用中文或英文。结论给依据（文件:行号、书名+页码、DOI）；依据不足写「未确证」。
- 提交信息末尾的署名行由各模型按自身环境添加。
