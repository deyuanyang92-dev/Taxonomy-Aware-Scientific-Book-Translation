建议将系统收敛为：**可追溯的段落状态机＋统一 QA＋受预算约束的模型路由＋唯一修改闸口**。保留“Google 初稿→便宜模型改写”的成本优势，但将**全文异模型意义核对、完整覆盖、失败阻断发布**设为不可降级条件。

本次仅做只读审查及内存探针，未修改文件，未运行会写入临时文件的完整测试，也未重新压测翻译服务；忽略了正在修改的 `ppocr*.py`。

**现状已经具备可复用组件，主要问题在于它们尚未形成一致的质量与状态契约。**

| 主要缺口 | 依据与实际风险 | 建议 |
|---|---|---|
| 通用语言参数覆盖不了底层假设 | [qa.py:9](/root/github/Taxonomy-Aware-Scientific-Book-Translation/scripts/qa.py:9) 按英文残留、中文标点检查；[yiku/db.py:35](/root/github/Taxonomy-Aware-Scientific-Book-Translation/yiku/yiku/db.py:35) 主表固定 `en/zh` | 核心统一 `source_lang/target_lang`；语言规则独立配置；在 **yiku 原主库内**扩展多语言词形与概念关系 |
| QA 插件停留在设计层 | [architecture.md:133](/root/github/Taxonomy-Aware-Scientific-Book-Translation/docs/architecture.md:133) 已定义插件，但护栏分别散落在 auto、gtrans、fidelity、apply 中 | 抽成可导入的纯函数库，各入口只负责调度 |
| 护栏存在漏报与误报 | [auto_translate.py:282](/root/github/Taxonomy-Aware-Scientific-Book-Translation/scripts/auto_translate.py:282) 主要检查缺失数字、斜体和部分检索表格式；残留检测未充分考虑目标文字系统 | 数字双向检查、段落映射、学名出现次数与位置、检索表图结构共同验证 |
| 续跑可能复用过期结果 | [auto_translate.py:489](/root/github/Taxonomy-Aware-Scientific-Book-Translation/scripts/auto_translate.py:489) 按改写文件存在续跑；检查缓存摘要也未包含检查引擎 | 所有阶段按完整依赖指纹复用；原文、语言对、规则或术语变化必须失效 |
| 失败有记录，却不一定阻止产物生成 | [auto_translate.py:559](/root/github/Taxonomy-Aware-Scientific-Book-Translation/scripts/auto_translate.py:559) 记录解析失败，随后仍生成 `checked.md`；[apply_issues.py:108](/root/github/Taxonomy-Aware-Scientific-Book-Translation/scripts/apply_issues.py:108) 拒绝部分改动后仍返回成功码 | 区分“候选稿”和“通过稿”；未完成、失败、待人工均阻止正式发布 |
| 第二模型只裁定已有问题，无法补足漏报 | [auto_translate.py:564](/root/github/Taxonomy-Aware-Scientific-Book-Translation/scripts/auto_translate.py:564) 仅在第一模型报错后调用裁定模型；夜间改写与找错可能同为 DeepSeek | 第二模型必须逐段检查原文与译文，不能只看第一模型的问题单 |
| 问题单闸口可绕开关键保护 | [apply_issues.py:75](/root/github/Taxonomy-Aware-Scientific-Book-Translation/scripts/apply_issues.py:75) 对“误译、漏译、增译、术语”豁免词数／数字丢失检查；缺少译文版本绑定 | 类型不能豁免事实保护；修改必须绑定段号、旧版本和证据，统一重跑 QA |
| Google 客户端重复且缓存契约不同 | [gtrans.py:127](/root/github/Taxonomy-Aware-Scientific-Book-Translation/scripts/gtrans.py:127) 缓存键只有原文；auto 另有带语言对的实现 | 共用客户端、缓存、限流和错误分类；旧缓存不得无条件迁入多语言缓存 |
| 夜间规则可绕过，重试可能越界 | [llm_engines.py:222](/root/github/Taxonomy-Aware-Scientific-Book-Translation/scripts/llm_engines.py:222) 支持环境变量绕过，时间检查在内部重试之前 | 每次真实请求前检查北京时间；08:00 后禁止新请求及重试，任务延期而非占住 worker |
| 既有能力值得保留 | [direct_mode.py:385](/root/github/Taxonomy-Aware-Scientific-Book-Translation/scripts/direct_mode.py:385) 已有临时文件替换，相关流程也有输入指纹和缺块拒绝合并 | 提炼已有实现，避免另造一套续跑系统 |

