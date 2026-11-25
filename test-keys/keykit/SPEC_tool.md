# keykit 工具规格（2026-11-23，主线程定；执行者照做）

目标：一个可用的检索表工具：读入（制作）→ 修正 → 排版 → 检查。全部在 test-keys/keykit/ 内，不改 booklayout/。

## 模块（新建）
1. ir.py —— 中间表示
   - dataclass Lead(text:str, kind:"jump"|"taxon"|"none", target:str, page:int|None=None, fig:str="", name_zh:str="")
   - dataclass Couplet(num:int, backref:int|None, leads:list[Lead])
   - dataclass KeyIR(heading:str, couplets:list[Couplet], lang:str="zh", source_style:str="")；to_json()/from_json()
   - from_keygraph(GKey) -> KeyIR：按 GBranch.couplet 分组，kind/target/jump/page 映射到 Lead；backref 取 GBranch.backref。
   - from_imajima_json(path, lang="zh", field="translation") -> list[KeyIR]：读 test-keys/imajima_keys/keys_2001.json 结构（pages[].blocks[]，role=heading 开新表，role=couplet 的 couplet{marker,lead,key,target,name}；同号两条 lead 合成一个 Couplet；target 为纯数字→jump，否则 taxon）。
   - from_markdown(md) -> list[KeyIR]：调用 keygraph.parse_text 再 from_keygraph。
2. profile.py
   - dataclass Profile(second_lead:"dash"|"prime"|"backref"|"serial"|"number", overflow:"wrap"|"fill", figref:"before"|"after"|"source", dest_zh_name:bool, font_size:float=10, latin_font="Times New Roman", cjk_font="SimSun", text_w_mm:float=150)
   - for_lang(lang, source_style=None) -> Profile：zh→overflow=wrap,dest_zh_name=True；en→fill,False；second_lead=source_style or 报错 ValueError("原书体例未确证，请指定 second_lead")。
   - load(path toml) 覆盖默认（tomllib）。
   - detect_style(raw_lead_tokens:list[str]) -> str|None：多数票："—/–/-"→dash，"1'/1′"→prime，"2 (1)"→backref，全数字独立递增→number；不足 70% 一致返回 None。
   - 规则依据写在 RULES.md 第四节，docstring 引用即可。
3. fix.py —— 修正（全部确定性，不调模型）
   - fix_text(s)：全角数字→半角（T2）；去 U+3000；点线前空格去掉；学名中属名+种加词之间的空格→NBSP（T6，用正则 [A-Z][a-z]+ [a-z]{3,}，只在 ASCII 拉丁词对之间）。
   - renumber(ir)：DFS 从 1 起按出现顺序重编号，jump 目标与 backref 同步更新；返回 (ir, 映射表)。
   - add_zh_names(ir, lookup)：lookup 是 callable(latin)->str|None（默认实现 yiku_lookup：subprocess 调 `yiku lookup <name> --domain 分类学`，只取状态为“已核”的中文名；解析失败返回 None）；无名的学名收集进报告列表返回，不拟名。
   - check(ir) -> list[dict(code,severity,detail)]：S1 两支、S2 死链/前指、S3 孤立号/重引用、L7 去向缺失、T2 全角数字、U+3000。
4. layout.py —— 排版（照 proto/tabtest.py build_table 已验证方案，必须保留：tblLayout fixed、tblCellMar 全 0、tblInd 0、tblGrid gridCol 宽度、tblW、行 cantSplit）
   - render_docx(irs:list[KeyIR], profile, out:Path) -> Path
   - 每表：标题段（keep_with_next）+ 两列无框表。编号列宽 = 按最长编号字符数估（每字符 0.55*字号pt 换 mm，+2mm，下限 8mm）。
   - 编号文本按 profile.second_lead：dash→第一条 "N."、第二条 "—"；prime→"N." / "N'."；backref→"N (B)." / "—"（B 为 backref，无则 "N."）；serial→每条独立序号 "k (m)" m 为对立条序号；number→"k."。
   - 去向文本：jump→数字；taxon→(dest_zh_name 且有 name_zh 则 "中文名 " + 学名) ；学名属/种斜体（ASCII 拉丁二名或单名斜体，作者年份正体；科及以上（-idae/-inae 结尾）正体）。图号按 figref 放去向前/后。
   - 去向通道宽 RIGHT = max(各去向估算宽度) + 4mm，上限 0.45*正文列宽（L8 全表统一）；估宽：CJK 字 1.0*字号，其他 0.5*字号（pt→mm ×0.3528）。
   - overflow=wrap：正文段 right_indent=RIGHT，右对齐点线制表位在单元格右缘（正文列宽），runs = 正文 + "\t" + 去向。
   - overflow=fill：正文段 right_indent=0，同一制表位；正文末尾 "\t" 后跟去向（Word/LO 会在行满时把去向推到下一行由点线引导——先实现，再由 verify 判定是否合格，不合格在报告中写明，不要绕过）。
   - 同偶句两行：第一行 keep_with_next（段落属性），满足 L6。
   - to_pdf(docx) -> Path：soffice --headless --convert-to pdf，输出同目录。
5. verify.py —— PDF 检查（PyMuPDF 1.27 已装）
   - verify_pdf(pdf, irs) -> list[dict]：逐页取 words/spans；对每个去向文本找到它所在行，检查 (L3) 去向右端 x 与版心右缘差 ≤ 1.5pt；(L5) 不存在“只有点线(+去向)的行”的前一行正文右端离通道左界 > 2 个字宽；(L8) 正文行右端不超过通道左界 +1pt；(L6) 同偶句两分支同页。
6. __main__.py —— CLI：python3 -m keykit {parse|check|fix|render|verify|make}
   - parse IN(.md|.json) -o ir.json；check ir.json；fix ir.json -o fixed.json [--renumber] [--zh-names]；render ir.json --profile p.toml|--lang zh -o out.docx [--pdf]；verify out.pdf ir.json；make IN --lang zh -o out.docx（parse→fix→check→render→pdf→verify 一条龙，输出报告 json）。
   - 退出码：有 severity=critical/major 时 1。
7. tests/ （pytest）：test_ir.py（imajima json 第 5 页解析出偶句数与去向）、test_profile.py（for_lang/detect_style）、test_fix.py（全角数字、点线前空格、NBSP、renumber 同步）、test_layout.py（生成 docx 后用 python-docx 读回：表 gridCol 宽度、cantSplit、tab stop 位置；若 soffice 存在则转 PDF 并 verify 无 L3/L5 问题，否则 skip）。

## 验收命令（必须全部跑并贴结果摘要）
cd test-keys/keykit/.. && python3 -m pytest -q keykit/tests
ruff check --line-length 120 keykit/ir.py keykit/profile.py keykit/fix.py keykit/layout.py keykit/verify.py keykit/__main__.py keykit/tests
mypy --ignore-missing-imports 同上文件
python3 -m keykit make imajima_keys/keys_2001.json --lang zh --source-style dash -o <scratch>/imajima2001_zh.docx  → 报告里 L3/L5/L8 问题数
