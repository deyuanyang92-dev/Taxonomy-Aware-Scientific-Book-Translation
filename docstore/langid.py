"""资料语言识别（纯脚本，零 token）。

用户要求（2026-11-15）：「搞个脚本快速识别输入文件是什么语言，不要总是用 tokens」；
「优先使用脚本，不行再用大模型，大模型也要优化脚本」。

做法：从 PDF 均匀抽若干页取文本（文本层可用直取；字符太少则 150 dpi 渲染后 Tesseract 多语种快识），
按「文字系统 → 功能词计数」逐页判语言，汇总为全书主语言与各语言页比例（论文常带外语摘要）。
功能词表 `rules/lang_words.toml`：判不准的样本由模型看过后，把新功能词加进这张表，下次脚本即可判（不再调模型）。
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from collections import Counter
from functools import lru_cache
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

RULES = Path(__file__).with_name("rules") / "lang_words.toml"

_KANA = re.compile(r"[぀-ヿ]")
_HANGUL = re.compile(r"[가-힯]")
_CJK = re.compile(r"[一-鿿㐀-䶿]")
_CYR = re.compile(r"[Ѐ-ӿ]")
_GREEK = re.compile(r"[Ͱ-Ͽ]")
_LATIN = re.compile(r"[A-Za-zÀ-ÿĀ-ž]")
_WORD = re.compile(r"[^\W\d_]+")


@lru_cache(maxsize=1)
def _words() -> dict[str, dict[str, set[str]]]:
    data = tomllib.loads(RULES.read_text(encoding="utf-8"))
    return {script: {lang: {w.lower() for w in ws} for lang, ws in langs.items()} for script, langs in data.items()}


@lru_cache(maxsize=None)
def _weights(script: str) -> dict[str, dict[str, float]]:
    """词 → {语言: 权重}。只属于一种语言的词记 1；n 种语言共有的词每种记 1/n；单字母词不计（OCR 碎片多）。"""
    seen: Counter = Counter()
    for ws in _words().get(script, {}).values():
        seen.update(ws)
    out: dict[str, dict[str, float]] = {}
    for lang, ws in _words().get(script, {}).items():
        for w in ws:
            if len(w) > 1:
                out.setdefault(w, {})[lang] = 1 / seen[w]
    return out


def _despace(text: str) -> str:
    """ABBYY 老扫描常把字母隔开（「G e s a H a r t m a n n」）；连续 ≥3 个单字母合并成词。"""
    return re.sub(r"\b(?:[^\W\d_] ){2,}[^\W\d_]\b", lambda m: m.group(0).replace(" ", ""), text)


def detect_text(text: str, min_hits: float = 2.5) -> tuple[str, float]:
    """返回 (语言代码, 置信度 0–1)。判不出返回 ("und", 0)。置信度 = 第一名得分 /（第一 + 第二）。"""
    if not text or not text.strip():
        return "und", 0.0
    n_kana, n_hangul, n_cjk = len(_KANA.findall(text)), len(_HANGUL.findall(text)), len(_CJK.findall(text))
    n_cyr, n_greek, n_lat = len(_CYR.findall(text)), len(_GREEK.findall(text)), len(_LATIN.findall(text))
    counts = {"cjk": n_kana + n_hangul + n_cjk, "cyrillic": n_cyr, "greek": n_greek, "latin": n_lat}
    script = max(counts, key=lambda k: counts[k])
    if counts[script] < 20:
        return "und", 0.0
    if script == "cjk":
        if n_kana > 0.05 * counts["cjk"]:
            return "ja", 1.0
        if n_hangul > 0.3 * counts["cjk"]:
            return "ko", 1.0
        return "zh", 1.0
    if script == "greek" and "greek" not in _words():
        return "el", 1.0
    weights = _weights(script)
    tokens = [w.lower() for w in _WORD.findall(_despace(text))]
    score: Counter[str] = Counter({lang: 0 for lang in _words().get(script, {})})
    for t in tokens:
        for lang, wgt in weights.get(t, {}).items():  # 多语共有词按 1/n 分摊，防 OCR 碎片误判
            score[lang] += wgt  # type: ignore[assignment]
    ranked = score.most_common(2)
    if not ranked or ranked[0][1] < min_hits:
        return "und", 0.0
    top, s1 = ranked[0]
    s2 = ranked[1][1] if len(ranked) > 1 else 0.0
    return top, round(s1 / (s1 + s2), 3) if s1 + s2 else 0.0


def _sample_pages(n_pages: int, k: int) -> list[int]:
    if n_pages <= k:
        return list(range(1, n_pages + 1))
    step = n_pages / k
    return sorted({int(1 + i * step + step / 2) for i in range(k)})


def _pdf_pages(pdf: Path) -> int:
    out = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True).stdout
    m = re.search(r"^Pages:\s+(\d+)", out, re.M)
    return int(m.group(1)) if m else 0


def page_text(pdf: Path, page: int, min_chars: int = 200, ocr: bool = True) -> tuple[str, str]:
    """返回 (文本, 来源 text_layer|ocr|none)。"""
    t = subprocess.run(["pdftotext", "-f", str(page), "-l", str(page), str(pdf), "-"],
                       capture_output=True, text=True).stdout
    if len(t.strip()) >= min_chars or not ocr or not shutil.which("tesseract"):
        return t, "text_layer" if t.strip() else "none"
    with tempfile.TemporaryDirectory() as d:
        base = Path(d) / "p"
        subprocess.run(["pdftoppm", "-r", "150", "-gray", "-f", str(page), "-l", str(page), "-png", "-singlefile",
                        str(pdf), str(base)], capture_output=True)
        img = base.with_suffix(".png")
        if not img.exists():
            return t, "none"
        o = subprocess.run(["tesseract", str(img), "-", "-l", _tess_model(img), "--psm", "3"],
                           capture_output=True, text=True)
        return o.stdout, "ocr"


# Tesseract OSD 的 Script 名 → 识别模型。只为判语言：拉丁文字用 eng 即可读出功能词（变音丢失不影响），
# 一个模型比 11 个语种合用快约 10 倍。
_SCRIPT_MODEL = {"Latin": "eng", "Cyrillic": "rus", "Han": "chi_sim", "Japanese": "jpn", "Katakana": "jpn",
                 "Hiragana": "jpn", "Hangul": "kor", "Greek": "ell"}


def _tess_model(img: Path) -> str:
    have = set(subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True).stdout.split())
    o = subprocess.run(["tesseract", str(img), "-", "--psm", "0"], capture_output=True, text=True)
    m = re.search(r"^Script:\s*(\w+)", o.stdout, re.M)
    c = re.search(r"^Script confidence:\s*([\d.]+)", o.stdout, re.M)
    # OSD 置信度低时常误判（Ceratonereis 1985 p.6 德文判成 Cyrillic，置信 0.35）→ 按拉丁文字处理
    sure = c is not None and float(c.group(1)) >= 2.0
    model = _SCRIPT_MODEL.get(m.group(1), "eng") if (m is not None and sure) else "eng"
    return model if model in have else "eng"


def detect_pdf(pdf: Path, k: int = 8, ocr: bool = True) -> dict:
    """全书语言：抽 k 页逐页判，主语言 = 页数最多者；返回各页结果与比例。"""
    n = _pdf_pages(pdf)
    per = []
    for p in _sample_pages(n, k):
        txt, src = page_text(pdf, p, ocr=ocr)
        lang, conf = detect_text(txt)
        per.append({"page": p, "lang": lang, "conf": conf, "source": src, "chars": len(txt.strip())})
    votes = Counter(r["lang"] for r in per if r["lang"] != "und")
    main = votes.most_common(1)[0][0] if votes else "und"
    share = {lang: round(c / len(per), 2) for lang, c in votes.most_common()} if per else {}
    return {"path": str(pdf), "pages": n, "lang": main, "share": share, "sampled": per}
