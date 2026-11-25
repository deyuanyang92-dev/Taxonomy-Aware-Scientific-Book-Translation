# 排版样板与硬规则（Imajima 2007 p1-12 v8 为下限）

样板：`/mnt/p/翻译-译作/日本-imajima/试译/baseline/imajima_p1-12_baseline.{docx,pdf}`（2026-11-21 用户确认"总体可以"；检索表除外，仍待改进）。
后续任何书的排版不得低于此样板。检索表版面不受此样板约束，以 `key-align` 流程为准。

## 流程（不可跳过）
1. 一切改版改 `make_aligned.py` / `profile.json` / `booklayout`，**不手改 HTML 或 docx**。
2. 构建：`python3 -m booklayout build --aligned A.json --figures F --metadata M.json --profile P.json --out X.docx --pdf --pdf-out X.pdf`（仓库根运行）。
3. 交付前三道闸，全过才交：
   - `python3 -m booklayout.stylecheck X.docx`（退出码 0；本文规则的自动检查）
   - `python3 /mnt/p/yzz-分类工作流/yzz.py zh check X.docx`
   - 逐页看图，与样板对照（先缩略图，再裁局部）。

## 格式规则（stylecheck 自动检查标★）
| 项 | 规则 |
|---|---|
| 斜体 | 只用于拉丁学名及拉丁文词。中文、日文一律不斜体★ |
| 标签 | 形态/生态/分类/分布 为粗体正体★；`**粗体**` 与 `*斜体*` 标记不得混用 |
| 图注、注释 | 同一样式：正体、左对齐、无首行缩进（profile `note_italic=false`）★ |
| 正文段落 | 首行缩进 5 mm，段间不空行，不用空段落调间距★ |
| 括号 | 后接中文时用全角（），英文/拉丁内容内部用半角★ |
| 标点 | 中文句内用全角（`cjk_punct`）；数字、拉丁词前后不加多余空格 |
| 空格 | 禁全角空格 U+3000★；拉丁词不拆行（`lang=en-US`、`lang_east_asia=zh-CN`；不得设 `lang=zh-CN`） |
| 章标题 | `chapter_headings=false` 时不生成章标题；无 level 的标题块默认一级 |
| ◆ 分布 | 种级保留 ◆（原书设计）；科级形态/生态/分类无 ◆ |

## 根因与防线（2026-11-21）
| 错误 | 根因 | 防线 |
|---|---|---|
| 标签斜体 | `**x**` 被当 `*x*` | `test_markdown_chunks_bold_not_italic`；stylecheck `label_not_bold` |
| 注释斜体且与图注不同 | 样式写死，未走 profile | `note_italic` 开关；stylecheck `caption_style_mismatch` |
| 半角/全角括号混用 | `cjk_punct` 缺"括号+中文"规则 | `test_cjk_punct_year_parens_fullwidth_before_cjk`；stylecheck `halfwidth_paren_before_cjk` |
| 以上均被 v8 交付后用户发现 | 无成品样式闸 | `booklayout/stylecheck.py` + `tests/test_stylecheck.py`，交付前必跑 |

新增格式问题：先在 stylecheck 加一项检查和测试，再改代码，最后更新本表。
