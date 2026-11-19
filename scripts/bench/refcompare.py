#!/usr/bin/env python3
"""参照译本对照比测：本流水线的译文 vs 名家译本（pub），或本流水线两次运行互比（compare-runs）。

配置文件 D/refcompare.json（或 .yaml），相对路径以配置文件所在目录为准：
  passages        段名列表；D/<段>_en.txt 原文，D/<段>_pub.txt 参照译本
  domain          技能领域包（domains/<domain>.md）；term_domains 是 yiku table 的领域列表（结果合并），缺省 [domain]
  book_desc, notes  写进系统提示词；skill_dir 缺省用仓库 skill/（或技能目录副本）
  engines         {"draft": "claude-sonnet", "review": "codex-sol", "judges": ["codex-sol", "cursor-grok"]}
  runs            可选，{"<run>": {"draft": ..., "review": ..., "skill_dir": ...}} 覆盖该次运行的设置
  leakage         防泄漏：yiku_db（缺省 $YIKU_DB 或 ~/.yiku/yiku.db）、exclude_sources（要排除的 yiku 来源键）、
                  exclude_note_like（note 含这些子串的术语条目也排除）、no_usage（yiku table --no-usage）、
                  exclude_docstore_keys（不开 no_usage 时，这些 docstore 键不当 KWIC 用例来源）
  hard_term_filter  核译改动若把 HARD 术语译名改掉则拒收（缺省 true）；terms_dir、seed 见 load_config

子命令（-j 并发，--force 重做与当前设置不一致的产物，--passages 只跑部分段）：
  terms CONFIG                        生成各段术语表（过滤后的 yiku 库副本 + 合并多个领域）
  draft CONFIG --run R                初译 -> R/<段>_draft.txt
  review CONFIG --run R               核译 -> R/<段>_issues.jsonl，精确替换（old 恰好出现 1 次）-> D/<段>_<R>.txt，拒收记 rejects
  judge CONFIG --run R [--against pub]  盲评 pub（或 --against 指定的版本）对 D/<段>_<R>.txt
  compare-runs CONFIG RUN_A RUN_B     同一盲评方案互比两次运行
  aggregate CONFIG PAIR [PAIR ...]    解盲，输出分数与 MQM 错误计数表（PAIR 形如 pub_vs_ours3）

已有产物旁写 .meta.json（引擎 + 系统提示词 + 用户消息的 sha256）；续跑时一致才跳过，不一致报 StaleOutputError。
所有文本只走文件；盲评每段每评委独立随机 A/B，映射存 judge/<对>/key.json。评委与核译提示词写明不得读本地文件。
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import random
import re
import sqlite3
import sys
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import direct_mode  # noqa: E402
import llm_engines  # noqa: E402
from direct_mode import Caller, StaleOutputError, _digest, _write  # noqa: E402

CATEGORIES = ("mistranslation", "omission", "addition", "terminology", "fluency_style", "register")
GATED_TYPES = ("术语", "误译", "漏译", "增译")  # 这几类改动允许删掉英文词或数字（与 apply_issues.py 闸口一致）
TOKEN = re.compile(r"[A-Za-z][A-Za-z\-]+|\d+(?:\.\d+)?")
ISOLATION = ("【隔离要求】只使用本消息里的文字：不得读取、列出、搜索或打开任何本地文件或目录（含 ~/.yiku 术语库），"
             "不得运行命令或调用工具。 Use only the text in this message; do not read local files, run commands or use tools.")

JUDGE_SYSTEM = f"""You are an expert reviewer of English-to-Chinese translation of scholarly prose. \
You will be given an English source passage and two anonymous Chinese translations, A and B. \
Judge each translation independently and strictly against the English source, then compare them.

