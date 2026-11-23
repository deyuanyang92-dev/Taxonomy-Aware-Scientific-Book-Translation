"""keykit CLI：python3 -m keykit {parse|check|fix|render|verify|make}。有 critical/major 问题时退出码 1。"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from . import fix as fx
from .ir import KeyIR, dump_irs, from_imajima_json, from_markdown, load_irs
from .layout import render_docx, to_pdf
from .profile import Profile, for_lang, load
from .verify import leader_gaps, verify_pdf


def _read(path: Path, lang: str, field: str) -> list[KeyIR]:
    if path.suffix == ".md" or path.suffix == ".txt":
        return from_markdown(path.read_text("utf-8"), lang)
    d = json.loads(path.read_text("utf-8"))
    if "pages" in d:
        return from_imajima_json(path, lang, field)
    return load_irs(path)


def _profile(args: argparse.Namespace, irs: list[KeyIR]) -> Profile:
    style = getattr(args, "source_style", None) or next((k.source_style for k in irs if k.source_style), None)
    prof = for_lang(args.lang, style)
    if getattr(args, "profile", None):
        prof = load(args.profile, prof)
    return prof


def _check_all(irs: list[KeyIR]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, k in enumerate(irs):
        for it in fx.check(k):
            it["key"] = i
            out.append(it)
    return out


def _bad(issues: list[dict[str, Any]]) -> bool:
    return any(i["severity"] in ("critical", "major") for i in issues)


def _fix_all(irs: list[KeyIR], renum: bool, zh: bool) -> dict[str, Any]:
    rep: dict[str, Any] = {"missing_zh": []}
    for k in irs:
        fx.fix_ir(k)
        if renum:
            fx.renumber(k)
        if zh:
            _, miss = fx.add_zh_names(k)
            rep["missing_zh"].extend(m for m in miss if m not in rep["missing_zh"])
    return rep


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="keykit")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--lang", default="zh")
        p.add_argument("--field", default="translation")
        p.add_argument("--source-style", dest="source_style")
        p.add_argument("--profile")

    p = sub.add_parser("parse")
    p.add_argument("input")
    p.add_argument("-o", required=True)
    common(p)
    p = sub.add_parser("check")
    p.add_argument("ir")
    p = sub.add_parser("fix")
    p.add_argument("ir")
    p.add_argument("-o", required=True)
    p.add_argument("--renumber", action="store_true")
    p.add_argument("--zh-names", action="store_true")
    p = sub.add_parser("render")
    p.add_argument("ir")
    p.add_argument("-o", required=True)
    p.add_argument("--pdf", action="store_true")
    common(p)
    p = sub.add_parser("verify")
    p.add_argument("pdf")
    p.add_argument("ir")
    common(p)
    p = sub.add_parser("make")
    p.add_argument("input")
    p.add_argument("-o", required=True)
    p.add_argument("--renumber", action="store_true")
    p.add_argument("--zh-names", action="store_true")
    common(p)
    a = ap.parse_args(argv)

    try:
        if a.cmd == "parse":
            irs = _read(Path(a.input), a.lang, a.field)
            dump_irs(irs, Path(a.o))
            print(json.dumps({"keys": len(irs), "couplets": [len(k.couplets) for k in irs]}, ensure_ascii=False))
            return 0
        if a.cmd == "check":
            iss = _check_all(load_irs(Path(a.ir)))
            print(json.dumps(iss, ensure_ascii=False, indent=1))
            return 1 if _bad(iss) else 0
        if a.cmd == "fix":
            irs = load_irs(Path(a.ir))
            rep = _fix_all(irs, a.renumber, a.zh_names)
            dump_irs(irs, Path(a.o))
            print(json.dumps(rep, ensure_ascii=False))
            return 0
        if a.cmd == "render":
            irs = load_irs(Path(a.ir))
            out = render_docx(irs, _profile(a, irs), Path(a.o))
            if a.pdf:
                print(to_pdf(out))
            print(out)
            return 0
        if a.cmd == "verify":
            irs = load_irs(Path(a.ir))
            iss = verify_pdf(Path(a.pdf), irs, _profile(a, irs))
            print(json.dumps(iss, ensure_ascii=False, indent=1))
            return 1 if _bad(iss) else 0
        irs = _read(Path(a.input), a.lang, a.field)
        rep = {"parse": {"keys": len(irs), "couplets": [len(k.couplets) for k in irs]}}
        prof = _profile(a, irs)
        pre = [x for x in _check_all(irs) if x["code"] == "D1"]
        # 中文 profile（dest_zh_name=on）自动从 yiku 补去向中文名；残缺的「亚科 X」在此修复，修复前的 D1 记入报告
        rep["fix"] = _fix_all(irs, a.renumber, a.zh_names or prof.dest_zh_name)
        rep["fix"]["d1_before"] = pre
        ck = _check_all(irs)
        out = render_docx(irs, prof, Path(a.o))
        pdf = to_pdf(out)
        # 两遍排版：量点线长度，短于 1 字宽（L9）的分支——fill 模式改按 L5(B) 重排；wrap 模式只报告
        short = {ki: {i for i, g in d.items() if g < prof.font_size} for ki, d in leader_gaps(pdf, irs, prof).items()}
        short = {k: v for k, v in short.items() if v}
        rep["pass2_breaks"] = {str(k): sorted(v) for k, v in short.items()}
        if short and prof.overflow == "fill":
            out = render_docx(irs, prof, Path(a.o), breaks=short)
            pdf = to_pdf(out)
            short = {ki: {i for i, g in d.items() if g < prof.font_size}
                     for ki, d in leader_gaps(pdf, irs, prof).items()}
        vf = verify_pdf(pdf, irs, prof)
        # 第三遍：跨页的偶句（L6）前拆表分页，最多 3 轮（每轮分页可能把后面的偶句推到新的页界）
        fill_breaks = rep["pass2_breaks"] and prof.overflow == "fill"
        page_before: dict[int, set[int]] = {}
        for _ in range(3):
            split = [x["at"] for x in vf if x["code"] == "L6" and "at" in x]
            if not split:
                break
            for ki, ci in split:
                page_before.setdefault(ki, set()).add(ci)
            out = render_docx(irs, prof, Path(a.o), breaks={int(k): set(v) for k, v in rep["pass2_breaks"].items()}
                              if fill_breaks else None, page_before=page_before)
            pdf = to_pdf(out)
            vf = verify_pdf(pdf, irs, prof)
        rep["page_before"] = {str(k): sorted(v) for k, v in page_before.items()}
        for ki, s in short.items():
            for i in sorted(s):
                vf.append({"code": "L9", "severity": "major", "page": 0, "detail": f"表 {ki + 1} 分支 {i + 1} 点线短于 1 字宽"})
        rep.update(docx=str(out), pdf=str(pdf), profile=prof.__dict__, check=ck, verify=vf)
        rep["counts"] = dict(Counter(i["code"] for i in ck + vf))
        rep["verify_counts"] = dict(Counter(i["code"] for i in vf))
        Path(a.o).with_suffix(".report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), "utf-8")
        print(json.dumps({k: rep[k] for k in ("docx", "pdf", "counts", "verify_counts")}, ensure_ascii=False))
        return 1 if _bad(ck + vf) else 0
    except ValueError as e:
        print(f"错误: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
