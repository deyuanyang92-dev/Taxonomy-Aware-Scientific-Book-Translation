# dichotomousKey (Hao Li, R)

## 1 定位与许可证
- R 包 v0.1.0，"操作已有二歧检索表"：交互式分类、抽取、格式转换；不是建表工具。dichotomousKey/DESCRIPTION:1-9
- 许可证 GPL v3。DESCRIPTION:10；LICENSE:1-2
- README 自述 dk_search/dk_extract 仅适用每节点 2 分支的表。README.md:20-21（"Note"段）

## 2 输入格式
- data.frame 4 列：id（父节点/条款编号）、P（表型描述）、G（基因型/种名/结果）、ref（下一条款 id；0=终止；-1=外部链接）。dichotomousKey/R/dichotomousKey.R:7,17-20；R/dk_as_list.R:11,15
- 同一 id 的多行即同一条款的备选支（一对 lead）。示例片段（R/dichotomousKey.R:17-20）：id=c(1,1,2,2,...) P=c('plants like','animal like',...) G=c('plants','animal',...) ref=c(2,3,0,0,...)
- 可含额外列 link/img/snd（富媒体）。R/print.R:24-32；dk_import.csv 读 CSV。R/print.R:1-3
- 没有性状矩阵输入：检索表需人工写好。

## 3 输出格式
- 结果仍是同结构 data.frame；dk_as_list 转嵌套 list（节点含 prim、pause）。R/dk_as_list.R:2-29
- 交互分类返回所选行。R/classify.R:28。无文本/HTML/DELTA 导出。

## 4 建表算法
- 无。包不构建检索表，不选分裂性状，不打分；多态/缺失/数值/权重/成本一概未涉及（全部 R/*.R 无此类逻辑，已逐文件读）。
- 终止条件仅指遍历时 ref==0。R/classify.R:5
- 回溯：dk_classify 有 'b' 分支但未实现（空操作）。R/classify.R:16-18
- 重编号：dk_reduce 将子表 id/ref 平移到从 1 起。R/dichotomousKey.R:72-79

## 5 混合层级能力（本包亮点）
- dk_append(dk1,dk2,append_to)：把 dk2 的 id 整体偏移 max(ref) 后接到 dk1 中 G==append_to 的行，并将该行 ref 改为新子表入口，即"科表→属表→种表"的嫁接。R/dichotomousKey.R:28-35
- dk_partition 切出某分类群以下子表（BFS 按 ref 收集）。R/dichotomousKey.R:38-70
- dk_is_a 判定从属关系；dk_extract 沿 ref 反查某种的路径性状（逆推）。R/dichotomousKey.R:81-114；R/extract.R:2-12
- 局限：以 G 的字符串匹配定位（重名则错）；偏移用 max(ref) 而非 max(id)，可能冲突（疑似 bug，未实测）。R/dichotomousKey.R:31-33

## 6 校验与错误处理
- 极少：print_dk 检查列名是否为 id,P,G,ref，仅 warning。R/print.R:15-17
- 未检查环、孤儿节点、悬空 ref、每 id 恰 2 支。dk_classify 对输入无验证（re>2 分支为空）。R/classify.R:20-22

## 7 可借鉴 / 不足
- 借鉴：①"id/ref/0 终止"的最小边表模型，易存、易做子表嫁接；②append/partition/reduce 三件套 = 层级拼接、抽取、重编号的清晰操作集；③ref=-1 作"外部链接"；④额外 link/img 列。
- 不足：无建表；无校验；以名字匹配；无回溯；二歧限定；GPL。
