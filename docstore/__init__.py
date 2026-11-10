"""docstore：本地资料库（资料登记、逐页文本、核对等级、全文检索）。

其他组件和技能只用这几个函数：
    open_store(root) -> Store
    store.search(q, **filters) / store.page(key, n) / store.pages(key) / store.doc(key)
"""

from .store import LEVELS, Store, open_store

__all__ = ["open_store", "Store", "LEVELS"]
__version__ = "0.1.0"
