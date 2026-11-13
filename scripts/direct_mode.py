"""run_batches.py 的直调模式：不经智能体，把原文切块后直接调 llm_engines 初译或核译。

流程（每章一个目录 <书>/核译/direct/<章>/，已有产物一律跳过，可断点续跑）：
  chunks/cNN.txt   原文块（约 9000 字符，在句末断开）
  terms/cNN.md     该块的 yiku 术语表（yiku table <块> --domain D [--scope 科名]）
  out/cNN.md       初译输出（含末尾「### 待定术语」「### 术语决策」节）
  decisions/cNN.jsonl  从 out 里解析出的术语决策（一行一个 JSON；格式不对的行存 cNN.invalid.txt）
  review/cNN.jsonl 核译问题单（解析通过才写；空文件 = 模型显式输出了 NO_ISSUES）
合并：<书>/译文/<章>_直译初译.md（已存在则不覆盖）、待定术语汇总 pending_terms.tsv、
      术语决策 <章>/term_decisions.jsonl 与全书汇总 <书>/核译/term_decisions.jsonl（yiku decide validate/review/apply）、
      问题单 <书>/核译/issues/<章>_direct.jsonl（old 在合并译文中恰好出现 1 次才收，其余进 rejected.jsonl）。
问题单交给 apply_issues.py --dry 过闸口，本模块不改译文。
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

PENDING_HEAD = "### 待定术语"
DECISION_HEAD = "### 术语决策"
DECISIONS_FILE = "term_decisions.jsonl"
MERGED_SUFFIX = "_直译初译.md"
MIN_ZH_RATIO = 0.05  # 汉字数/原文字符数低于此值视为疑似拒译或截断

Caller = Callable[..., tuple[str, dict[str, Any]]]


# ---------------------------------------------------------------- 技能文件

def skill_dir() -> Path:
    """RULES.md 等所在目录：技能目录副本里在 scripts/ 的上一级，仓库里在 skill/。"""
    root = Path(__file__).resolve().parent.parent
    return root if (root / "RULES.md").exists() else root / "skill"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf8")


def output_requirements(prompts_md: str) -> str:
    """取 PROMPTS.md 的「核译输出要求」一节（到下一个二级标题为止）。"""
    i = prompts_md.index("### 核译输出要求")
    j = prompts_md.find("\n## ", i)
    return prompts_md[i:j if j != -1 else len(prompts_md)].strip()


def build_system(mode: str, domain: str, book_desc: str = "", notes: str = "", skill: Path | None = None) -> str:
    """初译：用途说明 + 角色 + RULES + 领域包 + STYLE + 输出要求。核译：用途说明 + 角色 + RULES + 领域包 + 核译输出要求。

    开头的「用途说明」必须保留：缺了它，部分模型会以版权为由拒译。"""
    sk = skill or skill_dir()
    rules = _read(sk / "RULES.md")
    dom = _read(sk / "domains" / f"{domain}.md")
    desc = book_desc or "（一本专业书的一部分）"
    if mode == "translate":
        head = (f"用途说明：用户是{domain}研究者，拥有本书，此译稿仅供其个人学习研究、不公开发布。"
                "请完整逐句翻译，不要摘要或删节。\n\n"
                f"你是专业科学翻译。把用户给出的英文原文{desc}译成中文学术译文，严格遵守以下规范。")
        parts = [head, rules, dom, _read(sk / "STYLE.md"), TRANSLATE_OUTPUT]
    elif mode == "review":
        head = (f"用途说明：用户是{domain}研究者，拥有本书，此核译仅供其个人学习研究、不公开发布。\n\n"
                f"你是{domain}专著的独立核译员（与初译者不同的模型）。逐句对照英文原文{desc}核对中文译文，"
                "只报问题，不重写译文。")
        parts = [head, rules, dom, output_requirements(_read(sk / "PROMPTS.md")), REVIEW_OUTPUT]
    else:
        raise ValueError(f"mode 只能是 translate 或 review：{mode}")
    if notes.strip():
        parts.append("## 本书补充说明\n" + notes.strip())
    return "\n\n".join(p.strip() for p in parts) + "\n"


TRANSLATE_OUTPUT = """## 本次输出要求
- 只输出译文（Markdown），不要说明、前言或结语。本块可能从某节中间开始或在某节中间结束，照原样接续，不要补写或总结。
- 原文中独占一行的节标题用 ### 或 ####；段首的引导词（如 "Digestive system."）译为加粗引导词，如 **消化系统。**
- 若正文中混入页眉页码或孤立碎片，删去不译。正文中对图、表的引用照常翻译。
- 术语表分 HARD 与 SOFT 两节。HARD 必用，不得改译。SOFT 先读「定义/出处语境」判断本块里的义项，再取舍或另译；「已核」不等于必用，〔回退〕译名只在义项吻合时参考。拿不准的译名或词源上另有更贴切译法时，正文用通行名并加〔译注：…〕。
- 不写文件、不调用工具。译文之后依次另起两节，没有内容的节省略：
  1. 「### 待定术语」逐行列：English｜所用译法｜理由。
  2. 「### 术语决策」：对本块出现的每个 SOFT 术语，写一行 JSON（不加代码围栏，不加说明）：
     {"en":"cirrus","zh":"须","sense":"沙蚕疣足背须（形态）","reason":"本块指疣足背须，不是阴茎","source":"杨德渐2006 p.0168","chunk":"（填用户消息里的本块编号）"}
     en＝英文术语；zh＝本块实际所用译名；sense＝义项简述；reason＝取舍理由；source＝所依据的术语表来源及页码，没有依据就写空串，不要编造；
     同一术语在本块有不同义项时，各写一行。HARD 术语不用写。"""

NO_ISSUES = "NO_ISSUES"

REVIEW_OUTPUT = f"""## 本次输出
只输出 JSONL，每行一个问题对象（必须含 old、new 字段），不要任何其他文字（不要代码围栏）。file 字段填给定的文件名。\
old 必须逐字复制自译文，且在给出的译文块中只出现 1 次。
核完确实没有问题时，整个输出只写一行 {NO_ISSUES}（不要输出空内容：空输出会被当作失败重跑）。"""


def user_translate(table: str, chunk: str, tag: str = "") -> str:
    tag_line = f"本块编号：{tag}\n\n" if tag else ""
    return f"本块术语表（来自 yiku）：\n{table}\n\n{tag_line}请翻译以下英文原文：\n\n{chunk}"


def user_review(fname: str, table: str, src_chunk: str, zh_chunk: str) -> str:
    return (f"file: {fname}\n\n本块术语表：\n{table}\n\n=== 英文原文 ===\n{src_chunk}\n\n=== 中文译文 ===\n{zh_chunk}")


# ---------------------------------------------------------------- 切块

_ABBR = re.compile(r"(?:\b(?:[A-Za-z]|e\.g|i\.e|sp|spp|cf|fig|figs|vs|al|etc|no|nos|ca|ed|eds|vol|pp|p)\.)$", re.I)
_SENT_END = re.compile(r"[.!?][\"”’')\]]*(?=\s)")


def _sentence_cuts(window: str, lo: int) -> list[int]:
    cuts = []
    for m in _SENT_END.finditer(window):
        if m.end() < lo:
            continue
        before = window[max(0, m.start() - 8):m.start() + 1]
        if _ABBR.search(before):
            continue
        cuts.append(m.end())
    return cuts


def _ends_sentence(before: str) -> bool:
    """空行前的文字是否以句末标点收尾。PDF 抽取的空行常出现在句子中间（图注、换页），不能一律当段落边界。"""
    tail = before.rstrip()[-12:]
    return bool(re.search(r"[.!?][\"”’')\]]*$", tail)) and not _ABBR.search(tail.rstrip("\"”’')]"))


def _find_cut(rest: str, limit: int) -> int:
    window = rest[:limit]
    lo = int(limit * 0.6)
    paras = [m.end() for m in re.finditer(r"\n[ \t]*\n", window) if m.end() >= lo and _ends_sentence(window[:m.start()])]
    if paras:
        return paras[-1]
    sents = _sentence_cuts(window, lo)
    if sents:
        return sents[-1]
    ws = [m.start() for m in re.finditer(r"\s", window) if m.start() >= lo]
    return ws[-1] if ws else limit


def split_chunks(text: str, limit: int = 9000) -> list[str]:
    """按段落切块，每块约 limit 字符：优先在空行处断开，其次在句末（跳过 sp.、Fig.、O.F. 等缩写），
    再不行在空白处断开。末尾不足 min(1000, limit/5) 字符的零头并入前一块。"""
    rest = text.replace("\r\n", "\n").strip()
    chunks: list[str] = []
    while len(rest) > limit:
        cut = _find_cut(rest, limit)
        chunks.append(rest[:cut].strip())
        rest = rest[cut:].strip()
    if rest:
        if chunks and len(rest) < min(1000, limit // 5):
            chunks[-1] = chunks[-1] + "\n" + rest
        else:
            chunks.append(rest)
    return chunks


# ---------------------------------------------------------------- 术语表

def detect_scope(text: str) -> str:
    """类群取原文前 5 行里的 -idae/-ida 名（与 run_batches.term_table 同一规则）。"""
    head = " ".join(text.splitlines()[:5])
    return ";".join(sorted({w.capitalize() for w in re.findall(r"\b([A-Za-z]+(?:idae|ida))\b", head)}))


def yiku_table(chunk_file: Path, domain: str, scope: str = "", fallback: str | None = None,
               no_usage: bool = False, env: dict[str, str] | None = None) -> str:
    """fallback：yiku 的 --fallback（回退领域）；None 用 yiku 默认（分类学回退到进化生物学）。
    no_usage：加 --no-usage（不取资料库用例）；env：子进程环境（如 YIKU_DB 指向过滤后的库）。"""
    cmd = (["yiku", "table", str(chunk_file), "--domain", domain] + (["--scope", scope] if scope else [])
           + (["--fallback", fallback] if fallback else []) + (["--no-usage"] if no_usage else []))
    r = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if r.returncode != 0:
        raise RuntimeError(f"yiku table 失败（没有术语表不开跑）：{r.stderr.strip()[:200]}")
    return r.stdout


# ---------------------------------------------------------------- 输出整理

_FENCE = re.compile(r"^```[A-Za-z]*$")


def split_sections(zh: str) -> tuple[str, list[str], list[str]]:
    """把模型输出拆成 (正文, 待定术语行, 术语决策行)。两节在译文之后，顺序不限；每节到下一个节标题或文末为止。"""
    marks = sorted((i, h) for h in (PENDING_HEAD, DECISION_HEAD) if (i := zh.find(h)) != -1)
    if not marks:
        return zh.strip(), [], []
    sections: dict[str, list[str]] = {PENDING_HEAD: [], DECISION_HEAD: []}
    for k, (i, h) in enumerate(marks):
        j = marks[k + 1][0] if k + 1 < len(marks) else len(zh)
        sections[h] = [ln.strip() for ln in zh[i + len(h):j].splitlines() if ln.strip()]
    pending = [ln.lstrip("-*• ").strip() for ln in sections[PENDING_HEAD]]
    return zh[:marks[0][0]].strip(), [ln for ln in pending if ln], sections[DECISION_HEAD]


def strip_pending(zh: str) -> tuple[str, list[str]]:
    """去掉末尾「### 待定术语」「### 术语决策」两节，返回 (正文, 待定术语行)。"""
    body, pending, _ = split_sections(zh)
    return body, pending


