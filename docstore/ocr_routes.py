"""语种 -> OCR 引擎路由（规则在 rules/ocr_routes.toml）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

ROUTES_PATH = Path(__file__).resolve().parent / "rules" / "ocr_routes.toml"


@dataclass(frozen=True)
class Route:
    primary: str
    fallback: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    evidence: str = ""


@lru_cache(maxsize=1)
def _load(path: str = str(ROUTES_PATH)) -> dict[str, Route]:
    raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    return {
        lang: Route(
            primary=str(v["primary"]),
            fallback=tuple(v.get("fallback", ())),
            env={str(k): str(x) for k, x in v.get("env", {}).items()},
            evidence=str(v.get("evidence", "")),
        )
        for lang, v in raw.items()
    }


def route_for(lang: str | None) -> Route | None:
    """返回该语种的路由；表内没有则 None（调用方沿用旧默认）。"""
    return _load().get((lang or "").strip())
