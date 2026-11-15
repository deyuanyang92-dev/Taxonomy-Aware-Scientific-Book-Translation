#!/usr/bin/env python3
"""OCR 分级复核（auto 档）：免费手段优先，解决不了的行才交 Haiku，Haiku 拿不准的才交 Sonnet。

前提：该书已用 ppocr 引擎识别过（`docstore text <key> --engines ppocr --dpi 200`），行框缓存在 ~/.cache/docstore_ppocr/。
须在装有 paddleocr 的环境里运行（行识别模型）：

    /root/ocr_eval/venv_gpu/bin/python scripts/ocr_review.py <key> [--pages 1-50] [--max-tier free|haiku|sonnet] [--dry]

各级（阈值全部来自 docs/ocr_hard_scans.md 的实测）：
  0 免费  争议行 = server 与 mobile 识别器读法不同且 server 置信度 < 0.97（劣化页覆盖 99% 错字）
  1 免费  日文页：NDLOCR-Lite 读法与 server/mobile 之一一致即采用（96–97%）；8 读法投票 ≥7 票且 NDLOCR 同意才采用（100%，
         NDLOCR 不同意时仅 43%）。中文页：投票 ≥7 票即采用（NDLOCR 不适用）
  2 Haiku 其余争议行读两遍：第一遍带两个 OCR 读法作提示，第二遍不带提示；原尺寸裁图，每次请求 ≤40 行
         （固定开销大，攒批省钱），缺回的行再补发一次。两遍一致即采用（实测一致时 97–99% 正确）
  3 Sonnet 只处理两遍 Haiku 不一致的行（约 1/4；比「Haiku 第三读法就升级」少一半 Sonnet，准确率还更高）
护栏：模型读法与任一 OCR 读法相似度 ≥60 才采用，否则保留 server 原读法。
结果：每页写入一个新版本（producer=ppocr+review(<tiers>)，成为主版本，旧版本进 alternates），
改动逐行记 <库根>/_audit/ocr_review_<key>.jsonl；用量记同目录 ocr_review_usage.tsv。
"""
from __future__ import annotations

import argparse
import base64
import collections
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'docstore' / 'engines'))

import cv2  # noqa: E402
import fitz  # noqa: E402
import numpy as np  # noqa: E402
from rapidfuzz import fuzz  # noqa: E402

from docstore.engines.ppocr import _cache_file, rows_to_text  # noqa: E402
from docstore.store import Store, make_version  # noqa: E402
from ppocr_img import binarize, rebuild  # noqa: E402

CJK = re.compile(r'[一-鿿]')

# NDLOCR-Lite（日本国立国会图书馆 NDL Lab，CC BY 4.0，https://github.com/ndl-lab/ndlocr-lite）：日文活字行识别器，
# 仅用其 PARSeq ONNX 模型（src/parseq.py），按长度级联 30→50→100 字模型（同官方 process_cascade）。
NDL = os.environ.get('NDLOCR_LITE_SRC', '/root/ocr_eval/ext/ndlocr-lite/src')
NDL = NDL if os.path.isdir(NDL) else ''
_NDL_MODELS: tuple = ()


def ndl_read(img) -> str:
    global _NDL_MODELS
    if not _NDL_MODELS:
        import yaml
        sys.path.insert(0, NDL)
        from parseq import PARSEQ
        cl = list(yaml.safe_load(open(f'{NDL}/config/NDLmoji.yaml', encoding='utf-8'))['model']['charset_train'])
        m = f'{NDL}/model/parseq-ndl-24x{{}}-tiny-{{}}-tegaki3-r8data-202604.onnx'
        _NDL_MODELS = (PARSEQ(m.format('256-30', '189epoch'), cl), PARSEQ(m.format('384-50', '300epoch'), cl),
                       PARSEQ(m.format('768-100', '153epoch'), cl))
    r30, r50, r100 = _NDL_MODELS
    s = r30.read(img)
    if len(s) >= 25:
        s = r50.read(img)
        if len(s) >= 45:
            s = r100.read(img)
            if len(s) >= 98 and img.shape[0] < img.shape[1]:
                w = img.shape[1] // 2
                s = r100.read(img[:, :w]) + r100.read(img[:, w:])
    return s
