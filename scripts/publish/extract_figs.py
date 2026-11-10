# -*- coding: utf-8 -*-
"""从原书 PDF 裁出全部插图，按图号存为 图库/fig_XX.Y.png。

做法：图注（FIGURE x.y:）在图的正下方，故以相邻图注为界，把页面切成若干"图带"，
      每带内所有图像块求并集后整体裁剪 —— 这样瓦片拼图、跨栏图、矢量注记都能完整取到。

用法: python extract_figs.py [--dpi 300]
"""
import os, re, json, argparse
import pymupdf

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 书目录（脚本在 脚本/ 下）
SRC = os.path.join(BASE, '原书', 'Rouse2022_Annelida_专著全本.pdf')
OUT = os.path.join(BASE, '图库')

# 版心范围（页面坐标，单位 pt）：避开页眉页脚
CONTENT_TOP, CONTENT_BOT = 45, 760


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dpi', type=int, default=300)
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)

    doc = pymupdf.open(SRC)
    index, miss = {}, []

    for pno in range(doc.page_count):
        page = doc[pno]
        # 本页全部图注（按 y 排序）
        caps = []
        for b in page.get_text('blocks'):
            m = re.search(r'FIGURE\s+(\d+\.\d+)\s*[:：]', b[4])
            if m:
                caps.append({'label': m.group(1), 'y0': b[1], 'y1': b[3]})
        if not caps:
            continue
        caps.sort(key=lambda c: c['y0'])

        # 本页全部图像块
        rects = []
        for xref, *_ in page.get_images(full=True):
            for r in page.get_image_rects(xref):
                if r.width > 40 and r.height > 30:
                    rects.append(r)

        # 逐条图注切"图带"：上界 = 上一条图注底边（或版心顶），下界 = 本条图注顶边
        prev_bottom = CONTENT_TOP
        for c in caps:
            lo, hi = prev_bottom, c['y0'] - 1
            band = [r for r in rects if r.y1 > lo and r.y0 < hi]
            prev_bottom = c['y1']

            if not band:
                miss.append((pno + 1, c['label'], '图带内无图像块'))
                continue
            x0 = min(r.x0 for r in band); x1 = max(r.x1 for r in band)
            y0 = max(lo, min(r.y0 for r in band)); y1 = min(hi, max(r.y1 for r in band))
            if x1 - x0 < 80 or y1 - y0 < 60:
                miss.append((pno + 1, c['label'], '图带过小'))
                continue

            clip = pymupdf.Rect(x0 - 2, y0 - 2, x1 + 2, y1 + 2)
            pix = page.get_pixmap(clip=clip, dpi=a.dpi)
            fn = 'fig_%s.png' % c['label']
            pix.save(os.path.join(OUT, fn))
            index[c['label']] = {'file': fn, 'page': pno + 1,
                                 'w': pix.width, 'h': pix.height,
                                 'ratio': round(pix.width / pix.height, 3)}

    json.dump(index, open(os.path.join(OUT, '_index.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print('裁出 %d 张图 → %s' % (len(index), OUT))
    if miss:
        print('失败 %d 条：' % len(miss))
        for m in miss:
            print('   p%-4d 图%-6s %s' % m)
    # 尺寸分布
    rs = sorted(v['ratio'] for v in index.values())
    if rs:
        print('宽高比 min %.2f / 中位 %.2f / max %.2f' % (rs[0], rs[len(rs)//2], rs[-1]))


if __name__ == '__main__':
    main()
