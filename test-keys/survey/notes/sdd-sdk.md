# sdd-sdk（identification-resources/sdd-sdk，TDWG SDD 的 TypeScript SDK，实为 Clavis 导入雏形）

> 路径相对 `repos/sdd-sdk/`。仓库仅 3 个文件：package.json、tsconfig.json、src/import/clavis.ts（657 行）；无 README、无 LICENSE 文件、无测试。

## 1 定位与许可证
- package.json 声明 "SDK for TDWG SDD files"，作者 Lars Willighagen（package.json:4,13）；license 字段 MIT（package.json:14）；LICENSE 文件：未确证（仓库内无）。
- 现有代码并不处理 SDD XML：依赖含 xml2js（package.json 依赖段），但源码只有 clavis.ts，SDD 解析：未确证（未实现）。
- 实际功能：把 Clavis JSON 解析为 TypeScript 类型，并开始转成 JSON-LD（clavis.ts:516 parse、:591 convert）。

## 2 输入格式
- 输入为 Clavis JSON 字符串；parse 要求是对象，且 $schema 恰为 `https://raw.githubusercontent.com/Artsdatabanken/Clavis/main/Schema/Clavis.json`（clavis.ts:516-527）。其余校验标 TODO（:528 起 "TODO more validation"）。
- 类型镜像 Clavis schema：Taxon（含 isEndPoint、children、followUp，:97-146）、Character（exclusive|non-exclusive|numerical、logicalPremise、min/max/stepSize/unit，:148-189）、Statement（含 frequency:number，:377-397）、IdentificationKey（:208-292）。
- 示例：同 Clavis 笔记，不重复。

## 3 输出格式
- convert 输出 JSON-LD：只映射顶层元数据（dcterms:title/created/modified/creator、dc:language、ac:providerManagedID 等，:591-640）。
- taxa、characters、statements、persons 等映射均被注释掉，未实现（:644-655）。SDD XML 输出：未确证（无）。

## 4 建表算法
- 无。仅数据类型与格式转换；打分、分裂、多态、权重：未确证（无代码）。

## 5 混合层级能力
- 仅类型层面保留 Clavis 的 children、isEndPoint、followUp（clavis.ts:127-141）；无行为实现。

## 6 校验与错误处理
- 只检查是否为对象与 $schema 值，抛 TypeError（:516-527）。引用完整性、频率范围等：未确证（无）。

## 7 可借鉴到 keykit 与不足
- 借鉴：①Clavis 到 JSON-LD（Darwin Core、DCterms）的字段映射思路，可作 keykit 元数据导出参考；②用 TS 模板字面量类型约束 ID 前缀（:38-78）。
- 不足：基本是空壳，无 SDD 支持，无建表与校验；对 keykit 价值很低。SDD（TDWG Structured Descriptive Data）规范本身需另查官方资料：未确证。
