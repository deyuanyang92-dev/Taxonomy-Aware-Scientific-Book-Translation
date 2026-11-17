# 分类学排版的斜体/正体规则（英文译稿）

用户 2026-11-16 指出：译文里属名没有斜体，检索表里也没有。根因不是模型译错，而是 OCR 只给字形、不保留斜体，Google/DeepSeek 也不会替原文补排版；`transqa` 原有的学名护栏只检查“原文斜体是否保留”，原文没有斜体标记时这条检查是空的。

2026-11-17 用户再指出两类斜体错误：①作者名被排成斜体（`*Rouse and Fauchald*`、`*Rouse and* Fauchald`）；②整条图注全部斜体。核对原书：图注整体是 ITC Garamond Light Italic，学名正体（Vol. 45 p. 30）；但用户按出版惯例定：**图注正体、学名斜体**，不照搬原书的全斜体图注。

## 规则

| 阶元/成分 | 排版 | 例 |
|---|---|---|
| 属名（含单称、标题、检索表、图注） | 斜体 | *Opisthodonta*、*Lagisca* |
| 种加词、亚种加词（双名/三名） | 斜体 | *Opisthodonta morena*、*Lagisca zibrowii* |
| 属名缩写 + 种加词 | 斜体 | *O. morena*、*P. cirrata* |
| 亚属名（括号内） | 斜体 | *Opisthodonta* (*Opisthodonta*) *morena* |
| 三名法的亚种/变种加词 | 斜体 | *Opisthodonta morena morena* |
| `var.` / `f.` / `subsp.` 等阶元词 | 正体；后面的加词斜体 | *Laonice cirrata* var. *postcirrata*；*L. cirrata* subsp. *morena* |
| 科、亚科、族、总科等科级以上阶元 | 正体 | Syllidae、Eusyllinae、Polynoidae、Polychaeta、Annelida |
| 命名人与年份 | 正体 | Langerhans, 1879；Southern, 1914 |
| 阶元符号词 | 正体 | sp.、spp.、sp. n.、n. sp.、cf.、aff.、var.、gen. n. |
| 检索表编号、跳转数字、点线 | 正体 | `3. ... ..... 4` |

检索表、图注、标题、异名录、参考文献里的学名同样按上表处理；不能因为“在检索表里”就全部正体，也不能把科名一起斜体。

## 实现

`scripts/taxoformat.py`（0 token，确定性）：

- 属名/双名/三名优先取本机 WoRMS 缓存 `/root/.specimen_inventory/worms_cache.sqlite` 的 Annelida 记录（约 1500 属、7000 双名）。
- 文本中新描述的种（`sp. n.` / `n. sp.`）、带命名人年份的标题、`genus X` 标签、重复出现的双名，补进词表；不用“大写词 + 任意小写词”硬猜，避免把 `Richer de Forges`、`Dutch coast` 当学名。
- WoRMS 未收录的异名/新组合（如 `Syllis longifilis`）：属名后的第二个词若是小写、非阶元符号、非英语停用词，仍按双名斜体；`*Leanira* it`、`*Onuphis* cannot` 这类英语词只斜体属名。
- 已带斜体的属名后跟正体种加词时补全：`*Syllis* longifilis` → `*Syllis longifilis*`。
- 行首 OCR 脚注星号（`* ABSTRACT:`）后面是空格，不当斜体开头；否则会与真正的 `*Genus species*` 配对，产生 `**Genus species**`。不成对的星号输出为 `\*`，Markdown 渲染仍是字面星号。
- 已转义的 `\*` 不算斜体定界符（`(?<!\\)`）：上游把 `*B. clavata*` 拆成两页时会出现 `\*B.\n\nclavata\*`，旧代码把前一个 `\*` 当开头、后一个当结尾，输出拆坏的 `\**B. ... clavata*\*`。
- 学名各词之间只用 `_SEP`（段内空白，最多一个换行），不跨空行：否则缩写属名 `B.` 会与下一段的 `clavata` 拼成 `*B. clavata*`。
- 科名后缀（-idae/-inae/-ini/-oidea 等）、`sp./cf./aff.`、命名人一律不斜体。
- 保护 HTML 页标记、已有斜体、代码、链接，不重复套斜体。
- `auto_translate.py` 的英文定稿阶段自动调用；`_work/build_delivery.py` 生成交付文本时再跑一遍（兼容改动前已完成的译稿）。

测试：`tests/test_taxoformat.py`（双名、缩写、cf.、sp. n.、检索表、图注、全大写标题、三名、亚属、亚种同名、var./subsp.、未收录种加词、已有斜体属名补全、脚注星号、跨行转义星号、科名正体、停用词）。