BATCH = 40
PRICE = {'haiku': (0.00006, 0.0002), 'sonnet': (0.0009, 0.004)}
SONNET_SHARE = 0.25  # 两遍 Haiku 不一致的比例（bench：(51+31)/328）  # 实测：每行、每次调用固定开销（美元，claude -p 精简参数）
SYS = 'You transcribe printed text lines from scanned zoology books. Output JSON lines only.'
HEAD = ('Each image is one printed line from a scanned {lang} zoology book. For each numbered image, transcribe the line '
        'exactly ({script}, Latin names, numbers, punctuation). Two OCR readings are given as hints; they may both be '
        'wrong. Output JSON lines only: {{"id": N, "text": "..."}}')
HEAD_BLIND = ('Each image is one printed line from a scanned {lang} zoology book. For each numbered image, transcribe '
              'the line exactly ({script}, Latin names, numbers, punctuation). Output JSON lines only: {{"id": N, "text": "..."}}')


def norm(s: str) -> str:
    s = s.translate(str.maketrans('０１２３４５６７８９（）；，：~’”．。、―─－−', '0123456789();,:～\'"..,——--'))
    return re.sub(r'[\s.,;:()\'"\-—～~·◆、。，．；：（）*_…・\[\]【】「」]', '', s)


def ok(v: str, a: str, b: str) -> bool:
    return bool(v) and max(fuzz.ratio(norm(v), norm(a)), fuzz.ratio(norm(v), norm(b))) >= 60


def crop(page, poly, pad=2):
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    x0, x1 = max(0, int(min(xs)) - pad), min(page.shape[1], int(max(xs)) + pad)
    y0, y1 = max(0, int(min(ys)) - pad), min(page.shape[0], int(max(ys)) + pad)
    c = page[y0:y1, x0:x1]
    return c if c.size else np.full((16, 16, 3), 255, np.uint8)


