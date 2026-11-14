"""问题单条目：所有检查器（通用、领域插件）统一输出。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Severity = Literal['critical', 'major', 'minor', 'info']
BLOCKING = ('critical', 'major')


@dataclass
class Issue:
    code: str                       # 机器可读类别，如 coverage.page_missing、number.missing
    severity: Severity
    message: str                    # 中文说明（给人看）
    page: int | None = None
    segment: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def blocking(self) -> bool:
        return self.severity in BLOCKING
