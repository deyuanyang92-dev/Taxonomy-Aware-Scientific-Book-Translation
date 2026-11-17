"""Image-assisted proofreading of low-confidence OCR, with resumable page audits."""

from __future__ import annotations

import difflib
import json
import re
import subprocess
import tempfile
import time
from collections.abc import Callable, Iterable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from pathlib import Path

from .engines.pageimg import page_png
from .store import Store, _atomic_write, _flock, agent, make_version, now

PROMPT = """You proofread OCR output of one printed page of a German zoology paper (polychaete taxonomy, 1960-1998). The page image is attached; the Tesseract text is below.
Correct ONLY OCR recognition errors by comparing with the image: wrong or missing letters (especially ä ö ü ß), the symbols ♂ ♀ µ ‰ °, digits, wrongly split or merged words, stray characters. Rules:
- Do not translate, do not modernize or correct the author's spelling, do not add or remove content, keep Latin names and abbreviations as printed.
- Keep the same line breaks and reading order as the OCR text; keep hyphenation at line ends as it is.
- If you are not sure what the image shows, keep the OCR word.
- Output ONLY the corrected page text, nothing else.

--- OCR TEXT ---
"""

Runner = Callable[[str, Path], str]
WordDiff = list[tuple[list[str], list[str]]]


def page_conf(page: dict) -> float | None:
    """Recover confidence from an OCR alternate when old postprocessing lost it."""
    conf = (page.get("quality") or {}).get("ocr_conf")
    if conf is not None:
        return float(conf)
    for version in page.get("alternates", []):
        conf = (version.get("quality") or {}).get("ocr_conf")
        if version.get("method") == "ocr" and conf is not None:
            return float(conf)
    return None


def candidates(store: Store, key: str, below: float = 0.92, pages: Iterable[int] | None = None,
               min_chars: int = 300, *, include_unknown: bool = False) -> list[tuple[int, float | None]]:
    """Return eligible pages, lowest confidence first and unknown confidence last."""
    store.doc(key)
    wanted = set(pages) if pages is not None else None
    found = []
    for page in store.pages(key):
        n = int(page["page"])
        if wanted is not None and n not in wanted:
            continue
        versions = [page, *page.get("alternates", [])]
        if any(str(v.get("producer") or "").startswith("proofread:") for v in versions):
            continue
        if len("".join((page.get("text") or "").split())) < min_chars:
            continue
        conf = page_conf(page)
        if (conf is None and include_unknown) or (conf is not None and conf < below):
            found.append((n, conf))
    return sorted(found, key=lambda item: (item[1] is None, item[1] if item[1] is not None else 0, item[0]))


def word_diff(old: str, new: str) -> WordDiff:
    """Changed whitespace-token spans, including insertions and deletions."""
    a, b = old.split(), new.split()
    return [(a[i:j], b[k:end]) for tag, i, j, k, end in
            difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes() if tag != "equal"]


def _has_loop(words: list[str]) -> bool:
    """同一片段（3–30 词）紧挨着连续出现 ≥3 次。文献条目、图注会合法地重复同一短语，
    但不连续（2026-11-16 实测第 78 页 ×9、第 7 页 ×4）；模型的循环输出是连续重复。"""
    for i in range(len(words)):
        for period in range(3, 31):
            if i + 3 * period > len(words):
                break
            chunk = words[i:i + period]
            if words[i + period:i + 2 * period] == chunk and words[i + 2 * period:i + 3 * period] == chunk:
                return True
    return False


def sanity(old: str, new: str) -> list[str]:
    """Reject structural changes, substantial rewrites, repetition, and chatter."""
    if not new.strip():
        return ["empty text"]
    reasons = []
    if new.lstrip().startswith(("Here", "Sure", "```")) or "OCR TEXT" in new:
        reasons.append("non-text chatter")
    old_words, new_words = old.split(), new.split()
    ratio = len(new_words) / len(old_words) if old_words else float("inf")
    if not 0.93 <= ratio <= 1.07:
        reasons.append(f"word count ratio {ratio:.3f} outside 0.93..1.07")
    old_lines, new_lines = len(old.splitlines()), len(new.splitlines())
    if abs(new_lines - old_lines) > 0.1 * old_lines + 2:
        reasons.append(f"line count changed from {old_lines} to {new_lines}")
    changed = sum(max(len(a), len(b)) for a, b in word_diff(old, new))
    fraction = changed / len(old_words) if old_words else float("inf")
    if fraction > 0.5:
        reasons.append(f"rewrite: changed {fraction:.0%} of words")
    if _has_loop(new_words) and not _has_loop(old_words):
        reasons.append("repetition loop")
    return reasons