def variants(c):
    h = c.shape[0]
    return [c, cv2.resize(c, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC), binarize(c),
            cv2.copyMakeBorder(c, h // 3, h // 3, h // 3, h // 3, cv2.BORDER_CONSTANT, value=(255, 255, 255))]


def parse_pages(s: str | None, n: int) -> list[int]:
    if not s:
        return list(range(1, n + 1))
    out: list[int] = []
    for part in s.split(','):
        a, _, b = part.partition('-')
        out += list(range(int(a), int(b or a) + 1))
    return [p for p in out if 1 <= p <= n]


class Line:
    __slots__ = ('page', 'idx', 'srv', 'mob', 'img', 'final', 'how', 'haiku', 'haiku2', 'sonnet', 'ja')

    def __init__(self, page, idx, srv, mob, img, ja):
        self.page, self.idx, self.srv, self.mob, self.img, self.ja = page, idx, srv, mob, img, ja
        self.final, self.how, self.haiku, self.haiku2, self.sonnet = srv, 'ocr', '', '', ''


def call_model(model: str, lines: list[Line], usage: Path, hints: bool = True) -> dict[int, str]:
    """一批行（≤BATCH）一次 claude -p 请求；返回 {批内序号: 读法}。"""
    ja = sum(ln.ja for ln in lines) >= len(lines) / 2
    head = HEAD if hints else HEAD_BLIND
    content: list[dict] = [{'type': 'text', 'text': head.format(lang='Japanese' if ja else 'Chinese',
                                                               script='kanji/kana' if ja else 'simplified Chinese')}]
    with tempfile.TemporaryDirectory() as td:
        for k, ln in enumerate(lines):
            p = Path(td) / f'{k}.png'
            cv2.imwrite(str(p), ln.img)
            content.append({'type': 'text', 'text': f'#{k}  A: {ln.srv}  B: {ln.mob}' if hints else f'#{k}'})
            content.append({'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png',
                                                        'data': base64.b64encode(p.read_bytes()).decode()}})
    req = json.dumps({'type': 'user', 'message': {'role': 'user', 'content': content}}, ensure_ascii=False)
    cmd = ['--model', model, '--tools', '', '--setting-sources', '', '--strict-mcp-config', '--disable-slash-commands',
           '--exclude-dynamic-system-prompt-sections', '--no-session-persistence', '--effort', 'low',
           '--system-prompt', SYS, '--input-format', 'stream-json', '--output-format', 'stream-json', '--verbose']
    for _ in range(3):  # claude 自动更新时可执行文件会短暂缺失
        exe = shutil.which('claude')
        if not exe:
            import time
            time.sleep(20)
            continue
        r = subprocess.run([exe, '-p', *cmd], input=req, capture_output=True, text=True, timeout=900, cwd='/tmp')
        out: dict[int, str] = {}
        for evl in r.stdout.splitlines():
            try:
                ev = json.loads(evl)
            except json.JSONDecodeError:
                continue
            if ev.get('type') == 'result':
                with usage.open('a', encoding='utf-8') as f:
                    u = ev.get('usage') or {}
                    f.write(f"{dt.datetime.now().isoformat(timespec='seconds')}\t{model}\t{len(lines)}\t"
                            f"{u.get('input_tokens', 0) + u.get('cache_creation_input_tokens', 0) + u.get('cache_read_input_tokens', 0)}"
                            f"\t{u.get('output_tokens', 0)}\t{ev.get('total_cost_usd', 0)}\n")
                for row in re.findall(r'\{[^{}]*"id"[^{}]*\}', ev.get('result', '')):
                    try:
                        o = json.loads(row)
                        out[int(o['id'])] = str(o['text'])
                    except (json.JSONDecodeError, KeyError, ValueError):
                        pass
                return out
    raise RuntimeError('claude 不可用')


def ask_all(model: str, lines: list[Line], usage: Path, hints: bool = True) -> dict[int, str]:
    """攒批调用；缺回的行单独再补发一批。返回 {id(line): 读法}。"""
    res: dict[int, str] = {}
    todo = list(lines)
    for attempt in range(2):
        miss = []
        for k in range(0, len(todo), BATCH):
            batch = todo[k:k + BATCH]
            got = call_model(model, batch, usage, hints)
            for j, ln in enumerate(batch):
                if j in got:
                    res[id(ln)] = got[j]
                else:
                    miss.append(ln)
        if not miss:
            break
        todo = miss
    return res


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('key')
    ap.add_argument('--pages')
    ap.add_argument('--dpi', type=int, default=200)
    ap.add_argument('--max-tier', choices=('free', 'haiku', 'sonnet'), default='sonnet')
    ap.add_argument('--dry', action='store_true', help='只做免费级并估算模型费用，不调模型、不写库')
    a = ap.parse_args()

    from paddleocr import TextRecognition
    srv_rec = TextRecognition(model_name='PP-OCRv5_server_rec')
    mob_rec = TextRecognition(model_name='PP-OCRv5_mobile_rec')
    store = Store()
    doc = store.doc(a.key)
    pdf = fitz.open(doc['path'])
    pages = parse_pages(a.pages, pdf.page_count)
    audit = store.root / '_audit'
    audit.mkdir(exist_ok=True)
    usage = audit / 'ocr_review_usage.tsv'

    per_page: dict[int, tuple[list, float, dict]] = {}
    lines: list[Line] = []
    stat = collections.Counter()
    for n in pages:
        cf = _cache_file(doc['path'], n, a.dpi)
        if not cf.exists():
            stat['no_cache'] += 1
            continue
        meta = json.loads(cf.read_text(encoding='utf-8'))
        rows = meta['rows']
        if not rows:
            continue
        per_page[n] = (rows, meta['width'], meta)
        pix = pdf[n - 1].get_pixmap(dpi=a.dpi)
        img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)
        img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR if pix.n == 3 else cv2.COLOR_GRAY2BGR)
        page = rebuild(img, meta)
        crops = [crop(page, r[0]) for r in rows]
        mob = [str(o['rec_text']) for o in mob_rec.predict(crops, batch_size=16)]
        ja = any(re.search(r'[぀-ヿ]', r[1]) for r in rows)
        stat['lines'] += len(rows)
        for i, r in enumerate(rows):
            if norm(r[1]) == norm(mob[i]) or float(r[2]) >= 0.97 or len(norm(r[1])) < 2:
                continue
            ln = Line(n, i, r[1], mob[i], crops[i], ja)
            vs = variants(crops[i])
            reads = [str(o['rec_text']) for o in srv_rec.predict(vs, batch_size=8)] + \
                    [str(o['rec_text']) for o in mob_rec.predict(vs, batch_size=8)]
            (top, k), *_ = collections.Counter(norm(x) for x in reads).most_common()
            stat['disputed'] += 1
            if ja and NDL:  # 日文页：NDLOCR（与 PaddleOCR 不同源）当第三票
                nd = ndl_read(crops[i])
                if norm(nd) in (norm(ln.srv), norm(ln.mob)):  # 实测 96–97% 正确
                    ln.final, ln.how = nd if norm(nd) == norm(ln.srv) else ln.mob, 'ndl'
                    stat['ndl'] += 1
                elif k >= 7 and norm(nd) == top:  # 投票 ≥7 且 NDLOCR 同意：100%（不同意时仅 43%，交模型）
                    ln.final, ln.how = next(x for x in reads if norm(x) == top), 'vote'
                    stat['vote'] += 1
            elif k >= 7:  # 中文页：NDLOCR 不适用（一致时只对 83%），沿用投票
                ln.final, ln.how = next(x for x in reads if norm(x) == top), 'vote'
                stat['vote'] += 1
            lines.append(ln)

    rest = [ln for ln in lines if ln.how == 'ocr']
    calls_h = -(-len(rest) // BATCH)
    est_h = 2 * (len(rest) * PRICE['haiku'][0] + calls_h * PRICE['haiku'][1])
    ns = int(SONNET_SHARE * len(rest))
    est_s = ns * PRICE['sonnet'][0] + -(-ns // BATCH) * PRICE['sonnet'][1]
    print(f"{a.key}: {len(per_page)} 页，{stat['lines']} 行；争议 {stat['disputed']}，免费解决：NDLOCR 一致 {stat['ndl']}、投票 {stat['vote']}，"
          f"剩 {len(rest)} 行待模型（估 Haiku 两遍 ${est_h:.3f}，Sonnet 约 ${est_s:.3f}，按两遍不一致约 1/4 估）"
          + (f"；无缓存 {stat['no_cache']} 页" if stat['no_cache'] else ''))
    if a.dry:
        return

    if a.max_tier in ('haiku', 'sonnet') and rest:
        got = ask_all('haiku', rest, usage, hints=True)
        got2 = ask_all('haiku', rest, usage, hints=False)
        for ln in rest:
            ln.haiku, ln.haiku2 = got.get(id(ln), ''), got2.get(id(ln), '')
            if ok(ln.haiku, ln.srv, ln.mob):
                ln.final, ln.how = ln.haiku, 'haiku'
        esc = [ln for ln in rest if not ok(ln.haiku, ln.srv, ln.mob) or norm(ln.haiku) != norm(ln.haiku2)]
        for ln in rest:
            if ln not in esc:
                ln.how = 'haiku2'  # 两遍一致
        if a.max_tier == 'sonnet' and esc:
            got = ask_all('sonnet', esc, usage)
            for ln in esc:
                ln.sonnet = got.get(id(ln), '')
                if ok(ln.sonnet, ln.srv, ln.mob):
                    ln.final, ln.how = ln.sonnet, 'sonnet'
        print(f'  Haiku {len(rest)} 行，升级 Sonnet {len(esc) if a.max_tier == "sonnet" else 0} 行')

    tiers = '+'.join(t for t in ('ndl', 'vote', 'haiku2', 'sonnet') if any(ln.how == t for ln in lines)) or 'none'
    by_page = collections.defaultdict(list)
    for ln in lines:
        by_page[ln.page].append(ln)
    with (audit / f'ocr_review_{a.key}.jsonl').open('a', encoding='utf-8') as log:
        for n, lns in sorted(by_page.items()):
            rows, width, meta = per_page[n]
            new = [list(r) for r in rows]
            changed = 0
            for ln in lns:
                if ln.final != ln.srv:
                    new[ln.idx][1] = ln.final
                    changed += 1
                log.write(json.dumps({'page': n, 'line': ln.idx, 'server': ln.srv, 'mobile': ln.mob, 'haiku': ln.haiku,
                                      'haiku2': ln.haiku2, 'sonnet': ln.sonnet, 'final': ln.final, 'how': ln.how}, ensure_ascii=False) + '\n')
            if not changed:
                continue
            text, conf = rows_to_text(new, width)
            v = make_version(text, 'ocr', producer=f'ppocr+review({tiers})', engine=f'ppocr review {a.dpi}dpi',
                             dpi=a.dpi, conf=conf, source=f"{doc['path']}#review",
                             extra={'review': {'changed_lines': changed, 'max_tier': a.max_tier}})
            store.put_version(a.key, n, v, promote=True)
    c = collections.Counter(ln.how for ln in lines)
    print(f"  完成：NDLOCR {c['ndl']}，投票 {c['vote']}，Haiku 两遍一致 {c['haiku2']}，Sonnet 采用 {c['sonnet']}，"
          f"Sonnet 失败沿用 Haiku {c['haiku']}，保留 OCR {c['ocr']}；"
          f"日志 {audit / f'ocr_review_{a.key}.jsonl'}")


if __name__ == '__main__':
    main()
