"""Automatic OCR quality control: risk score, route pass/redo/human, checkpoint resume."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

from .store import VERSION_KEYS, Store, agent, make_version, now, quality as text_quality
from . import textify

LATIN_RE = re.compile(r"\b[A-Z][a-z\-]+(?:\s+[a-z][a-z\-]+){1,2}\b")
ZH_TAXON_RE = re.compile(r"[\u4e00-\u9fff]{2,12}(?:科|属|目|纲|门|种)")
DIGIT_RE = re.compile(r"\d+")
RULES_PATH = Path(__file__).resolve().parent / "rules" / "qc.toml"


def _norm_ws(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def edit_distance(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    if len(a) * len(b) > 4_000_000:
        # page-scale safeguard
        from difflib import SequenceMatcher

        return int(round((1.0 - SequenceMatcher(None, a, b).ratio()) * max(len(a), 1)))
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cur[j] = min(cur[j - 1] + 1, prev[j] + 1, prev[j - 1] + (ca != cb))
        prev = cur
    return prev[-1]


def cer(gold: str, hyp: str) -> float:
    g = _norm_ws(gold)
    if not g:
        return 0.0
    return edit_distance(g, _norm_ws(hyp)) / len(g)


def load_config(path: str | Path | None = None) -> dict:
    p = Path(path) if path else RULES_PATH
    if not p.exists():
        return {}
    return tomllib.loads(p.read_text(encoding="utf-8"))


class YikuIndex:
    """Latin + Chinese taxon strings from yiku (read-only)."""

    def __init__(self, db: str | Path | None = None):
        raw = db or str(Path.home() / ".yiku" / "yiku.db")
        self.path = Path(os.path.expanduser(str(raw)))
        self.latin: set[str] = set()
        self.latin_norm: set[str] = set()
        self.zh: set[str] = set()
        if self.path.exists():
            con = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
            try:
                for en, en_norm, zh in con.execute("SELECT en, en_norm, zh FROM terms"):
                    if isinstance(en, str) and en.strip():
                        self.latin.add(en.strip())
                    if isinstance(en_norm, str) and en_norm.strip():
                        self.latin_norm.add(en_norm.strip().lower())
                    if isinstance(zh, str) and zh.strip():
                        self.zh.add(zh.strip())
            finally:
                con.close()

    def unknown_latin(self, text: str) -> list[str]:
        out = []
        for m in LATIN_RE.findall(text or ""):
            if m in self.latin or m.lower() in self.latin_norm:
                continue
            # genus-only / species token often partial; keep species binomials
            out.append(m)
        return sorted(set(out))

    def unknown_zh_taxon(self, text: str) -> list[str]:
        out = []
        for m in ZH_TAXON_RE.findall(text or ""):
            if m in self.zh:
                continue
            out.append(m)
        return sorted(set(out))


@dataclass
class PageRisk:
    key: str
    page: int
    score: float
    action: str  # pass | redo | human | skip
    reasons: list[str] = field(default_factory=list)
    signals: dict[str, Any] = field(default_factory=dict)
    verify_level: str = ""
    text_sha1: str = ""


def _primary(page: dict) -> dict:
    return {k: page.get(k) for k in VERSION_KEYS}


def _sha1(text: str) -> str:
    import hashlib

    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()


def score_page(
    page: dict,
    *,
    cfg: dict | None = None,
    yiku: YikuIndex | None = None,
    has_multi_ocr: bool | None = None,
) -> PageRisk:
    cfg = cfg or load_config()
    th = cfg.get("thresholds", {})
    w = cfg.get("weights", {})
    yiku = yiku or YikuIndex((cfg.get("yiku") or {}).get("db"))

    key = str(page.get("key") or "")
    n = int(page.get("page") or 0)
    level = page.get("verify_level") or ""
    text = page.get("text") or ""
    q = page.get("quality") or text_quality(text, (page.get("quality") or {}).get("ocr_conf"))
    reasons: list[str] = []
    score = 0.0
    signals: dict[str, Any] = {
        "chars": q.get("chars"),
        "ocr_conf": q.get("ocr_conf"),
        "dpi": page.get("dpi"),
        "verify_level": level,
    }

    if level in ("text_layer", "ocr_verified", "blank"):
        return PageRisk(key, n, 0.0, "skip", [f"等级 {level} 跳过"], signals, level, _sha1(text))

    conf = q.get("ocr_conf")
    if conf is not None and float(conf) < float(th.get("min_ocr_conf", 0.85)):
        score += float(w.get("low_conf", 2.0))
        reasons.append(f"低置信 {conf}")

    chars = int(q.get("chars") or 0)
    if chars < int(th.get("min_chars", 30)):
        score += float(w.get("low_chars", 2.0))
        reasons.append(f"少字 {chars}")

    garble = int(q.get("pua") or 0) + int(q.get("replacement") or 0) + int(q.get("missing_glyph") or 0)
    signals["garble"] = garble
    if garble > int(th.get("max_garble", 0)):
        score += float(w.get("garble", 3.0))
        reasons.append(f"乱码/缺字 {garble}")

    dpi = page.get("dpi")
    prefer = int(th.get("prefer_dpi", 300))
    if dpi is not None and int(dpi) < prefer and level == "ocr_raw":
        score += float(w.get("low_dpi", 2.5))
        reasons.append(f"dpi {dpi}<{prefer}")

    if has_multi_ocr is False:
        score += float(w.get("no_consensus", 1.0))
        reasons.append("单引擎无共识")

    unk_lat = yiku.unknown_latin(text)
    signals["unknown_latin_n"] = len(unk_lat)
    signals["unknown_latin"] = unk_lat[:12]
    max_lat = int(th.get("max_unknown_latin", 3))
    if len(unk_lat) > max_lat:
        add = min(4.0, float(w.get("unknown_latin", 0.5)) * (len(unk_lat) - max_lat))
        score += add
        reasons.append(f"未知拉丁名 {len(unk_lat)}>{max_lat}")

    unk_zh = yiku.unknown_zh_taxon(text)
    signals["unknown_zh_n"] = len(unk_zh)
    signals["unknown_zh"] = unk_zh[:12]
    max_zh = int(th.get("max_unknown_zh_taxon", 5))
    if len(unk_zh) > max_zh:
        add = min(3.0, float(w.get("unknown_zh", 0.3)) * (len(unk_zh) - max_zh))
        score += add
        reasons.append(f"未知中文科属 {len(unk_zh)}>{max_zh}")

    # digit density: many digits but very low conf → anomaly
    dig = len("".join(DIGIT_RE.findall(text)))
    signals["digits"] = dig
    if dig >= 40 and conf is not None and float(conf) < 0.9:
        score += float(w.get("digit_dense_anomaly", 1.0))
        reasons.append("数字多且置信偏低")

    pass_max = float(th.get("pass_max", 2.0))
    human_min = float(th.get("human_min", 5.0))
    hard_human = garble > int(th.get("max_garble", 0))
    if hard_human or score >= human_min:
        action = "human"
    elif score >= pass_max or (dpi is not None and int(dpi) < prefer and level == "ocr_raw"):
        action = "redo"
    else:
        action = "pass"

    if not reasons:
        reasons.append("风险分低")
    return PageRisk(key, n, round(score, 3), action, reasons, signals, level, _sha1(text))


def _ocr_version_count(page: dict) -> int:
    n = 0
    for v in [_primary(page)] + list(page.get("alternates") or []):
        if v.get("method") == "ocr" and (v.get("text") or "").strip():
            n += 1
    return n


def _log_path(store: Store, key: str) -> Path:
    d = store.root / "quality" / "qc"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{key}.jsonl"


def _queue_path(store: Store, key: str) -> Path:
    d = store.root / "quality" / "qc"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{key}_human.tsv"


def _done_state(path: Path) -> dict[str, dict]:
    """Last decision per page+text_sha1 (later lines win)."""
    done: dict[str, dict] = {}
    if not path.exists():
        return done
    for ln in path.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        try:
            row = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if row.get("action") == "summary" or not row.get("text_sha1"):
            continue
        done[f"{row.get('page')}:{row['text_sha1']}"] = row
    return done

def _append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def redo_page(
    store: Store,
    key: str,
    n: int,
    *,
    by: str | None = None,
    dpi: int = 300,
    engines: list[str] | None = None,
    log: Callable[[str], None] = print,
) -> dict:
    """Append a new OCR(+consensus) version at higher dpi; never delete old versions."""
    by = agent(by)
    engines = engines or ["rapidocr"]
    d = store.doc(key)
    path = d.get("path") or ""
    if not path or not os.path.exists(path):
        return {"key": key, "page": n, "ok": False, "reason": "原件缺失"}
    t0 = time.time()
    readings = []
    for eng in engines:
        txt, conf = textify._run_engine(eng, path, n, dpi)
        readings.append(textify.Reading(source=eng, text=txt, conf=float(conf) if conf is not None else 0.5))
        store.put_version(
            key,
            n,
            make_version(
                txt,
                "ocr",
                producer=eng,
                engine=f"{eng} {dpi}dpi",
                dpi=dpi,
                conf=conf,
                source=path,
                extra={"run_by": by, "reason": "qc_redo"},
            ),
            index=False,
        )
    from .consensus import vote
    from .lexicon import Fixer

    text, conf, disagreements, unresolved = vote(readings)
    fixer = Fixer(Path(__file__).resolve().parent / "rules" / "ocr_fix.toml")
    fixed, changes = fixer.apply(text)
    lv = "ocr_sampled" if unresolved == 0 else "ocr_raw"
    store.put_version(
        key,
        n,
        make_version(
            fixed,
            "ocr",
            producer=f"consensus({'+'.join(engines)})",
            engine=f"qc_redo consensus {dpi}dpi",
            dpi=dpi,
            conf=conf,
            level=lv,
            source=f"{path}#qc_redo",
            extra={
                "run_by": by,
                "reason": "qc_redo",
                "disagreements": disagreements,
                "lexicon_changes": changes,
            },
        ),
    )
    log(f"[{key}] qc redo p{n} dpi={dpi} engines={engines} {time.time()-t0:.1f}s")
    return {"key": key, "page": n, "ok": True, "level": lv, "seconds": round(time.time() - t0, 2)}


def apply_pass(store: Store, key: str, n: int, risk: PageRisk, *, by: str | None = None) -> dict:
    """Promote ocr_raw → ocr_sampled with same text; keep trail."""
    from .store import _atomic_write, _flock

    by = agent(by)
    with _flock(store.root / "pages" / key / ".lock"):
        page = store.read_page(key, n)
        if page is None:
            return {"ok": False, "reason": "无页"}
        if page.get("verify_level") != "ocr_raw":
            return {"ok": False, "reason": f"当前 {page.get('verify_level')} 不提升"}
        text = page.get("text") or ""
        conf = (page.get("quality") or {}).get("ocr_conf")
        old = _primary(page)
        ver = make_version(
            text,
            "qc_pass",
            producer=by,
            engine="docstore-qc",
            dpi=page.get("dpi"),
            level="ocr_sampled",
            conf=conf,
            source=f"qc pass: {'; '.join(risk.reasons)[:120]}",
            extra={"qc_score": risk.score, "qc_reasons": risk.reasons, "qc_signals": risk.signals},
        )
        page["alternates"] = [old] + list(page.get("alternates") or [])
        for k in VERSION_KEYS:
            page[k] = ver.get(k)
        for k, v in ver.items():
            if k not in VERSION_KEYS:
                page.setdefault("extra", {})[k] = v
        page.setdefault("history", []).append(
            {
                "action": "qc_pass",
                "by": by,
                "time": now(),
                "level": "ocr_sampled",
                "from_level": "ocr_raw",
                "note": "; ".join(risk.reasons),
                "score": risk.score,
            }
        )
        _atomic_write(store.page_path(key, n), json.dumps(page, ensure_ascii=False, indent=1))
    store._index_page(page)
    store.con.commit()
    return {"ok": True, "level": "ocr_sampled"}

def run_qc(
    store: Store,
    key: str,
    *,
    by: str | None = None,
    pages: list[int] | None = None,
    apply: bool = False,
    redo: bool = False,
    limit: int | None = None,
    cfg: dict | None = None,
    log: Callable[[str], None] = print,
) -> dict:
    """Score pages, append jsonl checkpoint, optionally apply pass/redo."""
    by = agent(by)
    cfg = cfg or load_config()
    yiku = YikuIndex((cfg.get("yiku") or {}).get("db"))
    acts = cfg.get("actions") or {}
    log_path = _log_path(store, key)
    queue_path = _queue_path(store, key)
    done = _done_state(log_path)
    nums = pages or store.page_numbers(key)
    if limit is not None:
        nums = nums[:limit]

    # page continuity: printed page gaps (signal only on batch summary)
    offsets_ok = True
    off = store.doc(key).get("page_offset")
    if off not in (None, ""):
        try:
            int(str(off))
        except (TypeError, ValueError):
            offsets_ok = False

    counts = {"pass": 0, "redo": 0, "human": 0, "skip": 0, "applied_pass": 0, "applied_redo": 0}
    # ensure human queue header
    if not queue_path.exists():
        queue_path.write_text(
            "page\tverify_level\tscore\t理由\t页图命令\t可疑\n", encoding="utf-8"
        )

    t0 = time.time()
    for i, n in enumerate(nums, 1):
        page = store.read_page(key, n)
        if page is None:
            continue
        page = {**page, "key": key, "page": n}
        multi = _ocr_version_count(page) >= 2
        risk = score_page(page, cfg=cfg, yiku=yiku, has_multi_ocr=multi)
        prev = done.get(f"{n}:{risk.text_sha1}")
        need_apply = False
        if apply and risk.action == "pass" and acts.get("promote_on_pass", True):
            need_apply = not (prev and prev.get("action") == "pass" and prev.get("applied"))
        elif apply and redo and risk.action == "redo":
            need_apply = not (prev and prev.get("action") == "redo" and prev.get("applied"))
        if prev and prev.get("action") == risk.action and not need_apply:
            continue
        row = {
            "time": now(),
            "by": by,
            "key": key,
            "page": n,
            "action": risk.action,
            "score": risk.score,
            "reasons": risk.reasons,
            "signals": risk.signals,
            "text_sha1": risk.text_sha1,
            "verify_level": risk.verify_level,
            "applied": False,
        }
        if apply and risk.action == "pass" and acts.get("promote_on_pass", True):
            r = apply_pass(store, key, n, risk, by=by)
            row["applied"] = bool(r.get("ok"))
            if r.get("ok"):
                counts["applied_pass"] += 1
        elif apply and redo and risk.action == "redo":
            engines = list(acts.get("redo_engines") or ["rapidocr"])
            dpi = int(acts.get("redo_dpi") or 300)
            r = redo_page(store, key, n, by=by, dpi=dpi, engines=engines, log=log)
            row["applied"] = bool(r.get("ok"))
            row["redo_result"] = r
            if r.get("ok"):
                counts["applied_redo"] += 1
        _append_jsonl(log_path, row)
        done[f"{n}:{risk.text_sha1}"] = row
        counts[risk.action] = counts.get(risk.action, 0) + 1
        if risk.action == "human" and not (prev and prev.get("action") == "human"):
            with open(queue_path, "a", encoding="utf-8") as f:
                sus = ",".join(risk.signals.get("unknown_latin", [])[:5])
                f.write(
                    f"{n}\t{risk.verify_level}\t{risk.score}\t"
                    f"{'；'.join(risk.reasons)}\tdocstore page {key} {n} --image\t{sus}\n"
                )
        if i % 50 == 0:
            log(f"[{key}] qc {i}/{len(nums)} {counts}")
    summary = {
        "key": key,
        "pages_scored": sum(counts[k] for k in ("pass", "redo", "human", "skip")),
        "counts": counts,
        "seconds": round(time.time() - t0, 2),
        "log": str(log_path),
        "human_queue": str(queue_path),
        "page_offset_ok": offsets_ok,
        "by": by,
    }
    _append_jsonl(log_path, {"time": now(), "by": by, "key": key, "action": "summary", **summary})
    return summary


def _pick_rapid_hyp(page: dict) -> dict | None:
    best: dict | None = None
    best_rank = -1
    for v in [_primary(page)] + list(page.get("alternates") or []):
        if (v.get("method") or "") == "verified":
            continue
        if not (v.get("text") or "").strip():
            continue
        eng = (v.get("engine") or "").lower()
        prod = (v.get("producer") or "").lower()
        if not ("rapid" in eng or "rapidocr" in prod or "pp-ocr" in eng):
            continue
        dpi = int(v.get("dpi") or 0)
        rank = 3 if dpi >= 300 else (2 if dpi >= 200 else 1)
        if rank > best_rank:
            best, best_rank = v, rank
    return best


def _conf_counts(tp: int, fp: int, tn: int, fn: int) -> dict:
    recall = tp / (tp + fn) if (tp + fn) else None
    fpr = fp / (fp + tn) if (fp + tn) else None
    precision = tp / (tp + fp) if (tp + fp) else None
    return {
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "recall": None if recall is None else round(recall, 4),
        "false_positive_rate": None if fpr is None else round(fpr, 4),
        "precision": None if precision is None else round(precision, 4),
    }


def calibrate(store: Store, *, cfg: dict | None = None) -> dict:
    """Score RapidOCR hyp on gold pages; CER detection + low-dpi policy stats."""
    cfg = cfg or load_config()
    cer_bad = float((cfg.get("calibration") or {}).get("cer_bad", 0.05))
    yiku = YikuIndex((cfg.get("yiku") or {}).get("db"))
    prefer = int((cfg.get("thresholds") or {}).get("prefer_dpi", 300))
    all_c = {"tp": 0, "fp": 0, "tn": 0, "fn": 0}
    dpi300_c = {"tp": 0, "fp": 0, "tn": 0, "fn": 0}
    policy = {"low_dpi_pages": 0, "low_dpi_routed_redo_or_human": 0, "low_dpi_cer_ge_bad": 0}
    scored = 0
    for r in store.status():
        key = r["key"]
        if not r["levels"].get("ocr_verified"):
            continue
        for (n,) in store.con.execute(
            "SELECT page FROM pages WHERE key=? AND verify_level='ocr_verified'", (key,)
        ):
            page = store.read_page(key, n)
            if not page:
                continue
            hyp_v = _pick_rapid_hyp(page)
            if not hyp_v:
                continue
            gold = page.get("text") or ""
            hyp = hyp_v.get("text") or ""
            c = cer(gold, hyp)
            dpi = hyp_v.get("dpi")
            fake = {**hyp_v, "key": key, "page": n, "alternates": [], "verify_level": "ocr_raw"}
            risk = score_page(fake, cfg=cfg, yiku=yiku, has_multi_ocr=False)
            flagged = risk.action in ("human", "redo")
            bad = c >= cer_bad
            scored += 1
            bucket = "tp" if bad and flagged else "fn" if bad else "fp" if flagged else "tn"
            all_c[bucket] += 1
            if dpi is not None and int(dpi) >= prefer:
                dpi300_c[bucket] += 1
            if dpi is not None and int(dpi) < prefer:
                policy["low_dpi_pages"] += 1
                if flagged:
                    policy["low_dpi_routed_redo_or_human"] += 1
                if bad:
                    policy["low_dpi_cer_ge_bad"] += 1
    return {
        "cer_bad": cer_bad,
        "scored_pages": scored,
        "all_dpi": _conf_counts(**all_c),
        "dpi_ge_prefer": _conf_counts(**dpi300_c),
        "low_dpi_policy": policy,
        "note": (
            "low_dpi→redo 是提 DPI 策略（金标准上多数 200dpi 页 CER 仍 <cer_bad，"
            "但总体 CER 显著差于 300dpi）。查全率/误报率看 dpi_ge_prefer。"
        ),
        "pass_max": (cfg.get("thresholds") or {}).get("pass_max"),
        "human_min": (cfg.get("thresholds") or {}).get("human_min"),
    }

def iter_risks(store: Store, key: str, cfg: dict | None = None) -> Iterator[PageRisk]:
    cfg = cfg or load_config()
    yiku = YikuIndex((cfg.get("yiku") or {}).get("db"))
    for n in store.page_numbers(key):
        page = store.read_page(key, n)
        if not page:
            continue
        page = {**page, "key": key, "page": n}
        yield score_page(page, cfg=cfg, yiku=yiku, has_multi_ocr=_ocr_version_count(page) >= 2)
