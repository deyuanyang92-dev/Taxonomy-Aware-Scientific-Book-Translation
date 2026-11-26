import sys
from docx import Document
d=Document(sys.argv[1])
for p in d.paragraphs:
    if any(k in p.text for k in ('Aphrodita','Pontogenia')):
        print([ (r.text[-25:], bool(r.italic)) for r in p.runs[-4:]], [hex(ord(c)) for r in p.runs for c in r.text if ord(c) in (0x20,0x202f,0xa0)][:6])