def parse_decisions(lines: list[str], tag: str) -> tuple[list[dict[str, Any]], list[str]]:
    """宽松解析术语决策行：围栏标记行忽略；是 JSON 对象且 en、zh 都是非空字符串的收下，chunk 一律改写为本块编号
    （脚本比模型更清楚是哪一块）；其余行原样返回作为无效行。字段是否齐全由 yiku decide validate 严格检查。"""
    ok: list[dict[str, Any]] = []
    bad: list[str] = []
    for ln in lines:
        if _FENCE.match(ln):
            continue
        try:
            obj = json.loads(ln)
        except json.JSONDecodeError:
            bad.append(ln)
            continue
        if isinstance(obj, dict) and all(isinstance(obj.get(k), str) and obj[k].strip() for k in ("en", "zh")):
            ok.append({**obj, "chunk": tag})
        else:
            bad.append(ln)
    return ok, bad


class ReviewParseError(ValueError):
    """核译输出不是合法的 JSONL 问题单（也不是 NO_ISSUES）。"""


def parse_review(text: str) -> list[dict[str, Any]]:
    """严格解析核译输出。合法形态只有两种：
      1. 每个非空行都是 JSON 对象，且 old、new 都是字符串、old 非空（围栏标记行 ``` 忽略，围栏里的内容照常解析）
      2. 只有一行 NO_ISSUES（显式声明没有问题，返回空列表）
    其余一律抛 ReviewParseError：空输出、说明文字、坏 JSON、缺 old/new、JSON 数组、NO_ISSUES 与问题混写。
    不再静默丢弃任何行：丢掉的行可能就是漏报的问题。"""
    lines = [(n, ln.strip()) for n, ln in enumerate(text.splitlines(), 1) if ln.strip()]
    lines = [(n, ln) for n, ln in lines if not _FENCE.match(ln)]
    if not lines:
        raise ReviewParseError(f"输出为空；没有问题时应输出 {NO_ISSUES}")
    if any(ln == NO_ISSUES for _n, ln in lines):
        if len(lines) > 1:
            raise ReviewParseError(f"{NO_ISSUES} 与其他内容混写（第 {lines[0][0]} 行起）")
        return []
    items: list[dict[str, Any]] = []
    for n, ln in lines:
        try:
            obj = json.loads(ln)
        except json.JSONDecodeError as exc:
            raise ReviewParseError(f"第 {n} 行不是合法 JSON：{ln[:60]!r}（{exc.msg}）") from exc
        if not isinstance(obj, dict):
            raise ReviewParseError(f"第 {n} 行不是 JSON 对象：{ln[:60]!r}")
        if not isinstance(obj.get("old"), str) or not obj["old"] or not isinstance(obj.get("new"), str):
            raise ReviewParseError(f"第 {n} 行缺 old/new（或 old 为空）：{ln[:60]!r}")
        items.append(obj)
    return items