内存探针实际确认：`[1,"unexpected"]` 被解析成空问题单；删除无数字正文段、增加数字、调换页序分别通过了相关现有检查；正确的日译中“身体短”被报为原文残留。这些应成为 P0 回归用例。

评测口径也需统一：[model_bench.md:100](/root/github/Taxonomy-Aware-Scientific-Book-Translation/docs/model_bench.md:100) 的结论来自保→英九页样本，约 **$0.25 是改写阶段估算**，不是完整交付成本。用户提供的 16/125 对应采纳率 12.8%、未采纳率 87.2%；代码注释的 12/76 对应未采纳率 84.2%。两批应分别登记，且“未采纳”不完全等于误报，更不能据此计算漏报率。

**目标流程沿用现有 S0–S9，但在 S4 内增加即时护栏，在每次后续修改后重新验证。**

统一状态契约：每个源段具有稳定 ID、docstore 页面版本及位置；每个阶段记录原文、上游译文、语言对、模型配置、提示词、术语快照和 QA 版本的摘要。状态至少包括 `pending/running/done/failed/deferred/needs_human`。只有完整、校验通过的结果可标记 `done`；写盘原子提交，崩溃后回收过期任务租约。

| 阶段 | 输入→输出 | 引擎与路由 | 护栏、通过标准 | 断点续跑 |
|---|---|---|---|---|
| S0 立项 | 原书与需求→统一项目配置 | 无模型；选择语言对、领域包、预算、时间窗 | 检查引擎语言能力；不支持须显式阻断，不能偷偷转经英语 | 配置版本固定；统一 `project.toml/book.toml` 的主入口 |
| S1 解析 | docstore 页面→带位置的段落清单、图表和检索表结构 | 仅经 docstore 解析、OCR、校正 | 所有内容登记为“翻译／保留／排除并说明”；覆盖率100%；关键 OCR 疑点先解决 | 绑定页面版本；仅重建受影响段 |
| S2 术语 | 段落＋yiku/taxadb→相关术语、实体保护信息 | 确定性检索为主；缺口进入查证队列 | 术语带语言、领域、范围、出处、状态；候选不能冒充已核 | 每波次冻结快照；变更按命中段传播 |
| S3 样章 | 代表性开发样本→路由与阈值配置 | 比较 Google＋中档模型组合；Sonnet 少量盲评 | 覆盖叙述、检索表、异名录、标本记录；无未处理重大问题后扩量 | 保存完整配置与结果；不使用最终保留集调参 |
| S4 初译与改写 | 段落→Google 稿→改写候选 | Google 并发；夜间优先 DeepSeek flash 关思考；白天按下表 | 默认约3页并设 token 上限；不切断对句；返回全部段 ID；即时 QA 不过则有界修复或阻断 | Google 按段缓存；LLM 按块检查点；仅重跑失败块 |
| S5 异模型译审 | 原文＋候选→逐段审查回执与问题单 | 优先 codex-sol 全文核对 DeepSeek 改写稿；审核者必须不同于作者 | 每段明确已审；检查遗漏、增译、否定、数量与性状关系；不能以“未报问题”代替覆盖回执 | 回执绑定译文版本；变更后只重审受影响段及关联结构 |
| S6 自动验证 | 双语段＋问题单→结构化 QA 报告 | 通用 QA＋taxonomy 插件 | 检查覆盖、数字、单位、学名、命名人年份、检索表、标签、引用；风险提示逐条处理 | 确定性重算；保留规则版本和证据位置 |
| S7 表述 | 已核候选→局部风格修改提案 | 按需使用已通过 S3 的中档模型 | 默认不做全书再润色；所有改动进问题单；变化部分重走 S5/S6 | 无变更即跳过；按修改范围失效 |
| S8 裁定 | 问题与证据→接受／拒绝／待人工决定 | 普通问题异模型裁定；critical 与实质分歧交人工 | critical 由规则与模型共同识别，不能仅信模型标签；对照扫描件；旧版本不匹配拒绝应用 | 问题 ID、决定、应用记录持久化；不得把缺失裁定当作拒绝结案 |
| S9 发布与回流 | 已批准版本→出版物、报告、反馈 | 确定性导出及版式检查；Sonnet 少量独立抽检 | 覆盖100%、无失败任务、无未决阻断项；出版检查通过 | 固定发布清单与版本；回退到前一批准版本；反馈进入开发陷阱集 |

