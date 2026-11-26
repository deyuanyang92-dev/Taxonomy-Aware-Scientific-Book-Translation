
import json,sys,os
out=sys.argv[1]
for vol in ('2007','2001'):
    src=f'/mnt/p/翻译-译作/日本-imajima/交付/Imajima{vol}/zh/aligned.json'
    d=json.load(open(src))
    pages=[]; got=0
    for pg in d['pages']:
        bl=[b for b in pg.get('blocks',[]) if b.get('role')=='couplet' or (b.get('role')=='heading' and '检索' in (b.get('translation') or ''))]
        if not any(b['role']=='couplet' for b in bl):
            if got: break
            continue
        got+=1
        q=dict(pg); q['blocks']=bl; q['kind']='chapter' if got==1 else pg.get('kind','body')
        pages.append(q)
        if got>=2: break
    meta=d.get('metadata',{})
    json.dump({'pages':pages,'metadata':meta},open(f'{out}/keys_{vol}.json','w'),ensure_ascii=False,indent=1)
    print(vol,[p['page'] for p in pages],sum(len(p['blocks']) for p in pages))