def parse_jsonl(text: str) -> list[dict[str, Any]]:
    """宽松读取已落盘的问题单（run_review 只写过 parse_review 验证过的行）；模型的原始输出一律用 parse_review。"""
    out = []
    for ln in text.splitlines():
        ln = ln.strip()
        if ln.startswith("{"):
            try:
                obj = json.loads(ln)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and "old" in obj and "new" in obj:
                out.append(obj)
    return out


def zh_ratio(zh: str, src: str) -> float:
    return len(re.findall(r"[一-鿿]", zh)) / max(len(src), 1)


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(text, encoding="utf8")
    tmp.replace(p)


# ---------------------------------------------------------------- 每章工作目录

class Chapter:
    def __init__(self, book: Path, name: str, limit: int = 9000):
        self.book, self.name, self.limit = book, name, limit
        self.dir = book / "核译" / "direct" / name
        self.merged = book / "译文" / f"{name}{MERGED_SUFFIX}"
        self.issues = book / "核译" / "issues" / f"{name}_direct.jsonl"

    @property
    def source(self) -> Path:
        p = self.book / "src_en" / self.name
        return p if p.suffix == ".txt" else p.with_suffix(".txt")

    def prepare(self, domain: str, scope: str | None,
                table_fn: Callable[[Path, str, str], str] | None = None, fallback: str | None = None) -> list[str]:
        """切块并生成每块术语表；已有则复用。原文或块长变了就报错，避免新旧块混用。
        fallback：传给 yiku table --fallback 的回退领域（None＝yiku 默认）。"""
        if table_fn is None:
            table_fn = yiku_table if fallback is None else (lambda f, d, s: yiku_table(f, d, s, fallback))
        if not self.source.exists():
            raise FileNotFoundError(f"找不到原文 {self.source}")
        text = _read(self.source).replace("\r\n", "\n")
        sha = hashlib.sha1(text.encode("utf8")).hexdigest()[:12]
        manifest = self.dir / "chunks.json"
        if manifest.exists():
            old = json.loads(_read(manifest))
            if old.get("sha1") != sha or old.get("limit") != self.limit:
                raise RuntimeError(f"{self.name}：原文或块长已变，请先删除 {self.dir} 再重来")
        chunks = split_chunks(text, self.limit)
        sc = detect_scope(text) if scope is None else scope
        for i, c in enumerate(chunks):
            cp = self.dir / "chunks" / f"c{i:02d}.txt"
            tp = self.dir / "terms" / f"c{i:02d}.md"
            if not cp.exists():
                _write(cp, c + "\n")
            if not tp.exists():
                _write(tp, table_fn(cp, domain, sc))
        _write(manifest, json.dumps({"sha1": sha, "limit": self.limit, "n": len(chunks), "scope": sc}, ensure_ascii=False))
        return [f"c{i:02d}" for i in range(len(chunks))]

    def chunk_ids(self) -> list[str]:
        return sorted(p.stem for p in (self.dir / "chunks").glob("c*.txt"))

    def path(self, kind: str, cid: str, ext: str) -> Path:
        return self.dir / kind / f"{cid}.{ext}"

    def text(self, kind: str, cid: str, ext: str) -> str:
        return _read(self.path(kind, cid, ext))


