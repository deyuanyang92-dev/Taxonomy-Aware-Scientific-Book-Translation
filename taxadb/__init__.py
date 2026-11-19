"""taxadb：分类数据库（物种记述 treatment、名称用法 name_usage、来源 work）。

输入只来自 docstore 的库接口（open_store / store.pages / store.page / store.doc）；
切分规则全部放在 rules/*.toml，代码里不写某一卷的特例。
"""

from .db import DEFAULT_DB, open_db
from .rules import load_rules

__all__ = ["DEFAULT_DB", "open_db", "load_rules"]
__version__ = "0.1.0"
