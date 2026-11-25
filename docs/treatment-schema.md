# 分类专著固定版式：treatment 记录（OCR 之后第一步结构化）

一条 treatment = 一个分类单元。字段顺序固定（Imajima 系列实证；其他书用规则文件适配）：

| 字段 | 内容 | 必填(种) |
|---|---|---|
| latin | 拉丁名 + 命名人 + 年 | 是 |
| ja | 日文和名（片假名，常带「新称」） | 是 |
| zh | 中文名（可选） | 否 |
| ref | 原始文献/来源 | 是 |
| description | 描述 | 是 |
| distribution | 分布（「分布—」开头） | 是 |
| legend | 图版分图说明（a:… b:…） | 有图则是 |
| caption | 图注（図N） | 是 |

版面里图与图注常在种名**之前**：解析时落在上一种分布之后、或属条目之后的 legend/caption 归下一个种。
属条目（只有拉丁名+命名人）只要求 latin。

## 工具
`booklayout treatments <aligned.json> [--out treatments.json] [--json] [--strict]`（零模型，`booklayout/treatments.py`）。
检查码：missing_<字段>、legend_without_caption、multiple_captions、duplicate_figure_no、figure_no_gap。
这些缺失在 OCR 后立刻暴露，不必等翻译和排版之后。

## 未做（诚实记录）
- 图版图像本身：aligned.json 不含图像块，无法判「有图无注」，只能判「有注无图」的反面（缺 caption）。需 OCR 阶段登记图像块。
- 卷内图号按科重置的书（2007 实测出现大量 duplicate/gap）需按章分组校验。
- 分布跨块断裂（「◆鮮海峡」）和破折号 OCR 成「一」需 OCR 修正规则（已对「一」放行）。