# ---------------------------------------------------------------- 初译与核译

class StaleOutputError(RuntimeError):
    """已有产物不是用当前的引擎/系统提示词/术语表/译文生成的，续跑会混用不同来源的块。"""


def _digest(*parts: str) -> str:
    return hashlib.sha256("\x00".join(parts).encode("utf8")).hexdigest()


def _write_meta(ch: Chapter, kind: str, cid: str, engine: str, system: str, terms: str, extra: str = "") -> None:
    """每块产物旁写 cNN.meta.json：引擎，以及系统提示词 + 术语表（核译另加所核译文）的 sha256。"""
    meta = {"engine": engine, "system_sha256": _digest(system), "terms_sha256": _digest(terms),
            "input_sha256": _digest(extra), "sha256": _digest(system, terms, extra),
            "time": time.strftime("%Y-%m-%d %H:%M:%S")}
    _write(ch.path(kind, cid, "meta.json"), json.dumps(meta, ensure_ascii=False, indent=1) + "\n")


def _stale_reason(ch: Chapter, kind: str, cid: str, engine: str, system: str, terms: str, extra: str = "") -> str:
    """已有产物与当前设置一致返回空串，否则返回原因。没有 meta 的老产物无法确认来源，也算不一致。"""
    mp = ch.path(kind, cid, "meta.json")
    if not mp.exists():
        return "缺 meta.json，无法确认来源"
    try:
        meta = json.loads(_read(mp))
    except json.JSONDecodeError:
        return "meta.json 损坏"
    why = []
    if meta.get("engine") != engine:
        why.append(f"引擎 {meta.get('engine')} -> {engine}")
    if meta.get("system_sha256") != _digest(system):
        why.append("系统提示词变了")
    if meta.get("terms_sha256") != _digest(terms):
        why.append("术语表变了")
    if meta.get("input_sha256") != _digest(extra):
        why.append("所核译文变了")
    return "；".join(why)


