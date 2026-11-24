#!/usr/bin/env python3
"""多语言译本出版流水线：一条命令走 导出 → 翻译 → 图 → 对齐 → 检索表核对 → 排版 → 三审 → 闸口（issue #13）。

只编排仓库里已有的受支持命令，每一步的命令行、退出码、耗时、软件版本和输入 sha256 写进
`WORK/publish_run.json`，成品可追溯。不含任何书籍专用逻辑。

用法（源语言、目标语言用 Google 语言代码，如 es、de、ja、en、zh-CN）：
  # 从登记资料出发（docstore key；PDF 取登记表里的原件）
  python3 scripts/publish_book.py run --key Vol48 --pdf book.pdf --work work/vol48 --sl es --tl en
  # 已有页标记 Markdown 与译文：跳过导出/翻译
  python3 scripts/publish_book.py run --source-md src.md --translation-md tgt.md --pdf book.pdf --work work/x
  # 只看会执行什么
  python3 scripts/publish_book.py run ... --dry
  python3 scripts/publish_book.py stages          # 列出阶段

阶段（--only/--skip 可选）：export translate figures align keycheck build qa gate
  export    docstore export KEY --translate -o WORK/src.md             （给了 --source-md 则跳过）
  translate scripts/auto_translate.py run WORK/src.md ...  → WORK/tgt.md（给了 --translation-md 则跳过）
  figures   booklayout figures extract（源 PDF 显示矩形裁图 + manifest + source_figure_audit.json）
  align     booklayout align-md → aligned.json，再 normalize
  keycheck  booklayout key-model（来源端检索表图检查 + 译文逐支对齐）
  build     booklayout build（有 --pdf-out 时两遍：build → map-pages → build --map）
  qa        booklayout qa / check / key-report（任一不过不立刻停，交闸口汇总）
  gate      booklayout gate（qa + check + key report 必须全部干净；退出码 1 = 不得交付）

退出码：0 全过；1 某阶段失败或闸口不过。失败时 publish_run.json 里 `failed` 指出阶段。
翻译阶段会调用模型并产生费用与等待（DeepSeek 忙时自动等待）；先 --dry 检查，再小样（--pages 1-5）试跑。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
STAGES = ["export", "translate", "figures", "align", "styles", "keycheck", "build", "qa", "gate"]
SOFT = {"qa", "styles"}  # styles 为补充信息（粗体/标题级别/斜体 sidecar），失败不阻断排版  # 失败不立刻停：闸口汇总；但任何必需检查非零都令最终 rc 非零、releasable=False
STALE = {"keycheck": ("key_model.json",), "gate": ("gate.json",),
         "qa": ("qa.json", "check.json", "key_report.json", "keyrender.json")}  # 运行前删除的旧报告


def _sha(p: Path) -> str | None:
    if not p.is_file():
        return None
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


def _bl(*a: str) -> list[str]:
    return [sys.executable, "-m", "booklayout", *a]


def plan(args: argparse.Namespace) -> list[dict[str, Any]]:
    """返回 [{stage, cmd(list)|None, note, outputs}]，不执行。"""
    w: Path = args.work
    src = args.source_md or w / "src.md"
    tgt = args.translation_md or w / "tgt.md"
    fig, aligned = w / "figures", w / "aligned.json"
    docx, pdf = w / "book.docx", w / "book.pdf"
    meta = ["--metadata", str(args.metadata)] if args.metadata else []
    title = ["--title", args.title] if args.title else []
    has_pdf = not args.no_pdf
    out: list[dict[str, Any]] = []

    def add(stage: str, cmd: list[str] | None, outputs: list[Path], note: str = "") -> None:
        out.append({"stage": stage, "cmd": cmd, "outputs": outputs, "note": note})

    if args.source_md:
        add("export", None, [src], "给了 --source-md，跳过导出")
    else:
        if not args.key:
            raise SystemExit("需要 --key（docstore 资料）或 --source-md")
        ex = [sys.executable, "-c", "import sys; from docstore.cli import main; sys.exit(main(sys.argv[1:]))",
              "--by", "publish_book", "export", args.key, "--translate", "--strict", "-o", str(src)]
        if args.pages:
            ex += ["--pages", args.pages]
        add("export", ex, [src])
    if args.translation_md:
        add("translate", None, [tgt], "给了 --translation-md，跳过翻译")
    else:
        tr = [sys.executable, str(ROOT / "scripts" / "auto_translate.py"), "run", str(src), "-o", str(w / "translate"),
              "--sl", args.sl, "--tl", args.tl]
        if args.glossary:
            tr += ["--glossary", str(args.glossary)]
        if args.engine:
            tr += ["--engine", args.engine]
        add("translate", tr, [tgt], "产物 translate/checked.md|revised.md|draft.md 取最后一个存在的复制为 tgt.md")
    if args.pdf:
        fg = _bl("figures", "extract", "--pdf", str(args.pdf), "--out", str(fig), "--dpi", str(args.dpi))
        if args.pages:
            a, _, b = args.pages.partition("-")
            fg += ["--first", a, "--last", b or a]
        add("figures", fg, [fig / "figures_manifest.json", fig / "source_figure_audit.json"])
    else:
        add("figures", None, [fig / "source_figure_audit.json"], "未给 --pdf：不抽图，写空 source_figure_audit.json")
    add("align", _bl("align-md", "--source", str(src), "--translation", str(tgt), "--out", str(aligned),
                     "--report", str(w / "align_report.json")), [aligned])
    if args.key and args.pdf:
        sty = _bl("styles-measure", "--pdf", str(args.pdf), "--key", args.key, "--pages", args.pages or "1-1000")
        add("styles", sty, [], "排版样式测量（本地，不调 OCR）：字高/粗细/斜体/标题级别 -> styles/<key>/")
        out[-1]["extra"] = [_bl("styles-annotate", "--key", args.key),
                            _bl("styles-attach", "--key", args.key, "--aligned", str(aligned))]
    else:
        add("styles", None, [], "未给 --key/--pdf：跳过排版样式测量")
    add("keycheck", _bl("key-model", "--source", str(src), "--translation", str(tgt),
                        "--out", str(w / "key_model.json")), [w / "key_model.json"])
    build = _bl("build", "--aligned", str(aligned), "--figures", str(fig), "--translation", str(tgt),
                "--out", str(docx), "--report", str(w / "build_report.json"), *meta, *title)
    if has_pdf:
        build += ["--pdf", "--pdf-out", str(pdf)]
    add("build", build, [docx] + ([pdf] if has_pdf else []),
        "两遍排版（map-pages 后 build --map）在 build 阶段内部执行" if has_pdf else "")
    qa = _bl("qa", "--aligned", str(aligned), "--figures", str(fig), "--out", str(w / "qa.json"), *meta, *title)
    ck = _bl("check", "--aligned", str(aligned), "--figures", str(fig), "--out", str(w / "check.json"), *meta, *title)
    if has_pdf:
        qa += ["--pdf", str(pdf)]
        ck += ["--pdf", str(pdf)]
    add("qa", qa, [w / "qa.json"], "qa、check、key-report 依次执行")
    if not has_pdf:
        add("gate", None, [], "no PDF：没有 key-report，闸口不运行；产物只是草稿，不得交付")
    else:
        add("gate", _bl("gate", "--qa", str(w / "qa.json"), "--check", str(w / "check.json"),
                        "--key-report", str(w / "key_report.json"),
                        "--key-model", str(w / "key_model.json"), "--keyrender", str(w / "keyrender.json"),
                        "--out", str(w / "gate.json")),
            [w / "gate.json"])
    for s in out:
        s.setdefault("extra", [])
    for s in out:
        if s["stage"] == "qa":
            s["extra"].append(ck)
            if has_pdf:
                s["extra"].append(_bl("key-report", "--pdf", str(pdf), "--out", str(w / "key_report.json")))
                s["extra"].append([sys.executable, "-m", "booklayout.keyrender", str(pdf),
                                   "--report", str(w / "keyrender.json")])
    return out


def _versions() -> dict[str, str]:
    v = {"python": platform.python_version()}
    try:
        import booklayout
        v["booklayout"] = getattr(booklayout, "__version__", "?")
    except ImportError:  # pragma: no cover
        pass
    try:
        import fitz
        v["pymupdf"] = fitz.VersionBind
    except ImportError:  # pragma: no cover
        pass
    return v


def _run(cmd: list[str]) -> dict[str, Any]:
    t0 = time.time()
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    return {"cmd": shlex.join(cmd), "rc": p.returncode, "seconds": round(time.time() - t0, 1),
            "stdout_tail": p.stdout[-400:], "stderr_tail": p.stderr[-400:]}


def _post(stage: str, args: argparse.Namespace) -> None:
    w: Path = args.work
    if stage == "translate" and not args.translation_md:
        for name in ("checked.md", "revised.md", "draft.md"):
            f = w / "translate" / name
            if f.exists():
                (w / "tgt.md").write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
                return
    if stage == "figures" and not args.pdf:
        (w / "figures").mkdir(parents=True, exist_ok=True)
        (w / "figures" / "source_figure_audit.json").write_text('{"figures": []}', encoding="utf-8")


def _second_pass(args: argparse.Namespace, steps: list[dict[str, Any]]) -> None:
    """build 之后：量页 → 带映射再 build，使目录与索引页码指对页。"""
    w: Path = args.work
    mp = w / "page_map.json"
    meta = ["--metadata", str(args.metadata)] if args.metadata else []
    r = _run(_bl("map-pages", "--pdf", str(w / "book.pdf"), "--aligned", str(w / "aligned.json"),
                 "--out", str(mp), *meta))
    steps.append({"stage": "build", **r, "note": "map-pages"})
    if r["rc"] == 0:
        b = [c for c in plan(args) if c["stage"] == "build"][0]["cmd"]
        steps.append({"stage": "build", **_run([*b, "--map", str(mp)]), "note": "build --map"})


def run(args: argparse.Namespace) -> int:
    args.work.mkdir(parents=True, exist_ok=True)
    steps_plan = plan(args)
    only = set(args.only.split(",")) if args.only else set(STAGES)
    skip = set(args.skip.split(",")) if args.skip else set()
    record: dict[str, Any] = {"versions": _versions(), "argv": sys.argv[1:], "steps": [], "failed": None,
                              "inputs_sha256": {k: _sha(Path(p)) for k, p in
                                                (("pdf", args.pdf), ("source_md", args.source_md),
                                                 ("translation_md", args.translation_md),
                                                 ("metadata", args.metadata)) if p}}
    rc = 0
    record["releasable"] = False
    soft_failed = False
    if not args.dry:  # 旧报告不得冒充本轮结果：本轮要写的报告先删
        for s in steps_plan:
            if s["stage"] in only and s["stage"] not in skip:
                for f in STALE.get(s["stage"], ()):
                    (args.work / f).unlink(missing_ok=True)
    for s in steps_plan:
        if s["stage"] not in only or s["stage"] in skip:
            continue
        cmds = ([s["cmd"]] if s["cmd"] else []) + s["extra"]
        if args.dry:
            print(f"[{s['stage']}] {s['note']}")
            for c in cmds:
                print("   " + shlex.join(c))
            continue
        if not cmds:
            _post(s["stage"], args)
            record["steps"].append({"stage": s["stage"], "skipped": s["note"]})
            continue
        ok = True
        for c in cmds:
            r = _run(c)
            record["steps"].append({"stage": s["stage"], **r})
            if r["rc"] != 0:
                ok = False
        if ok and s["stage"] == "build" and not args.no_pdf:
            _second_pass(args, record["steps"])
            ok = all(x["rc"] == 0 for x in record["steps"] if x["stage"] == "build" and "rc" in x)
        _post(s["stage"], args)
        if not ok and s["stage"] not in SOFT:
            record["failed"] = s["stage"]
            rc = 1
            break
        if not ok and s["stage"] in SOFT:
            soft_failed = True
            rc = 1
        if not ok and s["stage"] == "gate":
            rc = 1
    if not args.dry:
        last = record["steps"][-1] if record["steps"] else {}
        if last.get("stage") == "gate" and "rc" in last:
            anybad = soft_failed or any(x.get("rc", 0) != 0 for x in record["steps"])
            record["releasable"] = last["rc"] == 0 and rc == 0 and not anybad
            rc = 0 if record["releasable"] else 1
        (args.work / "publish_run.json").write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"publish_run={args.work / 'publish_run.json'} failed={record['failed']} "
              f"releasable={record['releasable']} rc={rc}")
    return rc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("stages")
    r = sub.add_parser("run")
    r.add_argument("--key", help="docstore 资料 key")
    r.add_argument("--pdf", type=Path, help="源 PDF（抽图、量页）")
    r.add_argument("--work", type=Path, required=True)
    r.add_argument("--source-md", type=Path)
    r.add_argument("--translation-md", type=Path)
    r.add_argument("--sl", default="es")
    r.add_argument("--tl", default="en")
    r.add_argument("--glossary", type=Path)
    r.add_argument("--engine")
    r.add_argument("--pages", help="PDF 页范围，如 1-5（小样）")
    r.add_argument("--metadata", type=Path)
    r.add_argument("--title")
    r.add_argument("--dpi", type=int, default=300)
    r.add_argument("--no-pdf", action="store_true", help="只出 DOCX，不转 PDF（无 LibreOffice 时）")
    r.add_argument("--only")
    r.add_argument("--skip")
    r.add_argument("--dry", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "stages":
        print("\n".join(STAGES))
        return 0
    return run(a)


if __name__ == "__main__":
    sys.exit(main())
