# keybase（KeyBase 旧版，CodeIgniter PHP）

## 1 定位与许可证
- 皇家植物园 Victoria 的检索表托管站；上传已有 CSV/TSV/LPXK，存库，在线展示。许可 Apache-2.0 (`keybase/LICENSE:1-3`)。
- 不从矩阵建表；`keybase-ws/`、`keybase-docs/`、`keybase-redevelopment/` 是同系列但本笔记只读 keybase。

## 2 输入格式
- 分隔文本三列 from / leadText / to (`libraries/KeyUploadService.php:128-132`)；from 去掉 ':' 和 '.'。
- LPXK（Lucid/Pathfinder XML）解析 (`KeyUploadService.php:71-116`)。
- to 非数字 = item 名 (`:139-147`)；`{...}` 写在 item 名中 = link-to 外部 key (`ErrorCheckService.php:143-148`)。

## 3 输出格式
- 库表 keys/leads(ParentID,NodeNumber,ItemsID)/items；API/导出见 `ExportService.php`、`keybase-api-1.1.0.yaml`（未逐行读，格式细节未确证）。

## 4 建表算法
- 无。上传时把平面 from/to 转成树：从 firstStep 递归 `nextLead`，若 goto 属于 stepIDs 则下钻，若属于 itemIDs 则落叶 (`KeyUploadService.php:382-441`)。
- 同一对句被多处引用时，分支按引用次数复制（reticulation 被展开成树，`nextLead` 无已访问检查）。
- 无打分/权重/回溯；节点号 NodeNumber 递增 (`:342, :405`)。

## 5 混合层级能力
- 弱：靠 item 名与 `{link}` 文本链接别的 key，无 subkey 字段 (`keybase_model/README.md:34-44` 称旧版不支持子表)。
- Filter 全局名单筛 key (`libraries/FilterService.php`，细节未确证)。

## 6 校验与错误处理
- `ErrorCheckService::checkForErrors` (`:17-117`)：
  - 错误：too-few-columns(:67)、singleton-leads(from 出现<2,:72-74)、orphan-couplets(:78-79)、loops(:84-85)、dead-ends(to 为数字却无对应 from,:93-94)、link-to-errors(:96-97)。
  - 警告：polytomies(>2,:75-76)、reticulations(:87-88)、incorrect-link-to-format(:99)、possible-dead-ends(to 不像 Genus species,:102-103)、will-not-key-out(:105-107)。
- 环检测：DFS 带 path，goto 在 path 里记 loop (`:119-152`)。

## 7 可借鉴与不足
- 借鉴：同一套错误码可直接移植；“possible-dead-ends”用学名正则猜 to 是否合法，keykit 可换为对照分类表。
- 不足：全是字符串/数组 O(n²) 查找；reticulation 复制展开会膨胀；无子表。