def _check_resume(ch: Chapter, kind: str, ext: str, ids: list[str], reasons: dict[str, str], force: bool) -> None:
    """reasons：已有产物的块 -> 不一致原因（一致的不在其中）。无 force 就报错；有 force 就删掉这些块的产物（及下游核译产物）。"""
    if not reasons:
        return
    if not force:
        shown = "；".join(f"{c}：{r}" for c, r in list(reasons.items())[:5])
        more = f" 等共 {len(reasons)} 块" if len(reasons) > 5 else ""
        raise StaleOutputError(
            f"{ch.name}：{kind} 已有产物与当前设置不一致（{shown}{more}）。续跑会混用不同来源的块；"
            "确要重做这些块请加 --force（会删除它们的已有产物，初译重做时一并删除对应的核译产物）")
    for c in reasons:
        for k, e in ((kind, ext), (kind, "meta.json"), (kind, "suspect.md")) + ((("review", "jsonl"), ("review", "meta.json"), ("decisions", "jsonl"), ("decisions", "invalid.txt")) if kind == "out" else ()):
            ch.path(k, c, e).unlink(missing_ok=True)


def _save_decisions(ch: Chapter, cid: str, text: str) -> list[dict[str, Any]]:
    """解析该块输出里的「### 术语决策」，存 decisions/cNN.jsonl；格式不对的行存 cNN.invalid.txt。"""
    ok, bad = parse_decisions(split_sections(text)[2], f"{ch.name}/{cid}")
    _write(ch.path("decisions", cid, "jsonl"), "".join(json.dumps(d, ensure_ascii=False) + "\n" for d in ok))
    inv = ch.path("decisions", cid, "invalid.txt")
    if bad:
        _write(inv, "\n".join(bad) + "\n")
    else:
        inv.unlink(missing_ok=True)
    return ok