def flags(old: str, new: str) -> list[str]:
    """Flag substantial name/number changes for review without rejecting them."""
    result = []
    old_caps = [w for w in re.findall(r"[^\W\d_]+", old) if len(w) >= 4 and w[0].isupper()]
    known_caps = set(old_caps)
    added_caps = sum(1 for w in re.findall(r"[^\W\d_]+", new)
                     if len(w) >= 4 and w[0].isupper() and w not in known_caps)
    if added_caps > max(5, 0.03 * len(old_caps)):
        result.append(f"new_capitalised:{added_caps}")
    old_nums, new_nums = re.findall(r"\d+", old), re.findall(r"\d+", new)
    changed_nums = sum(max(j - i, end - k) for tag, i, j, k, end in
                       difflib.SequenceMatcher(None, old_nums, new_nums, autojunk=False).get_opcodes()
                       if tag != "equal")
    if changed_nums > max(3, 0.03 * len(old_nums)):
        result.append(f"digits_changed:{changed_nums}")
    return result


def _codex_runner(prompt: str, img_path: Path) -> str:
    """Use the pilot's CLI invocation, with a fresh empty working directory."""
    with tempfile.TemporaryDirectory(prefix="docstore_codex_") as td:
        out = Path(td) / "out.txt"
        wd = Path(td) / "work"
        wd.mkdir()
        subprocess.run(
            ["codex", "exec", "--skip-git-repo-check", "-s", "read-only", "-m", "gpt-6.1-sol",
             "-o", str(out), "-C", str(wd), "-i", str(img_path.resolve()), "-"],
            input=prompt, text=True, capture_output=True, timeout=900, cwd=str(wd), check=True,
        )
        return out.read_text(encoding="utf-8") if out.exists() else ""


def _run_page(runner: Runner, prompt: str, image: Path) -> tuple[str, float]:
    start = time.perf_counter()
    for _ in range(2):
        new = runner(prompt, image)
        if new.strip():
            return new, time.perf_counter() - start
    raise ValueError("empty output after one retry")


def _append_audit(path: Path, record: dict) -> None:
    with path.open("a", encoding="utf-8") as log:
        log.write(json.dumps(record, ensure_ascii=False) + "\n")


def _retain_promoted_metadata(store: Store, key: str, n: int, version: dict) -> None:
    """Keep custom fields that Store.put_version currently omits on promotion.

    Use the same page lock and atomic writer as Store. If another writer has
    already demoted this version, attach metadata to its alternate instead.
    Standard indexed fields are unchanged, so no index update is needed.
    """
    with _flock(store.root / "pages" / key / ".lock"):
        page = store.read_page(key, n)
        if page is None:
            raise RuntimeError(f"page disappeared after promotion: {key} {n}")
        for target in [page, *page.get("alternates", [])]:
            if all(target.get(field) == version.get(field) for field in ("text", "method", "source", "producer")):
                extras = target.setdefault("extra", {}) if target is page else target
                extras.update(proofread=version["proofread"], run_by=version["run_by"])
                _atomic_write(store.page_path(key, n), json.dumps(page, ensure_ascii=False, indent=1))
                return
        raise RuntimeError(f"proofread version disappeared after promotion: {key} {n}")


