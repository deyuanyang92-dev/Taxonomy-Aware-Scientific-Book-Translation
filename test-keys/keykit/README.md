# keykit：检索表工具独立沙盒

来源：从 `booklayout/` 复制（2026-11-23，仓库 HEAD 7821b8e，含当时未提交改动）。
在这里反复优化，稳定后再集成回翻译软件（booklayout）。期间 booklayout 原件不动。

## 文件
| 文件 | 作用 |
|---|---|
| keymodel.py | 检索表结构模型（markdown → 偶句） |
| keygraph.py | 偶句去向图、闭合检查 |
| keymarkers.py | 编号/破折号标记识别 |
| keycheck.py | 结构检查 |
| keyfix.py | 页面级修复 |
| keyalign.py | 与页面文本对齐 |
| keyrender.py | PDF 渲染后排版检查 KR1–KR7 |
| builder.py | 整份复制，仅为 italicize_key_address / split_key_target / tabbed / key_* 排版函数；待拆出 |
| ir.py | 中间表示 KeyIR/Couplet/Lead；读 markdown（keygraph）与 Imajima keys_*.json |
| profile.py | 体例参数（RULES 第四节）、按语言取默认、原书体例检测 |
| fix.py | 确定性修正（全角数字、点线前空格、学名 NBSP、重编号、yiku 已核中文名、D1）与结构检查 |
| layout.py | DOCX 排版：两列无框固定宽表（样张验证方案） |
| verify.py | PDF 检查 L3/L5/L6/L8，点线长度 leader_gaps（L9） |
| __main__.py | CLI：`python3 -m keykit {parse,check,fix,render,verify,make}`（在 test-keys/ 下运行） |

## 用法
```bash
cd test-keys
python3 -m keykit make imajima_keys/keys_2001.json --lang zh --source-style dash -o OUT.docx   # 解析→修正→检查→排版→PDF→验版
python3 -m keykit make key.md --lang en --source-style dash -o OUT.docx                         # 英文：fill 模式，两遍排版
```
同名 `.report.json` 记修正、检查、验版结果；有 critical/major 时退出码 1。`--profile p.toml` 覆盖体例参数。

## 旧 booklayout 的已知缺陷（2026-11-23，Imajima2009_zh.pdf p6；keykit 新流程 ir/layout/verify 已绕开 1–3，4 待集成）
1. keyrender.leads_of 续行判字号，点线 span 10.5pt≠正文 9.5pt → 点线行被丢，误报 KR5 并跳过 KR3。
2. builder 放不下时把"点线+去向"整体另起一行，正文行留空白尾巴。
3. 无规则：行内点线前空格、检索表正文全角数字。
4. keyrender 未接入交付闸口。

## 任务队列
- [x] research/ 下三份规则调研完成（网络规则、本地多毛类文献、中文志书）
- [x] 据调研写 RULES.md 草案 v0（待用户定第四节体例）
- [x] 用户审定第四节（2026-11-23）：四项体例改为 profile 参数，按目标语言/原书取默认，用户可覆盖
- [x] 样张验证（2026-11-23）：段落+越界制表位在 LibreOffice 失败；两列无框固定宽表 Word/LO 都对（RULES.md 第六节 2）
- [x] 工具实现（2026-11-23）：ir/profile/fix/layout/verify/CLI，17 测试；Imajima 2001、2007 中文验版 0 问题；英文 fill 两遍排版 0 问题
- [x] L6：verify 改按全文字符位置找分支（原按页找误报）；跨页偶句由 make 第三遍在其前拆表分页（LibreOffice 不认表格行间 keep_with_next）
- [ ] 更多英文原书检索表回归；Word 渲染抽查一次
- [ ] clean_text 学名内保留 NBSP（T6）；新增 L8、T6 检查
- [x] 实现 profile 四参数（second_lead / overflow / figref / dest_zh_name）+ 原书体例检测
- [x] 新写 keykit/layout.py（不依赖 builder.py）；builder.py 副本待删
- [ ] 修上面 4 个缺陷，配回归测试（p6 三行）
- [ ] 用 imajima_keys/ 与 research 样本做语料回归
- [ ] 集成回 booklayout