## 已知残留

- 缩写种名若正文没有全名，仍按“单字母属名缩写 + 小写种加词”斜体（*L. hubrechti*）；I/V/X 是罗马数字，不算属名缩写。
- 三名法中第三个词若不在 WoRMS 亚种表，也按“属名 + 种加词 + 同名亚种加词”斜体；其他未知第三词只斜体前两词，避免把后面的普通形容词误当亚种。
- OCR 把标题、作者、脚注并成一行时，脚注 `*` 可能被 Markdown 当成强调；属段落结构问题（issue #16），不是本脚本造成。
- 本机 WoRMS 缓存只覆盖 Annelida；其他类群需换对应分类库或 `--genera` 补表。

## 图注与斜体审计：`scripts/italic_check.py`

图注排版（2026-11-17 用户定）：图注正文正体，学名斜体；`booklayout` 的 `caption()` 已按此排。原书的“整条图注斜体”不采用。

检查项：

| kind | 级别 | 含义 |
|---|---|---|
| `italic.cjk` | critical | 斜体里有汉字 |
| `citation.italic` | major | 斜体是文献目录里确证的引证（年份+姓氏命中） |
| `italic.author` | major | 作者名斜体，但文献目录查不到 |
| `italic.mixed` | major | 学名后夹英语虚词（`*Torrea and*`、`*Miura and*`） |
| `caption.allitalic` | major | 整条图注都在斜体里 |
| `caption.name_roman` | major | 图注学名被排成正体（`--caption-names italic` 时报） |
| `italic.higher_taxon` | info | 科名斜体（原书作者名单里本来就斜体，不阻断） |
| `italic.other` | info | 书名、强调等 |

文献引证判别：`--aligned <aligned.json>` 用 `role=ref` 的块建「年份 → 姓氏」索引；不给时从 DOCX 的 References 节建。片段含年份且姓氏命中该年条目 → `citation.italic`（确证）；无年份但姓氏都在文献目录、且带 and/et al./与 等连词 → 按引证处理。

```
python3 scripts/italic_check.py md 译文.md [--report out.tsv]
python3 scripts/italic_check.py docx 书.docx [--aligned aligned.json] [--report out.tsv]
python3 scripts/italic_check.py docx 书.docx --fix --aligned aligned.json   # 写 书_italic.docx
python3 scripts/italic_check.py pdf 原书.pdf --pages 20-40                  # 审计原书图注字体
```

`--fix` 只改正体/斜体，不改文字：图注整段重排为“正文正体 + 学名斜体”；正文里引证、作者名、中文、学名夹虚词的斜体段去斜体，学名部分保留斜体。回归测试 `tests/test_italic_check.py`。

## 根因（2026-11-17）

- 作者名斜体：`booklayout.build_genus_set` 把段首 `Rouse y Fauchald…` 当成“属名 + 种加词”，`add_runs` 又把连词 `and/y` 当种加词，整段排成斜体。修复：段首第二个词是虚词（and/or/of/y/de…）时不收为属名；`add_runs` 跳过虚词种加词。回归测试 `test_caption_roman_with_italic_names`、`tests/test_italic_check.py`。
- 图注全斜体：`caption()` 照搬原书 `italic=True` 整段排。修复：改成正体，学名由属名检测/`*…*` 标成斜体。
- 属名后接英语词被整段斜体（2026-11-17 第二轮）：旧 `add_runs` 只排除虚词和 sp./cf. 等缩写，`Lopadorrhynchus comprises the`、`Onuphis deposited in` 这类“属名 + 英语词”被当成“属名 + 种加词”整段斜体；`build_genus_set` 同时把 `Material examined` 这类段首普通词语收成属名。修复：新增 `booklayout/english.py`，用系统 hunspell 词典（`/usr/share/hunspell/en_US.dic`，与 `scripts/taxoformat.py` 同源）判定英语词；种加词是英语词时只排属名斜体，`build_genus_set` 也跳过英语词。回归测试 `test_body_genus_followed_by_english_word_italicises_genus_only`、`test_genus_set_skips_english_second_word_and_authors`。
- 图注中单独出现的属名不斜体（2026-11-17 第二轮）：旧正则要求“属名 + 小写词”才斜体，`Cenogenus sp.`、`Apomatus Philippi, 1844`、`Apomatus (fig. 82A)` 里的属名都没排斜体。修复：属名单独出现也排斜体（分类学惯例），后接 sp./spp./cf./aff. 时缩写保持正体。回归测试 `test_caption_italicises_bare_genus_but_not_sp`、`test_caption_italicises_genus_before_author`。