模型降级应降低速度或延期，不能降低验证要求。

| 条件 | 路由规则 |
|---|---|
| 北京时间22:00–08:00 | 优先 DeepSeek flash 关思考改写；codex-sol 独立全文核对；DeepSeek 报出的修正仍须 codex-sol 裁定 |
| 白天，无紧迫期限 | 完成 Google、术语、自动 QA 和已有稿核对；新改写排队到夜间 |
| 白天必须推进 | 使用通过该语言对 S3 的 Codex／Cursor 中档模型；另一个实际基础模型核对。luna 不再因“白天默认值”自动获得资格 |
| Codex 额度不足 | 使用已验证且模型身份明确的 Cursor 中档模型；不同产品入口不代表不同模型 |
| 独立核对额度耗尽 | 保留候选并延期；不能用同模型自审替代，也不能把 Sonnet 自动提升为批量引擎 |
| 周末或重试跨08:00 | 仍遵守用户22:00–08:00硬约束；当前已发请求可收尾，停止新发请求 |

**今天的调研应按“可验证的工程机制”吸收，而非整体搬入产品。**

| 采纳来源 | 为什么适用 | 落点与最小实现 |
|---|---|---|
| FolioLoom 的覆盖账本、术语波次、发布阻断；[调研:80](/root/github/Taxonomy-Aware-Scientific-Book-Translation/docs/research/2026-11-15/opensource_projects.md:80) | 防遗漏、并发术语漂移、未决稿流出 | 项目状态库保存段 ID、docstore 引用、译文版本与状态；不另建页面库 |
| bilingual_book_maker 的计划预检；booktrans 的截断／错位拒收；[调研:21](/root/github/Taxonomy-Aware-Scientific-Book-Translation/docs/research/2026-11-15/opensource_projects.md:21) | 开跑前发现漏处理区域，失败只重试局部 | 分块 manifest、完整 ID 回执、输出截断检测；覆盖阈值采用100% |
| TranslateBooksWithLLMs 的相关术语注入与定点后修；[调研:33](/root/github/Taxonomy-Aware-Scientific-Book-Translation/docs/research/2026-11-15/opensource_projects.md:33) | 同时减少 token、干扰和无谓重译 | yiku 按语言、词形、领域与上下文筛选；返回命中证据；后修仍经统一闸口 |
| CAT 的可配置 QA、禁用词、标签及一致性检查；[商用调研:253](/root/github/Taxonomy-Aware-Scientific-Book-Translation/docs/research/2026-11-15/commercial_mt.md:253) | 成熟检查项可直接转成规则；自动检查与人工评价必须分开 | `qa.core` 加语言配置；数字区分数量、编号、日期和小数格式。此分工亦见 [memoQ 官方文档](https://docs.memoq.com/current/en/Workspace/edit-qa-settings.html) |
| gnfinder＋gnparser；[调研:273](/root/github/Taxonomy-Aware-Scientific-Book-Translation/docs/research/2026-11-15/opensource_projects.md:273) | 比“所有斜体都是学名”更贴近分类学 | taxonomy 插件保留原字符串、偏移、次数及解析成分；规范化结果只辅助比较，不改写原书用名。[gnparser 官方说明](https://github.com/gnames/gnparser) |
| Google Adaptive、Lara、CAT 的相关范例与已核记忆 | 用少量领域实例改善译法，避免全库注入 | 从已批准译文检索至多3–5例，限定语言对和文本类型；不依赖付费 Adaptive 服务。[Google 官方机制](https://docs.cloud.google.com/translate/docs/advanced/adaptive-translation) |
| 商用 MT 的术语／上下文／任务接口 | 为供应商故障提供替换能力 | 保留统一适配器；DeepL、Azure、Amazon、Yandex、百度、有道、腾讯等只在语言覆盖、试译质量和预算通过后接入 |

| 不采纳的建议 | 理由与替代 |
|---|---|
| TM 相似度≥75%直接复用并跳过核对 | 一个数字或否定词就可能改变诊断；模糊匹配只作范例。精确匹配也须语言、上下文、术语版本和批准状态兼容 |
| 只核对脚本或第一模型标出的疑点 | 无法发现两者都漏掉的意义错误；全文异模型检查保留，额外深审才按风险分配 |
| 只比较规范化学名集合 | 会丢失重复、位置、命名人括号和年份差异；比较带位置的出现记录 |
| 全量数字、地名都隐藏成占位符 | 容易遮蔽数量关系或妨碍合法转写；只保护明确不可变实体，数量仍向模型展示 |
| COMET／MetricX／Phrase QE 分高即通过 | 目标语言及分类学适用性尚需验证；仅作为 P2 人工队列排序信号 |
| 整套搬入小说框架、自动学习模型自己的术语 | 增加复杂度并放大未经核实的译法；借鉴机制，术语仍以 yiku 为准 |

**代码实施应先封住发布与状态漏洞，再增加节约 token 的能力。以下为建议接口，尚未实施。**

| 优先级／模块 | 建议接口与边界 | 测试验收条件 |
|---|---|---|
| **P0 共用 QA**：新增 `qa/core.py`、语言配置；`scripts/qa.py` 留作 CLI | `check(src_segments, tgt_segments, config) -> list[Issue]`；无隐式写入，未知语言规则标记能力不足 | 上述五个内存探针成为回归；段落缺失／重复、新增数字、日中共享文字、合法小数转换正确分类；所有入口结果一致 |
| **P0 taxonomy 插件** | 同一 `check(...)`；校验学名、命名人年份、异名关系、标本编号和检索表图 | 未斜体学名、缩写属名、括号变动、重复名称遗漏、悬空跳转均检出；历史用名不被自动替换为现行接受名 |
| **P0 状态与续跑**：提炼 `direct_mode` | `claim(stage, fingerprint) -> Lease`；`commit(lease, artifact, receipt)`；状态库存运行元数据 | 原文／语言／术语／模型变化导致相应失效；并发不能重复提交；崩溃可恢复；缺块或错序无法发布 |
| **P0 问题单与闸口**：统一 `apply_issues`、auto 内置应用 | `validate_issue(raw) -> Issue`；`apply(issue, decision, expected_revision) -> ApplyResult` | schema 严格；缺严重度、未知 ID、缺裁定不得通过；critical 不自动应用；路径限制、版本冲突、重叠修改、幂等与 dry-run 一致性均覆盖 |
| **P0 Google 客户端**：合并两个 `Google` 类 | `translate_many(segments, sl, tl, policy) -> list[SegmentResult]` | 跨语言缓存隔离；相同请求合并；空响应非成功；429全局冷却；单段失败保留 ID；重启只补缺项 |
| **P0 引擎路由**：`llm_engines`、`deepseek_offpeak`、`run_batches` | `route(task, language_pair, now, budget, provenance) -> RouteDecision`；调用返回结构化 usage | 每次重试遵守时间窗；额度耗尽返回延期；禁止作者与审核者同模型；失败向 CLI 传播；不依赖修改全局环境变量切换思考模式 |
| **P1 yiku 多语言与上下文** | `resolve_terms(text, sl, tl, domain, scope, snapshot) -> list[TermHit]` | 旧数据迁移无损；方向不能凭空反转；词形变化能命中，跨领域歧义不误锁；保留出处与已核状态 |
| **P1 TM／few-shot** | `retrieve_examples(segment, context, limit=5)`；`reuse_exact(segment, policy) -> ApprovedMatch \| None` | 未核稿不得入已批准记忆；近似数字／否定句不能直接复用；保留集不可被检索；TM 为可重建派生索引 |
| **P1 报告与文档** | `build_report(run_id) -> RunReport`；统一旧提示词、配置名、单库描述 | 分开报告字符、token、缓存、重试、耗时、API费用与订阅额度；未知用量不能记成0；所有未决项可定位 |
| **P2 评价与替代供应商** | `estimate_risk(pair, config)`；供应商实现统一翻译接口 | 按语言对验证增益；QE 故障不影响硬护栏；供应商切换不改变段 ID 与证据链 |

实施后的必要验收包括仓库规定的 `python3 -m pytest -q tests yiku/tests`、新增代码的 ruff 与 mypy，以及**另一模型审查代码和测试缺口**。当前测试中“重跑不花钱”仅覆盖 `no_llm=True`，不能证明 LLM 续跑无重复消费：[test_gtrans.py:316](/root/github/Taxonomy-Aware-Scientific-Book-Translation/tests/test_gtrans.py:316)。

**Google 提速以今天主会话的后补实测为依据。报告开头“约100段／分钟是结构性上限”的判断已被后续320段／分钟结果否定。**

| 方案 | 配置与控制 | 吞吐及边界 |
|---|---|---|
| 当前推荐：gtx逐段 | `urllib`，显式语言对，最多8 worker；去重、缓存、预取；健康状态不强加固定间隔 | 实测320段／分钟，样本150段；容量规划暂按 **200–300段／分钟**，5000个未缓存同量级段约17–25分钟，须持续测试验证 |
| 429／5xx降速 | 共享出口限流器；尊重 `Retry-After`，指数退避加抖动，并发8→4→2→1；达到重试预算后延期 | 所有 worker 一起冷却；不能由各线程各自重试形成请求风暴 |
| 缓存与请求复用 | 键含端点、语言对、原文摘要及影响结果的配置；只缓存有效成功响应；原文保留追溯引用 | 减少请求数比盲目加线程稳定；区分缓存命中吞吐和真实网络吞吐 |
| gtx拼段 | 不采用换行拼接再拆回 | 实测仅21段／分钟、100次重试及12组回退，且增加对齐风险 |
| 官方 API 后备 | 使用自有凭证、硬预算及经过验证的适配器 | 免费端点持续不可用时切换；未配置预算则延期 |

实测出处：[google_speed.md:179](/root/github/Taxonomy-Aware-Scientific-Book-Translation/docs/research/2026-11-15/google_speed.md:179)。`requests` 返回429而 `urllib` 正常的原因**未确证**，不能据此认定 TLS 指纹或请求大小就是封禁原因；不实施轮换代理、指纹伪装等规避方案。

若用户授权 `translateHtml`，还须明确凭证使用权并符合执行环境权限；此前被拦截的挂件内置 key 不应抓取、硬编码或自动刷新复用。条件满足后，可增加独立批量适配器：

| 项目 | 条件方案 |
|---|---|
| 起始参数 | 每批最多20段、序列化 UTF-8 请求体保守限制16 KiB、2 worker、批间隔0.5秒；均为待验证参数 |
| 对齐与安全 | 使用字符串数组；HTML escape/unescape；验证数组长度、每项内容和保护标记；不把原文中的 `<` 当标签；失败仅重试对应项 |
| 调整规则 | 明确的大小错误才拆批；429先冷却，不能一律解释为超长；使用同一缓存、状态与限流框架 |
| 吞吐预期 | 调研推算约1200段／分钟，可作为试验目标；4400段／分钟仅是短样本结果，不能承诺持续性能 |
| 回退 | 批量端点失效后回到 gtx 或获准的官方 API；不改变段落身份，不重新消费成功项 |

**最终可靠性依赖持续验证，而不是把一次好成绩固化为永久路由。**

| 风险 | 回退及验证规则 |
|---|---|
| 免费端点封禁、供应商停服 | 熔断、延期或切换已验证适配器；保留原始响应及失败类别；禁止原文回填后冒充成功译文 |
| 模型／订阅额度不足 | 预算分配优先保证核对；限制并发与单任务消耗；额度未知标为未知；缺独立模型时不发布 |
| 模型漂移、别名改变 | 保存实际模型身份及参数；固定开发哨兵集定期复测；模型变更先小批验证，失败退回已批准版本 |
| 术语与分类观点变化 | 原书名称用法保持可追溯；新解释进入注释或候选术语，不静默改写历史事实；只重核受影响段 |
| 保留集污染 | 按书籍／章节／类群分组划分开发集与锁定测试集，避免近重复跨集；测试页及答案排除于 TM、few-shot 和模型可读目录 |
| 在测试页上调参 | 已看过并用于修改提示词的页转入开发集；补充新的未见保留集；不能继续称其为独立测试 |
| 评测偏差 | 按语言对和文本类型分层报告重大错误、漏译、幻觉、术语及结构错误；用人工标注计算查准率／召回率，不以问题采纳率代替 |
| 抽检遗漏高风险短文本 | Sonnet 少量盲评须包括短检索表、异名录和标本记录，不能只抽长正文；隐藏模型标签、随机顺序；抽检通过不证明全书零错 |

发布标准应明确为：**全部内容有处理记录，全部译段有独立核对回执，全部阻断问题已解决，批准版本可复现、可回退**；而“模型判定无错”只是一份审查证据。