"""Input-hash cache for `booklayout build` (task 6).

Measured baseline (Vol. 48, 470 source pages): DOCX 16 s, LibreOffice PDF 43 s
(70 %), map-pages 2 s.  Re-running an unchanged build repeated all of it.

Two independent keys, both stored in a sidecar `<out>.buildcache.json`:
  * docx key  = hash of every input file, figure tree (name, size, mtime_ns),
    the booklayout source code, the effective output path and CLI options.
    Equal key and an existing DOCX -> skip `build()`, reuse the stored report.
    The code part is the builder-group fingerprint only (see `fingerprints`).
  * pdf key   = sha256 of the DOCX bytes.  Equal key and an existing PDF ->
    skip LibreOffice.
Any change to any input changes the key, so a stale artifact is never reused.
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

SIDECAR_SUFFIX = ".buildcache.json"
_PKG = Path(__file__).resolve().parent


def _sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _hash_files(paths: Iterable[Path]) -> str:
    h = hashlib.sha256()
    for p in sorted(paths):
        h.update(str(p.relative_to(_PKG)).encode())
        h.update(_sha_file(p).encode())
    return h.hexdigest()


def code_fingerprint() -> str:
    """Hash of the whole booklayout package source (kept for callers that want everything)."""
    return _hash_files(_PKG.rglob("*.py"))


def file_fingerprint(module: str) -> str:
    """sha256 of one package module's source (cache keys of per-page results)."""
    return _hash_files(_module_files(module))


def _imports_of(path: Path, top_level_only: bool = False) -> set[str]:
    """Top-level module names (inside this package) that `path` imports, at any nesting depth."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError):
        return set()
    found: set[str] = set()
    nodes = tree.body if top_level_only else ast.walk(tree)
    for node in nodes:
        if isinstance(node, ast.ImportFrom):
            if node.level >= 1 and not node.module:            # from . import x, y
                found.update(a.name for a in node.names)
            elif node.level >= 1 and node.module:               # from .x import y
                found.add(node.module.split(".")[0])
            elif node.module == "booklayout":                   # from booklayout import x
                found.update(a.name for a in node.names)
            elif node.module and node.module.startswith("booklayout."):
                found.add(node.module.split(".")[1])
        elif isinstance(node, ast.Import):
            found.update(a.name.split(".")[1] for a in node.names if a.name.startswith("booklayout."))
    return {m for m in found if (_PKG / f"{m}.py").is_file() or (_PKG / m / "__init__.py").is_file()}


def _module_files(name: str) -> list[Path]:
    f = _PKG / f"{name}.py"
    return [f] if f.is_file() else sorted((_PKG / name).rglob("*.py"))


def module_closure(roots: Iterable[str]) -> set[str]:
    """Package modules reachable from `roots` by static imports (lazy, in-function imports included)."""
    seen: set[str] = set()
    todo = list(roots)
    while todo:
        m = todo.pop()
        if m in seen:
            continue
        seen.add(m)
        for f in _module_files(m):
            todo.extend(_imports_of(f) - seen)
    return seen


BUILD_ROOTS = ("builder", "profile", "keymodel")   # what turns aligned.json into a DOCX
SOURCE_ROOTS = ("sourcecheck",)                    # what judges the PDF against the source scans


def fingerprints() -> dict[str, str]:
    """Per-module-group code fingerprints.

    builder: BUILD_ROOTS' static import closure plus cli.py/__init__.py/__main__.py (they hold the
             build command itself) and the modules cli.py imports at module level (normalize, styles,
             furniture...).  Editing qa.py, stylecheck.py or sourcecheck.py does NOT change
             it unless the builder imports them, so a gate edit no longer rebuilds the DOCX.
    source:  sourcecheck's closure (Tesseract triage, figure regions, folio).
    all:     every .py file.
    """
    def group(roots: Iterable[str], extra: Iterable[str] = ()) -> str:
        mods = module_closure(list(roots) + [m for e in extra for m in _imports_of(_PKG / f"{e}.py", True)])
        mods |= set(extra)
        files = [f for m in mods for f in _module_files(m)]
        return _hash_files(files)

    return {"builder": group(BUILD_ROOTS, ("cli", "__init__", "__main__")),
            "source": group(SOURCE_ROOTS), "all": code_fingerprint()}


def tree_fingerprint(root: Path) -> str:
    h = hashlib.sha256()
    if root.is_dir():
        for p in sorted(root.rglob("*")):
            if p.is_file():
                st = p.stat()
                h.update(f"{p.relative_to(root)}|{st.st_size}|{st.st_mtime_ns}\n".encode())
    return h.hexdigest()


def input_key(files: Iterable[Path | None], dirs: Iterable[Path | None], options: dict[str, Any]) -> str:
    h = hashlib.sha256()
    for f in files:
        h.update(b"F" + (str(f).encode() if f else b"-"))
        h.update(_sha_file(f).encode() if f and f.is_file() else b"missing")
    for d in dirs:
        h.update(b"D" + (str(d).encode() if d else b"-"))
        h.update(tree_fingerprint(d).encode() if d else b"-")
    h.update(json.dumps(options, sort_keys=True, default=str).encode())
    h.update(fingerprints()["builder"].encode())
    return h.hexdigest()


def sidecar(out_docx: Path) -> Path:
    return out_docx.with_name(out_docx.name + SIDECAR_SUFFIX)


def load(out_docx: Path) -> dict:
    p = sidecar(out_docx)
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save(out_docx: Path, state: dict) -> None:
    sidecar(out_docx).write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


def docx_hit(out_docx: Path, key: str) -> dict | None:
    """Stored report when the DOCX is current for `key`, else None."""
    st = load(out_docx)
    if st.get("docx_key") == key and out_docx.is_file() and out_docx.stat().st_size > 0 \
            and st.get("docx_sha256") == _sha_file(out_docx) and isinstance(st.get("report"), dict):
        return st["report"]
    return None


def pdf_hit(out_docx: Path, pdf: Path) -> bool:
    st = load(out_docx)
    return bool(pdf.is_file() and pdf.stat().st_size > 0 and st.get("pdf_docx_sha256")
                and st.get("pdf_docx_sha256") == _sha_file(out_docx) and st.get("pdf_path") == str(pdf))


def record_docx(out_docx: Path, key: str, report: dict) -> None:
    st = {"docx_key": key, "docx_sha256": _sha_file(out_docx), "report": report}
    save(out_docx, st)


def record_pdf(out_docx: Path, pdf: Path) -> None:
    st = load(out_docx)
    st.update({"pdf_docx_sha256": _sha_file(out_docx), "pdf_path": str(pdf)})
    save(out_docx, st)
