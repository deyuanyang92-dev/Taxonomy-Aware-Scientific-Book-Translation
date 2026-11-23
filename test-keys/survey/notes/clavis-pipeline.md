# clavis-pipeline（Artsdatabanken，把书/表转成 Clavis 检索表的 AI+脚本流水线）

> 路径均相对 `repos/clavis-pipeline/`。它不是“从性状矩阵自动生成二叉树”的建表器，而是“内容构建+校验+合并”流水线；检索时的候选筛选在 Clavis 查看器（不在本仓库）。

## 1 定位与许可证
- 用 AI 代理读源文献，确定性脚本做检查，产出经 schema 校验的 Clavis JSON（README.md:3,5,115-117）。步骤表：build/harvest/digitize/audit/refine/merge/determinability/translate（README.md:35-46）。
- 许可证：MIT，Copyright (c) 2026 Artsdatabanken（LICENSE:1-3）。schema 副本与 Clavis 仓库字节相同（schema/Clavis.json，36001 字节，diff 无差异）。
- 内容建表（选性状/分裂）靠 LLM 判断，脚本只做打分与校验；二叉树分裂算法：未确证（无此代码）。

## 2 输入格式
- 源材料：PDF/页图/表格/已有 Clavis/在线检索表（README.md:15）。中间物 `claims.jsonl`：每条 claim 含 trait、value、qualifier(always/usually/sometimes/rarely/range/comparative/unspecified)、value_num、diagnostic、same_as、quote、page（见 digitize-clavis-key/scripts/score_claims.py:28-52；字段表 skills/harvest-claims/references/claim-schema.md）。
- design.json（性状设计）：characters[{key,title,type,unit,states[{key,title,values[]}],traits[],absent}]、same_as_excludes、frequency_table（score_claims.py:7-26）。
- 频率表 frequency-table.json：always/range/comparative/unspecified=1.0，usually 0.9，sometimes 0.4，rarely 0.1；_secondary：usually 0.3，sometimes 0.6，rarely 1.0（frequency-table.json:3-16）。

## 3 输出格式
- 单个 Clavis JSON（schema/Clavis.json），另有 provenance.jsonl、gates.md、residue.md（score_claims.py:56-58；run_gates.py:2-23）。
- 数值性状：每个分类单元恰一条 statement，frequency 1，value [min,max]（frequency-and-inheritance.md:25）。1 写作 `1`，不写 0.9999（:26）。
- 分类单元默认为扁平列表，层级由合并步骤用分类注册库生成（frequency-and-inheritance.md:30）。

## 4 建表算法（性状/状态/频率/继承）
- 选性状：LLM 设计“单性状、可判定”的性状（partition-protocol.md:5-17：Test A 无重叠、Test B 无空隙）；测量一律数值性状，不得分箱（:24-30）。
- 打分公式（确定性）：claim.trait 归一化后与 design.traits 精确相等才归属（score_claims.py:30-31）；频率=frequency_table[qualifier]；多值时首状态取该限定词频率，其余取 _secondary（:38-40）；数值多 claim 取区间并集（:33-35）。
- 多态：非排他性状每个匹配状态各带频率（:41-42）；排他性状只写匹配状态，其余零由“同级有陈述”隐含，不写零频率语句（:43-44；frequency-and-inheritance.md:23）。0 表示排除，>0 即可达，大小只是弱先验（frequency-and-inheritance.md:7）。
- 缺失/推断：diagnostic 性状使其他分类单元获得 absent 状态（score_claims.py:48-52）；same_as 复制对方陈述，但跳过 same_as_excludes（:53-56）。无法匹配的 claim 进 residue 由人决定（:45-47）。
- 合并：先并集后约化，来源等权；排他性状先来源内交集，再跨来源交集，空交集=真分歧，保留所有值；非排他取并集且频率取最高；数值取区间并集（merge-clavis-keys/SKILL.md:26,63-65）。
- 粗化：贪心合并过细状态，须通过 redundancy.py 检查——无分类单元对失去最后一条分离路径；≥3 条路径的对不降到 3 以下；性状保留 ≥75% 自身分离力（coarsen.py:19-24；redundancy.py:3-6）。
- 权重/成本：无；终止条件：门禁全部归零（run_gates.py:11-23）；回溯/重编号：不适用（矩阵键，无编号）。

## 5 混合层级能力
- 继承：祖先陈述对所有后代有效；后代不得重述同一性状（无覆盖）（verify.py:264-282）。
- 提升（hoist）：仅当某节点所有后代完全一致才上提并从子节点删除，节点只剩一个子则折叠；运行后必须证明每个叶的有效值不变，否则中止（build_hierarchy.py:4-7；hoist_statements.py:2-15）。
- 层级来源：属级分组靠 binomial 首词（infer_hierarchy.py:2-4,24-31）或注册库 rank（build_hierarchy.py:1-3,20-21）。
- 科→属→种的“跳转”由 Clavis 的 followUp/isEndPoint 承担，本流水线未使用这两个字段（grep 无命中）。

## 6 校验与错误处理
- verify.py（357 行）：ID 唯一、引用存在、频率∈[0,1]（:156）、FREQ-EMPTY（:172）、数值区间 min≤max 与 NUM-MULTI（:211）、INHERIT-CONFLICT（:264）、叶向量碰撞 COLLISION（:284-311）、EMPTY-LEAF（:322）；`--without REGEX` 去掉某类性状后复查（如地理）（verify.py:9-12）。
- 门禁：verify、check_bins、claims 审计、roundtrip(零丢失)、redundancy、geography、coverage（run_gates.py:11-22）；roundtrip 将每条来源 claim 分类 survived/narrowed/removed/LOST（roundtrip.py:11-22）。
- 可判定性检查：flag_undeterminable 标出 COMPARATIVE/BUNDLE/RELATIVE/SHADES/NUMERIC-AS-STATES，并附“仅此性状能分开的物种对数”（flag_undeterminable.py:8-23）。

## 7 可借鉴到 keykit 与不足
- 借鉴：①频率定值表（qualifier→数字）固定、不投票；②“0 排除、>0 可达”的最小语义；③排他性状不写零；④碰撞检查=叶向量唯一性，可作建树前置闸口；⑤redundancy（每对分离路径数）与 ≥75% 保留率，可用于性状取舍/成本；⑥roundtrip 零丢失校验；⑦hoist 的“全体一致才上提”规则，适合科→属→种。
- 不足：不产出树形/缩进检索表，无信息增益等打分；缺失只靠隐含；无性状权重与成本；无多入口/单入口模式；性状设计依赖 LLM，不可复现。
