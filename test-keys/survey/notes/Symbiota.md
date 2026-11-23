# Symbiota 动态检索（ident/key.php + KeyDataManager，PHP/MySQL）

## 1 定位与许可证
- Symbiota 标本/名录门户的“动态多入口检索”：以名录（checklist clid）或动态名录为分类单元集，按性状状态过滤种（`classes/KeyDataManager.php:390-440`；`ident/key.php:1-58`）。旧版传统检索表 `ident/key-v1.php`（249 行，未读细节）。
- 许可证：稀疏树内无 LICENSE，PHP 头未见，未确证（凭记忆 GPL-2.0，不可作证据）。

## 2 输入格式
- 数据库表（无文件格式）：kmcharacters(CID,CharName,hid,DifficultyRank,glossid,helpurl)、kmcs(CID,CS,CharStateName,Description)、kmdescr(TID,CID,CS)、kmcharheading、kmcsimages（`KeyDataManager.php:80-83,197-201`）。矩阵单元 = kmdescr 一行(TID,CID,CS)；CS="-" 表未编码（`:58,182`）。多态 = 同一(TID,CID)多行。
- 用户输入：表单 attr[] = `cid-cs`（如 2-3）（`key.php:29`；`setAttrs` `:545-555`）。矩阵编辑器 `ident/tools/matrixeditor.php`（未读）。

## 3 输出格式
- HTML 页：剩余种列表（按科/学名排序，可显示俗名、图片）+ 右侧性状表单（`key.php:194-264`）。无文件导出（未确证）。

## 4 建表算法（无，纯过滤）
- 过滤：每选一个性状加一次 INNER JOIN kmdescr；同性状内多个状态用 OR，不同性状之间 AND（`:427-433`）。不允许错误容忍，不排序打分。
- 性状显示的相关性筛：只显示至少被 relevanceValue（默认 0.9）比例的当前种已编码的性状；无结果则阈值 ×0.9 重试至多 10 次（`:7,29,176-192`）。DifficultyRank 用于显示（`:197`），不参与过滤。
- 无信息增益、无权重、无数值/区间类型（性状均为离散状态；数值需离散化，未确证）。
- 种级限定 RankId 180-220（`:394`），即只含属下-种级。

## 5 混合层级能力
- 弱。过滤单元固定为种(RankId 180-220)；taxon 下拉仅按科或属（UnitName1）缩小集合（`:411-417`）；子名录 fmchklstchildren 合并（`:515-517`）。无科→属→种的串联检索表。

## 6 校验与错误处理
- 输入仅 FILTER_SANITIZE_NUMBER_INT / is_numeric（`key.php:19-33`）；SQL 靠 cleanInStr 拼串（`:420-433`）。矩阵无一致性校验（未确证，未见 check 函数）。

## 7 可借鉴与不足
- 可借鉴：①“相关性阈值”只展示大多数分类单元已编码的性状，避免空性状；②用名录(clid)限定检索范围，keykit 可用区域/类群子集生成局部检索表；③kmdescr 三元组 + CS="-" 未编码的稀疏存储；④性状分组 heading、DifficultyRank（难度）可映射为 keykit 的“成本”字段。
- 不足：不是检索表生成器；无容错；无数值型；固定到种级；SQL 拼接。
