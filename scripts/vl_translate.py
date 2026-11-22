"""对齐 JSON 逐页翻译（西/英→中，DeepSeek flash，按块），含防护：译文必须是字符串、数量与输入一致、失败重试、
单块兜底。用法：python3 scripts/vl_translate.py <aligned.json> --usage-file <jsonl> [--tag T]
只填没有 translation 的块，可反复运行（续译）。DeepSeek 只在折扣时段发请求（llm_engines 自动等待）。
2026-11-22：模型有时返回 {original,translation} 对象，旧试点脚本把它当字符串写入，qa 崩溃 -> 这里取 translation 字段并校验类型。"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import llm_engines as E  # noqa: E402

SYS = ("你是分类学专业译者。把{lang}（多毛类专著 Fauna Ibérica）逐块译成中文。学名、作者名、年份原样保留；"
       "术语不确定处保留原文并括号标“暂定”。只输出JSON数组，元素是与输入同序的中文译文字符串，数量必须一致。")
SYS1 = "把{lang}译成中文，学名原样保留。只输出译文纯文本，不要JSON，不要原文。"


BINOM = re.compile(r"\b[A-Z][a-z]{3,}\s+[a-z]{4,}\b")
ARABIC = re.compile("[" + chr(0x600) + "-" + chr(0x6FF) + "]")


def invented_names(src: str, zh: str) -> list[str]:
    """译文里出现、原文没有的拉丁双名（页级翻译易把相邻学名行串进图注）。"""
    words = set(re.findall(r"[A-Za-z]+", src))
    out = []
    for m in BINOM.findall(zh):
        if m in src or m.split()[0] in src:
            continue
        if difflib.get_close_matches(m.split()[0], words, n=1, cutoff=0.8):  # OCR 笔误被译者改正，不算串入
            continue
        out.append(m)
    return out


def audit(d: dict, usage: str, tag: str, lang: str, gloss: str) -> tuple[int, int]:
    """对串入学名的块逐块重译；返回 (发现数, 仍未清除数)。"""
    found = left = 0
    for pg in d["pages"]:
        for b in pg["blocks"]:
            if not invented_names(b["text"], b.get("translation") or ""):
                continue
            found += 1
            raw, _u = E.call("deepseek-flash", SYS1.format(lang=lang) + gloss + "\n只译给出的文字，不得添加原文没有的任何词。", b["text"], max_tokens=3000, tag=tag, usage_file=usage)
            b["translation"] = raw.strip()
            left += bool(invented_names(b["text"], b["translation"]))
    return found, left


def as_text(x: object) -> str | None:
    if isinstance(x, str):
        return x.strip() or None
    if isinstance(x, dict):
        v = x.get("translation") or x.get("zh") or x.get("译文")
        return as_text(v) if v is not None else None
    return None


def parse_reply(raw: str, n: int) -> list[str] | None:
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip()).strip()
    try:
        arr = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(arr, list) or len(arr) != n:
        return None
    out = [as_text(a) for a in arr]
    return None if any(o is None for o in out) else [o for o in out if o]


def load_glossary(path: str | None) -> str:
    if not path:
        return ""
    rows = [ln.split("\t") for ln in Path(path).read_text(encoding="utf-8").splitlines() if ln.strip()]
    return "\n术语表（必须照用，来源 yiku 已核）：" + "；".join(f"{r[0]}={r[2]}" for r in rows if len(r) >= 3)


def translate_page(pg: dict, lang: str, usage: str, tag: str, gloss: str = "") -> int:
    todo = [b for b in pg["blocks"] if not (b.get("translation") or "").strip()]
    if not todo:
        return 0
    user = json.dumps([b["text"] for b in todo], ensure_ascii=False)
    for _ in range(3):
        try:
            raw, _u = E.call("deepseek-flash", SYS.format(lang=lang) + gloss, user, max_tokens=8000, tag=tag, usage_file=usage)
        except E.EngineError:
            continue
        res = parse_reply(raw, len(todo))
        if res:
            for b, z in zip(todo, res):
                b["translation"] = z
            return 0
    left = 0
    for b in todo:
        try:
            raw, _u = E.call("deepseek-flash", SYS1.format(lang=lang) + gloss, b["text"], max_tokens=3000, tag=tag, usage_file=usage)
            b["translation"] = raw.strip()
        except E.EngineError:
            left += 1
    return left


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("aligned")
    ap.add_argument("--usage-file", required=True)
    ap.add_argument("--tag", default="vl_translate")
    ap.add_argument("--lang", default="西班牙语")
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--glossary", help="es_glossary.py 生成的 tsv")
    ap.add_argument("--audit", action="store_true", help="只做串入学名审计与逐块重译")
    ap.add_argument("--retranslate", action="store_true", help="清空已有译文重译")
    a = ap.parse_args(argv)
    p = Path(a.aligned)
    d = json.loads(p.read_text(encoding="utf-8"))
    if a.retranslate:
        for pg in d["pages"]:
            for b in pg["blocks"]:
                b.pop("translation", None)
    gloss = load_glossary(a.glossary)
    if a.audit:
        f, n = audit(d, a.usage_file, a.tag, a.lang, gloss)
        p.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        ar = sum(bool(ARABIC.search(b["text"])) for pg in d["pages"] for b in pg["blocks"])
        print(f"invented={f} still={n} arabic_ocr_blocks={ar}")
        return 0 if n == 0 else 1
    with ThreadPoolExecutor(a.threads) as ex:
        left = sum(ex.map(lambda pg: translate_page(pg, a.lang, a.usage_file, a.tag, gloss), d["pages"]))
    p.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"untranslated={left}")
    return 0 if left == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