def run_translate(ch: Chapter, ids: list[str], engine: str, system: str, caller: Caller, jobs: int = 1,
                  usage_file: Path | None = None, force: bool = False) -> tuple[int, int, list[str]]:
    """返回 (新译块数, 跳过块数, 失败说明列表)。疑似拒译（汉字太少）的输出存为 .suspect.md，不算完成。
    已有产物须与当前引擎、系统提示词、术语表一致才跳过；不一致报 StaleOutputError，force=True 才重做。"""
    done = skipped = 0
    fails: list[str] = []

    def one(cid: str) -> str | None:
        src = ch.text("chunks", cid, "txt")
        terms = ch.text("terms", cid, "md")
        text, _ = caller(engine, system, user_translate(terms, src, f"{ch.name}/{cid}"), tag=f"{ch.name}/{cid}",
                         usage_file=usage_file)
        body = strip_pending(text)[0]
        if len(src) > 500 and zh_ratio(body, src) < MIN_ZH_RATIO:
            _write(ch.path("out", cid, "suspect.md"), text)
            return f"{cid} 疑似拒译或截断（汉字/原文字符 {zh_ratio(body, src):.3f}），已存 {cid}.suspect.md"
        _write(ch.path("out", cid, "md"), text)
        _save_decisions(ch, cid, text)
        _write_meta(ch, "out", cid, engine, system, terms)
        return None

    def finished(c: str) -> bool:
        p = ch.path("out", c, "md")
        return p.exists() and p.stat().st_size > 0

    reasons = {c: r for c in ids if finished(c) and (r := _stale_reason(ch, "out", c, engine, system, ch.text("terms", c, "md")))}
    _check_resume(ch, "out", "md", ids, reasons, force)
    todo = [c for c in ids if not finished(c)]
    skipped = len(ids) - len(todo)
    with ThreadPoolExecutor(max(jobs, 1)) as ex:
        futs = {c: ex.submit(one, c) for c in todo}
        for c, f in futs.items():
            try:
                err = f.result()
            except Exception as exc:  # noqa: BLE001 - 单块失败不拖垮整章，记下后继续
                err = f"{c} 失败：{exc}"
            if err:
                fails.append(err)
            else:
                done += 1
    return done, skipped, fails


def run_review(ch: Chapter, ids: list[str], engine: str, system: str, caller: Caller, jobs: int = 1,
               usage_file: Path | None = None, force: bool = False) -> tuple[int, int, list[str]]:
    """核译。已有核译产物须与当前引擎、系统提示词、术语表、所核译文一致才跳过（译文重做后旧核译作废）。"""
    done = skipped = 0
    fails: list[str] = []
    fname = ch.merged.name

    def zh_of(cid: str) -> str:
        return strip_pending(ch.text("out", cid, "md"))[0]

    def one(cid: str) -> str | None:
        zh, terms = zh_of(cid), ch.text("terms", cid, "md")
        user = user_review(fname, terms, ch.text("chunks", cid, "txt"), zh)
        text, _ = caller(engine, system, user, tag=f"{ch.name}/{cid}/review", usage_file=usage_file)
        items = parse_review(text)  # 解析失败抛错：该块记为失败，不写完成文件，下次续跑会重核
        _write(ch.path("review", cid, "jsonl"), "".join(json.dumps(i, ensure_ascii=False) + "\n" for i in items))
        _write_meta(ch, "review", cid, engine, system, terms, zh)
        return None

    have_out = [c for c in ids if ch.path("out", c, "md").exists()]
    reasons = {c: r for c in have_out if ch.path("review", c, "jsonl").exists()
               and (r := _stale_reason(ch, "review", c, engine, system, ch.text("terms", c, "md"), zh_of(c)))}
    _check_resume(ch, "review", "jsonl", ids, reasons, force)
    todo = []
    for c in ids:
        if c not in have_out:
            fails.append(f"{c} 没有初译输出，先跑 translate")
        elif ch.path("review", c, "jsonl").exists():
            skipped += 1
        else:
            todo.append(c)
    with ThreadPoolExecutor(max(jobs, 1)) as ex:
        futs = {c: ex.submit(one, c) for c in todo}
        for c, f in futs.items():
            try:
                f.result()
                done += 1
            except Exception as exc:  # noqa: BLE001
                fails.append(f"{c} 失败：{exc}")
    return done, skipped, fails


