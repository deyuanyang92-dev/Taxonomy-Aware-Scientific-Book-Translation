# -*- coding: utf-8 -*-
"""用 Word COM 把 docx 转 PDF（供视觉检查），并可选更新目录域。

用法:
    C:/Python314/python.exe -X utf8 word_render.py 输入.docx [输出.pdf] [--toc]
"""
import os
import sys
import win32com.client as win32

# Windows 控制台默认 GBK，打印生僻字（如 𧍒）会崩；用法里要加 -X utf8，这里再兜底一层
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, 'reconfigure'):
        _stream.reconfigure(encoding='utf-8', errors='replace')

WD_FORMAT_PDF = 17


def main():
    src = os.path.abspath(sys.argv[1])
    dst = os.path.abspath(sys.argv[2]) if len(sys.argv) > 2 and not sys.argv[2].startswith('--') \
        else os.path.splitext(src)[0] + '.pdf'
    do_toc = '--toc' in sys.argv

    app = win32.DispatchEx('Word.Application')
    app.Visible = False
    app.DisplayAlerts = 0
    try:
        doc = app.Documents.Open(src, ReadOnly=False)
        if do_toc:
            # 正文、页眉页脚全量更新域，TOC 才会出页码
            doc.Fields.Update()
            for i in range(1, doc.TablesOfContents.Count + 1):
                doc.TablesOfContents(i).Update()
            for sec in doc.Sections:
                for hf in sec.Headers, sec.Footers:
                    pass
            doc.Repaginate()
            doc.Save()   # 目录页码写回 docx，用户直接打开即有页码
        # PDF/A（ISO 19005-1）强制嵌入全部字体；SaveAs 默认不嵌 Times New Roman
        doc.ExportAsFixedFormat(OutputFileName=dst, ExportFormat=WD_FORMAT_PDF,
                                OptimizeFor=0, CreateBookmarks=1, DocStructureTags=True,
                                UseISO19005_1=True)
        npage = doc.ComputeStatistics(2)  # wdStatisticPages
        print('PDF:', dst, '｜页数:', npage)
        doc.Close(SaveChanges=0)
    finally:
        app.Quit()


if __name__ == '__main__':
    main()
