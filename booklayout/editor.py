"""Editable HTML and its round trip back into aligned JSON.

`edit-html`   aligned JSON (+ figure crops) -> one self-contained HTML page.  Every
              block is a contenteditable element carrying its block_id.  Toolbar:
              bold, italic, roman, font family/size (recorded), line break
              (Shift+Enter), comment on a selection, undo/redo, autosave,
              "Save edits" -> edits.json.
`apply-html-edits`  edits.json -> block patch (old_translation precondition) -> aligned
              JSON.  Bold/italic/line breaks/text round-trip as the translation
              Markdown the builder already reads (`*x*`, `**x**`, newline).  Font
              family/size and comments are kept in the edits file and reported, not
              applied: the printed design belongs to the profile, not to a block.
Then `booklayout make` rebuilds DOCX/PDF.  No model is called.
"""
from __future__ import annotations

import html
import json
import re
import shutil
import sys
from html.parser import HTMLParser
from pathlib import Path

ROLE_TAG = {"heading": "h2", "caption": "p", "ref": "p", "index": "p", "body": "p"}


def md_to_html(md: str) -> str:
    s = html.escape(md or "", quote=False)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"\*([^*]+)\*", r"<i>\1</i>", s)
    return s.replace("\n", "<br>")


class _ToMd(HTMLParser):
    """Editor HTML -> translation Markdown.  b/strong, i/em, br, block-level div/p."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.stack: list[tuple[str, int]] = []

    def handle_starttag(self, tag, attrs):
        st = dict(attrs).get("style", "") or ""
        kind = None
        if tag in ("b", "strong") or re.search(r"font-weight:\s*(bold|[6-9]00)", st):
            kind = "**"
        elif tag in ("i", "em") or re.search(r"font-style:\s*italic", st):
            kind = "*"
        if tag == "br":
            self.out.append("\n")
        elif tag in ("div", "p") and self.out and not self.out[-1].endswith("\n"):
            self.out.append("\n")
        if tag != "br":
            self.stack.append((kind or "", len(self.out)))
            if kind:
                self.out.append(kind)

    def handle_endtag(self, tag):
        if tag == "br" or not self.stack:
            return
        kind, at = self.stack.pop()
        if kind:
            if not "".join(self.out[at + 1:]).strip():   # empty mark pair: drop it, keep the spaces
                self.out[at:] = [x for x in self.out[at + 1:]]
            else:
                self.out.append(kind)

    def handle_data(self, data):
        self.out.append(data.replace("\xa0", " ").replace("*", ""))


def html_to_md(frag: str) -> str:
    p = _ToMd()
    p.feed(frag)
    p.close()
    s = "".join(p.out)
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


_JS = r"""
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const KEY='bl-edit:'+document.title;
let comments=JSON.parse(localStorage.getItem(KEY+':c')||'[]');
function sync(){const n=$$('.blk').filter(b=>b.innerHTML!==b.dataset.orig).length;$('#cnt').textContent=n+' edited, '+comments.length+' comments';
 localStorage.setItem(KEY,JSON.stringify($$('.blk').map(b=>[b.dataset.id,b.innerHTML])));localStorage.setItem(KEY+':c',JSON.stringify(comments));}
(function restore(){try{const s=JSON.parse(localStorage.getItem(KEY)||'[]');const m=new Map(s);$$('.blk').forEach(b=>{if(m.has(b.dataset.id))b.innerHTML=m.get(b.dataset.id)});}catch(e){}})();
document.addEventListener('input',e=>{if(e.target.closest('.blk')){e.target.closest('.blk').classList.add('dirty');sync()}});
document.addEventListener('keydown',e=>{if(e.key==='Enter'&&e.shiftKey){e.preventDefault();document.execCommand('insertHTML',false,'<br>')}
 else if(e.key==='Enter'&&e.target.closest('.blk')){e.preventDefault()}});
function cmd(c,v){document.execCommand('styleWithCSS',false,false);document.execCommand(c,false,v||null);sync()}
function roman(){const sel=getSelection();if(!sel.rangeCount)return;document.execCommand('removeFormat');sync()}
const fmt={};
function setFont(prop,v){const s=getSelection();if(!s.rangeCount||s.isCollapsed)return;const b=s.anchorNode.parentElement.closest('.blk');
 document.execCommand('styleWithCSS',false,true);document.execCommand(prop==='size'?'fontSize':'fontName',false,prop==='size'?'7':v);
 if(prop==='size')$$('.blk font[size="7"]').forEach(f=>{f.removeAttribute('size');f.style.fontSize=v});
 if(b){(fmt[b.dataset.id]=fmt[b.dataset.id]||{})[prop]=v;}sync()}
