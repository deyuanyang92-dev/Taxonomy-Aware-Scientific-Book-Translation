# yiku 译库

Domain-aware English→Chinese terminology base for scientific translation. Learns the translator's term choices from published book pairs, ranks competing renderings by discipline, taxon scope and source authority, and injects the result into any LLM prompt (Codex, Claude, DeepSeek…). Translation itself stays with the model; terminology stays with the library.

领域化中英术语库。专业书翻译的难点在术语，而不在句子：同一英文词在不同学科、不同类群、不同学派有不同的规范译名，模型凭网络语料常常译错，几个模型轮换还会各译各的。yiku 只管术语。

## 设计

整体思路和框架示意图见 [docs/FRAMEWORK.md](docs/FRAMEWORK.md)。

- **一个库，多领域**：每条术语带 `领域`（分类学/进化生物学/科学史/分子系统学/`*`）、`类群范围`（如 `Serpulidae;Spirorbidae`）、`来源`、`页码`、`状态`（候选/已核/否决）。
- **来源分层**：用户裁定 0 < 权威专著 1 < 名录 3 < 名词委 4 < 名家译本/中文论著 5 < 学位论文 6 < Wikidata 8 < 模型 9。每个来源可单独指定层级。按用户 2026-11-09 的裁定，经典译作和名家论著在其本领域内为最高级；按领域生效的层级尚在计划中。
- **排序**：已核 > 候选；本领域 > 通用；本类群 > 通用；层级小者优先。其他领域的专用译名不返回，比如植物学的「居群」不会混进动物学书。
- **学习**：`paren` 从中文论著抽「中文（English）」；`pair` 从英文原著和中译本按章、按相对位置找译者实际用字。抽出来的都是候选，人工或主会话裁定后才生效。
- **与模型无关**：所有功能都是命令行，用的是 SQLite、TSV 和 Markdown。

## 用法
```bash
pip install -e .            # 扫描版 PDF：pip install -e .[ocr]
export YIKU_DB=~/.yiku/yiku.db

yiku source add mayr1982 --title "Mayr 1982 / 涂长晟等译 1990" --kind translation --domain 科学史
yiku pair en.pdf zh.pdf --source mayr1982 --domain 科学史 --auto --out review.tsv   # 审核后：
yiku import review.tsv --source mayr1982 --domain 科学史 --page-col 页码 --context-col 上下文
yiku paren 洪德元2016.pdf --source hong2016 --domain 进化生物学 --out paren.tsv

yiku table chapter.txt --domain 分类学 --scope Sabellidae   # 术语表 → 贴进任何模型的提示词
yiku check chapter.txt chapter_zh.md --domain 分类学        # 译文术语一致性（退出码 1 = 有问题）
yiku lookup population --domain 进化生物学
yiku review export queue.tsv && yiku review apply queue.tsv # 裁定候选
yiku wikidata Maldanidae --taxon                            # 网络线索，入库为 external 候选
yiku stats                                                  # 统计 + 未解决冲突
```
支持的格式：有文本层 PDF、扫描版 PDF（RapidOCR）、EPUB、DOCX、HTML、TXT/MD。

## 局限（已知）
- `pair` 的位置映射假定译本是全译、章序一致；节译或改编会降低准确度，章数对不上时退回整书映射（误差更大）。
- `paren` 的中文左边界靠虚词表截取，在洪德元 2016 上与人工核对表完全一致的约占 55%（32/58），其余要人工清理。
- Wikidata 中文标签只作线索：Maldanidae 在 Wikidata 作「缩头虫科」，与动物志、名录都不同（2026-11-09 查询）。
