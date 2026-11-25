"""Input-hash cache for `booklayout build` (task 6).

Measured baseline (Vol. 48, 470 source pages): DOCX 16 s, LibreOffice PDF 43 s
(70 %), map-pages 2 s.  Re-running an unchanged build repeated all of it.

Two independent keys, both stored in a sidecar `<out>.buildcache.json`:
  * docx key  = hash of every input file, figure tree (name, size, mtime_ns),
    the booklayout source code, the effective output path and CLI options.
    Equal key and an existing DOCX -> skip `build()`, reuse the stored report.
  * pdf key   = sha256 of the DOCX bytes.  Equal key and an existing PDF ->
    skip LibreOffice.
Any change to any input changes the key, so a stale artifact is never reused.
"""
from __future__ import annotations

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


def code_fingerprint() -> str:
    """Hash of the booklayout package source: new code must rebuild."""
    h = hashlib.sha256()
    for p in sorted(_PKG.rglob("*.py")):
        h.update(str(p.relative_to(_PKG)).encode())
        h.update(_sha_file(p).encode())
    return h.hexdigest()


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
    h.update(code_fingerprint().encode())
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
