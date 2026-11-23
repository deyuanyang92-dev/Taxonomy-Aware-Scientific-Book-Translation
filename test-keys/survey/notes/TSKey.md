# TSKey（二叉检索表编辑器，TypeScript/Vite）

## 1 定位与许可证
- 浏览器端“二叉检索表编辑器”，自动重编号步骤与图引用，导出 LaTeX/HTML/纯文本/JSON (`README.md:1-5`, `src/exporters/`)。许可 zlib (`LICENSE:1`)。
- 编辑器，不是生成器：无性状矩阵。

## 2 输入格式
- JSON 文档（`jsonExporter.ts`；类型 `src/store/keyStore.ts:47-92`）：
  `Couplet{id,alt1,alt2,branch1,branch2}`；`Branch = linked{targetId} | unresolved{couplet} | taxon{taxonId} | taxonDraft{name} | empty` (`:47-60`)。`Taxon` 含学名/作者/异名/描述/分布 (`:82-92`)。
- 纯文本 tab 分隔：`1.<TAB>描述<TAB>去向`，第二支以“—”，`...` 表空去向，`___` 表空描述 (`importers/plainTextImporter.ts:6-14`)。
- 导入容错：点线引导、PDF 断行、1a/1b、“2 (1)”回指、编码识别 (`:193-199, :246-280, :110`)。

## 3 输出格式
- HTML、LaTeX、纯文本、JSON；全部由 `keyDocumentModel.ts:1-8` 的单一解析模型驱动（解析一次，各导出器只做格式化）。

## 4 建表算法
- 无性状选择。只有版式算法 `autoOrderCouplets` (`src/store/coupletOps.ts:267-418`)：
  - 每对句 branch 分级 rank：taxon=1 < linked=unresolved=2 < broken=empty=3 (`:277-283`)；rank 大者换到 alt2，终端支排前。
  - 同 rank=2 时比较子树深度 `1+max(d1,d2)`（记忆化，visited 防环；未解析号当作深度）(`:294-312, :331-347`)，浅者先。
  - 然后迭代前序 DFS 重排，孤立/环子图追加 (`:371-417`)。
- 编号：couplet 号即显示序，id 永久不变；插入/删除自动重编号及文本引用（README 声称，实现在 `store/keyStore.ts`，未逐行读）。有 undo/redo。
- 多态/缺失/数值/权重/成本：不适用。

## 5 混合层级能力
- 无子表、无多入口。去向只能是本表步骤或分类单元；taxon 记录有 id，可挂描述 (`:82-92`)，但不跳转别的表。

## 6 校验与错误处理
- `diagnoseKey` (`keyStore.ts:240-`)：
  - error：指向不存在步骤、自环（Choice A/B loops directly）、无效/已删除目标。
  - warning：分支未完成、孤立（从 1 号不可达）、1 号被回指、汇合 Convergence（多父）、图引用丢失。
- `computeReachableNodes` 栈式可达 (`:137-158`)；`computePathFromRoot` BFS 求最短路径并容环 (`:178-235`)。

## 7 可借鉴与不足
- 借鉴：①Branch 联合类型把“已链接/未解析/分类单元/草稿/空”显式化，导入时容错降级 (`accToBranch`, `plainTextImporter.ts:304`)；②“一次解析模型 + 多格式 formatter”架构；③终端支前置 + 浅支前置的排版启发式，可作 keykit 后处理；④id 与显示号分离。
- 不足：仅二叉；无多路/子表；无矩阵；排序用启发式深度而非信息量。
