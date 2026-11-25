booklayout/cli.py:1310 — 高 — 同一稿件的大小写别名会取得不同的锁，两个补丁都能成功，后写者覆盖先写者的校订 — 当前 `/mnt/p` 上已只读验证 `AGENTS.md` 与 `agents.md` 指向同一文件却生成不同锁键；两个进程分别用 `Book.json`、`book.json` 修改不同块，若都在首次替换前读稿，最终只保留后写者的修改 — 按父目录身份和文件系统的文件名比较规则生成稳定锁键，确保原子替换前后及大小写别名共用同一把锁。

booklayout/cli.py:1379 — 高 — `patch-blocks` 的防覆盖检查比较路径字符串，大小写别名可使报告覆盖整本稿件，`repair` 的补丁保护也有同样问题 — 在当前 `/mnt/p` 上运行 `patch-blocks --aligned Book.json --patch edits.json --report book.json`，补丁即使只有 `{"edits":[]}`，最后写入稿件路径的也是报告 — 写入前对已存在的路径使用 `samefile()` 检查，对待创建的路径使用与锁一致的路径比较规则。

booklayout/cli.py:1220 — 高 — `normalize`、`key-align`、`backfill-source` 未检查报告、输出与受保护输入是否重合，可直接覆盖整本稿件、译文 Markdown 或源结构文件 — `normalize --aligned book.json --report book.json` 会以报告替换稿件并返回 0；`key-align --aligned book.json --translation tr.md --out tr.md` 会以 JSON 替换译文 — 三个命令共用写前路径检查，只允许稿件输出指回 `--aligned`。

booklayout/normalize.py:2188 — 高 — `key-align` 留下的 `_drop=true` 会使后来成功提交的人工校订被 `normalize` 无记录地删除 — 对跨两块的检索表条目运行 `key-align`，再用 `patch-blocks` 将被清空的续块改成 `role=note, translation="Verified note."`；内存复现中补丁报告 `applied`，随后 `normalize` 删除整条注释且 `changes=[]` — 在 `key-align` 提交时移除已合并的块，或在后续补丁恢复有效内容时清除删除标记。

booklayout/normalize.py:2292 — 高 — `repair` 接受已有块的结构字段却忽略其值，报告页面已修复，表格仍保留错误数据 — 已有表 `t` 的 `rows=[["10"]]`，提交 `{"pages":{"1":[{"block_id":"t","role":"table","rows":[["20"]]}]}}`；即使附上匹配的页摘要，结果仍是 `10`，报告为 `patched_pages=[1]` — 对已有块逐项应用受支持字段，或在提交前拒绝任何无法兑现的字段修改。

booklayout/normalize.py:1844 — 高 — `backfill-source` 仅凭页号和位置型块 ID 回填，重切后能把另一段的原文绑定到正确译文，并将其计为回填成功 — 旧源页中 `p1_01` 是 “Gills absent.”；重切后在页首新增 “Gills present.”，新源页将 `p1_01` 分给新段；用新源页回填仍持旧 ID、只有译文「无鳃」的块，所得原文为 “Gills present.” — 将回填绑定到生成对齐稿时的源结构版本，版本变化时要求稳定源块标识或已核对的映射。

booklayout/normalize.py:1348 — 高 — `normalize` 合并正文时只合并译文，直接丢弃第二块的原文与来源标识；跨页合并也只额外保留词数 — 同页两块的原文依次为 `Tiene`、`dos alas.`，译文为 `It has`、`two wings.`；归一化后唯一块的译文是 `It has two wings.`，原文却只剩 `Tiene` — 保留两个源块及其指纹，在排版层合段，或为合并块保存完整、有序的来源片段。

booklayout/normalize.py:1110 — 高 — `normalize` 将不足三个空白分词且没有卷页格式的正规引文当作残片，删除整个块 — 单页只有一个 `role=citation` 块，原文和译文均为 `Smith, 1900`；归一化后 `blocks=[]` — 删除前要求有图版噪声的正面证据，并保留具有作者和年份的引文。

booklayout/normalize.py:1460 — 高 — 检索表尾注会覆盖未参与重切的下一个标题，原有标题译文丢失 — 同页依次放两条原文以 `.... 2`、`.... 3` 结束的 `key` 和标题 `Distribution`，第二条译文以 `.... 3 (adult only)` 结束；归一化后标题变为 `(adult only)` — 仅当标题确实加入待重切文本时才回写标题，否则将余文保留在末条检索表项。

booklayout/builder.py:980 — 高 — `patch-blocks` 接受 `legend` 角色，但正文排版器没有对应分支，构建成功时整段图例消失；含 `figures` 的 `figure_group` 也会被跳过 — 将唯一正文块 `translation="Unique legend."` 的角色补丁改为 `legend`，补丁报告 `applied`；实际调用 `render_body` 后文档只含章名 — 为两种合法角色实现渲染，并让未分派的合法角色在构建时显式报错。