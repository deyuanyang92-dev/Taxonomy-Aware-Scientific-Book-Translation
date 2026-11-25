# open-delta（Atlas of Living Australia 的 DELTA 系统 Java 版，含 KEY 程序）

> 路径相对 `repos/open-delta/`。KEY 在 `key/`，共用算法在 `common/.../best/Best.java`。

## 1 定位与许可证
- DELTA 套件：CONFOR（转换）、KEY（建检索表）、INTKEY（交互检索）、DELFOR、delta-editor（README.md 与顶层目录 confor/key/intkey/delfor/delta-editor）。
- 许可证：仓库顶层无 LICENSE/COPYING 文件；源文件头为 Mozilla Public License 1.1（key/.../Key.java:1-12，Copyright 2011 Atlas of Living Australia）。以文件头为准，顶层许可文件：未确证。
- 源码确含 KEY 算法（KeyBest.java、Key.java）。

## 2 输入格式
- DELTA 数据集由指令文件组成：specs（*NUMBER OF CHARACTERS、*CHARACTER TYPES 如 `1,TE 2,RN 8,OM`）、chars（`#3. culms <注释>/` 后接 `1. woody …/` 状态行）、items（`# 名称/` 后 `特征号,状态` 对，如 `5,1/2` 多态、`86,1&2&3&5`、`85,30-40` 数值区间、`20,-` 不适用）（delta-editor/src/test/resources/dataset/{specs,chars,items}）。
- KEY 不直接读上述文本：先由 CONFOR 转成二进制 kchars/kitems（key/src/test/resources/sample/{kchars,kitems}；KeyItemsFileReader.java:46,165 读 INAPPLICABLE_BIT）。再由指令文件控制，如 `* RBASE 3`、`* ABASE 3`、`* VARYWT 1`（key/src/test/resources/sample/inputFile）。
- 已注册指令含 INCLUDE CHARACTERS/ITEMS、PRESET CHARACTERS、NUMBER OF CONFIRMATORY CHARACTERS、NO BRACKETED/TABULAR KEY、TRUNCATE TABULAR KEY AT、输出目录与 HTML 输出（KeyDirectiveParser.java:56-89）。

## 3 输出格式
- 先得表格式检索表（tabular key，Key.java:378 addRowsToTabularKey），再转括号式（bracketed key，KeyUtils.java:74 convertTabularKeyToBracketedKey）。
- 可排版为 RTF/HTML（Key.java 约 :1057、:1133 排版输出）。输出树为多叉（每状态一分支），不限二叉。

## 4 建表算法
- 递归 BEST：对当前类群集合，为每个可用性状算适用值 su，取最小者分裂，对每个子组递归（Key.java:247-376 doCalculateKey；KeyBest.java:63-257）。
- 分组：每个性状按状态把类群分入子组；多态类群进多个子组，故子组总数可大于类群数（KeyBest.java:215 的 sumNumTaxaInSubgroups）。
- 公式：sup0 = Σ(子组丰度×log2 子组大小)/Σ子组丰度；sep = log2(n) − sup0；sup = sup0 + dupf；su = 成本 + cmin·sup，su 越小越好（KeyBest.java:~195-228）。dupf 为变异惩罚：varw·(1+100·与原组同大子组数)·(Σ子组类群数−n)·((n+8)/(n·log2 n))（:215）。
- 成本与丰度：成本 = RBASE^(5−min(10,可靠度))；类群权重 = ABASE^(丰度−5)（KeyUtils.java:60,66）。默认 ABASE 2、RBASE 1.4、REUSE 1.01、VARYWT 0.8（KeyContext.java:100-103）。REUSE 用于除已用性状成本：未确证具体行号。
- 排除：全部子组与原组同大的性状 unsuitable；有同大子组且不允许 improper 子组时也排除（KeyBest.java:205-212）。sep 的绝对值不超阈值则置 0（:222）。平手按性状号小者先（:233-243）。
- 数值性状：KEY 只收多状态性状；CONFOR 按 key state boundaries 分箱，区间与边界比较得到所含状态（Best.java:425 generateKeyStatesForRealCharacter）。
- 不适用与缺失：控制性状使从属性状对该类群不适用（KeyItemsFileReader.java:185-199 checkApplicability）；建树时已用及不适用性状从可用集合剔除（Key.java:568 getSpecimenAvailableCharacters）。未知可按 TREAT UNKNOWN AS INAPPLICABLE 处理（KeyItemsFileReader.java:229）。
- 终止与其他：子组仅一类群或无可用性状即止；支持预置性状、确认性状数、STOP AFTER COLUMN（指令已注册）。回溯：不回溯（贪心）；重编号：括号式转换时编号（KeyUtils.java:74）。

## 5 混合层级能力
- 无显式多级检索表：不能科→属→种分级，也无子表跳转字段，仅括号式中的前后引用（未确证有其他）。
- 以 INCLUDE ITEMS 取子集重复运行，可手工得到各属子表。多入口/单入口切换：未确证（INTKEY 为多入口交互，KEY 为单入口树）。

## 6 校验与错误处理
- 指令解析抛 DirectiveException；VARYWT 须 0–1 的实数（KeyContext.java:163）。数据读入错误包成 RuntimeException（KeyUtils.java 加载段）。无独立的检索表质量校验。

## 7 可借鉴到 keykit 与不足
- 借鉴：①su = 成本 + cmin·sup，把性状可靠度、类群丰度、多态膨胀统一入分；②RBASE/ABASE/VARYWT 三个可调参数；③控制性状/不适用的显式建模；④预置性状与确认性状；⑤表格式→括号式两步输出；⑥DELTA 的 items 语法（`&` 多态、`-` 不适用、区间）可作导入格式。
- 不足：贪心无回溯；二进制中间文件；数值须预分箱；无层级跳转；公式中 100、8 等常数无文献依据：未确证。