# ---------------------------------------------------------------- 合并

def merge_translation(ch: Chapter, ids: list[str]) -> str:
    """合并各块译文并汇总待定术语。返回状态说明。译文文件已存在时不覆盖。"""
    missing = [c for c in ids if not ch.path("out", c, "md").exists()]
    if missing:
        return f"未合并：缺 {','.join(missing)}"
    bodies: list[str] = []
    pending: dict[str, list[str]] = {}
    for c in ids:
        body, lines = strip_pending(ch.text("out", c, "md"))
        bodies.append(body)
        for ln in lines:
            cells = [x.strip() for x in re.split(r"[｜|]", ln)]
            pending.setdefault(cells[0].lower(), cells)
    if pending:
        rows = ["English\t所用译法\t理由"] + ["\t".join((c + ["", ""])[:3]) for c in pending.values()]
        _write(ch.dir / "pending_terms.tsv", "\n".join(rows) + "\n")
    ndec = merge_decisions(ch, ids)
    if ch.merged.exists():
        return f"已存在 {ch.merged.name}，不覆盖（删除后可重新合并）；待定术语 {len(pending)} 条；术语决策 {ndec} 条"
    _write(ch.merged, "\n\n".join(bodies) + "\n")
    return f"已合并 {len(ids)} 块 -> {ch.merged}；待定术语 {len(pending)} 条；术语决策 {ndec} 条"


def merge_decisions(ch: Chapter, ids: list[str]) -> int:
    """合并各块术语决策 -> <章>/term_decisions.jsonl，并重写全书汇总 <书>/核译/term_decisions.jsonl。返回本章条数。
    优先读 decisions/cNN.jsonl；没有（旧产物）就从 out/cNN.md 现解析。"""
    rows: list[str] = []
    for c in ids:
        p = ch.path("decisions", c, "jsonl")
        if p.exists():
            rows.extend(ln for ln in _read(p).splitlines() if ln.strip())
        elif ch.path("out", c, "md").exists():
            ok, _bad = parse_decisions(split_sections(ch.text("out", c, "md"))[2], f"{ch.name}/{c}")
            rows.extend(json.dumps(d, ensure_ascii=False) for d in ok)
    rows = list(dict.fromkeys(rows))
    _write(ch.dir / DECISIONS_FILE, "".join(r + "\n" for r in rows))
    book_rows: list[str] = []
    for f in sorted((ch.book / "核译" / "direct").glob(f"*/{DECISIONS_FILE}")):
        book_rows.extend(ln for ln in _read(f).splitlines() if ln.strip())
    _write(ch.book / "核译" / DECISIONS_FILE, "".join(r + "\n" for r in dict.fromkeys(book_rows)))
    return len(rows)


def merge_review(ch: Chapter, ids: list[str]) -> tuple[int, int]:
    """合并各块问题单，写 核译/issues/<章>_direct.jsonl；old 在合并译文中不是恰好 1 次的进 rejected.jsonl。"""
    if ch.merged.exists():
        target = _read(ch.merged)
    else:
        target = "\n\n".join(strip_pending(ch.text("out", c, "md"))[0] for c in ids)
    ok: list[dict[str, Any]] = []
    bad: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for c in ids:
        p = ch.path("review", c, "jsonl")
        if not p.exists():
            continue
        for it in parse_jsonl(_read(p)):
            it = {**it, "file": ch.merged.name, "chunk": c}
            key = (str(it["old"]), str(it["new"]))
            if key in seen:
                continue
            seen.add(key)
            n = target.count(str(it["old"]))
            if it["old"] == it["new"]:
                bad.append({**it, "reject": "新旧相同"})
            elif n != 1:
                bad.append({**it, "reject": f"old 在合并译文中出现 {n} 次"})
            else:
                ok.append(it)
    _write(ch.issues, "".join(json.dumps(i, ensure_ascii=False) + "\n" for i in ok))
    _write(ch.dir / "rejected.jsonl", "".join(json.dumps(i, ensure_ascii=False) + "\n" for i in bad))
    return len(ok), len(bad)
