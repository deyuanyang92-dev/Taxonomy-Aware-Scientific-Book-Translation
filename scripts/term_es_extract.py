#!/usr/bin/env python3
"""西语（Fauna Ibérica 七卷）术语/专名候选抽取，零模型，可重跑。

每个出现都带位置：卷、docstore 页、印刷页（估算）、章节、科、亚科、属、种、小节。
位置由页内段落顺序上的标题状态机得出：Familia/Subfamilia/Orden/Género/种名标题/小节标签
（Distribución geográfica.— 等）。目录页（含 "....." 页码引导线）不当标题。

用法：
  python3 scripts/term_es_extract.py --out-dir DIR [--root _资料库] [--vols 21,25]
写出：
  pages_map.tsv          每个 docstore 页的位置（卷、页、印刷页、章节、科…）
  taxa_headings.tsv      分类单元（同 rank+name 只留正文首次出现；first_page/last_page；fixed_from=OCR 纠错前写法）；
                         目录页、检索表（Clave）页内的标题不入表
  raw_term_occurrences.tsv  term, kind(uni/bi/tri), vol, page, printed, family, genus, section, n
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import re
import statistics
import unicodedata
from pathlib import Path

DEFAULT_ROOT = Path("/mnt/p/翻译-译作/参考资料/_资料库")
# 卷号 -> docstore key（Vol 45 = Polychaeta V 2018；Vol 48 = Polychaeta VII）
VOLS = {
    21: "Fauna_Iberica_Vol21", 25: "Fauna_Iberica_Vol25", 36: "Fauna_Iberica_Vol36",
    41: "Fauna_Iberica_Vol41", 45: "Fauna_ib_rica_Vol_2", 47: "FaunaIberica_Vol_polyhchaeta_VI",
    48: "Fauna_ib_rica_Vol",
}
LEADER = re.compile(r"\.{3,}\s*\d+\s*$")
TOC_LINE = re.compile(r"^(?P<t>.+?)\s*\.{3,}\s*(?P<p>\d+)\s*$")
RE_FAM = re.compile(r"^Familia\s+([A-Za-z]{5,})\b")
RE_SUBFAM = re.compile(r"^Subfamilia\s+([A-Za-z]{5,})\b")
RE_ORDER = re.compile(r"^Orden\s+([A-Za-z]{4,})\b")
RE_KEY = re.compile(r"^Clave\b", re.I)
RE_END_CHAPTER = re.compile(r"^(bibliograf[ií]a|ap[eé]ndices?|[ií]ndices?\b)", re.I)
RE_GEN = re.compile(r"^G[eé]nero\s+([A-Z][A-Za-z]+)\b")
# 种名标题：Genus [(Subgenus)] epithet Author, 1888 [(fig. 38)]；不含 ". " 之后的文献出处
RE_SPEC = re.compile(
    r"^(?P<g>[A-Z][a-z]+)(?: \((?P<sg>[A-Z][a-z]+)\))? (?P<s>[a-z]{3,}(?: [a-z]{3,})?)"
    r" (?P<a>\(?[A-ZÀ-Ý][^.]{1,70}?(?:1[5-9]|20)\d\d[a-z]?\)?)(?: \(figs?\. [^)]*\))?\s*$"
)
SECTION_LABELS = (
    "Diagnosis", "Descripción", "Redescripción", "Distribución geográfica", "Distribución", "Biología",
    "Ecología", "Observaciones", "Material examinado", "Material estudiado", "Etimología",
    "Localidad tipo", "Sinonimia", "Hábitat", "Discusión", "Diagnosis genérica", "Especie tipo",
)
RE_SECTION = re.compile(r"^(" + "|".join(SECTION_LABELS) + r")\b[^.]{0,30}?\.\s*[—–-]")
STOP = set(
    """a al algo algunas algunos ante antes aquí así aun aunque bajo cada casi como con contra cual cuales cuando de del
