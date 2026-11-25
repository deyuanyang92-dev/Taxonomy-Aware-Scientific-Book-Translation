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
- **模型/审计发现问题必须回流脚本**：跑 `scripts/mine_script_gaps.py`（吃 `qa_issues`/`revise_issues`/`audit`/`check`），看 `script_gaps/backlog.md`。`uncovered`（漏检）先改检测器并补测试，再改书、再重建；禁止只改这一本的 aligned 就当交付完成。
- **排版三阶段**：A `booklayout preview`（html|typst，真图，DRAFT，只改 JSON，产物仅 `work/` 临时目录）→ B 模型核验（`audit`/`keys-check`/`layout_invariants` + 对照原 PDF 抽查乱码）+ 用户看小样确认 → C 仅 `verify` 全绿才 `build` 全书 Word/PDF 并交付。见 `docs/preview_workflow.md`、`docs/booklayout.md`（preview 节）。
- **正式交付必须严格验收零缺陷**：优先 `booklayout verify --aligned … --pdf … --out-dir …`（keys+qa+check+key-report+gate 一次过）。`qa` 默认要 PDF；`check --strict` 要 PDF+检索表格式。试译才可用 `--draft`。有格式/排版/文字缺陷不得交付。
- **verify 未绿禁止出/交付 Word·PDF**：门禁未过不得 `build --pdf`、不得生成/拷贝 DOCX·PDF 到交付目录；迭代禁止往交付目录刷半成品。迭代只用 audit / keys-check / 单元测 / `preview` 小样（`work/`）；勿往 work 刷半成品正式 PDF 干扰目检。交付目录已有未过检旧稿可保留不覆盖或标勿用。
- **禁止排版一次比一次差**：修版必须对照 `docs/layout_invariants.md` 与 `tests/test_layout_invariants.py`；不得删弱测试过关；改前改后 audit/keys 缺陷数不得无故恶化（变差回退）；已确认√样例（属名居中、种记述块序、目录清洗等）必须仍绿。规则详见 `.cursor/rules/delivery-gate.mdc`、`no-break-adjacent.mdc`。

## 改动规则

- 代码改动必须配测试：`python3 -m pytest -q tests yiku/tests` 全过；新代码过 `ruff check` 和 `mypy`。
- 不删除、不覆盖用户数据（原书、译文、术语库、资料库页面）。
- 不把书籍原文、译文、OCR 文本、数据库文件、个人联系方式提交进仓库（见 `.gitignore`）。
- 子任务不得再派生子任务；每完成一步写盘，中断不丢进度。
- 只用中文或英文。结论给依据（文件:行号、书名+页码、DOI）；依据不足写「未确证」。
- 提交信息末尾的署名行由各模型按自身环境添加。

## 防线：修 A 不得破 B

- **只改用户点名的项/卷**；发现旁路问题只记录，不顺手改。
- **版式按书族区分**：先确认 `layout_profile`（见 `docs/layout_profiles.md`）。今岛日本志用 `imajima_ja` / `docs/monograph_layout_ja.md`；其他书类似但有差异，须另建配置，**禁止**把今岛块序套到所有书。
- **改今岛排版前**须陈述物种记述块序：属（仅首次）→ 图N+拉丁学名（标题无中文种名）→ 日名 → 中文种名（日名下）→ 文献（属种斜体、不译）→ 描述 → 分布 → 图版 → 图注；页首上种尾巴 ≠ 新种开头。
- 通识不变量见 `docs/layout_invariants.md`（中文在前、检索表、管道不互撕等）；I4 物种记述块序**仅日本志**。
- 改 `booklayout` 前/后必跑：`.venv/bin/python -m pytest -q tests/test_layout_invariants.py`；不得删旧断言让新补丁过关。
- Cursor 规则：`.cursor/rules/no-break-adjacent.mdc`、`delivery-gate.mdc`（全局）、`.cursor/rules/booklayout-invariants.mdc`（改排版代码时）。
- **小样也要三审**（结构=物种记述序列 / keys+invariants / 对照原页）；未过审不得把路径当可看小样交给用户。
