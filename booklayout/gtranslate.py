"""Machine-translate an aligned.json with the free Google endpoint (no model).

"booklayout translate-aligned" fills each block's "translation" from its source
"text", keeping page/block structure, so "booklayout make" can typeset the
English or Chinese edition of a scanned book.  Protections (all deterministic):

* dot leaders and trailing page refs ("... 11", "..... Autolytinae (p. 7)") stay;
  only the label before the leader is translated;
* binomials whose genus is a WoRMS genus ("Syllis prolifera", "S. prolifera")
  are masked before the request and restored after; a block whose masks do not
  all come back is re-translated unmasked and listed as name_check;
* pure numbers / symbols / empty text are copied unchanged.

Reuses scripts/gtrans.py (cache, retry, parallel prefetch).  Writes a JSON report
with timings so speed can be tracked.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

from .english import worms_genera

ROLES = {"heading", "body", "caption", "key", "index", "ref", "couplet", "legend"}
LEADER_RE = re.compile(r"^(?P<label>.*?)(?P<lead>\s*\.{3,}\s*|\s+…+\s*)(?P<tail>.*)$", re.S)
BINOM_RE = re.compile(r"\b(?P<g>[A-Z][a-z]{3,}|[A-Z]\.)\s+(?P<s>[a-z]{3,})\b")
RANK_RE = re.compile(
    r"\b(?P<r>Superfamilia|Subfamilia|Familia|Suborden|Orden|Superorden|Clase|Subclase|Tribu|Género|Subgénero)"
    r"(?P<sp>\s+)(?P<n>[A-ZÁÉÍÓÚ][A-Za-záéíóú]{3,}|[A-ZÁÉÍÓÚ]{4,})\b")
LETTERS_RE = re.compile(r"[^\W\d_]", re.U)
# "Genus species Author, 1956" whose genus is not in WoRMS (junior synonym, e.g. Petitia) must still be kept
AUTHOR_YEAR_RE = re.compile(r"\s+\(?[A-Z][^\n]{0,70}?\b(?:1[6-9]\d\d|20[0-2]\d)\b")
NOMEN_RE = re.compile(r"\b(?:comb|sp|gen|nom|stat)\.\s*(?:n|nov)\.")  # comb. n., sp. nov. stay Latin
KEY_HEADINGS = {  # Spanish source headings Google mistranslates ("Clave de géneros" -> "类型键", "ÍNDICE" -> "指数")
    "clave de familias": ("Family key", "科检索表"), "clave de subfamilias": ("Subfamily key", "亚科检索表"),
    "clave de géneros": ("Genus key", "属检索表"), "clave de especies": ("Species key", "种检索表"),
    "índice": ("Contents", "目录"),
}
RANK_WORDS = {  # Spanish rank word -> (English, Chinese)
    "superfamilia": ("Superfamily", "总科"), "subfamilia": ("Subfamily", "亚科"), "familia": ("Family", "科"),
    "suborden": ("Suborder", "亚目"), "orden": ("Order", "目"), "superorden": ("Superorder", "总目"),
    "clase": ("Class", "纲"), "subclase": ("Subclass", "亚纲"), "tribu": ("Tribe", "族"),
    "género": ("Genus", "属"), "subgénero": ("Subgenus", "亚属"),
}
RANK_LINE_RE = re.compile(r"^(?P<r>" + "|".join(RANK_WORDS) + r")\s+(?P<n>[A-ZÁÉÍÓÚ][^\n]{3,90})$", re.I)
_ES_STOP = re.compile(r"\b(?:el|la|los|las|de|del|que|con|por|para|una|un|es|se)\b")


def fixed_heading(line: str, tl: str) -> str | None:
    """Exact translation for a key heading or a "Familia NAME Author, year" line, else None."""
    zh = tl.lower().startswith("zh")
    s = line.strip()
    k = KEY_HEADINGS.get(s.lower())
    if k:
        return k[1 if zh else 0]
    m = RANK_LINE_RE.match(s)
    if m and not _ES_STOP.search(m.group("n")) and "..." not in s and "…" not in s:
        en, cn = RANK_WORDS[m.group("r").lower()]
        return f"{cn} {m.group('n')}" if zh else f"{en} {m.group('n')}"
    return None


def _load_gtrans() -> Any:
    here = Path(__file__).resolve().parent.parent / "scripts" / "gtrans.py"
    if str(here.parent) not in sys.path:
        sys.path.insert(0, str(here.parent))  # gtrans imports sibling scripts
    spec = importlib.util.spec_from_file_location("gtrans", here)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules.setdefault("gtrans", mod)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def mask_names(text: str, genera: frozenset[str]) -> tuple[str, dict[str, str]]:
    """Replace genus+epithet pairs with opaque tokens; returns (masked, token->original)."""
    table: dict[str, str] = {}

    def sub(m: re.Match[str]) -> str:
        g = m.group("g")
        if not g.endswith(".") and g not in genera and not AUTHOR_YEAR_RE.match(text, m.end()):
            return m.group(0)
        tok = f"Zq{len(table):03d}x"
        table[tok] = m.group(0)
        return tok

    text = BINOM_RE.sub(sub, text)

    def nomen_sub(m: re.Match[str]) -> str:
        tok = f"Zq{len(table):03d}x"
        table[tok] = m.group(0)
        return tok

    text = NOMEN_RE.sub(nomen_sub, text)

    def rank_sub(m: re.Match[str]) -> str:
        tok = f"Zq{len(table):03d}x"
        table[tok] = m.group("n")
        return m.group("r") + m.group("sp") + tok

    # "Familia SYLLIDAE", "Subfamilia Eusyllinae": the higher-taxon name must survive translation
    return RANK_RE.sub(rank_sub, text), table


def unmask(text: str, table: dict[str, str]) -> tuple[str, bool]:
    ok = True
    for tok, orig in table.items():
        if tok not in text:
            ok = False
        text = text.replace(tok, orig)
    return text, ok


def _needs_translation(s: str) -> bool:
    return len(LETTERS_RE.findall(s)) >= 2


class Translator:
    def __init__(self, sl: str, tl: str, workers: int = 8, cache: str | None = None):
        self.g = _load_gtrans()
        self.google = self.g.Google(self.g.Cache(cache), sl=sl, tl=tl, pause=(0.0, 0.0))
        self.workers = workers
        self.tl = tl
        self.genera = worms_genera()
        self.name_check: list[dict[str, str]] = []

    def plan(self, text: str) -> list[tuple[str, str]]:
        """Split a block into (kind, string): kind 'tr' is translated, 'keep' is copied."""
        out: list[tuple[str, str]] = []
        for line in text.split("\n"):
            fx = fixed_heading(line, getattr(self, "tl", ""))
            if fx is not None:
                out += [("keep", fx), ("keep", "\n")]
                continue
            m = LEADER_RE.match(line)
            if m and _needs_translation(m.group("label")):
                out += [("tr", m.group("label")), ("keep", m.group("lead") + m.group("tail")), ("keep", "\n")]
            elif _needs_translation(line):
                out += [("tr", line), ("keep", "\n")]
            else:
                out += [("keep", line), ("keep", "\n")]
        if out:
            out.pop()
        return out

    def masked(self, s: str) -> tuple[str, dict[str, str]]:
        return mask_names(s, self.genera)

    def prefetch(self, texts: list[str]) -> int:
        reqs: list[str] = []
        for t in texts:
            for kind, s in self.plan(t):
                if kind == "tr":
                    reqs.append(self.masked(s)[0])
        return self.google.prefetch(reqs, self.workers)

    def translate_block(self, text: str, block_id: str = "") -> str:
        parts: list[str] = []
        for kind, s in self.plan(text):
            if kind == "keep":
                parts.append(s)
                continue
            ms, table = self.masked(s)
            tr, ok = unmask(self.google.translate(ms), table)
            if not ok:
                tr = self.google.translate(s)
                self.name_check.append({"block_id": block_id, "source": s, "output": tr})
            parts.append(tr)
        return "".join(parts)


_ZH_PAREN = re.compile(r"\(([^()（）]*)[）)](?=\s*[一-鿿，。；：、])|\(([^()（）]*)）|（([^()（）]*)\)")


def zh_punct(s: str) -> str:
    """Google mixes half- and full-width parentheses around Chinese text ("Fauvel (1923a、1932 等）"):
    make every such pair full-width."""
    s = _ZH_PAREN.sub(lambda m: "（" + (m.group(1) or m.group(2) or m.group(3) or "") + "）", s)
    # Google leaves spaces around full-width marks: "Pierantoni （1903） 的", "图97A ，107A", "图 169A"
    s = re.sub(r"[ \t]+(?=[，。；：、）！？])", "", s)
    s = re.sub(r"(?<=[（])[ \t]+", "", s)
    s = re.sub(r"(?<=[一-鿿A-Za-z0-9])[ \t]+(?=（)", "", s)
    s = re.sub(r"(?<=[），。；：、])[ \t]+(?=[一-鿿])", "", s)
    s = re.sub(r"(?<=[一-鿿])[ \t]+(?=[一-鿿])", "", s)
    return re.sub(r"(?<=图)[ \t]+(?=\d)", "", s)


def join_continuations(data: dict[str, Any]) -> int:
    """Join a body block that continues over a page break (previous block has no
    terminal punctuation, next page's first body block starts lower-case) into one
    source block *before* translation, so the translation is not cut mid-sentence
    (a split sentence translates as two capitalised fragments)."""
    from .structure import _TERMINAL, _flow

    genera = worms_genera()
    pages = data["pages"]
    n = 0
    for pg in pages:  # the lower-case tail of a figure legend that OCR typed as a body block
        bl = pg.get("blocks") or []
        for k in range(len(bl) - 1, 0, -1):
            cap, tail = bl[k - 1], bl[k]
            if (cap.get("role") == "caption" or cap.get("text", "").startswith("Fig.")) and tail.get("role") == "body" \
                    and tail.get("text", "")[:1].islower() and not _TERMINAL.search(cap.get("text", "").rstrip()):
                cap["text"] = cap["text"].rstrip() + " " + tail["text"].lstrip()
                cap["translation"] = cap["text"]
                del bl[k]
                n += 1
    prev = None  # last page with running text; plates (caption-only pages) in between do not break a paragraph
    for nxt in pages:
        b_flow = _flow(nxt.get("blocks") or [])
        if not b_flow:
            continue
        a_flow = _flow(prev.get("blocks") or []) if prev else []
        last, prev = prev, nxt
        if not a_flow or last is None:
            continue
        a, b = a_flow[-1], b_flow[0]
        if a.get("role") != "body" or b.get("role") != "body":
            continue
        at, bt = a.get("text", "").rstrip(), b.get("text", "").lstrip()
        if not at or not bt or _TERMINAL.search(at):
            continue
        first_word = re.match(r"[^\W\d_]+", bt)
        # lower-case start, or a genus name ("... se han estudiado | Polybostrichus al microscopio")
        if not (bt[:1].islower() or (first_word and first_word.group(0) in genera)):
            continue
        a["text"] = (at[:-1] + bt) if re.search(r"[^\W\d_]-$", at) else at + " " + bt
        a["translation"] = a["text"]
        nxt["blocks"].remove(b)
        if not _flow(nxt["blocks"]):
            prev = last  # nothing of this page is left: the joined paragraph now ends on the earlier page
        n += 1
    return n


def use_translation_as_source(data: dict[str, Any]) -> int:
    """Make the hand-corrected source-language "translation" the text to translate.

    The source edition (e.g. Spanish) is proofread by patching "translation"; "text"
    stays raw OCR (lost key targets "..... 2", wrong page refs).  Machine translation
    must start from the proofread string, so copy it over "text" (raw kept in "text_ocr").
    """
    n = 0
    for p in data["pages"]:
        for b in p["blocks"]:
            tr = (b.get("translation") or "").strip()
            if b.get("role") in ROLES and tr and tr != b.get("text", "").strip():
                b["text_ocr"] = b.get("text", "")
                b["text"] = tr
                n += 1
    return n


def translate_aligned(aligned: Path, out: Path, sl: str, tl: str, pages: tuple[int, int] | None = None,
                      workers: int = 8, report: Path | None = None,
                      source_field: str = "text") -> dict[str, Any]:
    t0 = time.time()
    data = json.loads(aligned.read_text(encoding="utf8"))
    promoted = use_translation_as_source(data) if source_field == "translation" else 0
    joined = join_continuations(data)
    tr = Translator(sl, tl, workers)
    todo: list[dict[str, Any]] = []
    for p in data["pages"]:
        if pages and not pages[0] <= p["page"] <= pages[1]:
            continue
        todo += [b for b in p["blocks"] if b.get("role") in ROLES and b.get("text", "").strip()]
    n_new = tr.prefetch([b["text"] for b in todo])
    t1 = time.time()
    for b in todo:
        b["translation"] = tr.translate_block(b["text"], b.get("block_id", ""))
        if b.get("role") in {"caption", "legend"}:  # hard OCR line breaks glued "of\nS." into "ofS."
            b["translation"] = re.sub(r"[ \t]*\n[ \t]*", " ", b["translation"]).strip()
        elif b.get("role") == "body" and "..." not in b["translation"]:  # legend OCR'd as body: mid-sentence break
            b["translation"] = re.sub(r"(?<=[a-z,;])[ \t]*\n[ \t]*(?=\S)", " ", b["translation"])
        if tl.lower().startswith("zh"):
            b["translation"] = zh_punct(b["translation"])
    data["lineage"] = {"derived_from": str(Path(aligned).resolve()), "stage": "google-translate",
                       "sl": sl, "tl": tl, "source_field": source_field}
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf8")
    rep = {"sl": sl, "tl": tl, "source_field": source_field, "promoted_from_translation": promoted,
           "joined_across_pages": joined, "blocks": len(todo), "chars": sum(len(b["text"]) for b in todo),
           "google_requests": tr.google.requests, "prefetched": n_new, "cache_hits": tr.google.hits,
           "prefetch_s": round(t1 - t0, 1), "translate_s": round(time.time() - t1, 1),
           "total_s": round(time.time() - t0, 1), "name_check": tr.name_check}
    if report:
        report.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf8")
    return rep


def add_parser(sub: Any) -> None:
    p = sub.add_parser("translate-aligned", help="Google-translate aligned.json blocks (no model)")
    p.add_argument("--aligned", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--sl", default="es")
    p.add_argument("--tl", required=True, help="Google code, e.g. en, zh-CN")
    p.add_argument("--pages", help="first-last, e.g. 1-50")
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--source-field", choices=["text", "translation"], default="text",
                   help="translation: start from the proofread source-language edition (patched 'translation') instead of raw OCR 'text'")
    p.add_argument("--report", type=Path)
    p.set_defaults(func=run)


def run(args: Any) -> int:
    pages = None
    if args.pages:
        a, _, b = args.pages.partition("-")
        pages = (int(a), int(b or a))
    rep = translate_aligned(args.aligned, args.out, args.sl, args.tl, pages, args.workers, args.report, args.source_field)
    print(json.dumps({k: v for k, v in rep.items() if k != "name_check"}, ensure_ascii=False))
    if rep["name_check"]:
        print(f"name_check: {len(rep['name_check'])} blocks re-translated unmasked")
    return 0
