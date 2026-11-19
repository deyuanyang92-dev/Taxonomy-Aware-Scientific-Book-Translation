# booklayout 交付复盘：为什么反复重建、哪些问题没解决

日期：2026-11-17
范围：Fauna Ibérica Vol. 45/47/48 英文译本交付（`/mnt/p/翻译-译作/yanjie/`）。

## 1. 已修并验证的（可复现证据）

| 项 | 结果 | 证据 |
|---|---|---|
| 图注贴图 | 图注与上图间距全部 12.07 pt（源书最小 10.88） | `audit_captions.py`：Vol45 203 条、Vol47 144 条、Vol48 138 条，`<8 pt` 为 0 |
| 图注断词 | 自动断词 0 处 | `caption_word_breaks: 0`；仅 `narrow-hooded`、`mid-region` 原有连字符 |
| 检索表目标贴右缘 | 0 例外 | 全书扫描 `(p. N)` 目标 173/141/152 行；key-report `breaks 0 / defects 0` |
| 译者序 | 三卷均有 | “TRANSLATOR'S PREFACE” + “Translated by Yang Deyuan (杨德援).” |
| 未译内容块 | 0 | `untranslated_content_blocks: 0`（50/9/28 条为目录点线、文献等语言中性块） |

排版修复的代码根因与做法见 `docs/booklayout.md`；
本轮提交 `7bef9b6`（U+202F 原子目标、40 mm 最短引导点、合并条目拆分、图注 12 pt）。

## 2. 未解决的（必须明说）

1. **翻译质量从未系统检查。** 三审的文本检查只取 `role == "body"` 的块
   （`booklayout/cli.py:625` 起的过滤），实际检查 1447/5654、887/3722、938/3619，
   约 25%；citation、entry、caption、key 的译文不在检查范围内。
2. **机器核译仍有未决段**：`work/Vol*/translation/check_failed.json` 分别 119、90、6 段。
3. **gate 覆盖不全**：`booklayout gate` 只核对 qa/check/key-report，
   不含 `yzz.py zh check`、不含图注间距审计；而这些是工作区 `AGENTS.md` 第 1 节的交付要求。

## 3. 根因（本轮代价的直接来源）

1. **缺“一次查全”的审计入口。** 缺陷一类一跑：U+00A0 与 zh check 冲突、合并条目
   （`… 5 3. Collar …`）都是全量 PDF 出来后才发现，各触发一轮重建。
   本轮共 4 轮 × 3 卷重建、21 次 build pass、7 次整书 PDF 转换。
2. **修复顺序错。** 先改代码再验证，未先在数据层静态审计检索表行结构
   （条目号/目标/引导点长度可完全从 aligned JSON 判定，无需生成 PDF）。
3. **构建输入不可追溯。** `/tmp/rebuild_v2.sh` 依赖 `/tmp/norm5_47.json`、
   `/tmp/norm6_45.json`、`/tmp/norm5_48.json`；仓库无任何命令可生成这些文件，
   违反 `AGENTS.md` 0c“交付物必须由可追溯脚本流程生成”。
4. **主线程做机械活。** 读页图、量 bbox、grep、改数据都在主线程完成，
   未交脚本或 haiku 子代理，违反 token 节省规则。
5. **代码只做症状级修补。** qa 覆盖面、gate 内容、构建趟数、/tmp 依赖均未改变，
   同类缺陷在下一本书仍会漏过。

## 4. 计划的防线（按优先级）

| 优先级 | 改动 | 消除 |
|---|---|---|
| P0 | 新增 `booklayout audit`：一次输出全书缺陷计数（检索表内联/拆行/短引导点、图注间距/断词、重复段、截断句、西语残留、覆盖率），纯脚本 | 一类一跑、反复重建 |
| P0 | `gate` 串联 `zh check`、图注审计，并要求检查覆盖率 100%（按角色声明范围） | 最后一刻才发现 U+00A0 |
| P0 | 构建输入移入 `work/Vol*/layout/`，`build_report.json` 记录输入 SHA256 与命令行；rebuild 拒绝 /tmp 输入 | 交付不可复现 |
| P1 | key-breaks 改为从 aligned 数据静态计算，去掉 pass1 PDF 与 key-report 往返 | 3 趟构建降至 2 趟 |
| P1 | 三审扩展到 caption/entry/note 文本 | 图注、条目译文无检查 |
| P1 | 1 页样张 preflight：新字符/分隔符须过 soffice + `zh check` 才允许全量 | 字符兼容性返工 |
| P2 | `check_failed.json` 未决段交离线 DeepSeek flash（非思考、优惠时段），经 issues 闸口回填 | 翻译存疑段长期悬空 |

## 5. 结论

本轮交付解决的是**排版渲染**，不是**翻译内容**。在 P0 项落地前，
`gate.json` 的 `ok: true` 只能证明 qa/check/key-report 三类确定性检查通过，
不能作为“全书无翻译错误”的证据。
