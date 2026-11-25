booklayout/cli.py:1375 — 高 — 原地写回会更换 inode。等待旧 inode 锁的进程与取得新 inode 锁的进程可以同时读到同一版书稿，各自报告成功，后写者覆盖先写者的修改。— 建议加锁后重新核对全部目标的当前身份，任一变化就释放全部锁并重试。最小反例：三个 `patch-blocks` 进程分别修改同一文件的 A、B、C 三块。让 B 等待 A 的锁，A 写回后让 B 读稿并暂停，再让 C 完成，最后恢复 B。三个命令均成功，C 的修改消失。

booklayout/cli.py:1357 — 高 — 在 Linux 挂载的大小写不敏感目录中，若输出和报告都尚未创建，`resolve()` 会保留各自的大小写拼写，守卫会放行同一文件的两个名字。报告随后覆盖整份输出稿。— 建议按目标目录的实际文件名语义判重，或在写入输出后、写报告前再次用 `samefile` 检查。最小反例：在该目录中确保 `Out.json` 尚不存在，对有效书稿运行 `patch-blocks --aligned book.json --patch p.json --out Out.json --report out.json`，其中 `p.json` 为 `{"edits":[]}`。命令返回 0，打开 `Out.json` 得到补丁报告。

booklayout/normalize.py:2284 — 高 — `repair` 只在目标页查找已有块。跨页移动同一块时，它会按新块重建，静默丢掉原文和几何信息，并把来源页改成目标页。— 建议按全书唯一 `block_id` 找回原块并保留来源和几何字段，或在写回前拒绝跨页复用 ID。最小反例（内存实测）：第 1 页含 `{"block_id":"a","role":"body","text":"A","translation":"甲","source_page":1,"y0":20}`，第 2 页为空。应用 `{"pages":{"1":[],"2":[{"block_id":"a","role":"body","translation":"甲"}]}}` 后返回成功，第 2 页的 `a` 缺少 `text` 和 `y0`，`source_page` 变成 2。

booklayout/normalize.py:2281 — 高 — 同页已有块 ID 重复时，字典索引只保留最后一块。后续唯一性检查只看替换后的列表，单块补丁可以改错原文并删掉另一块。— 建议在建立索引前检查原稿 ID 唯一性，发现目标 ID 有歧义就拒绝整批。最小反例（内存实测）：第 1 页有两个 `role:"body"`、`block_id:"a"` 的块，原文依次为 `A`、`B`。应用 `{"pages":{"1":[{"block_id":"a"}]}}` 返回成功，只剩原文 `B`。

booklayout/normalize.py:2244 — 高 — 原稿页号重复时，`repair` 将补丁静默应用到最后一个同号页。清页操作会删除该页全部内容并报告成功。— 建议在建立 `by_page` 前拒绝重复页号。最小反例（内存实测）：两页的 `page` 都是 1，分别仅含块 `a`、`b`。应用 `{"pages":{"1":[]}}` 返回 `{"patched_pages":[1]}`，块 `a` 保留，块 `b` 被删除。

booklayout/normalize.py:2081 — 高 — v1 补丁接受显式 `page`，却只在 v2 校验页号。块移到另一页后，旧补丁仍能成功删除它。— 建议只要补丁提供 `page` 就校验类型和页号，同时保留 v1 省略该字段的兼容行为。最小反例（内存实测）：块 `a` 位于第 2 页，应用 `{"edits":[{"block_id":"a","page":1,"remove":true}]}`，结果 `removed` 为 `["a"]`、`stale` 为空，第 2 页被清空。