function addComment(){const s=getSelection();if(!s.rangeCount||s.isCollapsed)return alert('Select text first');
 const b=s.anchorNode.parentElement.closest('.blk');if(!b)return;const note=prompt('Comment');if(!note)return;
 comments.push({block_id:b.dataset.id,quote:s.toString(),note});b.classList.add('commented');renderC();sync()}
function renderC(){$('#cm').innerHTML=comments.map((c,i)=>'<div class=cmt><b>'+c.block_id+'</b> <i>'+c.quote.slice(0,60).replace(/</g,'&lt;')+'</i><br>'+c.note.replace(/</g,'&lt;')+' <a href="#" onclick="comments.splice('+i+',1);renderC();sync();return false">x</a></div>').join('')}
renderC();
function save(){const edits=$$('.blk').filter(b=>b.innerHTML!==b.dataset.orig).map(b=>({block_id:b.dataset.id,old_html:b.dataset.orig,html:b.innerHTML,fmt:fmt[b.dataset.id]||null}));
 const blob=new Blob([JSON.stringify({version:1,source:document.title,edits,comments},null,1)],{type:'application/json'});
 const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=document.title+'.edits.json';a.click()}
sync();
"""

_CSS = """
body{font-family:'Times New Roman',serif;margin:0;background:#f3f1ea}
#bar{position:sticky;top:0;z-index:9;background:#222;color:#eee;padding:6px 10px;display:flex;gap:6px;flex-wrap:wrap;align-items:center;font:13px sans-serif}
#bar button,#bar select{font:13px sans-serif}
#wrap{display:flex;gap:16px;max-width:1200px;margin:0 auto;padding:12px}
#doc{flex:1;background:#fff;padding:24px 36px;box-shadow:0 0 6px #0003}
#side{width:260px;font:12px sans-serif}
.cmt{background:#fff8c6;padding:4px 6px;margin-bottom:6px;border-left:3px solid #e0b000}
.blk{outline:none;margin:6px 0;line-height:1.4;text-align:justify}
.blk:focus{background:#fffbe0}.blk.dirty{border-left:3px solid #4a90e2;padding-left:4px}.blk.commented{background:#fff8c6}
h2.blk{font-size:15pt;margin:16px 0 6px}p.cap{font-size:9.5pt}p.ref{font-size:9.5pt;padding-left:1.5em;text-indent:-1.5em}
.pg{color:#999;font:11px sans-serif;border-top:1px dashed #ccc;margin-top:14px}
figure{margin:10px 0;text-align:center}figure img{max-width:100%}
"""


def build_editor(aligned: dict, figures_dir: Path | None, out_html: Path, title: str = "") -> dict:
    out_html = Path(out_html)
    files = out_html.with_name(out_html.stem + "_files")
    figs: dict[int, list[str]] = {}
    if figures_dir and (Path(figures_dir) / "source_figure_audit.json").exists():
        audit = json.loads((Path(figures_dir) / "source_figure_audit.json").read_text(encoding="utf-8"))
        files.mkdir(parents=True, exist_ok=True)
        for f in audit.get("figures", []):
            src = Path(figures_dir) / f["crop"]
            if src.exists():
                shutil.copy(src, files / src.name)
                figs.setdefault(int(f.get("source_pdf_page", 0)), []).append(f"{files.name}/{src.name}")
    parts: list[str] = []
    n = 0
    for page in aligned.get("pages", []):
        parts.append(f"<div class=pg>page {html.escape(str(page.get('page', '')))}</div>")
        queue = list(figs.get(int(page.get("page", 0)), []))
        for b in page.get("blocks", []):
            if b.get("role") == "figure_group":
                for fg in b.get("figures", []):
                    cp = Path(figures_dir or ".") / fg.get("crop", "")
                    if cp.exists():
                        files.mkdir(parents=True, exist_ok=True)
                        shutil.copy(cp, files / cp.name)
                        parts.append(f"<figure><img src='{html.escape(files.name + '/' + cp.name, quote=True)}' "
                                     f"style='height:{float(fg.get('height_mm', 16))}mm;max-width:none'></figure>")
                continue
            md = b.get("translation") if b.get("translation") is not None else b.get("text", "")
            bid = html.escape(str(b.get("block_id", "")), quote=True)
            role = b.get("role", "body")
            tag = ROLE_TAG.get(role, "p")
            if role == "caption":
                img = queue.pop(0) if queue else None
                if img:
                    parts.append(f"<figure><img src='{html.escape(img, quote=True)}'></figure>")
            inner = md_to_html(md)
            cls = {"caption": "cap", "ref": "ref"}.get(role, "")
            parts.append(f"<{tag} class='blk {cls}' contenteditable=true data-id='{bid}' "
                         f"data-role='{html.escape(role)}' data-orig='{html.escape(inner, quote=True)}'>{inner}</{tag}>")
            n += 1
        for img in queue:
            parts.append(f"<figure><img src='{html.escape(img, quote=True)}'></figure>")
    toolbar = (
        "<div id=bar><button onclick=\"cmd('bold')\"><b>B</b></button>"
        "<button onclick=\"cmd('italic')\"><i>I</i></button><button onclick='roman()'>Roman</button>"
        "<select onchange=\"setFont('family',this.value)\"><option>Font</option><option>Times New Roman</option>"
        "<option>Arial</option><option>Georgia</option><option>SimSun</option></select>"
        "<select onchange=\"setFont('size',this.value)\"><option>Size</option>"
        + "".join(f"<option>{s}pt</option>" for s in (8, 9, 10, 10.5, 11, 12, 14, 16))
        + "</select><button onclick=\"cmd('undo')\">Undo</button><button onclick=\"cmd('redo')\">Redo</button>"
        "<button onclick='addComment()'>Comment</button><button onclick='save()'>Save edits</button>"
        "<span id=cnt></span><span>Shift+Enter = line break</span></div>")
    doc = (f"<!doctype html><html><head><meta charset=utf-8><title>{html.escape(title or out_html.stem)}</title>"
           f"<style>{_CSS}</style></head><body>{toolbar}<div id=wrap><div id=doc>" + "\n".join(parts)
           + f"</div><div id=side><b>Comments</b><div id=cm></div></div></div><script>{_JS}</script></body></html>")
    out_html.write_text(doc, encoding="utf-8")
    return {"html": str(out_html), "blocks": n, "figures": sum(len(v) for v in figs.values())}


def edits_to_patch(edits_doc: dict, aligned: dict) -> tuple[dict, dict]:
    """edits.json -> (block patch, report).  Unchanged-after-conversion edits are dropped."""
    cur = {b.get("block_id"): b for p in aligned.get("pages", []) for b in p.get("blocks", [])}
    out, skipped, fmt_only = [], [], []
    for e in edits_doc.get("edits", []):
        bid = e["block_id"]
        b = cur.get(bid)
        if b is None:
            skipped.append({"block_id": bid, "why": "unknown block_id"})
            continue
        old = b.get("translation") if b.get("translation") is not None else b.get("text", "")
        new = html_to_md(e.get("html", ""))
        if new == (old or "").strip() or new == old:
            if e.get("fmt"):
                fmt_only.append(bid)
            continue
        out.append({"block_id": bid, "old_translation": old, "translation": new})
    rep = {"patched": len(out), "skipped": skipped, "font_changes_not_applied": fmt_only,
           "comments": edits_doc.get("comments", [])}
    return {"version": 1, "edits": out}, rep


def add_parser(sub) -> None:
    e = sub.add_parser("edit-html", help="editable HTML (bold/italic/line breaks/comments) from aligned JSON")
    e.add_argument("--aligned", type=Path, required=True)
    e.add_argument("--figures", type=Path)
    e.add_argument("--profile", type=Path)
    e.add_argument("--out", type=Path, required=True)
    e.set_defaults(func=cmd_edit_html)
    a = sub.add_parser("apply-html-edits", help="edits.json saved from the editable HTML -> aligned JSON")
    a.add_argument("--aligned", type=Path, required=True)
    a.add_argument("--edits", type=Path, required=True)
    a.add_argument("--out", type=Path, required=True)
    a.add_argument("--report", type=Path)
    a.set_defaults(func=cmd_apply)


def cmd_edit_html(args) -> int:
    data = json.loads(args.aligned.read_text(encoding="utf-8"))
    print(json.dumps(build_editor(data, args.figures, args.out), ensure_ascii=False))
    return 0


def cmd_apply(args) -> int:
    from .normalize import apply_block_edits

    data = json.loads(args.aligned.read_text(encoding="utf-8"))
    patch, rep = edits_to_patch(json.loads(args.edits.read_text(encoding="utf-8")), data)
    if patch["edits"]:
        result = apply_block_edits(data, patch)
        rep["apply"] = {k: result[k] for k in ("applied", "removed", "missing", "stale", "invalid")}
        if result["stale"] or result["invalid"] or result["missing"]:
            print("patch rejected: " + json.dumps(rep["apply"], ensure_ascii=False), file=sys.stderr)
            return 2
    args.out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    if args.report:
        args.report.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"patched={rep['patched']} font_changes_not_applied={len(rep['font_changes_not_applied'])} "
          f"comments={len(rep['comments'])}")
    return 0
