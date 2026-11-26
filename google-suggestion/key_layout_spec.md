# 生物分类学检索表排版内参（`docs/key_layout_spec.md`）

> **用途**：本文件为 [Taxonomy-Aware-Scientific-Book-Translation](https://www.google.com/search?q=https://drive.google.com/drive/folders/11hDuVsft1u9BW8IHLTQl-7UBYJILuL_e) 仓库的**检索表排版唯一规范（Single Source of Truth）**，供 Claude Code、Cursor、DeepSeek 与 `booklayout` 渲染脚本共同遵守。
> **核心原则**：**剥夺大模型的排版控制权**。大模型只负责从原书提取/翻译干净的**结构化数据**并选择预设模板代号，严禁手打点线（`....`/`……`）、空格或制表符；所有缩进、点线制表位、成对防拆页、学名斜体与页码重映射全部由确定性脚本按本内参执行。

## 一、四大标准检索表内参模板（`booklayout/key_presets.yaml`）

全球 99% 的生物分类学专著检索表可归入以下 4 套预设模板。新书处理时由 `booklayout learn-style` 或译者四选一（默认推荐 `bracketed_hanging`，特征极长或老扫描极难对齐时降级为 `tabular_3col`）：

| 预设代号 | 常见名称与代表文献 | 序号形式 | 版面结构与适用场景 |
| :--- | :--- | :--- | :--- |
| **`bracketed_hanging`**（默认） | **平行式·悬挂缩进**<br>*Die Tierwelt Deutschlands*（Hartmann-Schröder 1996）、*中国动物志*、*Zootaxa* | `1 (2)` / `2 (1)` 或 `1.` / `2.` | **最通用（占 70%+）**。同对两条紧挨；左侧序号固定占宽，多行特征严格垂直悬挂对齐，右端点线引出跳转号或`*斜体学名* (p. N)`。 |
| **`bracketed_letter`** | **字母成对式**<br>*ZooKeys*、*Journal of Natural History* 等英文刊 | `1a.` / `1b.` 或 `2a (1b)` | 与 `bracketed_hanging` 版面一致，序号改用数字+字母成对；适合英文中继版与现代期刊风格。 |
| **`indented_step`** | **阶梯缩进式（缩格检索表）**<br>部分经典英美志书（如 Fauchald 等） | `1a` 嵌套 `2a` | 同对两条不紧挨，按分支深度逐级右缩进（每级 `+5.5 mm`）；默认无点线，终结学名接在描述末尾或右对齐。 |
| **`tabular_3col`**（保底） | **无边框三列表格**<br>特征长达 4–6 行、含多组量度/图号或复杂多栏 | 任意序号形式 | 左列序号（`13 mm`）、中列特征（自由折行不侵入两侧）、右列右对齐目标（`28 mm`）。视觉接近平行式，但**在 Word/LibreOffice 中零错位风险**。 |

### 内置 YAML 预设参数（可直接存为 `booklayout/key_presets.yaml`）

```yaml
# 版心默认 134 mm（170×240 mm 开本，左右页边距各 18 mm）；若 BookMeta 修改版心宽度，right_tab_mm 自动取 TEXT_W
defaults:
  font_size_pt: 9.5
  line_spacing: 1.05
  min_leader_mm: 8.0          # 点线短于 8 mm 时强制将目标整体换至下一行右对齐，杜绝 1–2 个点的“假省略号”
  couplet_gap_pt: 3.5         # 不同项对（Couplet）之间的段后呼吸间距
  lead_gap_pt: 0.0            # 同一项对内部两条之间的段后距
  keep_couplet_together: true # 同一项对前一条强制 keep_with_next=True，严禁跨页拆散一对二歧项
  italicize_taxa: true        # 目标区与特征区中的学名自动斜体，作者与页码正体
  remap_pages: true           # 第二遍构建时根据 page_map 自动将原书页码更新为新书页码

presets:
  bracketed_hanging:
    mode: tab_hanging
    label_col_mm: 13.0        # 悬挂缩进 left_indent=13mm, first_line_indent=-13mm，13mm 处设左对齐 Tab
    right_tab_leader: dots    # TEXT_W 处设右对齐点线 Tab (WD_TAB_LEADER.DOTS)
    label_bold: false
    continued_suffix_en: " (continued)"
    continued_suffix_zh: "（续）"

  bracketed_letter:
    mode: tab_hanging
    label_col_mm: 14.0        # 兼容 12a (11b) 稍宽的字母回溯序号
    right_tab_leader: dots
    label_bold: true
    continued_suffix_en: " (continued)"
    continued_suffix_zh: "（续）"

  indented_step:
    mode: stepped_indent
    step_mm: 5.5              # 每深入一层缩进 +5.5 mm
    label_col_mm: 9.0
    right_tab_leader: none    # 默认无点线，终结目标直接后接或右对齐
    label_bold: false

  tabular_3col:
    mode: borderless_table
    col_widths_mm: [13.0, 93.0, 28.0]  # 合计 134.0 mm；随 TEXT_W 等比缩放中列宽度
    cell_padding_pt: {top: 1.0, bottom: 1.0, left: 1.5, right: 1.5}
    right_col_align: right
    label_bold: false
```

## 二、五条不可违反的排版铁律（“至少是完整的一行”）

所有检索表（无论采用哪套预设、何种语言）在渲染时必须由代码强制执行以下 5 条硬规则：

1. **三段式逻辑行原子化**：每一条检索项（Lead）无论特征折成 1 行还是 5 行，都是一个完整的 `[序号] + [特征描述] + [目标]` 对象；严禁将下一项的序号粘进本行，也严禁在找不到点线时静默退化成普通段落。
2. **三区互不侵犯（悬挂对齐 + 点线保护）**：左侧序号固定占宽，特征描述折行后严格对齐特征区左缘（绝不顶回左页边距淹没序号）；右侧目标贴紧版心右缘；若末行过长导致点线不足 `8 mm`，强制将目标整体换行至下一行右对齐并铺满点线。
3. **目标区不可拆断（Atomic Target）**：右端的跳转号（如 `14`）或终结物种+页码（如 `*Harmothoe imbricata* (p. 46)`）作为一个整体禁止断词或跨行折断，且在第二遍建书时自动重映射为新书页码。
4. **项对成双、绝不拆页（Couplet Integrity）**：同一对二歧项内部紧贴（段后 `0 pt`），前一条强制 `keep_with_next = True` 防止把 `1(2)` 留在页底而把 `2(1)` 踢到下一页；项对之间统一留 `3.5 pt` 间距。
5. **跨页续表可追溯**：长检索表允许在项对之间自然分页，跨页顶端自动续印标题 + `(continued)` / `（续）`。

## 三、强结构化输入契约（大模型与脚本的交界标准）

翻译/OCR 阶段输出给 `booklayout/key_renderer.py` 的检索表必须采用以下标准 JSON（或在人工校对的 Markdown 中采用极简三列管道语法 `序号 | 特征描述 | 目标` 再由脚本转为 JSON）：

```json
{
  "key_id": "key_polynoidae_genera",
  "title": "Key to the genera of the family Polynoidae",
  "style": "bracketed_hanging",
  "couplets": [
    {
      "id": "1",
      "leads": [
        {
          "label": "1 (2)",
          "diagnosis": "15 pairs of elytra; prostomium with distinct cephalic peaks.",
          "target_type": "taxon",
          "target_label": "Harmothoe",
          "target_taxon_id": "HS1996_G012",
          "source_page": 42
        },
        {
          "label": "2 (1)",
          "diagnosis": "12 pairs of elytra; prostomium without cephalic peaks.",
          "target_type": "couplet",
          "target_id": "3"
        }
      ]
    }
  ]
}
```

## 四、老文献抗歪斜“原书样式学习”（默认还原原书 + 支持自由排版）

针对老扫描件常见的 1°–2° 歪斜、书脊弯曲与奇偶页裁切偏移，样式学习模块（`booklayout learn-style`）必须执行**两步抗噪解耦**，避免被单页歪斜带偏：

1. **先纠斜 + 全书抽样中位数统计（定量参数）**：
   * 抽样 10–15 页典型样页（标题、种记述、检索表、图注、文献），先按主文本行角度做 **Deskew 纠斜归零**，再按奇偶页分组扣除装订边偏移。
   * 缩进差值（Δx）、版心宽高比、字高比均取全书**中位数**，并自动吸附到标准出版刻度（如 4.3 mm → 4.0 mm），自动滤除个别歪斜离群页。
2. **大模型只判“定性风格”，产出可编辑 `book_style.yaml`**：
   * VLM 仅负责填写定性字段（如标题居中/全大写、检索表匹配 `key_presets.yaml` 中的 4 套预设之一、索引栏数等），生成人类可读的 `book_style.yaml` 并自动渲染 5 页预览样张供确认。
   * **还原原书模式（默认）**：沿用学出的 `book_style.yaml`，同时自动享受脚本级的纠平对齐、防拆页与页码重映射。
   * **自由排版模式**：因内容已结构化为 `TaxonTreatment` + `DichotomousKey`，随时可通过 `--style zootaxa` / `--style fauna-sinica` 或修改 `book_style.yaml` 一键切换全书版式，无需改动任何译文。

## 五、检索表构建前自动 QA 检查项（`transqa/key_qa.py`）

每次构建 DOCX/PDF 前自动执行以下零 Token 拓扑与版式检查，任一硬错误直接报错定位到具体 `key_id` 与 `couplet.id`：

* **成对完整性**：每个 `couplet` 至少包含 2 条 `lead`，序号连续无跳号、无重复。
* **图论可达性**：所有 `target_type == "couplet"` 的目标编号必须存在，从 `id == "1"` 出发可达所有终结物种，且无自环或死循环。
* **学名与页码校验**：所有 `target_type == "taxon"` 的学名与本书 `TaxonTreatment` / WoRMS 缓存一致；若含页码则确认 `page_map` 映射成功。
* **防退化断言**：渲染后的 DOCX 中不存在被静默降级为普通 `para()` 的检索行，也不存在残留的文本点线（`....` / `……` / ``）。
