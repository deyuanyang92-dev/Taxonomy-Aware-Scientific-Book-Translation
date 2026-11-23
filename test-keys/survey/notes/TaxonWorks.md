# TaxonWorks（观察矩阵 + 多入口交互检索 + 手写二叉表 Lead，Ruby on Rails）

## 1 定位与许可证
- 大型分类学 Rails 应用；本仓库为稀疏检出（repos/taxonworks_sparse，仅 app/config/db/lib/spec）。相关三块：多入口检索 `lib/tools/interactive_key.rb`（663 行）、观察矩阵 `app/models/observation_matrix.rb`（353 行）、二叉表 Lead（任务 `app/controllers/tasks/leads/`；Lead 模型不在稀疏树内，未读）。
- 许可证：稀疏树内无 LICENSE，未确证（凭记忆为 NCSA，不可当证据）。

## 2 输入格式
- 数据库而非文件：矩阵 = rows（OTU/CollectionObject 等，`observation_matrix.rb:39-44`）× columns（Descriptor，`:48`）；描述符类型 Qualitative / Continuous / Sample(min,max) / PresenceAbsence / Media / Gene（`:52-72`）。
- 检索参数（`interactive_key.rb:1-200`）：selected_descriptors 串 `123:1|3||125:3|5||135:2||140:3-5`（`:337-348`，`||` 分性状、`|` 分状态、`a-b` 数值区间）、error_tolerance、eliminate_unknown、sorting、identified_to_rank、row/otu 过滤。
- 迁移 `db/migrate/20250907234656_add_observation_matrix_id_to_lead.rb`：leads 增加可空 observation_matrix_id（二叉表可挂到矩阵）。

## 3 输出格式
- JSON（jbuilder）：`app/views/tasks/observation_matrices/interactive_key/key.json.jbuilder`（剩余/淘汰分类单元、性状及状态含 status、number_of_objects、usefulness）；`app/views/leads/api/v1/key.json.jbuilder` 输出手写 lead 树。

## 4 建表算法（多入口，非二叉）
- 淘汰 `remaining_taxa`（`:353-443`）：对每行、每个已选性状算错误数 errors。
  - 定性/有无：行的值集与所选集交集为空 → errors+1（`:369-396`）；Sample 区间重叠判断（`:397-417`，注意 `p1`/`p2` 变量 bug：p2 恒 true、p1 赋值未使用，errors_for_key 对 Sample 实际不会触发，推测，未跑验证）。
  - 缺失：eliminate_unknown=true 则缺失算错误，否则只增 errors_for_key（不淘汰，`:362-367`）。
  - errors > error_tolerance 即淘汰（`:430-431`）；同一阶元(identified_to_rank)只保留一行，聚合到祖先 OTU（`:421,432`）。
- 性状排序 `useful_descriptors`（`:478-661`）：
  - 定性/有无 usefulness = N/k + sqrt(Σ(N/k − nᵢ)²)，N=剩余分类单元数，k=状态数，nᵢ=含状态 i 的单元数（`:584,587,641,644`）。注意分数越大越不均衡，但 'optimized' 升序排序（`:659`）→ 最均衡者在前。
  - 连续 usefulness = N · s · (2 − 测量数/N)，s=(min−min/10)/(max−min)（`:594-595`）；Sample 类同形（`:609-622`）。
  - 状态 status：used / useful / useless；某状态覆盖全部或 0 个剩余单元即 useless（`:574-576`）。
  - 排序：ordered=按 position；weighted=按 −weight 再 usefulness；optimized=usefulness（`:653-660`）。
- 无权重以外的成本；无回溯；每步由用户选性状（交互），不自动生成固定检索表。

## 5 混合层级能力
- 矩阵行可是 OTU，identified_to_rank 把结果上卷到任意阶元的 OTU/分类名祖先（`:421`、参数 `:1-200`），一个矩阵可同时服务科/属/种级检索（多入口）。
- 二叉表 Lead 树可通过 observation_matrix_id 关联矩阵；Lead 子表/跳转机制未读（模型不在树内），未确证。

## 6 校验与错误处理
- 输入校验弱：selected_descriptors 解析无格式检查（`:339-348`）；描述符未在矩阵中则 `next`（`:360`）。
- 错误以 error_descriptors 文字列表回传，如 `性状: 值1 OR 值2`（`:373,382,391`），便于 UI 解释淘汰原因。
- spec：`spec/lib/tools/interactive_key_spec.rb`（未读）。

## 7 可借鉴与不足
- 借鉴：①error_tolerance（允许 n 个性状冲突仍留名单）；②eliminate_unknown 与 errors_for_key 区分“缺失”与“冲突”；③状态均衡度 usefulness 排序，可直接作 keykit 选性状启发式（升序最均衡）；④used/useful/useless 三态；⑤identified_to_rank 上卷；⑥Sample(min,max) 与连续值分型；⑦淘汰原因可解释输出。
- 不足：交互式非自动成表；usefulness 对连续性状启发式粗糙（s 公式用 min 而非区间宽）；Sample 分支疑似 bug；无信息增益；无子表/成本；应用耦合 Rails/DB，难单独复用。
