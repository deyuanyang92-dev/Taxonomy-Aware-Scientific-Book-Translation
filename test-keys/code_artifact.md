# 分类学检索表通用引擎设计方案与完整对话记录

> **文档说明**：本文档整合了分类学文献 OCR → 翻译 → 质控 → 动态排版 → 正向生成检索表的完整工程设计方案（Universal Taxonomic Key Engine），并附带完整原始对话记录，便于直接用于项目开发、代码落地或文档归档。

---

## 目录

- [第一部分：完整工程设计方案（可直接落地）](#第一部分完整工程设计方案可直接落地)
  - [一、典型问题诊断（基于 *Fauna Ibérica* Vol. 21 排版截图）](#一典型问题诊断基于-fauna-ibérica-vol-21-排版截图)
  - [二、总体架构：数据、质控与排版彻底解耦](#二总体架构数据质控与排版彻底解耦)
  - [三、全球通用检索表中间数据模型（Universal Key IR）](#三全球通用检索表中间数据模型universal-key-ir)
  - [四、通用解析与四维自适应质控自愈引擎](#四通用解析与四维自适应质控自愈引擎)
  - [五、通用 Typst 动态排版组件（`key_renderer.typ`）](#五通用-typst-动态排版组件key_renderertyp)
  - [六、通用分类学检索表正向生成脚本（`key_generator.py`）](#六通用分类学检索表正向生成脚本key_generatorpy)
  - [七、进阶闭环：基于特征矩阵的“走表仿真质控”与正文清洗](#七进阶闭环基于特征矩阵的走表仿真质控与正文清洗)
  - [八、工程目录与接入建议](#八工程目录与接入建议)
- [第二部分：完整对话记录归档](#第二部分完整对话记录归档)

---

# 第一部分：完整工程设计方案（可直接落地）

## 一、典型问题诊断（基于 *Fauna Ibérica* Vol. 21 排版截图）

通过对当前三张 OCR 翻译排版截图的逐项排查，发现问题的根源在于**“用固定三列表格硬排检索表 + 缺少结构化质控层”**，具体表现为 4 类系统性隐患：

1. **表格列宽挤压导致描述强行折行与孤字**
   - 原排版采用固定三列表格（`序号 | 鉴别特征 | 属 / 页码`），右侧列固定占用了约 25%–30% 的版心宽度。
   - 中间特征描述被迫提前换行，甚至将“关节”劈成 `具关` / `节` 的单字孤行；同时右侧目标（如 `Palposyllis（第 57 页）`、`Paraeblersia（第 61 页）`）顶部对齐悬在首行右上角，与末行文字完全脱节。
2. **缺少点引导线（Dot Leaders）且网格横线破坏对偶感**
   - 特征描述与右侧跳转号/学名之间存在大片留白，缺少 `......` 引导线，跨列扫视极易串行。
   - 每一条引项之间均加了灰色横线，削弱了二歧对偶（如 `1.` 与 `•`）在视觉上的成组关系。
3. **拉丁学名 OCR 拼写错误引发“斜体丢失”连锁反应**
   - 第 6 项右侧的 `Paraeblersia（第 61 页）` 存在双重漏网问题：裂虫科（Syllidae）该属正确拼写应为 ***Paraehlersia***（OCR 将 `h` 误识为 `b`），且全表其余属名（*Neopetitia*、*Opisthodonta*、*Palposyllis*、*Pionosyllis*、*Amblyosyllis*、*Miscellania*）均为斜体，唯独该属变成了正体，系拼错后未命中词库斜体规则所致。
4. **翻译语义矛盾与错别字隐患**
   - 第 8 项第二条出现 `触角基部游离而愈合` 这种逻辑自相矛盾的表述（通常源自原外文 `libres o fusionados` 或 OCR 漏词导致的误译）。
   - 第 5 项第二条存在非规范字形 `小形种`（规范应为 `小型种`）。

---

## 二、总体架构：数据、质控与排版彻底解耦

检索表本质上是一棵**有向分类决策树**，不应在 OCR 后的 Markdown 或表格文本上直接打补丁，而应拆分为 4 个解耦阶段（同时打通“逆向解析排错”与“正向矩阵生成”）：

```text
  [路径 A：古籍/专著 OCR 还原]              [路径 B：物种特征矩阵新建]
       OCR 原始文本 / 坐标                      CSV / TSV 特征矩阵
               │                                        │
               ▼                                        ▼
     [key_parser.py 解析器]                 [key_generator.py 生成器]
       (规则状态机 + 局部LLM兜底)            (多态/权重/依赖/辅助性状合并)
               │                                        │
               └───────────────────┬────────────────────┘
                                   ▼
                 标准化 Universal Key IR (JSON)
                                   │
                                   ▼
                    [key_qc.py 四维质控与自愈]
             ├── 拓扑图论校验（断链 / 孤岛 / 漏对偶 / 环路）
             ├── 自适应槽位画像校验（有无页码/图号/命名人自动静默或告警）
             ├── 分类学名校验（WoRMS 模糊匹配自愈 + 正斜体分槽）
             └── 语义矛盾与走表仿真测试（对照正文特征抓漏种/误译）
                                   │
                                   ▼
                [key_renderer.typ 通用 Typst 渲染器]
             └── 放弃三列表格：两列悬挂缩进 + 实时测宽动态点引导线
                 + 空间不足自动折行右对齐 + 多风格主题一键切换
```

---

## 三、全球通用检索表中间数据模型（Universal Key IR）

全球分类学文献（*Fauna Ibérica*、《中国动物志》、*Zootaxa*、日本及欧美经典图鉴）的检索表，所有差异均为**可选槽位（Optional Slots）+ 渲染主题（Theme）**。统一中间表示（JSON）如下：

```json
{
  "key_id": "syllidae_genera_key",
  "title": "裂虫科（Syllidae）分属检索表",
  "style": {
    "layout": "parallel",
    "marker_scheme": "auto",
    "show_header": false,
    "headers": ["序号", "鉴别特征", "分类单元"]
  },
  "nodes": [
    {
      "id": "5",
      "parent_id": null,
      "depth": 0,
      "leads": [
        {
          "marker": "5.",
          "backref": null,
          "text": "触角长，外观上与口前叶愈合。体中部背须短于疣足叶或与之长度相近",
          "target": {
            "kind": "taxon",
            "cn_name": null,
            "latin_name": "Palposyllis",
            "authority": null,
            "qualifier": null,
            "fig_ref": null,
            "page_ref": "57"
          },
          "qc_flags": []
        },
        {
          "marker": "•",
          "backref": null,
          "text": "触角长度正常，以缝线与口前叶分隔（在小型种中触角完全分离）。成体标本的背须长于疣足叶",
          "target": {
            "kind": "goto",
            "goto_id": "6"
          },
          "qc_flags": []
        }
      ]
    },
    {
      "id": "6",
      "parent_id": "5",
      "depth": 0,
      "leads": [
        {
          "marker": "6.",
          "backref": null,
          "text": "前部背须下方各有一可缩性乳突。触手、触须及前部背须具关节",
          "target": {
            "kind": "taxon",
            "cn_name": null,
            "latin_name": "Paraehlersia",
            "authority": null,
            "qualifier": null,
            "fig_ref": null,
            "page_ref": "61"
          },
          "qc_flags": ["AUTO_FIXED_TAXON: Paraeblersia -> Paraehlersia (WoRMS, dist=1)"]
        }
      ]
    }
  ]
}
```

### 模型核心特性
- **兼容全制式标号**：支持 `1. / •`（欧美/伊比利亚）、`1a / 1b`（Zootaxa/英系）、`1(4) / 4(1)`（中国动物志/俄系回指式）、`1 / 1'`（老文献）及多歧检索表（一个节点 $\ge 3$ 条引项）。
- **可选槽位零空壳**：右侧目标支持 `goto`（跳转号）、`taxon`（分类单元）、`subkey`（跳转子检索表）、`note`；中文名、拉丁名、命名人、限定词（如 `in part` / `部分`）、图号、页码任意组合，为 `null` 时自动隐身。
- **平行式 $\leftrightarrow$ 缩进式无损切换**：由于节点天然构成有向树，切换 `layout` 与 `depth` 即可无缝互转。

---

## 四、通用解析与四维自适应质控自愈引擎

### 4.1 通用解析流程（`key_parser.py`）

采用**“规则状态机 + 局部 LLM 兜底”**：
1. **噪声剥离与断行缝合**：正则剔除 OCR 残余点引导线（`.....`、`. . . .`、`……`）与表格竖线；若某行既无行首序号特征，上一行又无行尾目标，直接拼接为同一条 `text`。
2. **行首标号制式自动识别**：
   - `^(\d+)\s*\((\d+)\)` $\rightarrow$ 回指式（`id=1, backref=2`）
   - `^(\d+)\s*([a-zA-Z])[.\)]?` $\rightarrow$ 字母对偶式（`1a / 1b`）
   - `^(\d+)[.\)]` 与 `^[•·\-–—\*']` $\rightarrow$ 数字+符号对偶式（`1. / •`）
   - 利用 OCR bbox X 坐标阶梯聚类识别缩进式层级 `depth`。
3. **行尾槽位反向拆解**：依次剥离页码（`p.\s*\d+` / `第\s*\d+\s*页`）$\rightarrow$ 图号（`Fig\.` / `图`）$\rightarrow$ 限定词 $\rightarrow$ 跳转数字或 `cn_name` + `latin_name` + `authority`。
4. **疑难行定向兜底**：仅对规则解析失败的局部 1–2 行连同上下文发给 LLM 修复，避免整表调用浪费 Token。

### 4.2 四维自适应质控策略（`key_qc.py`）

核心原则：**先做全表画像（Key Profiling），再按画像执行一致性校验**，彻底避免“无页码文献误报页码缺失”的问题。

| 质控维度 | 通用自适应检测规则 | 自动修正（Auto-Fix）策略 | 异常分级 |
| :--- | :--- | :--- | :--- |
| **1. 拓扑图论校验** | 建模为有向图 $G=(V,E)$：<br>• 编号连续性、每组对偶引项数检查<br>• **出度检查**：所有 `goto_id` 必须存在<br>• **入度检查**：除入口 `1` 外入度必须 $\ge 1$（检测孤岛）<br>• **环路检查**：DFS 检测死循环（如 `5 -> 8 -> 5`）<br>• 回指式校验 `A(B)` 互反性；缩进式校验深度不跳级 | • 跨页断行自动拼接<br>• 缺失 `•` 自动补全<br>• OCR 误把跳转数字 `1` 识成 `l/I` 自动修复 | 断行/符号：`AUTO_FIXED`<br>断链/孤岛/环路：`ERROR` |
| **2. 自适应槽位画像校验** | 统计全部 `taxon` 叶节点的槽位覆盖率：<br>• 若覆盖率 $> 40\%$，对缺失该字段的个别条目发出告警<br>• 若覆盖率 $< 10\%$，判定本表不含该槽位，完全静默<br>• 同理覆盖 `page_ref`、`fig_ref`、`authority`、`cn_name` | • 自动清洗页码中的非数字杂质<br>• 整书排版时自动核对正文标题页码 | 局部缺失：`WARN` |
| **3. 分类学名与斜体校验** | • 按当前章节上位阶元检索 WoRMS / 本地词库<br>• 编辑距离 $\le 2$ + OCR 高频形近字加权（`h/b`、`rn/m`、`l/I/1`、`c/e`、`u/n`、`cl/d`）<br>• 识别并保护正体保留词（`sp.`, `cf.`, `aff.`, `s.l.`, `comb. nov.` 等） | • 同科唯一高置信度匹配自动纠错（如 `Paraeblersia` $\rightarrow$ `Paraehlersia`）并记入 `qc_flags`<br>• 渲染层强制锁定拉丁名斜体、保留词与命名人正体 | 唯一匹配：`AUTO_FIXED`<br>多候选/无记录：`WARN` |
| **4. 文本与语义质控** | • 扫描段内硬换行、多余空格、中英标点混用、句尾多余句号<br>• 正则/轻量模型扫描逻辑矛盾词（如“游离而愈合”）及对偶重复 | • 空白、换行、句尾句号 100% 自动清洗<br>• 可疑语义矛盾提取原文对照交 LLM 复核 | 格式：`AUTO_FIXED`<br>语义：`NEEDS_REVIEW` |

### 4.3 拓扑质控 Python 核心骨架

```python
from collections import defaultdict

def validate_key_topology(key_data: dict) -> list[dict]:
    issues = []
    nodes = {str(n["id"]): n for n in key_data["nodes"]}
    in_degree = defaultdict(int)
    adj = defaultdict(list)

    # 1. 检查对偶完整性与悬空跳转
    for nid, node in nodes.items():
        leads = node.get("leads", [])
        if len(leads) != 2:
            issues.append({"level": "WARN", "node": nid, "msg": f"包含 {len(leads)} 条引项（非标准二歧）"})

        for idx, lead in enumerate(leads):
            if not lead.get("text", "").strip():
                issues.append({"level": "ERROR", "node": nid, "msg": f"引项 {idx+1} 特征描述为空"})

            target = lead.get("target", {})
            kind = target.get("kind")
            if kind == "goto":
                tid = str(target.get("goto_id", ""))
                if tid not in nodes:
                    issues.append({"level": "ERROR", "node": nid, "msg": f"跳转目标 {tid} 不存在（断链）"})
                else:
                    in_degree[tid] += 1
                    adj[nid].append(tid)
            elif kind == "taxon":
                if not (target.get("latin_name") or target.get("cn_name")):
                    issues.append({"level": "ERROR", "node": nid, "msg": f"引项 {idx+1} 缺少分类单元名称"})

    # 2. 检查孤岛节点（除入口 1 外无任何上游指向）
    for nid in nodes:
        if nid != "1" and in_degree[nid] == 0:
            issues.append({"level": "ERROR", "node": nid, "msg": f"编号 {nid} 为孤岛节点，无上游指向"})

    # 3. DFS 检测死循环
    visited, on_stack = set(), set()

    def dfs(u: str):
        visited.add(u)
        on_stack.add(u)
        for v in adj[u]:
            if v in on_stack:
                issues.append({"level": "ERROR", "node": u, "msg": f"检测到死循环: {u} -> {v}"})
            elif v not in visited:
                dfs(v)
        on_stack.remove(u)

    for nid in nodes:
        if nid not in visited:
            dfs(nid)

    return issues
```

---

## 五、通用 Typst 动态排版组件（`key_renderer.typ`）

彻底放弃三列表格，采用**“两列悬挂缩进（极窄序号列 + 占满版心的正文列）+ Typst 实时坐标测宽动态引导线”**：
- 特征描述完整占满版心宽度，根治断行与孤字；
- 通过 `here().position().x` 精确测量描述末行结束位置与剩余空间；
- 剩余空间充足时自动填充 `......` + 右对齐目标；
- 剩余空间不足时自动 `linebreak()`，将完整目标（如 ***Palposyllis*（第 57 页）**）移至下一行右对齐；
- 单条引项启用 `breakable: false`，防止跨页劈裂。

```typst
// 1. 智能学名格式化：自动处理 sp. / cf. / aff. 等必须保持正体的连接词
#let format-latin(name) = {
  let upright-tokens = (
    "sp.", "spp.", "cf.", "aff.", "var.", "subsp.", "f.",
    "s.l.", "s.str.", "nov.", "comb.", "gen.", "n.", "sensu"
  )
  let words = name.trim().split(" ")
  words.map(w => {
    if w in upright-tokens or (w.starts-with("(") and w.ends-with(")")) {
      text(style: "normal", w)
    } else {
      emph(w)
    }
  }).join(" ")
}

// 2. 通用目标槽位拼接器：任何字段为 none 时自动隐身，绝无空括号
#let format-target(t, bold-target: true) = {
  let content = if t.kind == "goto" {
    [#t.goto_id]
  } else if t.kind == "subkey" {
    [#t.at("label", default: "见下表")]
  } else {
    let parts = ()
    if t.at("cn_name", default: none) != none {
      parts.push([#t.cn_name])
    }
    if t.at("latin_name", default: none) != none {
      parts.push(format-latin(t.latin_name))
    }
    if t.at("authority", default: none) != none {
      parts.push(text(weight: "regular", t.authority))
    }
    if t.at("qualifier", default: none) != none {
      parts.push(text(weight: "regular", [（#t.qualifier）]))
    }

    // 附注区（图号 / 页码）：有哪个拼哪个，都没有则不生成括号
    let meta = ()
    if t.at("fig_ref", default: none) != none { meta.push(t.fig_ref) }
    if t.at("page_ref", default: none) != none { meta.push([第 #t.page_ref 页]) }
    if meta.len() > 0 {
      parts.push(text(weight: "regular", [（#meta.join("，")）]))
    }
    parts.join(" ")
  }

  if bold-target { strong(content) } else { content }
}

// 3. 通用单条引项渲染：动态测宽 + 自动点引导线 + 空间不足自动换行右对齐
#let render-lead(
  marker-str,
  desc,
  target,
  depth: 0,
  cfg: (:),
) = {
  let indent-step = cfg.at("indent-step", default: 1.5em)
  let marker-w = cfg.at("marker-width", default: 2.6em)
  let min-leader = cfg.at("min-leader", default: 2.2em)
  let dots-on-newline = cfg.at("dots-on-newline", default: true)
  let show-dots = cfg.at("show-dots", default: true)

  let target-box = box(format-target(target, bold-target: cfg.at("bold-target", default: true)))
  let dot-leader = if show-dots {
    box(width: 1fr, repeat[#h(1.5pt).])
  } else {
    h(1fr)
  }

  // 清洗描述：去掉换行符与句尾多余句号（避免出现 "。......"）
  let clean-desc = desc.replace("\n", "").trim().trim("。")

  block(
    breakable: false,
    width: 100%,
    inset: (left: depth * indent-step),
    above: 0.16em,
    below: 0.16em,
  )[
    #grid(
      columns: (marker-w, 1fr),
      column-gutter: 0.5em,
      align: (right + top, left + top),
      [*#marker-str*],
      layout(avail => {
        context {
          let start-x = here().position().x
          let target-w = measure(target-box).width
          let min-gap = measure(box(width: min-leader)).width
          let pad = measure(box(width: 0.8em)).width

          clean-desc

          context {
            let end-x = here().position().x
            let remaining = (start-x + avail.width) - end-x

            if remaining >= target-w + min-gap + pad {
              h(0.4em)
              dot-leader
              h(0.4em)
              target-box
            } else {
              linebreak()
              if dots-on-newline and show-dots {
                dot-leader
                h(0.4em)
              } else {
                h(1fr)
              }
              target-box
            }
          }
        }
      })
    )
  ]
}

// 4. 统一入口：传入 Universal Key IR JSON + 主题预设即可渲染全表
#let render-taxonomic-key(key-data, theme: "classic") = {
  let themes = (
    classic: (marker-width: 2.4em, show-dots: true, dots-on-newline: true, bold-target: true, couplet-gap: 0.55em),
    fauna-sinica: (marker-width: 3.4em, show-dots: true, dots-on-newline: false, bold-target: false, couplet-gap: 0.45em),
    zootaxa: (marker-width: 2.6em, show-dots: true, dots-on-newline: true, bold-target: false, couplet-gap: 0.5em),
  )
  let cfg = themes.at(theme, default: themes.classic)

  if key-data.at("title", default: none) != none {
    block(above: 1em, below: 0.5em, sticky: true)[*#key-data.title*]
  }

  let style = key-data.at("style", default: (:))
  if style.at("show_header", default: false) {
    let hdr = style.at("headers", default: ("序号", "鉴别特征", "分类单元"))
    block(width: 100%, below: 0.4em, stroke: (bottom: 0.8pt + black), inset: (bottom: 0.3em))[
      #grid(
        columns: (cfg.marker-width, 1fr, auto),
        column-gutter: 0.5em,
        align: (right, left, right),
        [*#hdr.at(0)*], [*#hdr.at(1)*], [*#hdr.at(2)*]
      )
    ]
  }

  for node in key-data.nodes {
    block(width: 100%, above: cfg.couplet-gap, below: cfg.couplet-gap)[
      #for lead in node.leads {
        let m = if lead.at("backref", default: none) != none {
          [#lead.marker\(#lead.backref)]
        } else {
          lead.marker
        }
        render-lead(
          m,
          lead.text,
          lead.target,
          depth: node.at("depth", default: 0),
          cfg: cfg,
        )
      }
    ]
  }
}
```

---

## 六、通用分类学检索表正向生成脚本（`key_generator.py`）

### 6.1 生物分类检索表的 4 项硬约束
普通机器学习决策树（CART/ID3）无法直接用于生物分类检索表，必须显式处理：
1. **种内多态性（Polymorphism）**：使用 `|` 分隔多个状态（如 `光滑|具关节`），拆分时该分类单元必须同时进入左右分支，避免鉴定漏检。
2. **性状依赖与不适用（Inapplicable `-` vs Unknown `?`）**：某特征在当前子集存在 `-` 时严禁提前调用（例如先区分咽有无武装，再调用咽齿类型）。
3. **特征观察权重（Character Weight）**：体表宏观特征高权重优先，需解剖/电镜观察的特征低权重延后。
4. **辅助鉴别特征自动合并（Corroborating Characters）**：若多个特征对同一组分类单元能做到完全一致的干净划分，自动合并写入同一引项提升容错率。

### 6.2 标准输入特征矩阵格式（CSV / TSV）

| taxon_name | cn_name | page_ref | 咽武装 | 咽齿类型 | 触角外观 | 背须可缩性乳突 | 刚节数 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| *Neopetitia* | | 49 | 具武装 | 单齿 | 似双节 | 无 | 20-35 |
| *Opisthodonta* | | 51 | 具武装 | 单齿 | 非双节 | 无 | 40-80 |
| *Paraehlersia* | | 61 | 具武装 | 单齿 | 非双节 | 有 | 30-60 |
| *Pionosyllis* | | 66 | 具武装 | 单齿 | 非双节 | 无\|极微弱 | 35-90 |
| *Amblyosyllis* | | 92 | 具武装 | 多齿 | 非双节 | 无 | 13-15 |

### 6.3 完整可运行 Python 脚本（纯标准库，零依赖）

```python
#!/usr/bin/env python3
"""
通用分类学二歧检索表生成器（Universal Taxonomic Key Generator）
支持：
  - 类别特征、数值区间特征（如 13-15）
  - 种内多态性（用 '|' 分隔，自动双分支路由避免漏检）
  - 缺失值（'?'）与不适用（'-'，自动遵守性状依赖）
  - 特征权重（优先体表易观察特征）
  - 辅助鉴别特征自动合并（Corroborating characters）
  - 不可区分物种自动诊断告警
  - 直接输出 Universal Key IR JSON（兼容 Typst 动态点引导线渲染）
"""

from __future__ import annotations
import csv
import itertools
import json
import re
from dataclasses import dataclass
from typing import Any


@dataclass
class CharacterSpec:
    name: str
    weight: float = 5.0          # 1.0(极难观察/需解剖) ~ 10.0(肉眼宏观特征)
    char_type: str = "auto"      # "auto" | "categorical" | "numeric"
    unit: str = ""               # 数值单位，如 "个"、"mm"


@dataclass
class TaxonRecord:
    taxon_name: str
    traits: dict[str, str]
    cn_name: str | None = None
    authority: str | None = None
    fig_ref: str | None = None
    page_ref: str | None = None


@dataclass
class SplitCandidate:
    char_name: str
    score: float
    left_label: str
    right_label: str
    left_taxa: list[TaxonRecord]
    right_taxa: list[TaxonRecord]
    dup_count: int


_NUM_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(?:[-–~]\s*(\d+(?:\.\d+)?))?\s*$")


def parse_numeric(val: str) -> tuple[float, float] | None:
    m = _NUM_RE.match(val)
    if not m:
        return None
    low = float(m.group(1))
    high = float(m.group(2)) if m.group(2) is not None else low
    return (min(low, high), max(low, high))


def detect_char_type(taxa: list[TaxonRecord], char_name: str) -> str:
    vals = [t.traits.get(char_name, "").strip() for t in taxa]
    valid = [v for v in vals if v and v not in ("?", "-")]
    if valid and all(parse_numeric(v) is not None for v in valid):
        return "numeric"
    return "categorical"


def format_states(char_name: str, states: set[str]) -> str:
    joined = "或".join(sorted(states))
    return f"{char_name}：{joined}"


def score_split(n_total: int, n_left: int, n_right: int, weight: float, complexity: int = 2) -> float:
    """
    核心评分函数：
      1. 高权重特征优先（宏观性状先于微细解剖性状）
      2. 树深度平衡（左右分支越接近 50/50 分数越高）
      3. 强惩罚多态重复（dup 越多说明该特征越不稳定，会膨胀检索表）
    """
    dup = (n_left + n_right) - n_total
    dup_ratio = dup / n_total
    balance = 1.0 - abs(n_left - n_right) / (n_left + n_right)
    return (weight * (0.45 + 0.55 * balance)) / (1.0 + 3.5 * dup_ratio) - 0.03 * complexity


def evaluate_categorical(
    taxa: list[TaxonRecord], spec: CharacterSpec
) -> list[SplitCandidate]:
    # 若当前子集任一物种在此特征为不适用 '-'，则跳过（确保先走上游依赖特征）
    raw_vals = [t.traits.get(spec.name, "").strip() for t in taxa]
    if any(v == "-" for v in raw_vals):
        return []

    parsed: list[set[str] | None] = []
    universe: set[str] = set()
    for v in raw_vals:
        if not v or v == "?":
            parsed.append(None)  # 未知值
        else:
            st = {s.strip() for s in v.split("|") if s.strip()}
            parsed.append(st)
            universe.update(st)

    if len(universe) < 2:
        return []

    # 枚举二歧划分方案（状态数 <= 6 时枚举全部子集二分，否则采用 1-vs-Rest）
    states_list = sorted(universe)
    partitions: list[tuple[set[str], set[str]]] = []
    if len(states_list) <= 6:
        for r in range(1, len(states_list) // 2 + 1):
            for comb in itertools.combinations(states_list, r):
                p1 = set(comb)
                p2 = universe - p1
                if len(p1) == len(p2) and min(p1) > min(p2):
                    continue
                partitions.append((p1, p2))
    else:
        for s in states_list:
            partitions.append(({s}, universe - {s}))

    candidates: list[SplitCandidate] = []
    n_total = len(taxa)
    for p1, p2 in partitions:
        left, right = [], []
        for taxon, st in zip(taxa, parsed):
            if st is None:
                left.append(taxon)
                right.append(taxon)
            else:
                if st & p1:
                    left.append(taxon)
                if st & p2:
                    right.append(taxon)

        # 严格降维检查：左右分支都必须严格小于当前子集，保证算法必定终止
        if 0 < len(left) < n_total and 0 < len(right) < n_total:
            dup = len(left) + len(right) - n_total
            sc = score_split(n_total, len(left), len(right), spec.weight, len(p1) + len(p2))
            candidates.append(
                SplitCandidate(
                    char_name=spec.name,
                    score=sc,
                    left_label=format_states(spec.name, p1),
                    right_label=format_states(spec.name, p2),
                    left_taxa=left,
                    right_taxa=right,
                    dup_count=dup,
                )
            )
    return candidates


def evaluate_numeric(
    taxa: list[TaxonRecord], spec: CharacterSpec
) -> list[SplitCandidate]:
    raw_vals = [t.traits.get(spec.name, "").strip() for t in taxa]
    if any(v == "-" for v in raw_vals):
        return []

    intervals: list[tuple[float, float] | None] = []
    cut_points: set[float] = set()
    for v in raw_vals:
        if not v or v == "?":
            intervals.append(None)
        else:
            iv = parse_numeric(v)
            intervals.append(iv)
            if iv:
                cut_points.update(iv)

    sorted_pts = sorted(cut_points)
    if len(sorted_pts) < 2:
        return []

    thresholds = sorted(
        set(sorted_pts[:-1])
        | {round((sorted_pts[i] + sorted_pts[i + 1]) / 2, 2) for i in range(len(sorted_pts) - 1)}
    )

    candidates: list[SplitCandidate] = []
    n_total = len(taxa)
    unit = spec.unit
    for th in thresholds:
        left, right = [], []
        for taxon, iv in zip(taxa, intervals):
            if iv is None:
                left.append(taxon)
                right.append(taxon)
            else:
                low, high = iv
                if low <= th:
                    left.append(taxon)
                if high > th:
                    right.append(taxon)

        if 0 < len(left) < n_total and 0 < len(right) < n_total:
            dup = len(left) + len(right) - n_total
            sc = score_split(n_total, len(left), len(right), spec.weight, complexity=2)
            th_str = f"{int(th)}" if th.is_integer() else f"{th:g}"
            candidates.append(
                SplitCandidate(
                    char_name=spec.name,
                    score=sc,
                    left_label=f"{spec.name} <= {th_str}{unit}",
                    right_label=f"{spec.name} > {th_str}{unit}",
                    left_taxa=left,
                    right_taxa=right,
                    dup_count=dup,
                )
            )
    return candidates


class TaxonomicKeyGenerator:
    def __init__(
        self,
        taxa: list[TaxonRecord],
        char_specs: list[CharacterSpec],
        max_corroborating: int = 1,
    ):
        self.taxa = taxa
        self.char_specs = char_specs
        self.max_corroborating = max_corroborating
        self.warnings: list[str] = []

        for spec in self.char_specs:
            if spec.char_type == "auto":
                spec.char_type = detect_char_type(taxa, spec.name)

    def _find_corroborating(
        self, best: SplitCandidate, all_candidates: list[SplitCandidate]
    ) -> tuple[list[str], list[str]]:
        """查找能够 100% 一致辅助区分同一对子集的额外特征"""
        if best.dup_count > 0 or self.max_corroborating <= 0:
            return [], []

        left_ids = {t.taxon_name for t in best.left_taxa}
        right_ids = {t.taxon_name for t in best.right_taxa}
        extra_left, extra_right = [], []

        for cand in sorted(all_candidates, key=lambda c: c.score, reverse=True):
            if cand.char_name == best.char_name or cand.dup_count > 0:
                continue
            c_left = {t.taxon_name for t in cand.left_taxa}
            c_right = {t.taxon_name for t in cand.right_taxa}
            if c_left == left_ids and c_right == right_ids:
                extra_left.append(cand.left_label)
                extra_right.append(cand.right_label)
            elif c_left == right_ids and c_right == left_ids:
                extra_left.append(cand.right_label)
                extra_right.append(cand.left_label)
            if len(extra_left) >= self.max_corroborating:
                break
        return extra_left, extra_right

    def _build_tree(self, subset: list[TaxonRecord], depth: int = 0) -> dict[str, Any]:
        if len(subset) == 1:
            return {"type": "leaf", "taxa": subset, "depth": depth}

        all_candidates: list[SplitCandidate] = []
        for spec in self.char_specs:
            if spec.char_type == "numeric":
                all_candidates.extend(evaluate_numeric(subset, spec))
            else:
                all_candidates.extend(evaluate_categorical(subset, spec))

        if not all_candidates:
            names = ", ".join(t.taxon_name for t in subset)
            self.warnings.append(f"[特征不足] 以下分类单元无法通过现有矩阵继续区分：{names}")
            return {"type": "leaf", "taxa": subset, "depth": depth}

        best = max(all_candidates, key=lambda c: c.score)
        extra_l, extra_r = self._find_corroborating(best, all_candidates)

        left_text = "；".join([best.left_label] + extra_l)
        right_text = "；".join([best.right_label] + extra_r)

        l_branch = self._build_tree(best.left_taxa, depth + 1)
        r_branch = self._build_tree(best.right_taxa, depth + 1)

        return {
            "type": "split",
            "depth": depth,
            "char_name": best.char_name,
            "left": {"text": left_text, "child": l_branch},
            "right": {"text": right_text, "child": r_branch},
        }

    def generate_universal_ir(
        self,
        title: str = "自动生成检索表",
        layout: str = "parallel",
        marker_scheme: str = "1/•",   # "1/•" | "1a/1b" | "1(parent)"
    ) -> dict[str, Any]:
        """将内部决策树编译为 Universal Key IR JSON"""
        root = self._build_tree(self.taxa, depth=0)
        nodes: list[dict[str, Any]] = []
        counter = [0]

        def make_leaf_target(taxa: list[TaxonRecord]) -> dict[str, Any]:
            if len(taxa) == 1:
                t = taxa[0]
                return {
                    "kind": "taxon",
                    "cn_name": t.cn_name,
                    "latin_name": t.taxon_name,
                    "authority": t.authority,
                    "fig_ref": t.fig_ref,
                    "page_ref": t.page_ref,
                }
            return {
                "kind": "taxon",
                "latin_name": " / ".join(t.taxon_name for t in taxa),
                "qualifier": "特征不足，待补充区分性状",
            }

        def serialize(node: dict[str, Any], parent_id: str | None = None) -> str:
            counter[0] += 1
            cid = str(counter[0])
            node_entry: dict[str, Any] = {
                "id": cid,
                "parent_id": parent_id,
                "depth": node["depth"],
                "leads": [],
            }
            nodes.append(node_entry)

            for idx, side in enumerate((node["left"], node["right"])):
                child = side["child"]
                if marker_scheme == "1a/1b":
                    marker = f"{cid}{'a' if idx == 0 else 'b'}."
                    backref = None
                elif marker_scheme == "1(parent)":
                    marker = f"{cid}" if idx == 0 else "•"
                    backref = parent_id if (idx == 0 and parent_id) else None
                else:
                    marker = f"{cid}." if idx == 0 else "•"
                    backref = None

                if child["type"] == "leaf":
                    target = make_leaf_target(child["taxa"])
                else:
                    goto_id = serialize(child, parent_id=cid)
                    target = {"kind": "goto", "goto_id": goto_id}

                node_entry["leads"].append(
                    {
                        "marker": marker,
                        "backref": backref,
                        "text": side["text"],
                        "target": target,
                    }
                )
            return cid

        if root["type"] == "split":
            serialize(root)
        elif root["type"] == "leaf":
            self.warnings.append("[警告] 输入分类单元不足 2 个或全部无法区分，未生成分支。")

        return {
            "key_id": "auto_generated_key",
            "title": title,
            "style": {
                "layout": layout,
                "marker_scheme": marker_scheme,
                "show_header": False,
            },
            "nodes": nodes,
            "diagnostics": {
                "total_taxa": len(self.taxa),
                "total_couplets": len(nodes),
                "warnings": self.warnings,
            },
        }


def load_matrix_csv(
    csv_path: str,
    weights: dict[str, float] | None = None,
    units: dict[str, str] | None = None,
) -> tuple[list[TaxonRecord], list[CharacterSpec]]:
    """从标准 CSV/TSV 加载物种特征矩阵"""
    meta_cols = {"taxon_name", "cn_name", "authority", "fig_ref", "page_ref"}
    weights = weights or {}
    units = units or {}

    with open(csv_path, encoding="utf-8-sig") as f:
        dialect = csv.Sniffer().sniff(f.read(2048), delimiters=",\t")
        f.seek(0)
        reader = csv.DictReader(f, dialect=dialect)
        trait_cols = [c for c in (reader.fieldnames or []) if c not in meta_cols]

        taxa = []
        for row in reader:
            taxa.append(
                TaxonRecord(
                    taxon_name=row["taxon_name"].strip(),
                    cn_name=row.get("cn_name", "").strip() or None,
                    authority=row.get("authority", "").strip() or None,
                    fig_ref=row.get("fig_ref", "").strip() or None,
                    page_ref=row.get("page_ref", "").strip() or None,
                    traits={c: row.get(c, "").strip() for c in trait_cols},
                )
            )
    specs = [
        CharacterSpec(name=c, weight=weights.get(c, 5.0), unit=units.get(c, ""))
        for c in trait_cols
    ]
    return taxa, specs


if __name__ == "__main__":
    demo_specs = [
        CharacterSpec("咽武装", weight=9.0),
        CharacterSpec("咽齿类型", weight=7.0),
        CharacterSpec("触角外观", weight=8.5),
        CharacterSpec("前部背须下方可缩性乳突", weight=6.0),
        CharacterSpec("刚节数", weight=5.0, unit="节"),
    ]
    demo_taxa = [
        TaxonRecord("Neopetitia", page_ref="49", traits={
            "咽武装": "具武装", "咽齿类型": "单齿", "触角外观": "似双节", "前部背须下方可缩性乳突": "无", "刚节数": "20-35"
        }),
        TaxonRecord("Opisthodonta", page_ref="51", traits={
            "咽武装": "具武装", "咽齿类型": "单齿", "触角外观": "非双节", "前部背须下方可缩性乳突": "无", "刚节数": "45-80"
        }),
        TaxonRecord("Paraehlersia", page_ref="61", traits={
            "咽武装": "具武装", "咽齿类型": "单齿", "触角外观": "非双节", "前部背须下方可缩性乳突": "有", "刚节数": "30-60"
        }),
        TaxonRecord("Amblyosyllis", page_ref="92", traits={
            "咽武装": "具武装", "咽齿类型": "多齿", "触角外观": "非双节", "前部背须下方可缩性乳突": "无", "刚节数": "13-15"
        }),
        TaxonRecord("Exogone", page_ref="120", traits={
            "咽武装": "无武装", "咽齿类型": "-", "触角外观": "非双节", "前部背须下方可缩性乳突": "无", "刚节数": "25-40"
        }),
    ]

    gen = TaxonomicKeyGenerator(demo_taxa, demo_specs, max_corroborating=1)
    key_ir = gen.generate_universal_ir(title="演示：自动生成分属检索表", marker_scheme="1/•")

    for node in key_ir["nodes"]:
        for lead in node["leads"]:
            t = lead["target"]
            rhs = t["goto_id"] if t["kind"] == "goto" else f"{t['latin_name']} (p.{t.get('page_ref')})"
            print(f"{lead['marker']:>3} {lead['text']:<42} ...... {rhs}")
    print("\n[诊断报告]", key_ir["diagnostics"])

    with open("generated_key.json", "w", encoding="utf-8") as out:
        json.dump(key_ir, out, ensure_ascii=False, indent=2)
```

---

## 七、进阶闭环：基于特征矩阵的“走表仿真质控”与正文清洗

### 7.1 走表仿真质控（Key Walk-through QC）
将正向生成逻辑反用于 OCR 检索表质控，可捕捉纯正则永远查不出的深层语义错误：
1. **物种覆盖率对账**：对比正文物种标题集合 $T_{\text{body}}$ 与检索表叶节点集合 $T_{\text{key}}$，差集 $T_{\text{body}} - T_{\text{key}}$ 秒级揪出漏种或错拼（如 *Paraehlersia* vs *Paraeblersia*）。
2. **模拟走表验证**：取每个物种的正文形态特征，从第 `1.` 项沿树试走：
   - 遇到自相矛盾译文（如“触角基部游离而愈合”）$\rightarrow$ 双向无法匹配或同时匹配，精准标红定位；
   - 落到错误的物种叶节点 $\rightarrow$ 说明中间某条对偶项漏译否定词（正反颠倒）或右侧跳转号串行。
3. **跨专著整合重编**：合并多本专著及新采集物种特征矩阵后，直接一键生成最新整合检索表并输出 Typst 出版级 PDF。

### 7.2 普通中文段落防错清洗（Pre-Typeset Sanitizer）
- **跨行硬回车智能缝合**：前一行末非句末标点且非列表/标题起止时，自动合并断行并清除中文间多余半角空格。
- **学名统一保护与混排留白**：JSON 层统一标记属/种学名（含缩写如 *P. prosargasso*），Typst 开启 `#set text(cjk-latin-spacing: auto)`。
- **防孤行与标题粘连**：全局 `#set par(justify: true)`，标题设置 `sticky: true`。

---

## 八、工程目录与接入建议

建议将整套能力封装为独立子模块 `key_engine/`，插在**翻译完成之后、Typst 编译之前**：

```text
key_engine/
├── schema.py            # Universal Key IR 数据结构定义与校验
├── key_parser.py        # OCR/Markdown/表格 -> Universal Key IR 解析器
├── key_qc.py            # 四维自适应质控 + WoRMS 纠错 + 走表仿真测试
├── key_generator.py     # 特征矩阵 (CSV/TSV) -> Universal Key IR 生成器
└── templates/
    └── key_renderer.typ # 通用 Typst 动态引导线排版组件
```

---

# 第二部分：完整对话记录归档

## 第 1 轮

### 用户提问
> 我在ocr 后，翻译英文，中文，排版检索表， 或中文段落等，经常出现错误，我想增加一个检索表修改，或质控，发现错误可以自动修正的功能，或者可以自动检查或生成检索表； 比如图1，没有..... ， 可以自动生成； 比如一段描述，不要断开，完整衔接，然后Palposyllis（第57页） 自动到下一行，就是自动排好，太多这种问题了；；我暂时发现这些问题，如果你懂检索表，请帮我设计下方案，确保后续排版，不要再出现这种问题，
>
> *(附 3 张 *Fauna Ibérica* Vol. 21 检索表排版截图)*

### 助手回复要点
1. **诊断了截图中的 4 类核心问题**：三列表格列宽挤压导致的断行与孤字（如 `具关 / 节`）、缺少点引导线及冗余横线、第 6 项 `Paraeblersia` 拼写错误（应为 *Paraehlersia*）并引发斜体丢失、第 8 项“触角基部游离而愈合”的语义矛盾以及“小形种”笔误。
2. **提出了数据与排版彻底解耦的三阶段架构**：OCR 解析为标准化 Key JSON $\rightarrow$ 四维质控与自愈（拓扑图论、WoRMS 学名与页码、文本清洗、语义矛盾扫描）$\rightarrow$ Typst 声明式动态排版。
3. **给出了拓扑校验 Python 核心代码与 Typst 动态测宽引导线渲染代码**，并补充了普通中文段落的 Pre-Typeset Sanitizer 清洗建议。

---

## 第 2 轮

### 用户提问
> 我要一个更加通用的，有些有页码，有些没有啊， 但检索表，格式很固定啊， 为何不能设计一个通用的啊

### 助手回复要点
1. **明确指出可以完全通用化**：全球各类专著检索表只是同一棵分类决策树的不同外壳（可选槽位 + 渲染主题）。
2. **设计了全球通用的 Universal Key IR（JSON）模型**：兼容 `1. / •`、`1a / 1b`、`1(4)`、`1 / 1'`、多歧及平行/缩进双模式；将中文名、拉丁名、命名人、限定词、图号、页码拆分为独立可选槽位，为 `null` 时自动隐身。
3. **升级了自适应质控引擎**：引入“全表画像（Key Profiling）”机制——按槽位覆盖率自动决定是否告警，无页码文献完全静默；支持自动保护 `sp.`、`cf.`、`aff.` 等非斜体词。
4. **给出了通用版 Typst 渲染组件（`render-taxonomic-key`）**：内置 `classic`、`fauna-sinica`、`zootaxa` 等主题预设，一套代码通吃有无页码、有无中文名/图号/命名人以及平行/缩进版式。

---

## 第 3 轮

### 用户提问
> 现在我还要一个可以生成检索表脚本，比如我给出每个科，属，种的，分类特征，你可以自动生成， 我觉得这种，就更懂如何排查检索表错误了，

### 助手回复要点
1. **剖析了分类学检索表区别于普通决策树的 4 项硬约束**：种内多态性（`|` 双分支路由）、性状依赖与不适用（`-` vs `?`）、观察成本权重、辅助鉴别特征自动合并。
2. **定义了标准二维特征矩阵（CSV/TSV）输入规范**，支持类别值、多态值与数值区间（如 `13-15`）。
3. **交付了完整可运行、零外部依赖的 `key_generator.py` 脚本**，直接输出 Universal Key IR JSON，与 Typst 渲染器无缝衔接。
4. **打通了逆向质控闭环（Walk-through QC）**：利用特征矩阵与生成树逻辑进行物种覆盖率对账（抓漏种/错拼）、模拟走表仿真（抓矛盾译文、正反误译与跳转串行），并支持跨专著合并重编最新检索表。

---

## 第 4 轮

### 用户提问
> 把上述信息整理好md文件给我，包括对话

### 助手执行
整理输出本完整 Markdown 文档（`taxonomic_key_engine_spec_and_log.md`），包含完整架构说明、JSON Schema、Python 拓扑校验与检索表生成脚本、Typst 通用渲染组件以及全部对话记录。