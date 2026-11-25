# Clavis（Artsdatabanken，识别检索表 JSON schema）

> 仓库只含 schema，不含建表/运行算法（Clavis 查看器在别处）。以下均指 `repos/Clavis/`。

## 1 定位与许可证
- 仅是 JSON Schema（draft-07）：描述“分类单元 × 性状 × 状态 × 陈述(频率)”的矩阵式检索表（Clavis.json:2-4,204-232）。README 仅 5 行，给出 PLOS ONE DOI 10.1371/journal.pone.0277752（README.md:1,5）。
- 许可证：MIT，Copyright (c) 2019 Artsdatabanken（LICENSE:1-3）。
- 仓库内无任何建表代码；“建表算法”：未确证（属于查看器，不在此仓库）。

## 2 输入格式（即 Clavis 文件本体）
- 顶层必填：$schema,title,language,license,creator,lastModified,identifier,taxa,characters,statements,persons（Clavis.json:6-18）。
- taxon：id 形如 `taxon:[a-z0-9_]+`（:327-331），可嵌套 children（:814-819），含 scientificName/rank/label(形态型如 male、larva)/isEndPoint/followUp/externalReference（:721-843）。
- character：id,title；类型 exclusive|non-exclusive|numerical，默认 exclusive（:913-922）；分类性状带 states，数值性状必须带 min,max,stepSize,unit（:853-868）；logicalPremise 控制该问题何时出现（:928-933）；userRequirement 提示用户前置条件（:923-927）。
- statement：id,taxon,character,value,frequency 全必填（:1038-1044）；value=stateID 或 [min,max]（:1058-1073）；frequency 数值 0..1（:1074-1079）。
- 示例（据 schema 构造，非仓库原文）：`{"id":"statement:s1","taxon":"taxon:a","character":"character:c1","value":"state:x","frequency":0.9}`

## 3 输出格式
- 输出即同一 JSON（schema 自身是交换格式）。多语言靠 localizedString：字符串或 {语言码:字符串}（:250-266）；媒体可内嵌 base64 或 URL（:372-395）。
- 无独立的“成品检索表”输出规范；二叉/缩进检索表文本：未确证（不在 schema 内）。

## 4 建表算法
- 本仓库无算法：未确证。schema 只定义语义：statement.frequency 描述“该分类单元取此值的频率”（:1074-1076）。
- 多态：同一 (taxon,character) 可有多条 statement，各带频率（schema 结构隐含，:1038-1044）；缺失：不写 statement（语义在 clavis-pipeline 中补充，见该笔记）。
- 数值性状：taxon 给区间 [min,max]（:1058-1073）；权重/成本：未确证（无字段；仅 userRequirement 可提示难度，:923-927）。

## 5 混合层级能力
- taxa 可嵌套 children，陈述挂在祖先上由后代继承（继承语义见 clavis-pipeline verify.py:264-282）。
- isEndPoint：该分类单元为唯一剩余候选时即停止，即使还有子类群（:809-813）。
- followUp：指向外部服务中该类群的下级检索表，即“科表→属表”的跳转（:835-839）。
- 单个 taxon 可用 label 表示同种不同形态（雄/幼体）（:799-807）。多入口/单入口切换：未确证。

## 6 校验与错误处理
- 仅 JSON Schema 约束：ID 正则前缀（:327-370）、additionalProperties:false（:248,845）、frequency 0..1（:1077-1078）。引用完整性、继承冲突等需外部验证（clavis-pipeline/tools/verify.py）。

## 7 可借鉴与不足
- 借鉴：①“矩阵 + 树 + 继承”单一文件；②frequency 0..1 统一表达多态/稀有态；③isEndPoint/followUp 实现分级停止与跨表跳转；④logicalPremise 表达性状依赖（相当于 DELTA 的 controlling characters）；⑤数值性状 [min,max]+unit。
- 不足：无算法；无缺失/“不适用”显式值；无权重/成本字段；跨表链接仅 URL/外部服务，缺本地子表引用；ID 强制 ASCII 小写下划线，中文需另设 label。
