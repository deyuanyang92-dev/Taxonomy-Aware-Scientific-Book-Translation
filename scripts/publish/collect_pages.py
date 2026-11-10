# -*- coding: utf-8 -*-
"""用 Word 量出每个章标题所在的真实页码（正文页码，自 1 起），写入 _toc_pages.json。

用法: C:/Python314/python.exe collect_pages.py 文件.docx
"""
import json, os, sys
import win32com.client as win32

WD_ADJUSTED_PAGE = 1   # wdActiveEndAdjustedPageNumber：反映 pgNumType 重设后的显示页码


def main():
    src = os.path.abspath(sys.argv[1])
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '_toc_pages.json')   # 书目录

    app = win32.DispatchEx('Word.Application')
    app.Visible = False
    app.DisplayAlerts = 0
    try:
        doc = app.Documents.Open(src, ReadOnly=True)
        doc.Repaginate()
        # 正文起始页（第 2 节第 1 页）的物理页号，用于换算成正文页码

        data = {}
        for p in doc.Paragraphs:
            try:
                if p.Style.NameLocal not in ('Heading 1', '标题 1'):
                    continue
            except Exception:
                continue
            txt = p.Range.Text.strip().replace('\r', '')
            if not txt:
                continue
            data[txt] = int(p.Range.Information(WD_ADJUSTED_PAGE))
        doc.Close(SaveChanges=0)
    finally:
        app.Quit()

    json.dump(data, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('量得 %d 个章标题页码 → %s' % (len(data), os.path.basename(out)))
    for k in list(data)[:5]:
        print('  ', k, data[k])


if __name__ == '__main__':
    main()