def proofread_doc(store: Store, key: str, *, below: float = 0.92, pages: Iterable[int] | None = None,
                  limit: int | None = None, engine: str = "codex-sol", workers: int = 3,
                  dry: bool = False, runner: Runner | None = None, by: str | None = None,
                  include_unknown: bool = False) -> dict[str, int]:
    """Proofread selected pages; render and write on the caller thread only.

    ``candidates`` counts all eligible pages before the limit; ``done`` counts
    completed attempts, including failures. Dry runs leave all completion counts zero.
    """
    if workers < 1 or (limit is not None and limit < 0):
        raise ValueError("workers must be positive and limit must be non-negative")
    if runner is None and engine != "codex-sol":
        raise ValueError(f"unsupported proofreading engine: {engine}")
    eligible = candidates(store, key, below, pages, include_unknown=include_unknown)
    selected = eligible if limit is None else eligible[:limit]
    stats = {"candidates": len(eligible), "done": 0, "accepted": 0, "rejected": 0, "failed": 0, "flagged": 0}
    if dry:
        for n, conf in selected:
            print(f"{key}\tpage={n}\tconf={conf}\tdry", flush=True)
        print(f"{key}\tcandidates={len(eligible)}\tprojected_calls={len(selected)}\tdry", flush=True)
        return stats
    if not selected:
        return stats

    run_by = agent(by)
    pdf_path = store.doc(key)["path"]
    audit_dir = store.root / "_audit"
    audit_dir.mkdir(exist_ok=True)
    call = runner if runner is not None else _codex_runner

    def finish(n: int, conf: float | None, base: dict, new: str, seconds: float,
               error: Exception | None = None) -> None:
        diff = word_diff(base.get("text") or "", new) if error is None else []
        reasons = [f"{type(error).__name__}: {error}"] if error is not None else sanity(base["text"], new)
        page_flags = flags(base["text"], new) if error is None else []
        accepted = error is None and not reasons
        changed = sum(max(len(a), len(b)) for a, b in diff)
        metadata = {"changed_words": changed, "base_producer": base.get("producer")}
        if error is None:
            version = make_version(
                new, base.get("method") or "ocr", producer=f"proofread:{engine}",
                engine=f"{base.get('engine') or ''} + proofread:{engine}", dpi=base.get("dpi"),
                level=base.get("verify_level"), conf=conf,
                source=f"{pdf_path}#proofread:{engine} by {run_by}",
                extra={"proofread": metadata, "run_by": run_by},
            )
            store.put_version(key, n, version, promote=accepted)
            if accepted:
                _retain_promoted_metadata(store, key, n, version)
        record = {"page": n, "conf": conf, "accepted": accepted, "reasons": reasons, "flags": page_flags,
                  "word_diff": diff[:200], "proofread": metadata, "by": run_by,
                  "engine": engine, "time": now(), "seconds": round(seconds, 3)}
        _append_audit(audit_dir / f"proofread_{key}.jsonl", record)
        status = "failed" if error is not None else ("accepted" if accepted else "rejected")
        if status == "rejected":
            _append_audit(audit_dir / f"proofread_rejects_{key}.jsonl", record)
        stats["done"] += 1
        stats[status] += 1
        stats["flagged"] += bool(page_flags)
        flag_text = f"\tflags={','.join(page_flags)}" if page_flags else ""
        print(f"{key}\tpage={n}\tconf={conf}\t{status}\t{seconds:.1f}s{flag_text}", flush=True)

    # page_png caches a shared PyMuPDF document; never render inside worker threads.
    # Bound in-flight work so completed pages are saved before rendering more images.
    with tempfile.TemporaryDirectory(prefix="docstore_proofread_") as td, ThreadPoolExecutor(workers) as pool:
        pending: dict[Future[tuple[str, float]], tuple[int, float | None, dict, float]] = {}
        todo = iter(selected)
        exhausted = False
        while pending or not exhausted:
            while not exhausted and len(pending) < workers:
                item = next(todo, None)
                if item is None:
                    exhausted = True
                    break
                n, conf = item
                base = store.read_page(key, n) or {}
                start = time.perf_counter()
                try:
                    image = Path(td) / f"p{n:04d}.png"
                    image.write_bytes(page_png(pdf_path, n, base.get("dpi") or 300))
                    future = pool.submit(_run_page, call, PROMPT + base["text"], image)
                    pending[future] = (n, conf, base, start)
                except Exception as error:
                    finish(n, conf, base, "", time.perf_counter() - start, error)
            if not pending:
                continue
            completed, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in completed:
                n, conf, base, start = pending.pop(future)
                try:
                    new, seconds = future.result()
                except Exception as error:
                    finish(n, conf, base, "", time.perf_counter() - start, error)
                else:
                    finish(n, conf, base, new, seconds)
    return stats


def rejudge_doc(store: Store, key: str, *, pages: Iterable[int] | None = None,
                dry: bool = False, by: str | None = None) -> dict[str, int]:
    """Recheck stored proofread alternates against their current primary OCR.

    Choose the newest alternate by timestamp, breaking ties by storage order.
    Dry runs count checks and remaining rejections but never promote or write.
    """
    store.doc(key)
    wanted = set(pages) if pages is not None else None
    stats = {"checked": 0, "promoted": 0, "still_rejected": 0}
    run_by = agent(by)
    audit_dir = store.root / "_audit"
    for page in store.pages(key):
        n = int(page["page"])
        if wanted is not None and n not in wanted:
            continue
        if str(page.get("producer") or "").startswith("proofread:"):
            continue
        alternates = [v for v in page.get("alternates", [])
                      if str(v.get("producer") or "").startswith("proofread:")]
        if not alternates:
            continue
        _, version = max(enumerate(alternates), key=lambda item: (item[1].get("time") or "", item[0]))
        old, new = page.get("text") or "", version.get("text") or ""
        reasons, page_flags = sanity(old, new), flags(old, new)
        accepted = not reasons
        stats["checked"] += 1
        stats["still_rejected"] += not accepted
        flag_text = f"\tflags={','.join(page_flags)}" if page_flags else ""
        status = "promoted" if accepted else "still rejected"
        if dry:
            status = "would promote" if accepted else status
            print(f"{key}\tpage={n}\t{status}\tdry{flag_text}", flush=True)
            continue

        diff = word_diff(old, new)
        version = dict(version)
        version.setdefault("proofread", {"changed_words": sum(max(len(a), len(b)) for a, b in diff),
                                         "base_producer": page.get("producer")})
        version.setdefault("run_by", run_by)
        if accepted:
            store.put_version(key, n, version, promote=True)
            _retain_promoted_metadata(store, key, n, version)
            stats["promoted"] += 1
        record = {"page": n, "conf": page_conf(page), "accepted": accepted, "reasons": reasons,
                  "flags": page_flags, "rejudged": True, "word_diff": diff[:200],
                  "proofread": version["proofread"], "by": run_by,
                  "engine": version["producer"].removeprefix("proofread:"), "time": now()}
        audit_dir.mkdir(exist_ok=True)
        _append_audit(audit_dir / f"proofread_{key}.jsonl", record)
        if not accepted:
            _append_audit(audit_dir / f"proofread_rejects_{key}.jsonl", record)
        print(f"{key}\tpage={n}\t{status}{flag_text}", flush=True)
    return stats
