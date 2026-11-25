# 检索表通用性对抗审核：共用规范（v1，2026-11-23）

## 目的
检索表的抽取、检查、修正、排版要对任何书、任何编号格式、任何语种都成立。
Codex 为攻击方：写样例（corpus）及期望结果，尽量击穿实现。
Claude 为实现方：实现 booklayout/keygraph.py（通用图层），并接入现有入口。
双方互审：Claude 可质疑 Codex 期望值是否合理（须给原书惯例依据）；Codex 审 Claude 的 diff。

## 规范化分支号（canonical lead）
每条分支写成「偶句号 + 字母」：第一支 a，第二支 b，多歧依次 c、d……
- 1 / 1' / 1′ / 1’ → 1a / 1b；1a / 1b → 1a / 1b；1A / 1B 同
- 1 / — / -（横线或 • 表示上一号的备择支）→ 1a / 1b
- 1(3) 括号回指式：1a，且 backref=3（表示从偶句 3 跳来）
- 多歧 1a/1b/1c 合法（polytomy），不报错
- **正反条成对编号（俄/苏定检表式，Marinov 1977 等）**：每条各有号，括号内为对立条号，如 1(8) … 8(1)、2(5) … 5(2)。
  识别：同一表内带括号的号各出现一次且 n(m) 与 m(n) 成对出现 → 按此式解析，否则按括号回指式。
  偶句号取成对中较小者，出现顺序给 a/b（1(8)→1a，8(1)→1b）。无去向的条隐式跳到「本条号+1」所在偶句。
  同一表内两种括号式不能混判；成对不全（只有 n(m) 无 m(n)）报 lone_alternate 或 single_branch。
- 去向中的「1. Genus Harmothoe Kinberg」「2. H. reticulata (Claparède)」：去掉前导序号、阶元词（Genus/Род/属）与命名人，taxon 记学名。
- 缩进式（indented key，无编号或 A/AA、字母层级）：按出现顺序给偶句号 1,2,3…，同层同前缀的两支为一对

## 去向（target）
- jump：偶句号（"5"、"5'"不常见，规范化为 5）；范围 "5-6" 记 jump 到 5
- page：(p. 76)、p. 76、S. 12、第 12 页、pág. 3
- taxon：类群名（可带页码，如 "Nereis pelagica (p. 76)" 记 taxon，另记 page）
- none：缺去向

## 问题码（findings code，固定词表）
| code | 含义 |
|---|---|
| no_keys | 预期有表（调用方声明）却识别出 0 张 |
| single_branch | 偶句只有一支 |
| lone_alternate | 有备择支（b/'/—）而无主支 a |
| duplicate_lead | 同一规范化分支号出现两次 |
| no_target | 分支无去向 |
| dangling_jump | 跳到本表不存在的偶句 |
| unreachable | 从入口偶句（默认最小号，可声明多入口）走不到的偶句 |
| cycle | 有环（给出路径） |
| multi_parent | 一个偶句被多处跳入（仅 warn，网状检索表合法） |
| backref_mismatch | 1(3) 形式中回指号与实际跳入来源不符 |
| empty_key | 有检索表标题但没有一条有效分支 |
| key_count | 原译表数不同 |
| missing_branch / extra_branch | 译文缺/多分支 |
| target_changed | 译文去向变化（跳转号、页码、拉丁学名任一不同） |
| order_changed | 译文分支顺序变化 |

## 样例文件格式（corpus/*.json，一例一文件）
{
 "id": "en_prime_basic",
 "format": "prime|ab|dash|bullet|backref|indented|polytomy|table|other",
 "lang": "en|ja|ru|fr|de|la|es|zh",
 "source": "原文文本，分页用 <!-- PDF p.N --> 标记，一行一支或按原书折行",
 "translation": "可选，译文文本，同样分页",
 "declared_entries": ["1"],            // 可选
 "expect": {
   "keys": 1,
   "branches": [["1a","jump","2"],["1b","taxon","Nereis pelagica"], ...],  // 按出现顺序；taxon 只写学名部分
   "findings": ["dangling_jump"]       // 期望命中的问题码集合（多余的、缺的都算失败）
 },
 "why": "这个样例要击穿什么、依据（原书惯例、文献）"
}
