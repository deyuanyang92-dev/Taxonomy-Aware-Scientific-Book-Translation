import sys,re
from collections import Counter
from docx import Document
NB=chr(0x202f)
for f in sys.argv[1:]:
    d=Document(f); bad=[]
    for p in d.paragraphs:
        for r in p.runs:
            t=r.text.replace(NB,' ')
            if not r.italic:
                for m in re.finditer(r'[A-Z][a-z]+(?: +[a-z]{3,})?|\b[A-Z]\. *[a-z]{3,}', t):
                    bad.append(m.group(0))
    print(f.split('/')[-1], Counter(bad).most_common(40))