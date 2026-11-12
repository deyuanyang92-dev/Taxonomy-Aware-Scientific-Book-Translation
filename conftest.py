"""让仓库内的 yiku/ 与 docstore/ 优先于本机其他已安装副本（如 /root/github/yiku 的 pip -e 安装）。"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
for p in (_ROOT / "yiku", _ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
# scripts/ 下是独立脚本，不是包；追加到末尾，避免 qa、extract 等模块名遮住其他库
for p in (_ROOT / "scripts", _ROOT / "scripts" / "publish", _ROOT / "scripts" / "bench"):
    if str(p) not in sys.path:
        sys.path.append(str(p))