desde donde dos durante e el ella ellas ello ellos en entre era eran es esa esas ese eso esos esta están estas este esto
estos fue fueron ha han hasta hay la las le les lo los más mas me mi mientras muy ni no nos o otra otras otro otros para
pero poco por porque pues que qué se sea según ser si sí sido sin sobre sólo solo son su sus también tan tanto te tiene
tienen todo todos tras un una uno unas unos y ya cuyo cuya cuyos cuyas dicho dicha dichos dichas""".split()
)
RE_WORD = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]+(?:-[A-Za-zÀ-ÖØ-öø-ÿ]+)*")
MIN_UNI_LEN = 4


def _clean_heading(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().strip("#* ").strip())


def paragraphs(text: str) -> list[str]:
    return [p for p in (x.strip() for x in re.split(r"\n\s*\n|\n", text or "")) if p]


def parse_toc(pages: list[tuple[int, str]]) -> list[tuple[str, int]]:
    """目录条目 (标题, 印刷页)；只扫前 20 页里含引导线的行。"""
    out: list[tuple[str, int]] = []
    for no, text in pages:
        if no > 20:
            break
        for para in paragraphs(text):
            m = TOC_LINE.match(para)
            if m:
                out.append((_clean_heading(m["t"]), int(m["p"])))
    return out


def norm_family(s: str) -> str:
    return s[:1].upper() + s[1:].lower()


def _nk(s: str) -> str:
    """章节标题比较键：只留字母，小写。"""
    return re.sub(r"[^a-zà-ÿ]", "", s.lower())


def edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return min(prev[-1], 99)


def toc_names(toc: list[tuple[str, int]], prefix: str, suffix: str) -> set[str]:
    """目录里的科/亚科名（规范大小写）。prefix 如 'Familia '，suffix 如 'idae'。"""
    out = set()
    for t, _ in toc:
        t = t.strip()
        if t.lower().startswith(prefix.lower()):
            t = t[len(prefix):].strip()
        m = re.match(r"([A-Za-z]{5,})", t)
        if m and m[1].lower().endswith(suffix):
            out.add(norm_family(m[1]))
    return out


def fix_name(name: str, known: set[str], suffix: str) -> tuple[str, str] | None:
    """OCR 纠错：返回 (名称, 原写法或空)；无法确认返回 None。"""
    if name in known:
        return name, ""
    best = sorted((edit_distance(name.lower(), k.lower()), k) for k in known)
    if best and best[0][0] <= 2 and (len(best) == 1 or best[1][0] > best[0][0]):
        return best[0][1], name
    if name.lower().endswith(suffix):
        return name, ""
    return None


def is_list_page(paras: list[str]) -> bool:
    """分类系统总表页：>=3 个 Familia/Orden/Superfamilia 行挤在一页，不当正文标题。"""
    n = sum(1 for p in paras if re.match(r"^(Familia|Orden|Superfamilia)\s+[A-Za-z]{4,}", _clean_heading(p)))
    return n >= 3


def is_toc_page(paras: list[str]) -> bool:
    return sum(1 for p in paras if LEADER.search(_clean_heading(p))) >= 3


def is_chapter_heading(head: str, chapters: set[str]) -> bool:
    """独立短标题才算章节：<=80 字符、非小写开头、去掉尾部页码/标点后与目录标题整段相等。"""
    if not head or len(head) > 80 or head[0].islower():
        return False
    core = re.sub(r"[\s.\-–—·]*\d*[\s.]*$", "", head)
    return bool(core) and _nk(core) in chapters


class State:
    def __init__(self) -> None:
        self.ended = False
        self.chapter = self.order = self.family = self.subfamily = self.genus = self.species = self.section = ""

    def row(self) -> dict[str, str]:
        return {"chapter": self.chapter, "order": self.order, "family": self.family,
                "subfamily": self.subfamily, "genus": self.genus, "species": self.species, "section": self.section}

    def clear_taxa(self) -> None:
        self.order = self.family = self.subfamily = self.genus = self.species = self.section = ""


def walk(pages: list[tuple[int, str]], toc: list[tuple[str, int]], vol: int):
    """按页、按段落推进状态；yield (page, [(para, state_row, skip)], taxa 原始标题行列表)。

    目录页（>=3 条引导线）、分类系统总表页（>=3 个 Familia/Orden 行）、检索表（Clave…）段之后到页末，
    标题不入 taxa、不改状态。
    """
    chapters = {_nk(t) for t, _ in toc if not t.lower().startswith(("familia ", "subfamilia ", "género ", "orden "))}
    chapters.discard("")
    fams = toc_names(toc, "Familia ", "idae")
    subs = toc_names(toc, "Subfamilia ", "inae")
    st = State()
    taxa: list[dict] = []
    for no, text in pages:
        plist = paragraphs(text)
        toc_page = is_toc_page(plist)
        list_page = is_list_page(plist)
        in_key = False
        paras = []
        for para in plist:
            head = _clean_heading(para)
            if toc_page or LEADER.search(head):
                paras.append((para, st.row(), True))
                continue
            if is_chapter_heading(head, chapters):
                key = bool(RE_KEY.match(head))
                if not (key and st.family):
                    st.chapter, st.section = head, ""
                    st.ended = bool(RE_END_CHAPTER.match(head))
                if st.ended:
                    st.clear_taxa()
            if st.ended:
                paras.append((para, st.row(), False))
                continue
            if RE_KEY.match(head) and len(head) < 80:
                in_key = True
            if in_key or list_page:
                paras.append((para, st.row(), False))
                continue
            m = RE_ORDER.match(head)
            if m and len(head) < 60:
                st.order, st.section = m[1].capitalize(), ""
                taxa.append(_taxon("orden", m[1].capitalize(), "", "", vol, no, st))
            m = RE_FAM.match(head)
            fx = fix_name(norm_family(m[1]), fams, "idae") if m and len(head) < 90 else None
            if fx:
                st.family, st.subfamily, st.genus, st.species, st.section = fx[0], "", "", "", ""
                st.chapter = f"Familia {st.family}"
                a, y = _author_year(head[m.end():].strip())
                taxa.append(_taxon("familia", st.family, a, y, vol, no, st, fx[1]))
            m = RE_SUBFAM.match(head)
            fx = fix_name(norm_family(m[1]), subs, "inae") if m and len(head) < 90 else None
            if fx:
                st.subfamily, st.genus, st.species, st.section = fx[0], "", "", ""
                a, y = _author_year(head[m.end():].strip())
                taxa.append(_taxon("subfamilia", st.subfamily, a, y, vol, no, st, fx[1]))
            m = RE_GEN.match(head)
            if m and len(head) < 120:
                st.genus, st.species, st.section = m[1], "", ""
                a, y = _author_year(head[m.end():].strip())
                taxa.append(_taxon("género", st.genus, a, y, vol, no, st))
            m = RE_SPEC.match(head)
            if m and len(head) < 140 and "." not in head.replace("fig.", "").replace("figs.", "").replace("sp.", ""):
                st.species = f"{m['g']} {m['s']}"
                st.genus = st.genus or m["g"]
                st.section = ""
                a, y = _author_year(m["a"])
                taxa.append(_taxon("especie", st.species, a, y, vol, no, st))
            m = RE_SECTION.match(head)
            if m:
                st.section = m[1]
            paras.append((para, st.row(), False))
        yield no, paras, taxa


def dedupe_taxa(taxa: list[dict]) -> list[dict]:
    """同 (rank,name) 只留正文首次出现，另记 first_page/last_page。"""
    seen: dict[tuple[str, str], dict] = {}
    for t in taxa:
        k = (t["rank"], t["name"])
        if k not in seen:
            seen[k] = dict(t, first_page=t["page"], last_page=t["page"])
        else:
            seen[k]["last_page"] = max(seen[k]["last_page"], t["page"])
            if not seen[k]["fixed_from"] and t["fixed_from"]:
                seen[k]["fixed_from"] = t["fixed_from"]
    return list(seen.values())


def _author_year(s: str) -> tuple[str, str]:
    m = re.search(r"((?:1[5-9]|20)\d\d[a-z]?)", s)
    y = m[1] if m else ""
    a = re.sub(r"[,\s]*(?:1[5-9]|20)\d\d[a-z]?\)?\s*$", "", s).strip(" ,()") if y else s.strip(" ,()")
    return a, y


def _taxon(rank: str, name: str, author: str, year: str, vol: int, page: int, st: State, fixed_from: str = "") -> dict:
    return {"rank": rank, "name": name, "author": author, "year": year, "vol": vol, "page": page,
            "family": st.family, "genus": st.genus, "fixed_from": fixed_from}


def fold(s: str) -> str:
    return unicodedata.normalize("NFC", s.lower())


def tokens(para: str) -> list[str]:
    return [fold(w) for w in RE_WORD.findall(para)]


def candidates(para: str) -> list[tuple[str, str]]:
    """段内候选 (term, kind)。小写词；n-gram 首尾不得是停用词；含数字/图号的片段不成词。"""
    # 以标点和括号断开，避免跨句 n-gram
    out: list[tuple[str, str]] = []
    for seg in re.split(r"[.;:,()\[\]¿?¡!\"“”«»—–=/]|\d", para):
        toks = tokens(seg)
        for i, w in enumerate(toks):
            if len(w) >= MIN_UNI_LEN and w not in STOP:
                out.append((w, "uni"))
            for n, kind in ((2, "bi"), (3, "tri")):
                g = toks[i:i + n]
                if len(g) == n and g[0] not in STOP and g[-1] not in STOP and all(len(x) > 1 for x in g) \
                        and sum(1 for x in g if x in STOP) <= 1:
                    out.append((" ".join(g), kind))
    return out


def load_pages(root: Path, key: str) -> list[tuple[int, str]]:
    res = []
    for f in sorted((root / "pages" / key).glob("p*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        res.append((int(f.stem[1:]), d.get("text") or ""))
    return res


def page_offset(taxa: list[dict], toc: list[tuple[str, int]]) -> int:
    """印刷页 = docstore 页 − offset；取各科标题页与目录页之差的中位数。"""
    want = {t.lower().replace("familia ", ""): p for t, p in toc if t.lower().startswith("familia ")}
    diffs = [t["first_page"] - want[t["name"].lower()] for t in taxa if t["rank"] == "familia" and t["name"].lower() in want]
    return int(statistics.median(diffs)) if diffs else 0


def run(root: Path, out_dir: Path, vols: list[int], split_raw: bool = False) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    page_rows: list[dict] = []
    taxa_all: list[dict] = []
    stats: dict[int, dict] = {}
    raw_fields = ["term", "kind", "vol", "page", "printed", "family", "genus", "section", "n"]
    raw_path = out_dir / "raw_term_occurrences.tsv"
    fh = None if split_raw else raw_path.open("w", encoding="utf-8", newline="")
    wr = None
    if fh:
        wr = csv.writer(fh, delimiter="\t", lineterminator="\n")
        wr.writerow(raw_fields)
    n_raw = 0
    for vol in vols:
        pages = load_pages(root, VOLS[vol])
        toc = parse_toc(pages)
        pg_paras = list(walk(pages, toc, vol))
        taxa = dedupe_taxa(pg_paras[-1][2] if pg_paras else [])
        scope: dict[tuple[str, str], int] = {}
        for no, paras, _ in pg_paras:
            for _p, row, _s in paras:
                for rk, fld in (("orden", "order"), ("familia", "family"), ("subfamilia", "subfamily"),
                                ("género", "genus"), ("especie", "species")):
                    if row[fld]:
                        scope[(rk, row[fld])] = no
        for tx in taxa:
            tx["last_page"] = max(tx["first_page"], scope.get((tx["rank"], tx["name"]), 0))
        off = page_offset(taxa, toc)
        taxa_all += [dict(t, printed=t["first_page"] - off) for t in taxa]
        occ: dict[tuple, int] = collections.Counter()
        v_rows = []
        for no, paras, _ in pg_paras:
            last = paras[-1][1] if paras else State().row()
            v_rows.append({"vol": vol, "page": no, "printed": no - off, **last, "n_chars": sum(len(p[0]) for p in paras)})
            for para, row, skip in paras:
                if skip:
                    continue
                for term, kind in candidates(para):
                    occ[(term, kind, vol, no, no - off, row["family"], row["genus"], row["section"])] += 1
        page_rows += v_rows
        fam_pages = [t["first_page"] for t in taxa if t["rank"] == "familia"]
        first_fam = min(fam_pages) if fam_pages else 0
        stats[vol] = {
            "pages": len(v_rows),
            **{r: sum(1 for t in taxa if t["rank"] == r) for r in ("orden", "familia", "subfamilia", "género", "especie")},
            "toc_families": len(toc_names(toc, "Familia ", "idae")),
            "family_empty_after_first_family": sum(1 for r in v_rows if first_fam and r["page"] > first_fam and not r["family"]),
            "fixed": sum(1 for t in taxa if t["fixed_from"]),
            "raw_rows": len(occ),
        }
        n_raw += len(occ)
        rows = (list(k) + [n] for k, n in occ.items())
        if split_raw:
            with (out_dir / f"raw_term_occurrences_vol{vol}.tsv").open("w", encoding="utf-8", newline="") as f2:
                w2 = csv.writer(f2, delimiter="\t", lineterminator="\n")
                w2.writerow(raw_fields)
                w2.writerows(rows)
        else:
            wr.writerows(rows)
    if fh:
        fh.close()
    _w(out_dir / "pages_map.tsv", page_rows)
    _w(out_dir / "taxa_headings.tsv", taxa_all)
    return {"stats": stats, "occurrences": n_raw}


def _w(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=str(DEFAULT_ROOT))
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--split-raw", action="store_true", help="raw 表按卷分文件")
    ap.add_argument("--vols", default=",".join(map(str, VOLS)))
    a = ap.parse_args(argv)
    print(run(Path(a.root), Path(a.out_dir), [int(v) for v in a.vols.split(",")], a.split_raw))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
