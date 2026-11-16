"""Deterministic book layout from aligned translation blocks.

The package turns an aligned JSON produced by the translation pipeline into a
typeset DOCX/PDF: front matter, contents, body, figures, keys, references,
appendix and a re-paginated index.
"""
from __future__ import annotations

from .builder import BookMeta, BookPaths, build, make_page_map

__all__ = ["BookMeta", "BookPaths", "build", "make_page_map"]
__version__ = "0.1.0"
