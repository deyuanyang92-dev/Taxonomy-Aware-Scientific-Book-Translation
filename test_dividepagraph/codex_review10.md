发现 **6 项高严重度、5 项中严重度问题**。其中有两个反例只需合法输入：`normalize` 与 `patch-blocks` 均返回成功却丢掉校订，以及旧整页补丁在取得锁后删除后来新增的块。

全程只读，未修改文件。指定测试中，**78 项通过，17 项因涉及文件、CLI 或输出捕获夹具而跳过**。以下反例另在内存中验证。各片段共用这段准备代码：

```python
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from booklayout import cli
from booklayout.blockid import check_coverage, fingerprint_table, remap
from booklayout.normalize import (
    apply_block_edits, apply_page_patch, block_src_hash, block_struct_digest,
)
from booklayout.profile import validate_aligned

def book():
    b = {"block_id": "a", "role": "body", "text": "A", "translation": "甲"}
    return {"pages": [{"page": 1, "blocks": [b]}]}

def blocks(d):
    return d["pages"][0]["blocks"]

args = SimpleNamespace(aligned=Path("book"), patch=Path("patch"), out=None, report=None)
```

### 1. 高｜`normalize` 可覆盖已成功提交的块补丁

`patch-blocks` 与 `repair` 已共用锁，但 `normalize` 仍能在补丁前读取旧稿、在补丁后原地替换。实测即使 `normalize` 报告 `changed_blocks=0`，也会把刚写入的“新校”恢复为“甲”。`key-align`、`backfill-source` 同样有直接读改写入口。见 [cli.py:1197](booklayout/cli.py#L1197)、[cli.py:1200](booklayout/cli.py#L1200)、[cli.py:1329](booklayout/cli.py#L1329)。

```python
fs = book()
original = cli.normalize_aligned

def normalize_after_patch(snapshot):
    assert cli._patch_blocks_locked(args) == 0
    assert blocks(fs)[0]["translation"] == "新校"
    return original(snapshot)

def write(path, value):
    if path is not None:
        fs.update(deepcopy(value))

edit = {"edits": [{"block_id": "a", "translation": "新校"}]}
with patch.object(cli, "load_aligned", lambda p: deepcopy(fs)), \
     patch.object(cli, "_load_patch", lambda p: edit), \
     patch.object(cli, "_write_json", write), \
     patch.object(cli, "normalize_aligned", normalize_after_patch):
    assert cli.cmd_normalize(args) == 0
assert blocks(fs)[0]["translation"] == "甲"
```

建议让所有原地修改对齐稿的命令共用同一事务入口，加锁后才读稿，持锁直至替换完成。回归测试应固定上述交错，并断言最终译文。

### 2. 高｜旧整页补丁取得锁后仍会删除后来新增的块

`repair` 的锁只能串行化命令执行。补丁可以提前生成，而整页替换没有旧页摘要。用户生成只列 `a` 的补丁后，另一位校者加入 `b`，此时单独运行 `repair` 就会报告成功并删除 `b`。这个反例没有并发执行，也没有块 ID 漂移。见 [normalize.py:2228](booklayout/normalize.py#L2228)、[normalize.py:2245](booklayout/normalize.py#L2245)。

```python
d = book()
pending = {"pages": {"1": [{"block_id": "a"}]}}
blocks(d).append({"block_id": "b", "role": "body", "text": "B"})
assert apply_page_patch(d, pending)["patched_pages"] == [1]
assert [b["block_id"] for b in blocks(d)] == ["a"]
```

建议给整页补丁增加按页的 `old_page_digest`，绑定生成时的完整有序块列表。持锁后先核对所有目标页，任一页变化即整批拒绝。旧格式可保留为显式的无前置条件整页替换。

### 3. 高｜两个不同 JSON 键可指向同一页，后项静默覆盖前项

`"1"` 与 `"01"` 均通过重复 JSON 键检查，随后 `int(number)` 将两者解析为同一页。实测首项校订被第二项清空，报告甚至将页 1 计为成功两次。见 [normalize.py:2218](booklayout/normalize.py#L2218)、[normalize.py:2229](booklayout/normalize.py#L2229)。

```python
d = book()
p = {"pages": {"1": [{"block_id": "a", "translation": "校订"}], "01": []}}
assert apply_page_patch(d, p)["patched_pages"] == [1, 1]
assert blocks(d) == []
```

建议在预检阶段生成规范页号映射，拒绝归一后重复的页号，再开始替换。

### 4. 高｜对齐稿中的重复 JSON 键会在写回时永久丢失

补丁使用严格解析器，对齐稿仍通过默认 `json.loads` 读取。只要输入稿重复出现 `pages`，前一份页数组就会在加载时消失。实测一个合法的 v2 空补丁也会返回 0，并把空书写回。第八轮修复的重复键检查仅覆盖补丁输入。见 [cli.py:1349](booklayout/cli.py#L1349)、[cli.py:1380](booklayout/cli.py#L1380)、[cli.py:1399](booklayout/cli.py#L1399)。

```python
raw = '{"pages":[{"page":1,"blocks":[{"text":"原稿"}]}],"pages":[]}'
written = {}
def read(path, **kw):
    return raw if path == args.aligned else '{"version":2,"edits":[]}'
with patch.object(Path, "read_text", read), \
     patch.object(cli, "_write_json", lambda p, v: written.update(v) if p else None):
    assert cli._patch_blocks_locked(args) == 0
assert written == {"pages": []}
```

建议所有会写回的入口对对齐稿也使用逐层重复键检查，解析失败时保留原件。

### 5. 高｜`repair` 能提交重复块 ID，使后续块补丁全部失效

页补丁只逐条检查 ID 是非空字符串，没有验证替换后全书 ID 唯一。下例把一个块复制为两个同 ID 块，`repair` 报成功，而 `apply_block_edits` 随后连空补丁都会拒绝。另一个入口是新块沿用未修改页中的 ID。见 [normalize.py:2225](booklayout/normalize.py#L2225)、[normalize.py:2244](booklayout/normalize.py#L2244)、[normalize.py:2046](booklayout/normalize.py#L2046)。

```python
d = book()
p = {"pages": {"1": [{"block_id": "a"}, {"block_id": "a"}]}}
assert apply_page_patch(d, p)["patched_pages"] == [1]
assert any("duplicate block_id" in s for s in validate_aligned(d))
# 此时 apply_block_edits(d, {"edits": []}) 抛出 ValueError
```

建议先构造候选结果，把替换页和保留页一起检查。任何重复 ID 都应在提交前报告，并给出冲突的页和块位置。

### 6. 高｜`repair` 接受完整新表格，却丢弃原文和单元格

构造新块时只复制 `role`、`translation`、`level`。提交者明确提供的 `text` 和 `rows` 被静默忽略，旧页随即被替换，输出连仓库自己的结构校验也无法通过。见 [normalize.py:2234](booklayout/normalize.py#L2234)、[normalize.py:2241](booklayout/normalize.py#L2241)、[normalize.py:2245](booklayout/normalize.py#L2245)。

```python
d = book()
entry = {"block_id": "t", "role": "table", "translation": "表",
         "text": "Table", "rows": [["标本号", "123"]]}
assert apply_page_patch(d, {"pages": {"1": [entry]}})["patched_pages"] == [1]
assert "rows" not in blocks(d)[0] and "text" not in blocks(d)[0]
assert validate_aligned(d)
```

建议明确新块支持的字段并保留其值，对不支持的字段报错。整页候选通过角色结构校验后才替换原页。

### 7. 中｜`repair` 收到块补丁时会返回成功

传错补丁文件是可复现的正常操作失误。缺少顶层 `pages` 时，默认值 `{}` 把整个请求变为空操作；CLI 仍写出结果并返回 0。依赖退出码的下游会把请求的修改视为已完成。见 [normalize.py:2213](booklayout/normalize.py#L2213)、[cli.py:1414](booklayout/cli.py#L1414)。

```python
d = book()
wrong = {"version": 2, "edits": [{"block_id": "a", "remove": True}]}
assert apply_page_patch(d, wrong) == {"patched_pages": []}
assert len(blocks(d)) == 1
```

建议要求顶层为对象且显式包含 `pages`，拒绝未知顶层字段。需要空操作时可明确传 `{"pages": {}}`。

### 8. 中｜更新操作会忽略显式提交的 `old_struct`

`old_struct` 在编辑字段白名单内，实际比较却只在 `remove` 分支执行。调用者对角色转换显式设置整块前置条件后，即使人工已改变块内容，转换仍进入 `applied`。见 [normalize.py:1878](booklayout/normalize.py#L1878)、[normalize.py:2084](booklayout/normalize.py#L2084)。

```python
d = book()
b = blocks(d)[0]
e = dict(block_id="a", page=1, role="heading", old_role="body",
         old_hash=block_src_hash(b), old_prev="", old_next="",
         old_struct=block_struct_digest(b))
b["translation"] = "人工新校"
assert apply_block_edits(d, {"version": 2, "edits": [e]})["applied"] == ["a"]
```

建议只要提交 `old_struct` 就执行比较。如果协议决定该字段仅适用于删除，则应将其用于更新的请求判为 `invalid`。

### 9. 中｜完整覆盖闸口把布尔型源页 `true` 当成第 1 页

`_sp` 原样返回布尔值。Python 中 `True == 1`，两者也有相同的哈希值，因此跨页比较和完整源块多重集检查同时放行。实测 `block_level_checked=True` 且 `ok=True`。见 [blockid.py:31](booklayout/blockid.py#L31)、[blockid.py:186](booklayout/blockid.py#L186)、[blockid.py:201](booklayout/blockid.py#L201)。

```python
d = book()
b = blocks(d)[0]
b["source_page"] = True
r = check_coverage(d, [1], expected_blocks=[(1, block_src_hash(b))])
assert r["block_level_checked"] and r["ok"]
```

建议统一验证逻辑页和源页的类型。保留已约定的数字字符串兼容，显式拒绝布尔值和浮点数，并把异常页号加入失败诊断。

### 10. 中｜同一旧 ID 混有孤儿行和歧义行时，人工队列会丢掉可用候选

第九轮测试覆盖了“两行各有候选”。另一个分支仍按 ID 建立 `orphan_set`。只要其中一行是孤儿，同 ID 的另一行也会被写成孤儿，即使它有明确的人工复核候选。见 [blockid.py:118](booklayout/blockid.py#L118)、[blockid.py:122](booklayout/blockid.py#L122)、[test_blockid.py](tests/test_blockid.py)。

```python
d = book()
row = {**fingerprint_table(d)[0], "block_id": "dup"}
r = remap([row, {**row, "hash": "missing"}], d)
assert r["ambiguous"]["dup"] == ["a"]
assert [(x["status"], x["candidates"]) for x in r["queue"]] == [
    ("orphan", []), ("orphan", [])
]
```

建议在首次遍历时按行号保存**状态和候选**，直接从行记录生成队列。回归测试应断言两种输入顺序下，有候选的原始行始终保留 `["a"]`。

### 11. 中｜表格列宽数超过实际列数仍通过角色转换，排版随后失败

单元格和 `colspan` 全部合法时，`col_widths_mm` 仍可比实际表格多一列。补丁报告转换成功，排版器访问不存在的第二列，实测抛出 `IndexError`。见 [profile.py:135](booklayout/profile.py#L135)、[normalize.py:2106](booklayout/normalize.py#L2106)、[builder.py:1010](booklayout/builder.py#L1010)。

```python
from docx import Document
from booklayout.builder import render_generic_block

d = book()
blocks(d)[0].update(rows=[["唯一一列"]], col_widths_mm=[20, 20])
p = {"edits": [{"block_id": "a", "role": "table"}]}
assert apply_block_edits(d, p)["applied"] == ["a"]
render_generic_block(Document(), blocks(d)[0], set())
# IndexError: column index [1] is out of range
```

建议在共享校验器中按各行 `colspan` 总和计算实际列数，拒绝超长列宽列表，并补测转换失败后仍保留原角色。