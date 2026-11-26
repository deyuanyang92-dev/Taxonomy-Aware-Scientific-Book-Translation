"""PP-StructureV3（云 API 或本地）版面结果 -> booklayout 对齐 JSON（aligned/2，零模型）。

PP-StructureV3 的 prunedResult 与 PaddleOCR-VL 同为 parsing_res_list{block_label, block_content, block_bbox}，
区别只在标签集：多了 table / chart / formula / algorithm / reference 等。本脚本复用 vl_to_aligned.convert，
只换标签映射并把 table、chart 当图裁切（表格 HTML 不进正文，留给 booklayout 的表格角色另行处理）。
src.engine 默认 pp-structurev3。注意：仓库里 bench/api_runs/PP-StructureV3 只存了 markdown，没有 prunedResult 的 JSON，
本转换器只用合成样例测过，未对真实 PP-StructureV3 输出验证（T6，2026-11-26）。

用法：python3 scripts/structv3_to_aligned.py <版面目录 pNNNN.json[l]> <页图目录或 PDF> <输出目录> [--chapter KEY] [--pages 1-50]
      [--heading-levels auto] [--no-tess-fallback]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vl_to_aligned as V  # noqa: E402

MAP = {**V.MAP, "reference": "ref", "formula": "body", "algorithm": "body", "table_title": "caption",
       "chart_title": "caption", "figure_caption": "caption", "caption": "caption", "sidebar_text": "body"}
IMAGE_LABELS = ("image", "chart", "table")


def convert(layout_dir: Path, png_dir: Path, out: Path, chapter: str = "Book", pages_sel: set[int] | None = None,
            heading_levels: str = "flat", tess_fallback: bool = True, engine: str = "pp-structurev3") -> dict:
    return V.convert(layout_dir, png_dir, out, chapter, pages_sel, engine=engine, heading_levels=heading_levels,
                     tess_fallback=tess_fallback, label_map=MAP, image_labels=IMAGE_LABELS)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("layout_dir"), ap.add_argument("png_dir"), ap.add_argument("out")
    ap.add_argument("--chapter", default="Book")
    ap.add_argument("--pages", default=None)
    ap.add_argument("--heading-levels", choices=["flat", "auto"], default="flat")
    ap.add_argument("--no-tess-fallback", action="store_true")
    a = ap.parse_args(argv)
    r = convert(Path(a.layout_dir), Path(a.png_dir), Path(a.out), a.chapter, V.parse_pages(a.pages),
                a.heading_levels, not a.no_tess_fallback)
    print(f"pages={len(r['pages'])} blocks={sum(len(p['blocks']) for p in r['pages'])} figures={len(r['figures'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
