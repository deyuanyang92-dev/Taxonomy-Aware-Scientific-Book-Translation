#!/usr/bin/env python3
"""语料级翻译驱动：多本书（或多章）排队跑 auto_translate.py，可续跑、有状态文件、有交付清单。

用法：
  python3 scripts/translate_corpus.py run   BOOK.md [BOOK2.md ...] --work ROOT --sl de --tl en
        [--md-dir DIR]            # 参数不是现成文件时，当作 docstore key，读 DIR/<key>.md
        [--glossary G.tsv] [--names N.tsv] [--engine none] [--verify-engine none]
        [--tier draft|release]    # release：须 --chapters 且 --verify-engine 非 none（token_economy.guard_tier）
        [--chapters]              # 按章：先用 chapter_split 计划切章，每章一个作业（章间并行）
        [--jobs 2] [--extra "--workers 6 --no-entities"] [--force]
  python3 scripts/translate_corpus.py status   --work ROOT      # 打印 corpus_status.json 摘要
  python3 scripts/translate_corpus.py manifest --work ROOT      # 重写 delivery_manifest.json

约定：
  - 每本书独立工作目录 ROOT/<key>/（章模式：ROOT/<key>/chapters/<章>/），书与书之间不共享可变状态；
    重跑只复用 auto_translate 的块级缓存（draft/revise/check 的 digest 缓存），不删任何已有产物。
  - 跳过规则：checked.md 与 report.md 都在、且 ROOT/<key>/source.sha256 与当前原文 sha256 一致。
    原文变了：旧 checked.md 先备份成 checked.md.bak-<旧摘要前8位>，再重跑（缓存按内容摘要失效，不会串稿）。
  - 一本失败不中断队列；退出码 0=全部完成，1=有失败，2=参数/原文校验失败。
  - 状态文件 ROOT/corpus_status.json：book, stage, pages_done/total, attempts, engine, started, finished,
    log, exit_status；日志 ROOT/<key>/driver.log。
  - 交付清单 ROOT/delivery_manifest.json：每本书恰好一条，列 draft/revised/checked/report/
    human_review_queue 路径（缺则 null）、提示词版本、原文摘要、tier。
  - 试译档（draft）= 省 token 默认；交付档（release）见 docs/plans/2026-11-17-translation-approach-optimization.md。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
PAGE_MARK = re.compile(r"^<!--\s*PDF p\.(\d+)", re.M)
STATUS_FILE = "corpus_status.json"
MANIFEST_FILE = "delivery_manifest.json"
DELIVERABLES = {
    "draft": "draft.md",
    "revised": "revised.md",
    "checked": "checked.md",
    "report": "report.md",
    "human_review_queue": "human_review_queue.csv",
}
_lock = threading.Lock()


class CorpusError(SystemExit):
    """参数或原文校验失败（退出码 2）。"""

    def __init__(self, msg: str) -> None:
        super().__init__(f"[translate_corpus] {msg}")
        self.code = 2


@dataclass
class Job:
    book: str          # 书 key
    key: str           # 作业 key（书或 书/章）
    src: Path
    work: Path
    digest: str
    pages_total: int
    chapter: str | None = None


# ------------------------------------------------------------------ 校验
def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def count_pages(p: Path) -> int:
    return len(set(PAGE_MARK.findall(p.read_text(encoding="utf-8", errors="replace"))))


def resolve_sources(items: Sequence[str], md_dir: Path | None) -> list[tuple[str, Path]]:
    """参数 → [(key, md 路径)]；key 取文件名主干，必须唯一；原文必须带 <!-- PDF p.N --> 页标记。"""
    out: list[tuple[str, Path]] = []
    seen: dict[str, Path] = {}
    for it in items:
        p = Path(it)
        if not p.is_file() and md_dir is not None:
            p = md_dir / f"{it}.md"
        if not p.is_file():
            raise CorpusError(f"找不到原文：{it}（不是文件；--md-dir 下也没有 {it}.md）")
        key = p.stem
        if key in seen:
            raise CorpusError(f"key 重复：{key}（{seen[key]} 与 {p}）")
        if count_pages(p) == 0:
            raise CorpusError(f"{p} 没有 <!-- PDF p.N --> 页标记，auto_translate 无法分页")
        seen[key] = p
        out.append((key, p))
    if not out:
        raise CorpusError("没有给任何原文")
    return out


# ------------------------------------------------------------------ 状态
def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def load_status(root: Path) -> dict[str, Any]:
    f = root / STATUS_FILE
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            pass
    return {"books": {}}


def update_status(root: Path, key: str, **fields: Any) -> None:
    """线程安全、原子写（tmp + replace）；只改自己那一条。"""
    with _lock:
        st = load_status(root)
        rec = st["books"].setdefault(key, {"book": key})
        rec.update(fields)
        st["updated"] = _now()
        f = root / STATUS_FILE
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(f)


def stage_of(work: Path) -> tuple[str, int]:
    """由已落盘产物推断阶段与已完成页数：draft → revise → check → done。"""
    if (work / "checked.md").exists() and (work / "report.md").exists():
        return "done", count_pages(work / "checked.md")
    if (work / "revised.md").exists():
        return "check", count_pages(work / "revised.md")
    if (work / "draft.md").exists():
        return "revise", count_pages(work / "draft.md")
    return "draft", 0


def is_done(job: Job) -> bool:
    w = job.work
    if not ((w / "checked.md").exists() and (w / "report.md").exists()):
        return False
    rec = w / "source.sha256"
    return rec.exists() and rec.read_text(encoding="utf-8").strip() == job.digest


# ------------------------------------------------------------------ 作业
def auto_cmd(job: Job, a: argparse.Namespace) -> list[str]:
    cmd = [sys.executable, str(a.auto_script), "run", str(job.src), "-o", str(job.work),
           "--sl", a.sl, "--tl", a.tl, "--engine", a.engine, "--verify-engine", a.verify_engine,
           "--tier", a.tier]
    if a.glossary:
        cmd += ["--glossary", a.glossary]
    if a.names:
        cmd += ["--names", a.names]
    if a.chapters:
        cmd.append("--chaptered")
    if a.extra:
        cmd += shlex.split(a.extra)
    return cmd


def run_job(job: Job, a: argparse.Namespace, runner: Callable[[list[str], Path], int] | None = None) -> dict[str, Any]:
    root = Path(a.work)
    job.work.mkdir(parents=True, exist_ok=True)
    if not a.force and is_done(job):
        update_status(root, job.key, book=job.book, chapter=job.chapter, stage="done", skipped=True,
                      pages_done=job.pages_total, pages_total=job.pages_total, exit_status=0,
                      source_digest=job.digest)
        return {"key": job.key, "rc": 0, "skipped": True}
    old = job.work / "source.sha256"
    old_digest = old.read_text(encoding="utf-8").strip() if old.exists() else ""
    ck = job.work / "checked.md"
    if ck.exists() and old_digest != job.digest:           # 原文变了/来历不明：留底再重跑，不覆盖
        ck.replace(job.work / f"checked.md.bak-{(old_digest or 'unknown')[:8]}")
    old.write_text(job.digest + "\n", encoding="utf-8")
    prev = load_status(root)["books"].get(job.key, {})
    attempts = int(prev.get("attempts", 0)) + 1
    log = job.work / "driver.log"
    update_status(root, job.key, book=job.book, chapter=job.chapter, stage=stage_of(job.work)[0],
                  pages_done=stage_of(job.work)[1], pages_total=job.pages_total, attempts=attempts,
                  engine=a.engine, tier=a.tier, started=_now(), finished=None, log=str(log),
                  exit_status=None, source_digest=job.digest, skipped=False)
    cmd = auto_cmd(job, a)
    try:
        rc = (runner or _run_subprocess)(cmd, log)
    except Exception as exc:  # noqa: BLE001  一本失败不中断队列
        with open(log, "a", encoding="utf-8") as fp:
            fp.write(f"[driver] 异常：{exc!r}\n")
        rc = 99
    stage, done = stage_of(job.work)
    update_status(root, job.key, stage=stage if rc == 0 else f"failed@{stage}", pages_done=done,
                  finished=_now(), exit_status=rc)
    return {"key": job.key, "rc": rc, "skipped": False}


def _run_subprocess(cmd: list[str], log: Path) -> int:
    with open(log, "a", encoding="utf-8") as fp:
        fp.write(f"\n[driver] {_now()} $ {' '.join(shlex.quote(c) for c in cmd)}\n")
        fp.flush()
        return subprocess.call(cmd, stdout=fp, stderr=subprocess.STDOUT)


# ------------------------------------------------------------------ 章模式
def chapter_jobs(book: str, src: Path, root: Path, a: argparse.Namespace) -> list[Job]:
    import chapter_split as cs
    plan_p = root / book / "chapter_plan.json"
    plan = cs.load_plan(plan_p) if plan_p.exists() else cs.build_plan(src)
    if not plan_p.exists():
        plan_p.parent.mkdir(parents=True, exist_ok=True)
        cs.save_plan(plan, plan_p)
    if plan.get("needs_review") and not plan.get("confirmed"):
        raise CorpusError(f"{book} 的章节计划需人工确认：编辑 {plan_p}（改 start/end，设 confirmed=true）后重跑")
    files = cs.split_md(src, plan, root / book / "chapters")
    out = []
    for cid, f in files.items():
        out.append(Job(book=book, key=f"{book}/{cid}", src=f, work=f.parent, digest=sha256_file(f),
                       pages_total=count_pages(f), chapter=cid))
    return out


# ------------------------------------------------------------------ 清单
def prompt_version() -> str:
    m = re.search(r"^PROMPT_VERSION\s*=\s*'([^']+)'", (HERE / "auto_translate.py").read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else "unknown"


def _files(work: Path) -> dict[str, str | None]:
    return {k: (str(work / v) if (work / v).exists() else None) for k, v in DELIVERABLES.items()}


def build_manifest(root: Path) -> dict[str, Any]:
    """每本书恰好一条；章模式下该条带 chapters 字典。"""
    st = load_status(root)["books"]
    books: dict[str, dict[str, Any]] = {}
    for key, rec in st.items():
        bk = rec.get("book", key)
        ent = books.setdefault(bk, {"book": bk, "chapters": {}})
        if rec.get("chapter"):
            ent["chapters"][rec["chapter"]] = {**_files(root / bk / "chapters" / rec["chapter"]),
                                               "source_digest": rec.get("source_digest"),
                                               "exit_status": rec.get("exit_status")}
        else:
            ent.update(_files(root / bk))
            ent.update(source_digest=rec.get("source_digest"), exit_status=rec.get("exit_status"))
        ent["tier"] = rec.get("tier")
    for ent in books.values():
        ch = ent.pop("chapters")
        if ch:
            ent["chapters"] = ch
            ent["complete"] = all(c.get("checked") and c.get("report") for c in ch.values())
        else:
            ent["complete"] = bool(ent.get("checked") and ent.get("report"))
        ent["prompt_version"] = prompt_version()
    return {"generated": _now(), "prompt_version": prompt_version(),
            "books": [books[k] for k in sorted(books)]}


def write_manifest(root: Path) -> Path:
    out = root / MANIFEST_FILE
    out.write_text(json.dumps(build_manifest(root), ensure_ascii=False, indent=1), encoding="utf-8")
    return out


# ------------------------------------------------------------------ CLI
def cmd_run(a: argparse.Namespace, runner: Callable[[list[str], Path], int] | None = None) -> int:
    from token_economy import guard_engine, guard_tier
    guard_engine(a.engine, force=a.force_engine)
    guard_tier(a.tier, verify_engine=a.verify_engine, chaptered=a.chapters)
    root = Path(a.work)
    srcs = resolve_sources(a.sources, Path(a.md_dir) if a.md_dir else None)
    root.mkdir(parents=True, exist_ok=True)
    jobs: list[Job] = []
    for key, p in srcs:
        update_status(root, key, book=key, stage="queued", exit_status=None)
        if a.chapters:
            try:
                jobs += chapter_jobs(key, p, root, a)
            except CorpusError as exc:
                update_status(root, key, stage="plan-review", exit_status=2, finished=_now())
                print(exc, file=sys.stderr)
        else:
            jobs.append(Job(book=key, key=key, src=p, work=root / key, digest=sha256_file(p),
                            pages_total=count_pages(p)))
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, a.jobs)) as ex:
        futs = [ex.submit(run_job, j, a, runner) for j in jobs]
        results = [f.result() for f in futs]
    write_manifest(root)
    bad = [r["key"] for r in results if r["rc"] != 0]
    plan_bad = [k for k, v in load_status(root)["books"].items() if v.get("stage") == "plan-review"]
    for r in results:
        print(f"{'SKIP' if r['skipped'] else ('OK  ' if r['rc'] == 0 else 'FAIL')} {r['key']}")
    return 1 if bad or plan_bad else 0


def cmd_status(a: argparse.Namespace) -> int:
    st = load_status(Path(a.work))["books"]
    for k in sorted(st):
        v = st[k]
        print(f"{k}\t{v.get('stage')}\t{v.get('pages_done', 0)}/{v.get('pages_total', 0)}\t"
              f"attempts={v.get('attempts', 0)}\trc={v.get('exit_status')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("sources", nargs="+")
    r.add_argument("--work", required=True)
    r.add_argument("--md-dir")
    r.add_argument("--sl", required=True)
    r.add_argument("--tl", required=True)
    r.add_argument("--glossary")
    r.add_argument("--names")
    r.add_argument("--engine", default="none", help="默认 none=零模型（用户 2026-11-25）；auto 或模型名才调模型")
    r.add_argument("--verify-engine", default="none")
    r.add_argument("--force-engine", action="store_true")
    r.add_argument("--tier", choices=["draft", "release"], default="draft")
    r.add_argument("--chapters", action="store_true", help="按章切分并行（见 chapter_split.py）")
    r.add_argument("--jobs", type=int, default=1, help="并行作业数（书或章），默认 1")
    r.add_argument("--extra", default="", help="原样追加给 auto_translate.py 的参数串")
    r.add_argument("--force", action="store_true", help="忽略跳过规则")
    r.add_argument("--auto-script", default=str(HERE / "auto_translate.py"))
    for name in ("status", "manifest"):
        s = sub.add_parser(name)
        s.add_argument("--work", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "run":
        return cmd_run(a)
    if a.cmd == "status":
        return cmd_status(a)
    print(write_manifest(Path(a.work)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
