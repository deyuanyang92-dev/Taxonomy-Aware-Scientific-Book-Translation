"""booklayout review: one page for every open source-check item.

Why: a 50-page make runs in ~20 s, but each open source-check item used to cost a model
round-trip (open the crop PNG, decide, append the id to accepted.json).  Vol25 p1-50 needed
309 such decisions.  This command puts all open items on one self-contained HTML page: the
user ticks "output is right" or "needs fixing" and exports accepted.json / fixes.json with
no model involved.
"""
from __future__ import annotations

import argparse
import base64
import html
import json
from pathlib import Path
from typing import Any

ORDER = {"missing": 0, "moved": 1, "output_error": 2, "conflict": 3, "name_suspect": 4, "review": 5}

JS = """
const PREV=__PREV__;
function rows(){return [...document.querySelectorAll('tr[data-id]')]}
function val(r){const c=r.querySelector('input:checked');return c?c.value:null}
function upd(){let a=0,f=0;rows().forEach(r=>{const v=val(r);r.className=v||'';if(v=='ok')a++;if(v=='fix')f++});
 document.getElementById('cnt').textContent='成品对 '+a+' / 要改 '+f+' / 未判 '+(rows().length-a-f)}
document.addEventListener('change',upd);
function allok(){rows().forEach(r=>{if(!val(r))r.querySelector('input[value=ok]').checked=true});upd()}
function accepted(){return [...new Set(PREV.concat(rows().filter(r=>val(r)=='ok').map(r=>r.dataset.id)))].sort()}
function fixes(){return rows().filter(r=>val(r)=='fix').map(r=>({id:r.dataset.id,note:r.querySelector('.note').value}))}
function dl(n,o){const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(o,null,1)],
 {type:'application/json'}));a.download=n;a.click()}
upd();
"""

CSS = """body{font:14px sans-serif;margin:1em}table{border-collapse:collapse}td,th{border:1px solid #ccc;
padding:4px;vertical-align:top}td.t{font:16px serif;white-space:pre-wrap}img{max-width:420px}
tr.ok{background:#e8f6e8}tr.fix{background:#fde8e8}#bar{position:sticky;top:0;background:#fff;padding:6px 0}"""


def open_items(report: dict[str, Any], accepted: set[str]) -> list[dict[str, Any]]:
    """Items that still block the gate: not Tesseract noise, not already accepted."""
    items = [it for it in report.get("items", [])
             if it.get("type") in ORDER and it.get("id") not in accepted and it.get("blocking", True)]
    return sorted(items, key=lambda it: (ORDER[it["type"]], it.get("src_page") or 0))


def _img_tag(path: str | None) -> str:
    if not path or not Path(path).exists():
        return "<i>(no crop)</i>"
    data = base64.b64encode(Path(path).read_bytes()).decode()
    return f'<img src="data:image/png;base64,{data}">'


def render_html(items: list[dict[str, Any]], accepted: set[str], qa_problems: list[str]) -> str:
    e = html.escape
    rows = []
    for n, it in enumerate(items, 1):
        sug = f'<br><small>建议: {e(it["suggest"])}</small>' if it.get("suggest") else ""
        rows.append(
            f'<tr data-id="{e(it["id"])}"><td>{n}</td><td>{e(it.get("category") or it["type"])}</td>'
            f'<td>{it.get("src_page")}&rarr;{it.get("out_page")}</td><td>{_img_tag(it.get("crop"))}</td>'
            f'<td class="t">{e(it.get("source", ""))}</td><td class="t">{e(it.get("output", ""))}{sug}</td>'
            f'<td><small>{e(it.get("context", ""))}</small></td>'
            f'<td><label><input type="radio" name="r{n}" value="ok">成品对</label><br>'
            f'<label><input type="radio" name="r{n}" value="fix">要改</label><br>'
            f'<input class="note" placeholder="改成…"></td></tr>')
    qa = "".join(f"<li>{e(p)}</li>" for p in qa_problems)
    qa_block = f"<h3>qa 未过</h3><ul>{qa}</ul>" if qa else ""
    js = JS.replace("__PREV__", json.dumps(sorted(accepted)))
    return (f'<!doctype html><html lang="zh"><meta charset="utf-8"><title>source-check 审核</title>'
            f"<style>{CSS}</style>"
            f'<div id="bar"><b>{len(items)} 项待审</b>（原书扫描 vs 成品）。'
            '<button onclick="allok()">未判的全标成品对</button> '
            "<button onclick=\"dl('accepted.json',accepted())\">导出 accepted.json</button> "
            "<button onclick=\"dl('fixes.json',fixes())\">导出 fixes.json</button> <span id=\"cnt\"></span></div>"
            f"{qa_block}<table><tr><th>#</th><th>类型</th><th>页 原→成</th><th>原书</th><th>原书 OCR</th>"
            f"<th>成品</th><th>上下文</th><th>判定</th></tr>{''.join(rows)}</table>"
            f"<script>{js}</script></html>")


def _qa_problems(qa: Path | None) -> list[str]:
    if not qa or not qa.exists():
        return []
    tr = json.loads(qa.read_text(encoding="utf-8")).get("three_reviews", {})
    return [p for r in tr.values() if isinstance(r, dict) for p in r.get("problems", [])]


def run(source_check: Path, out: Path, accepted_path: Path | None = None,
        qa: Path | None = None) -> dict[str, Any]:
    report = json.loads(source_check.read_text(encoding="utf-8"))
    accepted: set[str] = set()
    if accepted_path and accepted_path.exists():
        accepted = set(json.loads(accepted_path.read_text(encoding="utf-8")))
    qa_problems = _qa_problems(qa)
    items = open_items(report, accepted)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_html(items, accepted, qa_problems), encoding="utf-8")
    res: dict[str, Any] = {"open": len(items), "html": str(out), "qa_problems": len(qa_problems)}
    return res


def cmd_review(args: argparse.Namespace) -> int:
    print(json.dumps(run(args.source_check, args.out, args.accepted, args.qa), ensure_ascii=False))
    return 0


def add_parser(sub: Any) -> None:
    p = sub.add_parser("review", help="one HTML page to accept/flag all open "
                                      "source-check items; exports accepted.json without a model")
    p.add_argument("--source-check", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True, help="review .html")
    p.add_argument("--accepted", type=Path, help="existing accepted.json (already-reviewed ids are skipped)")
    p.add_argument("--qa", type=Path, help="qa.json: list its open problems at the top")
    p.set_defaults(func=cmd_review)
