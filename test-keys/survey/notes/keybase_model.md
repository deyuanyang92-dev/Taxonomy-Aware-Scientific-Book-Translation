# keybase_model（KeyBase 新数据模型，Laravel）

## 1 定位与许可证
- KeyBase 重写版的数据模型 + 导入导出动作；`keybase_model/README.md:3-30` 称 key = leads 图（邻接表）+ items 叶。
- 许可：`composer.json` 声明 MIT（`grep license composer.json`）；仓库无 LICENSE 文件，未确证。
- 只做“已写成的检索表”的存储/校验/导出，不从性状矩阵建表（无建表算法）。

## 2 输入格式
- CSV/TSV 三列 `from,statement,to`；to = 数字（跳到下一对句）或名称（item）。示例 `docs/examples/key-import-example.csv:1-4`：
  `1,"Plants to 1 mm tall; ...",2` / `2,"Costa excurrent ...","Acaulon chrysacanthum"`
- 子表：第 4 列 `subkey`，须有表头 (`docs/processing-keys.md:529-545`)。
- 捷径 shortcut：to 列写 `科:种`，如 'Ginkgoaceae:Ginkgo biloba' (`README.md:60-72`)。
- DB 表：keys / leads(id,parent_id,statement,subkey_id,node_name) / items / lead_item(多对多) / key_item / filters (`database.dbml:68-160`)。

## 3 输出格式
- 导出 `from,statement,to[,shortcut]`，to = couplet 号或 item 名 (`app/Actions/Exports/GetKey.php:45-65`)；zip 打包 (`CreateZipArchive.php`)。
- 另有 nested sets 左右值 (`CreateNestedSets.php:35-66`)，供缩进/括号式渲染。

## 4 建表算法
- 无。不选性状、无打分、无权重/多态/数值/缺失处理（未确证：全库 grep 无 character/matrix）。
- 只有版式算法：
  - RenumberCouplets：按出现顺序给 from 重新编 1..n (`RenumberCouplets.php:47-58`)。
  - BalanceKey：先算 nested set，size=right-left，再按 size 升序重排（小枝在前）(`BalanceKey.php:46-63`, `CreateNestedSets.php:51`)。
- 终止条件：叶 = item。支持重编号，不支持回溯（非交互）。

## 5 混合层级能力
- 强：item 可作另一 key 的根 (`keys.item_id/root_id`, `README.md:20-24`)；子表 `leads.subkey_id` 直接跳 key；shortcut 跨多级跳过缺中间 key 的阶元；lead→多 item 多对多 (`README.md:8-14`)。
- 同一 project 内 key 互链；filter 用 item 名单裁剪出所需 key 链 (`README.md:147-190`)。
- 作者倾向不鼓励 reticulation (`README.md:45-58`)。

## 6 校验与错误处理
- 文档分级 (`docs/processing-keys.md:252-760`)：Error = singleton(266)/orphan(327)/dead end(357)/loop(387)/unreachable subkey(627)/chained shortcut(707)/shortcut already in key(689)；Warning = polytomy(297)/reticulation(463)/multi-item lead(749)；Info = subkey、shortcut。
- 导出时校验：to_couplet 必须都在 from 中，否则返回 false (`GetKey.php:24-30`)。

## 7 可借鉴与不足
- 借鉴：①错误/警告/信息三级分类直接做 keykit 校验清单；②item 作子 key 根 + subkey 列 + shortcut 三机制就是“科→属→种”链接的现成规格；③nested set + 小枝在前的平衡排版；④lead↔item 多对多容纳未解决段。
- 不足：无矩阵、无建表；校验靠文档示例而非可复用库；节点号重编后无稳定 ID 映射。