Use an MQM-style error annotation. Error categories (use exactly these keys):
- mistranslation: meaning differs from the source (wrong sense, wrong logic or reference, wrong number or name)
- omission: source content missing
- addition: content not in the source
- terminology: wrong, inconsistent or non-standard Chinese scientific term or proper-name rendering
- fluency_style: unidiomatic, ambiguous, clumsy or hard-to-read Chinese
- register: not in the register of Chinese academic writing (too colloquial, too literal, wrong tone, overly hedged or strengthened)
Severity: "major" (changes meaning, misleads, or a clearly wrong key term) or "minor" (small, does not change meaning). \
Do not count differences in punctuation width, footnote markers or citation formatting. \
Do not penalise a translation for dropping a purely bibliographic parenthetical citation unless the sentence then loses meaning. \
Do not try to guess who or what produced either translation.

Give each translation a score from 0 to 100 (100 = publishable as is; deduct for the errors you listed). \
Name the preferred translation ("A", "B" or "tie") and give a reason of at most 80 words that cites specific terms or sentences.

{ISOLATION}

Output strict JSON only, no code fence, no text before or after, in this schema:
{{"A": {{"errors": [{{"category": "...", "severity": "major|minor", "source_span": "short English quote", \
"target_span": "short Chinese quote", "comment": "one sentence"}}], "score": 0}},
 "B": {{"errors": [], "score": 0}},
 "preferred": "A|B|tie",
 "reason": "..."}}"""


# ---------------------------------------------------------------- 配置

@dataclass
class Cfg:
    root: Path
    passages: list[str]
    domain: str
    term_domains: list[str]
    book_desc: str = ""
    notes: str = ""
    skill_dir: str | None = None
    engines: dict[str, Any] = field(default_factory=dict)
    runs: dict[str, dict[str, Any]] = field(default_factory=dict)
    leakage: dict[str, Any] = field(default_factory=dict)
    hard_term_filter: bool = True
    terms_dir: Path = Path("terms")
    seed: str = "refcompare"

    def engine(self, role: str, run: str = "") -> str:
        return str(self.runs.get(run, {}).get(role) or self.engines[role])

    def skill(self, run: str = "") -> Path:
        sd = self.runs.get(run, {}).get("skill_dir") or self.skill_dir
        return Path(sd).expanduser() if sd else direct_mode.skill_dir()

    def file(self, pid: str, version: str) -> Path:
        return self.root / f"{pid}_{version}.txt"

    def text(self, pid: str, version: str) -> str:
        p = self.file(pid, version)
        if not p.exists():
            raise FileNotFoundError(f"找不到 {p.name}（版本 {version!r} 还没生成？）")
        return p.read_text(encoding="utf8").strip()

    def run_dir(self, run: str) -> Path:
        return self.root / run

    @property
    def usage(self) -> Path:
        return self.root / "usage.tsv"


def load_config(path: str | Path) -> Cfg:
    p = Path(path)
    raw = p.read_text(encoding="utf8")
    if p.suffix in (".yaml", ".yml"):
        import yaml
        d = yaml.safe_load(raw)
    else:
        d = json.loads(raw)
    engines = {"draft": "claude-sonnet", "review": "codex-sol", "judges": ["codex-sol", "cursor-grok"], **d.get("engines", {})}
    leak = {"yiku_db": None, "exclude_sources": [], "exclude_note_like": [], "no_usage": True,
            "exclude_docstore_keys": [], **d.get("leakage", {})}
    root = p.resolve().parent
    return Cfg(root=root, passages=list(d["passages"]), domain=d["domain"],
               term_domains=list(d.get("term_domains") or [d["domain"]]), book_desc=d.get("book_desc", ""),
               notes=d.get("notes", ""), skill_dir=d.get("skill_dir"), engines=engines, runs=d.get("runs", {}),
               leakage=leak, hard_term_filter=bool(d.get("hard_term_filter", True)),
               terms_dir=root / d.get("terms_dir", "terms"), seed=str(d.get("seed", "refcompare")))


# ---------------------------------------------------------------- 术语表（防泄漏）

def filtered_db(cfg: Cfg) -> Path | None:
    """yiku 库副本：删掉 exclude_sources 来源的术语、note 含 exclude_note_like 子串的术语。无过滤且未指定库时返回 None（用默认库）。"""
    lk = cfg.leakage
    src = Path(lk["yiku_db"] or os.environ.get("YIKU_DB") or Path.home() / ".yiku" / "yiku.db").expanduser()
    srcs, likes = list(lk["exclude_sources"]), list(lk["exclude_note_like"])
    if not (srcs or likes):
        return src if lk["yiku_db"] else None
    out = cfg.terms_dir / "yiku_filtered.db"
    side = out.with_suffix(".json")
    st = src.resolve().stat()
    spec = {"src": str(src.resolve()), "size": st.st_size, "mtime_ns": st.st_mtime_ns, "sources": srcs, "note_like": likes}
    if out.exists() and side.exists() and json.loads(side.read_text(encoding="utf8")).get("spec") == spec:
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    s, d = sqlite3.connect(f"file:{src.resolve()}?mode=ro", uri=True), sqlite3.connect(out)
    s.backup(d)
    s.close()
    removed = 0
    if srcs:
        qs = ",".join("?" * len(srcs))
        removed += d.execute(f"DELETE FROM terms WHERE source IN ({qs})", srcs).rowcount
        d.execute(f"DELETE FROM sources WHERE key IN ({qs})", srcs)
    for x in likes:
        removed += d.execute("DELETE FROM terms WHERE instr(coalesce(note,''), ?) > 0", [x]).rowcount
    d.commit()
    d.close()
    side.write_text(json.dumps({"spec": spec, "removed_terms": removed}, ensure_ascii=False, indent=1), encoding="utf8")
    print(f"yiku 过滤库 {out.name}：删除 {removed} 条术语")
    return out


def _split_table(txt: str) -> tuple[list[str], list[str], list[str]]:
    head: list[str] = []
    hard: list[str] = []
    soft: list[str] = []
    cur = ""
    for ln in txt.splitlines():
        if ln.startswith("## HARD"):
            cur = "h"
        elif ln.startswith("## SOFT"):
            cur = "s"
        elif not cur:
            head.append(ln)
        else:
            (hard if cur == "h" else soft).append(ln)
    return head, hard, soft


def _rows(lines: list[str]) -> list[str]:
    return [x for x in lines if x.startswith("|") and not x.startswith("|---") and not x.startswith("| 英文") and "（无）" not in x]


def _hdr(lines: list[str]) -> list[str]:
    return [x for x in lines if x.startswith("| 英文") or x.startswith("|---")]


def _en(row: str) -> str:
    return row.split("|")[1].strip().lower()


def merge_tables(tables: list[str], domains: list[str]) -> str:
    """多个领域的 yiku 术语表合并：以第一个领域为主，其余领域只补主表里没有的英文条目（英文长度 > 2）。"""
    if len(tables) == 1:
        return tables[0]
    head, hard, soft = _split_table(tables[0])
    seen = {_en(r) for r in _rows(hard) + _rows(soft)}
    xh: list[str] = []
    xs: list[str] = []
    for t in tables[1:]:
        _, h, s = _split_table(t)
        for rows, extra in ((_rows(h), xh), (_rows(s), xs)):
            for r in rows:
                if _en(r) not in seen and len(_en(r)) > 2:
                    extra.append(r)
    first = head[0].split("；", 1)
    top = f"领域：{' + '.join(domains)}（合并）；" + (first[1] if len(first) > 1 else "")
    out = [top, *head[1:], "", "## HARD（必用）", *_hdr(hard), *_rows(hard), *xh,
           "", "## SOFT（先判义项，再取舍）", *_hdr(soft), *_rows(soft), *xs]
    return "\n".join(out) + "\n"


def build_terms(cfg: Cfg, passages: list[str] | None = None, table_fn: Callable[[Path, str], str] | None = None) -> list[Path]:
    """每段生成 terms_dir/<段>.md；已有则跳过（删掉重做）。table_fn(原文文件, 领域) 默认调 yiku table。"""
    out = []
    for pid in passages or cfg.passages:
        dest = cfg.terms_dir / f"{pid}.md"
        if not dest.exists():
            if table_fn is None:  # 真要调 yiku 时才建过滤库
                table_fn = _default_table_fn(cfg)
            src = cfg.root / f"{pid}_en.txt"
            _write(dest, merge_tables([table_fn(src, d) for d in cfg.term_domains], cfg.term_domains))
        out.append(dest)
    return out


def _default_table_fn(cfg: Cfg) -> Callable[[Path, str], str]:
    db = filtered_db(cfg)
    env = dict(os.environ)
    if db:
        env["YIKU_DB"] = str(db)
    if cfg.leakage["exclude_docstore_keys"]:
        env["YIKU_USAGE_EXCLUDE_KEYS"] = ",".join(cfg.leakage["exclude_docstore_keys"])
    return partial(_yiku, no_usage=bool(cfg.leakage["no_usage"]), env=env)


def _yiku(src: Path, domain: str, no_usage: bool, env: dict[str, str]) -> str:
    return direct_mode.yiku_table(src, domain, no_usage=no_usage, env=env)


def hard_terms(terms_md: str) -> list[str]:
    """HARD 节每行译名列的第一个译名。"""
    zh: list[str] = []
    for r in _rows(_split_table(terms_md)[1]):
        cells = [c.strip() for c in r.strip("|").split("|")]
        if len(cells) >= 2 and (z := re.split(r"[、，；;/]", cells[1])[0].strip()):
            zh.append(z)
    return zh


# ---------------------------------------------------------------- 带续跑检查的模型调用

def _meta_reason(meta: Path, engine: str, system: str, user: str) -> str:
    if not meta.exists():
        return "缺 meta.json，无法确认来源"
    try:
        m = json.loads(meta.read_text(encoding="utf8"))
    except json.JSONDecodeError:
        return "meta.json 损坏"
    why = [f"引擎 {m.get('engine')} -> {engine}"] * (m.get("engine") != engine)
    why += ["系统提示词变了"] * (m.get("system_sha256") != _digest(system))
    why += ["用户消息变了"] * (m.get("user_sha256") != _digest(user))
    return "；".join(why)


def run_step(raw: Path, engine: str, system: str, user: str, *, caller: Caller, tag: str, usage_file: Path,
             validate: Callable[[str], Any], force: bool = False, attempts: int = 3) -> tuple[str, bool]:
    """调一次模型并存 raw + raw.meta.json；已有且与当前设置一致就跳过。返回 (原始输出, 是否新生成)。
    validate(text) 抛 ValueError 表示输出不合格，重试至多 attempts 次；失败的输出存 <raw>.failN。"""
    meta = raw.with_name(raw.name + ".meta.json")
    if raw.exists() and raw.stat().st_size > 0:
        why = _meta_reason(meta, engine, system, user)
        if not why:
            return raw.read_text(encoding="utf8"), False
        if not force:
            raise StaleOutputError(f"{raw.name} 与当前设置不一致（{why}）；确要重做请加 --force")
    last = ""
    for k in range(attempts):
        text, _ = caller(engine, system, user, tag=f"{tag}/try{k}", usage_file=usage_file)
        try:
            validate(text)
        except ValueError as exc:
            last = str(exc)[:100]
            _write(raw.with_name(f"{raw.name}.fail{k}"), text)
            continue
        _write(raw, text)
        _write(meta, json.dumps({"engine": engine, "system_sha256": _digest(system), "user_sha256": _digest(user)}, indent=1) + "\n")
        return text, True
    raise RuntimeError(f"{tag}：{attempts} 次输出都不合格（{last}）")


def _isolate(system: str, engine: str) -> str:
    """非 Claude 引擎（codex、cursor 能读本地文件）的提示词末尾加隔离要求。"""
    return system if engine in llm_engines.CLAUDE_ENGINES else system.rstrip() + "\n\n" + ISOLATION + "\n"


def _pmap(fn: Callable[[Any], str], items: list[Any], jobs: int) -> None:
    """并发跑 fn（返回一行状态）；单项失败不拖垮其余，全部跑完后打印状态，有失败则抛 RuntimeError。"""
    def safe(x: Any) -> str:
        try:
            return fn(x)
        except Exception as exc:  # noqa: BLE001
            return f"FAILED {x}: {type(exc).__name__}: {str(exc)[:160]}"

    with ThreadPoolExecutor(max(jobs, 1)) as ex:
        lines = list(ex.map(safe, items))
    print("\n".join(lines))
    if bad := [x for x in lines if x.startswith("FAILED")]:
        raise RuntimeError(f"{len(bad)} 项失败（已完成的产物已落盘，修正后重跑会续跑）")


# ---------------------------------------------------------------- 初译、核译

def draft(cfg: Cfg, run: str, passages: list[str] | None = None, caller: Caller | None = None, jobs: int = 1,
          force: bool = False) -> None:
    caller = caller or llm_engines.call
    build_terms(cfg, passages)
    engine = cfg.engine("draft", run)
    system = _isolate(direct_mode.build_system("translate", cfg.domain, cfg.book_desc, cfg.notes, cfg.skill(run)), engine)
    rd = cfg.run_dir(run)
    _write(rd / "system_draft.md", system)   # 留底：这次运行用的系统提示词（含当时的 RULES/STYLE）

    def one(pid: str) -> str:
        en = (cfg.root / f"{pid}_en.txt").read_text(encoding="utf8").strip()
        terms = (cfg.terms_dir / f"{pid}.md").read_text(encoding="utf8")
        user = direct_mode.user_translate(terms, en)

        def ok(t: str) -> None:
            body = direct_mode.strip_pending(t)[0]
            if len(en) > 500 and direct_mode.zh_ratio(body, en) < direct_mode.MIN_ZH_RATIO:
                raise ValueError("疑似拒译或截断")

        text, fresh = run_step(rd / f"{pid}_draft_raw.md", engine, system, user, caller=caller, tag=f"{run}/{pid}/draft",
                               usage_file=cfg.usage, validate=ok, force=force)
        body, pending = direct_mode.strip_pending(text)
        _write(rd / f"{pid}_draft.txt", body + "\n")
        _write(rd / f"{pid}_pending.txt", "\n".join(pending) + "\n")
        if fresh:  # 初译重做后，旧核译与成品作废
            for suffix in ("_review_raw.txt", "_review_raw.txt.meta.json", "_issues.jsonl"):
                (rd / f"{pid}{suffix}").unlink(missing_ok=True)
            cfg.file(pid, run).unlink(missing_ok=True)
        return f"{pid} draft {'new' if fresh else 'kept'} {len(body)} chars"

    _pmap(one, passages or cfg.passages, jobs)


def apply_issues(text: str, issues: list[dict[str, Any]],
                 hard: Sequence[str] = ()) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    """依次把问题单精确替换进译文。拒收：old 不是恰好出现 1 次、新旧相同、非术语/误译/漏译/增译类丢了英文词或数字、
    把 HARD 术语译名改掉（纯删除除外）。返回 (新译文, 已应用, 拒收（带 reject 原因）)。"""
    applied: list[dict[str, Any]] = []
    rejects: list[dict[str, Any]] = []
    for it in issues:
        old, new = str(it["old"]), str(it["new"])
        n = text.count(old)
        lost = sorted(set(TOKEN.findall(old)) - set(TOKEN.findall(new)))
        hit = [z for z in hard if new.strip() and z in old and z not in new]
        why = (f"old 出现 {n} 次" if n != 1 else "新旧相同" if old == new else
               f"丢失英文/数字 {lost[:5]}（type={it.get('type')}）" if lost and it.get("type") not in GATED_TYPES else
               f"改掉 HARD 术语 {hit}" if hit else "")
        if why:
            rejects.append({**it, "reject": why})
        else:
            text = text.replace(old, new, 1)
            applied.append(it)
    return text, applied, rejects


def review(cfg: Cfg, run: str, passages: list[str] | None = None, caller: Caller | None = None, jobs: int = 1,
           force: bool = False) -> None:
    caller = caller or llm_engines.call
    engine = cfg.engine("review", run)
    system = _isolate(direct_mode.build_system("review", cfg.domain, cfg.book_desc, cfg.notes, cfg.skill(run)), engine)
    rd = cfg.run_dir(run)
    _write(rd / "system_review.md", system)

    def one(pid: str) -> str:
        en = (cfg.root / f"{pid}_en.txt").read_text(encoding="utf8").strip()
        terms = (cfg.terms_dir / f"{pid}.md").read_text(encoding="utf8")
        zh = (rd / f"{pid}_draft.txt").read_text(encoding="utf8").strip()
        user = direct_mode.user_review(f"{pid}_draft.txt", terms, en, zh)
        text, _ = run_step(rd / f"{pid}_review_raw.txt", engine, system, user, caller=caller, tag=f"{run}/{pid}/review",
                           usage_file=cfg.usage, validate=direct_mode.parse_review, force=force)
        items = direct_mode.parse_review(text)
        _write(rd / f"{pid}_issues.jsonl", "".join(json.dumps(i, ensure_ascii=False) + "\n" for i in items))
        final, ok, bad = apply_issues(zh, items, hard_terms(terms) if cfg.hard_term_filter else [])
        _write(rd / f"{pid}_rejects.jsonl", "".join(json.dumps(i, ensure_ascii=False) + "\n" for i in bad))
        _write(rd / f"{pid}_applied.jsonl", "".join(json.dumps(i, ensure_ascii=False) + "\n" for i in ok))
        _write(cfg.file(pid, run), final + "\n")
        return f"{pid} review issues {len(items)} applied {len(ok)} rejected {len(bad)}"

    _pmap(one, passages or cfg.passages, jobs)


# ---------------------------------------------------------------- 盲评

def parse_judge(text: str) -> dict[str, Any]:
    """严格解析评委输出：JSON 对象，A、B 各含 errors（category 在 CATEGORIES、severity 为 major/minor）与 0 到 100 的 score，
    preferred 为 A/B/tie，reason 为字符串。不合格抛 ValueError。"""
    t = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text.strip())
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j < i:
        raise ValueError("没有 JSON 对象")
    try:
        o = json.loads(t[i:j + 1])
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 解析失败：{exc.msg}") from exc
    if not isinstance(o, dict) or o.get("preferred") not in ("A", "B", "tie") or not isinstance(o.get("reason"), str):
        raise ValueError("缺 preferred/reason 或取值不合法")
    for v in ("A", "B"):
        e = o.get(v)
        if not isinstance(e, dict) or not isinstance(e.get("errors"), list):
            raise ValueError(f"{v} 缺 errors")
        sc = e.get("score")
        if isinstance(sc, bool) or not isinstance(sc, (int, float)) or not 0 <= sc <= 100:
            raise ValueError(f"{v}.score 不是 0 到 100 的数")
        for x in e["errors"]:
            if not isinstance(x, dict) or x.get("category") not in CATEGORIES or x.get("severity") not in ("major", "minor"):
                raise ValueError(f"{v} 的错误条目 category/severity 不合格")
    return o


def judge_pair(cfg: Cfg, left: str, right: str, passages: list[str] | None = None, judges: list[str] | None = None,
               caller: Caller | None = None, jobs: int = 1, force: bool = False) -> str:
    """盲评 left 与 right 两个版本（文件 D/<段>_<版本>.txt）。每段每评委独立随机 A/B，映射存 judge/<对>/key.json。返回对名。"""
    caller = caller or llm_engines.call
    pair = f"{left}_vs_{right}"
    jd = cfg.root / "judge" / pair
    kf = jd / "key.json"
    key: dict[str, dict[str, dict[str, str]]] = json.loads(kf.read_text(encoding="utf8")) if kf.exists() else {}
    tasks = [(pid, j) for pid in passages or cfg.passages for j in judges or cfg.engines["judges"]]
    for pid, j in tasks:  # 先把映射全部落盘，线程里只读
        if j not in key.setdefault(pid, {}):
            flip = random.Random(f"{cfg.seed}|{pair}|{pid}|{j}").random() < 0.5
            key[pid][j] = {"A": right, "B": left} if flip else {"A": left, "B": right}
    _write(kf, json.dumps(key, ensure_ascii=False, indent=1) + "\n")

    def one(t: tuple[str, str]) -> str:
        pid, j = t
        m = key[pid][j]
        en = (cfg.root / f"{pid}_en.txt").read_text(encoding="utf8").strip()
        user = (f"=== English source ===\n{en}\n\n=== Translation A ===\n{cfg.text(pid, m['A'])}\n\n"
                f"=== Translation B ===\n{cfg.text(pid, m['B'])}\n")
        text, fresh = run_step(jd / f"{pid}_{j}.raw.txt", j, _isolate(JUDGE_SYSTEM, j), user, caller=caller,
                               tag=f"{pair}/{pid}/{j}", usage_file=cfg.usage, validate=parse_judge, force=force)
        o = parse_judge(text)
        return f"{pid} {j} {'new' if fresh else 'kept'} preferred={m.get(o['preferred'], 'tie')} A={o['A']['score']} B={o['B']['score']}"

    _pmap(one, tasks, jobs)
    return pair


# ---------------------------------------------------------------- 解盲与汇总

def unblind(cfg: Cfg, pair: str) -> list[dict[str, Any]]:
    """读 judge/<对>/ 下全部评委输出，按 key.json 解盲。每行：段、评委、各版本分数与错误、偏好（版本名或 tie）。"""
    jd = cfg.root / "judge" / pair
    key = json.loads((jd / "key.json").read_text(encoding="utf8"))
    rows = []
    for pid in sorted(key):
        for j, m in sorted(key[pid].items()):
            f = jd / f"{pid}_{j}.raw.txt"
            if not f.exists():
                continue
            o = parse_judge(f.read_text(encoding="utf8"))
            rows.append({"passage": pid, "judge": j, "score": {m[k]: o[k]["score"] for k in "AB"},
                         "errors": {m[k]: o[k]["errors"] for k in "AB"}, "preferred": m.get(o["preferred"], "tie")})
    return rows


def _errtable(rows: list[dict[str, Any]], vers: list[str]) -> list[str]:
    c: collections.Counter[tuple[str, str, str]] = collections.Counter()
    for r in rows:
        for v in vers:
            for e in r["errors"][v]:
                c[(v, e["category"], e["severity"])] += 1
    out = ["| category | " + " | ".join(f"{v} major | {v} minor" for v in vers) + " |", "|---|" + "---|" * (2 * len(vers))]
    for cat in CATEGORIES:
        out.append(f"| {cat} | " + " | ".join(f"{c[(v, cat, 'major')]} | {c[(v, cat, 'minor')]}" for v in vers) + " |")
    out.append("| total | " + " | ".join(
        f"{sum(c[(v, k, 'major')] for k in CATEGORIES)} | {sum(c[(v, k, 'minor')] for k in CATEGORIES)}" for v in vers) + " |")
    return out


def aggregate(cfg: Cfg, pairs: list[str]) -> str:
    """每个 PAIR 一节：逐段分数与偏好、各评委均分、错误计数（合计与分评委）、MQM 罚分（major=5、minor=1）。
    多个 PAIR 时末尾加一张「版本 × 类别」major/minor 对照表。只含数字，不含书中文字。"""
    out: list[str] = []
    per: dict[tuple[str, str], collections.Counter[tuple[str, str]]] = {}
    for pair in pairs:
        left, right = pair.split("_vs_", 1)
        vers = [left, right]
        rows = unblind(cfg, pair)
        judges = sorted({r["judge"] for r in rows})
        out += [f"## {pair}", "", f"| Passage | Judge | {left} | {right} | preferred |", "|---|---|---|---|---|"]
        out += [f"| {r['passage']} | {r['judge']} | {r['score'][left]} | {r['score'][right]} | {r['preferred']} |" for r in rows]
        for j in judges:
            rj = [r for r in rows if r["judge"] == j]
            out.append(f"| mean | {j} | " + " | ".join(f"{sum(r['score'][v] for r in rj) / len(rj):.1f}" for v in vers) + " | |")
        wins = collections.Counter(r["preferred"] for r in rows)
        out += ["", f"preferred: {left} {wins[left]}, {right} {wins[right]}, tie {wins['tie']} (of {len(rows)})", "",
                "Error counts, all judges:", "", *_errtable(rows, vers)]
        for j in judges:
            out += ["", f"Error counts, judge {j}:", "", *_errtable([r for r in rows if r["judge"] == j], vers)]
        out += ["", "MQM penalty (major=5, minor=1):", "", f"| judge | {left} | {right} |", "|---|---|---|"]
        for j in judges:
            pen = {v: sum(5 if e["severity"] == "major" else 1 for r in rows if r["judge"] == j for e in r["errors"][v]) for v in vers}
            out.append(f"| {j} | {pen[left]} | {pen[right]} |")
        out.append("")
        for v in vers:
            per[(pair, v)] = collections.Counter(
                (e["category"], e["severity"]) for r in rows for e in r["errors"][v])
    if len(pairs) > 1:
        cols = list(per)
        out += ["## Error counts per version (major/minor, all judges)", "",
                "| category | " + " | ".join(f"{v}@{p}" for p, v in cols) + " |", "|---|" + "---|" * len(cols)]
        for cat in CATEGORIES:
            out.append(f"| {cat} | " + " | ".join(f"{per[k][(cat, 'major')]}/{per[k][(cat, 'minor')]}" for k in cols) + " |")
        out.append("")
    return "\n".join(out)


# ---------------------------------------------------------------- 命令行

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="参照译本对照比测")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name: str, *pos: str, run: bool = False, against: bool = False) -> argparse.ArgumentParser:
        p = sub.add_parser(name)
        p.add_argument("config")
        for x in pos:
            p.add_argument(x, nargs="+" if x == "pairs" else None)
        if run:
            p.add_argument("--run", required=True)
        if against:
            p.add_argument("--against", default="pub")
        if name != "aggregate":
            p.add_argument("--passages", help="逗号分隔，缺省全部")
        if name not in ("terms", "aggregate"):
            p.add_argument("-j", "--jobs", type=int, default=1)
            p.add_argument("--force", action="store_true")
        if name in ("judge", "compare-runs"):
            p.add_argument("--judges", help="逗号分隔，缺省用配置里的 judges")
        return p

    add("terms")
    add("draft", run=True)
    add("review", run=True)
    add("judge", run=True, against=True)
    add("compare-runs", "run_a", "run_b")
    add("aggregate", "pairs")
    a = ap.parse_args(argv)
    try:
        return _run(a)
    except (RuntimeError, FileNotFoundError) as exc:  # 含 StaleOutputError；各项状态已在上面打印
        print(f"错误：{exc}", file=sys.stderr)
        return 1


def _run(a: argparse.Namespace) -> int:
    cfg = load_config(a.config)
    ps = a.passages.split(",") if getattr(a, "passages", None) else None
    kw: dict[str, Any] = {"jobs": getattr(a, "jobs", 1), "force": getattr(a, "force", False)}
    js = a.judges.split(",") if getattr(a, "judges", None) else None
    if a.cmd == "terms":
        for p in build_terms(cfg, ps):
            print(p)
    elif a.cmd == "draft":
        draft(cfg, a.run, ps, **kw)
    elif a.cmd == "review":
        review(cfg, a.run, ps, **kw)
    elif a.cmd in ("judge", "compare-runs"):
        left, right = (a.against, a.run) if a.cmd == "judge" else (a.run_a, a.run_b)
        judge_pair(cfg, left, right, ps, js, **kw)
        pair = f"{left}_vs_{right}"
        _write(cfg.root / f"agg_{pair}.md", aggregate(cfg, [pair]) + "\n")
        print(f"汇总 -> agg_{pair}.md")
    else:
        text = aggregate(cfg, a.pairs)
        _write(cfg.root / f"agg_{'+'.join(a.pairs)}.md", text + "\n")
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
