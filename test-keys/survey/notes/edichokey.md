# edichokey（LaTeX 缩进式二叉检索表排版包）

## 1 定位与许可证
- 纯排版宏包，dichokey（Nico Dam）的扩展 (`edichokey-doc-en.tex`；`README.md:1-8`)。版本 2.01y，2020-08-31 (`edichokey.sty:22`)。
- 许可证：LPPL 1.3c (`edichokey.sty:4-10`)；示例键取自 Flora of North America，CC BY 3.0 (`edichokey-ex.tex:21-30`)。

## 2 输入格式
- LaTeX 环境，缩进即层级，无编号：
  `\begin{Key}[P.]` / `\alter 文字` / `\name[前缀]{学名}` / `\end{Key}` (`edichokey-doc-en.tex` demo)。例（4 行）：
  `\alter Leaves large \name{macrophyllus}` / `\alter Leaves small.` / `\alter Flower solitary. ... \name{...}`（缩进 \alter 表示下级）。
- 层级只靠嵌套书写顺序：\alter 跟在 \name 之后为同级的第二支，否则为下一级 (`edichokey.sty:81-93`)。

## 3 输出格式
- PDF（经 LaTeX）：缩进式（indented style）检索表，号为 `1. 2. ...`；对句同号，第二支回到上一层缩进 (`doc-en.tex` 三种样式对比)。可选 hyperref：对句互相超链接 (`sty:94-102`)。
- 去向点线：`\dot@line`，点线可折为两行，分类名右齐 (`sty:54-57,71-75`)；右边距让出 \taxonrightskip=2em (`sty:32,66`)。

## 4 建表算法
- 无选性状算法。只有自动编号：\alter 内维护 \edk@depth 与 \edk@couplet，号 = 递增的对句计数；数组 `edk@array@<depth>` 记每层当前号，\name 后回退到最近仍有未结分支的层 (`sty:81-93`)。
- 缩进 leftskip = 基础 + depth×1.2em + 号宽 (`sty:105`)。
- 多态/缺失/数值/权重/成本/回溯：不适用。

## 5 混合层级能力
- 无。单个 Key 环境为独立表；只有 \name 终止，不支持跳转或子表（仅 hyperref 对句互链）。README 的改进愿望含“为复杂检索表重写核心算法”（未逐行核，待确证）。

## 6 校验与错误处理
- 无校验。\alter 数目、嵌套缺漏不报错（未见 \PackageError，grep `sty` 全文）；号码错位只能目测。

## 7 可借鉴与不足
- 借鉴：①缩进式（indented）为国际期刊常用样式，keykit 可作输出格式之一；②点线可折行、分类名右齐、右边距预留，与我们两列固定宽表设计思路一致；③以嵌套深度而非显式编号作输入，用于作者手写；④hyperref 对句互链可映射到 docx 书签/PDF 链接。
- 不足：无编号稳定性、无子表、无校验；层级靠缩进易出错；仅 LaTeX。
