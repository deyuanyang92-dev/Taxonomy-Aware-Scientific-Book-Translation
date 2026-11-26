#!/usr/bin/env python3
"""Normalise Travisia 'adopted values' (free text) into species x character matrix for keykit tabkey.
Run: python3 examples/make_travisia_lit.py   (reads travisia_adopted.csv, writes travisia_lit_*)
Rules: only adopted values; blank = unknown '?'; no guessing -> '?' + review row."""
import csv, re, sys
from pathlib import Path
D = Path(__file__).parent
rows = list(csv.reader(open(D/'travisia_adopted.csv', encoding='utf-8-sig')))
H = rows[0]; SP = [r[0] for r in rows[1:]]
RAW = {h: {r[0]: r[j].strip() for r in rows[1:]} for j, h in enumerate(H) if j}
OUT = {}      # char -> {species: value}
REV = []      # (species, char, raw, canon, level, reason)
def put(ch, sp, val, raw='', level='', reason=''):
    OUT.setdefault(ch, {})[sp] = val
    if level or (raw and reason):
        REV.append((sp, ch, raw, val, level or 'ROUTINE', reason))
def fmt(x):
    return ('%g' % x)
def numparse(raw):
    """-> (value|None, level, reason). None = nothing to say."""
    s = raw.replace('–', '-').replace('—', '-').strip()
    if not s: return ('?', '', '')
    if re.search(r'Ringel|Linien', s): return ('?', 'UNCERTAIN', 'original unit is rings/lines, not comparable')
    if re.search(r'[<>≥≤]|up to', s): return ('?', 'UNCERTAIN', 'inequality/upper bound only; not entered as value')
    flags = []
    if '~' in s or re.search(r'\babout\b|\bca\.?\b|approx', s): flags.append('approximate')
    if 'tentative' in s: flags.append('tentative')
    if 'computed' in s: flags.append('computed')
    t = re.sub(r'\(\s*rarely\s*([^()]*)\)', r' \1 ', s)
    n_par = len(re.findall(r'\([^()]*\)', t))
    t = re.sub(r'\([^()]*\)', ' ', t)
    t = re.sub(r'\bto\b', '-', t)
    t = re.sub(r'\b(chaetigers?|setigers?|segments?|ch\.?|mm|about|ca\.?|approx\.?)\b', ' ', t)
    if re.search(r'[A-Za-z]', re.sub(r'[~]', '', t)): return ('?', 'UNCERTAIN', 'text, no clean number')
    nums = [float(x) for x in re.findall(r'\d+(?:\.\d+)?', t)]
    if not nums: return ('?', 'UNCERTAIN', 'no number')
    lo, hi = min(nums), max(nums)
    v = fmt(lo) if lo == hi else fmt(lo) + '-' + fmt(hi)
    why = []
    if n_par: why.append('parenthetical (holotype/range/notes) dropped; observed min-max kept')
    if len(nums) > 2 and not n_par: why.append('several values -> min-max')
    if flags: why.append('; '.join(flags))
    lvl = 'UNCERTAIN' if flags else ('ROUTINE' if (why or v != s.replace(' ', '')) else '')
    return (v, lvl, '; '.join(why))
def numcol(newname, col, ovr=None, xform=None):
    for sp in SP:
        raw = RAW[col].get(sp, '')
        if not raw: put(newname, sp, '?'); continue
        if ovr and (col, sp) in ovr:
            v, why = ovr[(col, sp)]; put(newname, sp, v, raw, 'UNCERTAIN' if v == '?' or 'uncertain' in why else 'ROUTINE', why); continue
        v, lvl, why = numparse(raw)
        put(newname, sp, v, raw, lvl if (lvl or v != raw) else '', why or ('reformatted' if v != raw else ''))
        if v == raw and not lvl: REV and None
# ---------- numeric / count ----------
# Toc/Tos mixed cells
TOC_OVR = {}
for sp in SP:
    r = RAW['Toc'].get(sp, '')
    m = re.match(r'Tos=([\d\-]+);\s*Toc=([\d\-]+)', r)
    if m: TOC_OVR[('Toc', sp)] = (m.group(2), 'cell held both Tos and Toc; Toc part kept'); RAW['Tos'][sp] = RAW['Tos'].get(sp) or 'Tos=' + m.group(1)
TOC_OVR.update({
 ('Toc','Travisia hernandezalcantarai'): ('26-28','range across type series (holotype 26)'),
 ('Toc','Travisia thailandensis'): ('20-26','adults 26, juveniles 20-24; observed range'),
})
numcol('total_chaetigers', 'Toc', TOC_OVR)
for sp in SP:  # Tos moved from Toc cell
    r = RAW['Tos'].get(sp, '')
    if r.startswith('Tos='):
        put('total_somites', sp, r[4:], RAW['Toc'][sp], 'ROUTINE', 'Tos taken from mixed Toc cell')
TOS_OVR = {('Tos','Travisia hernandezalcantarai'): ('28-32','holotype 28-30, series ~28-32, both computed (uncertain)')}
for sp in SP:
    if OUT.get('total_somites', {}).get(sp): continue
    raw = RAW['Tos'].get(sp, '')
    if not raw: put('total_somites', sp, '?'); continue
    if ('Tos', sp) in TOS_OVR: v, why = TOS_OVR[('Tos', sp)]; put('total_somites', sp, v, raw, 'UNCERTAIN', why); continue
    v, lvl, why = numparse(raw); put('total_somites', sp, v, raw, lvl, why)
# foetida: achaetous cell carries Tos=31
if RAW['achaetous'].get('Travisia foetida','').find('Tos=31')>=0 and OUT['total_somites'].get('Travisia foetida','?')=='?':
    put('total_somites','Travisia foetida','31',RAW['achaetous']['Travisia foetida'],'UNCERTAIN','Tos=31 taken from achaetous cell (Toc 27 + 4 achaetous = 31, consistent)')
ACH_OVR = {('achaetous','Travisia oksae'): ('3','variation note dropped (may extend to last segment)')}
numcol('achaetous_anterior', 'achaetous', ACH_OVR)
GB = {('br_last','Travisia gigas'): ('44-45','p.104 gives 44, p.105 gives 45 (author inconsistent)'),
      ('br_last','Travisia hobsonae'): ('30-32','"last chaetiger (30-32)": number taken from parenthesis (uncertain)'),
      ('br_last','Travisia satunensis'): ('35','holotype'),
      ('br_pairs','Travisia satunensis'): ('34','holotype 34; lower counts 29-30 flagged by source as likely undercount'),
      ('br_pairs','Travisia gigas'): ('43-44','p.104 gives 43, p.105 gives 44 (author inconsistent)'),
      ('br_pairs','Travisia japonica'): ('26','count derived from ch2-27, not stated by author'),
      ('br_pairs','Travisia elongata'): ('?','author hedges: gills probably fallen off'),
      ('br_last','Travisia elongata'): ('?','gills apparently still present posteriorly; no number'),
      ('br_pairs','Travisia chinensis'): ('?','">25": lower bound only'),
      ('br_last','Travisia chinensis'): ('?','">=26": lower bound only')}
numcol('gill_first_chaetiger','br_first')
numcol('gill_last_chaetiger','br_last',GB)
numcol('gill_pairs','br_pairs',GB)
numcol('gill_free_posterior_chaetigers','br_abr_post')
# lobe onset / well-developed
LO = {('lap_noto_first','Travisia arborifera'):('10','14'),('lap_neuro_first','Travisia arborifera'):('10','14'),
 ('lap_noto_first','Travisia brevis'):('2','16'),('lap_neuro_first','Travisia brevis'):('2','16'),
 ('lap_neuro_first','Travisia fusiformis'):('2','17'),
 ('lap_noto_first','Travisia hobsonae'):('1','14'),('lap_neuro_first','Travisia hobsonae'):('?','16-18'),
 ('lap_noto_first','Travisia olens'):('1','13'),
 ('lap_noto_first','Travisia tribus'):('1','14-16'),('lap_neuro_first','Travisia tribus'):('1','12-14'),
 ('lap_noto_first','Travisia zieglerae'):('2','8'),('lap_neuro_first','Travisia zieglerae'):('2','8'),
 ('lap_neuro_first','Travisia thailandensis'):('1','15-20'),
 ('lap_noto_first','Travisia forbesii intermedia'):('11-13','')}
DEV = {}
def lobecol(newname, col):
    for sp in SP:
        raw = RAW[col].get(sp, '')
        if not raw: put(newname, sp, '?'); continue
        if raw.startswith('absent'): put(newname, sp, '-', raw, 'ROUTINE', 'lobes absent -> not applicable'); continue
        if (col, sp) in LO:
            f, dv = LO[(col, sp)]
            if dv: DEV.setdefault(sp, []).append(dv)
            put(newname, sp, f, raw, 'UNCERTAIN' if f == '?' else 'ROUTINE', 'onset kept here; "well developed from" moved to lobe_well_dev_from' if dv else 'own-form value kept, other species'' values in cell dropped')
            continue
        if raw.startswith('present'): put(newname, sp, '?', raw, 'UNCERTAIN', 'present but first chaetiger not stated'); continue
        v, lvl, why = numparse(raw); put(newname, sp, v, raw, lvl, why)
lobecol('lobe_notopodial_first','lap_noto_first'); lobecol('lobe_neuropodial_first','lap_neuro_first')
for sp in SP:
    d = DEV.get(sp)
    if not d: put('lobe_well_dev_from', sp, '?'); continue
    ns = [float(x) for dd in d for x in re.findall(r'\d+', dd)]
    v = fmt(min(ns)) if min(ns) == max(ns) else fmt(min(ns)) + '-' + fmt(max(ns))
    put('lobe_well_dev_from', sp, v, ' | '.join(d), 'ROUTINE', 'union of notopodial/neuropodial "well developed from" values')
# annulation
AT = {'Travisia gigas':('15','complete 5-15; 3-4 indistinct'),'Travisia palmeri':('19-20','"1-19 or 1-20"'),
 'Travisia oksae':('19','dorsal 3-19, ventral 4-19'),'Travisia pupa':('14','ch2 partly fused; fully triannulate ch3-14'),
 'Travisia brevis':('15-16','2-15/16')}
for sp in SP:
    raw = RAW['ann_tri'].get(sp, '')
    if not raw: put('triannulate_last_chaetiger', sp, '?'); continue
    if sp in AT: put('triannulate_last_chaetiger', sp, AT[sp][0], raw, 'ROUTINE', 'upper end of triannulate zone: ' + AT[sp][1]); continue
    m = re.fullmatch(r'(?:chaetiger\s*)?(\d+)\s*-\s*(\d+)(?:/(\d+))?', raw.replace('–', '-').strip())
    if m:
        hi = m.group(2) if not m.group(3) else m.group(2) + '-' + m.group(3)
        put('triannulate_last_chaetiger', sp, hi, raw, 'ROUTINE', 'zone start-end given; last (upper) chaetiger of triannulate zone kept')
    else: put('triannulate_last_chaetiger', sp, '?', raw, 'UNCERTAIN', 'qualitative or no exact range')
AU = {'Travisia amadoi':('25','segment 1 and 25-30; first posterior uniannulate chaetiger'),'Travisia pupa':('20','ch18-19 transitional; strictly uniannulate from 20'),
 'Travisia hobsonae':('27-28','27/28-end'),'Travisia hernandezalcantarai':('18','18-end'),'Travisia una':('1','1-last (all)'),
 'Travisia fusiformis':('35','last segment only'),'Travisia brevis':('19','from 19')}
for sp in SP:
    raw = RAW['ann_uni'].get(sp, '')
    if not raw: put('uniannulate_first_chaetiger', sp, '?'); continue
    if sp in AU: put('uniannulate_first_chaetiger', sp, AU[sp][0], raw, 'ROUTINE', 'first chaetiger of uniannulate zone: ' + AU[sp][1]); continue
    m = re.fullmatch(r'(?:chaetiger\s*)?(\d+)\s*-\s*(\d+)(?:/\d+)?(?:\s*\(first 2-3 of these with vague subdivision\))?(?:\s*\(computed\))?', raw.replace('–', '-').strip())
    if m: put('uniannulate_first_chaetiger', sp, m.group(1), raw, 'ROUTINE', 'zone start-end given; first (lower) chaetiger of uniannulate zone kept')
    else: put('uniannulate_first_chaetiger', sp, '?', raw, 'UNCERTAIN', 'qualitative, partial or ambiguous zone')
A1 = {'Travisia japonica':'3','Travisia una':'1'}
for sp in SP:
    raw = RAW['ann_ch1'].get(sp, '')
    if not raw: put('annuli_on_chaetiger1', sp, '?'); continue
    if raw in ('2','1'): put('annuli_on_chaetiger1', sp, raw); continue
    if raw.startswith('2 ('): put('annuli_on_chaetiger1', sp, '2', raw, 'ROUTINE', 'parenthetical dropped'); continue
    if raw == 'triannulate': put('annuli_on_chaetiger1', sp, '3', raw, 'ROUTINE', 'triannulate = 3 annuli'); continue
    if raw.startswith('chaetiger 1 biannulate'): put('annuli_on_chaetiger1', sp, '2', raw, 'ROUTINE', 'biannulate = 2 annuli; longitudinal subdivision ignored'); continue
    put('annuli_on_chaetiger1', sp, '?', raw, 'UNCERTAIN', 'chaetiger 1 not described, by inference, or cross-reference only')
numcol('nephridial_pore_first','np_first',{('np_first','Travisia japonica'):('2-4','"4 (variable, sometimes 2)"'),
  ('np_first','Travisia hernandezalcantarai'):('?','not observed (not necessarily absent)'),('np_first','Travisia forbesii'):('?','rings, not chaetigers')})
numcol('nephridial_pore_last','np_last',{('np_last','Travisia forbesii'):('?','rings, not chaetigers')})
IP = {('intp_first','Travisia gigas'):('?','author term "subparapodial sense organs"; not equated with interramal sense organs'),
 ('intp_last','Travisia gigas'):('?','same'),('intp_last','Travisia amoyana'):('33-34','"1-33/34": upper end'),
 ('intp_first','Travisia japonica'):('?','"anterior to ch1"'),('intp_first','Travisia pupa'):('?','"anterior to ch1"'),
 ('intp_first','Travisia hobsonae'):('1','present on all chaetigers'),('intp_first','Travisia profundi'):('?','"from chaetiger 2 (at least)"'),
 ('intp_last','Travisia chinensis'):('28','"~28 (last chaetiger 29 lacks it)"'),
 ('intp_first','Travisia kerguelensis'):('?','given in postoral segments'),('intp_last','Travisia kerguelensis'):('?','given in postoral segments'),
 ('intp_last','Travisia tribus'):('40','"26-40": taken as extent start-end, upper end'),('intp_last','Travisia una'):('15','"13-15": range of last chaetiger')}
numcol('interramal_organ_first','intp_first',IP); numcol('interramal_organ_last','intp_last',IP)
PL = {('pyg_lobes','Travisia concinna'):('7','6 small + 1 large ventral = 7'),('pyg_lobes','Travisia zieglerae'):('11','~10 small dorsal + 1 large ventral (approximate)'),
 ('pyg_lobes','Travisia glabra'):('0','absent (no processes)'),('pyg_lobes','Travisia araciae'):('8','about 8 outer-series elements (approximate)'),
 ('pyg_cirri','Travisia glabra'):('0','absent'),('pyg_cirri','Travisia hernandezalcantarai'):('0','absent'),('pyg_cirri','Travisia thailandensis'):('0','absent per diagnosis'),
 ('pyg_cirri','Travisia brevis'):('12','12 short perianal papillae (approximate homology)'),('pyg_cirri','Travisia gigas'):('6','dorsal half of collar'),
 ('pyg_cirri','Travisia satunensis'):('10','6 digitiform + 4 short'),('pyg_int_cirri','Travisia monroi'):('2','pair of short dorsal anal cirri')}
numcol('pygidial_lobes','pyg_lobes',PL); numcol('pygidial_cirri','pyg_cirri',PL); numcol('pygidial_interramal_cirri','pyg_int_cirri',PL)
SZ = {('size_L','Travisia carnea'):('12-25','25 extended, <=12 contracted (uncertain: contraction state)'),
      ('size_L','Travisia fusiformis'):('22-35','22 average of 14, 35 holotype'),
      ('size_W','Travisia palmeri'):('2-5','anterior 2, posterior 5'),
      ('size_W','Travisia novaezealandi'):('4.5-7','7 at segments 8-10, 4.5 mid-body'),
      ('size_W','Travisia profundi'):('5.25','width; 6 is dorsoventral depth'),
      ('size_W','Travisia gigas'):('?','"up to 13": upper bound only'),
      ('size_W','Travisia forbesii'):('?','3 Linien, old unit; not converted'),
      ('size_L','Travisia forbesii'):('?','">25.4": lower bound only')}
numcol('body_length_mm','size_L',SZ); numcol('body_width_mm','size_W',SZ)
# ---------- categorical ----------
def cat(newname, col, fn):
    for sp in SP:
        raw = RAW[col].get(sp, '')
        if not raw: put(newname, sp, '?'); continue
        v, lvl, why = fn(sp, raw)
        put(newname, sp, v, raw, lvl, why)
def lo(s): return s.lower()
def gills(sp, r):
    l = lo(r)
    if l == 'absent' or l.startswith('no visible branchiae'): return ('absent', 'ROUTINE' if l != 'absent' else '', 'no visible branchiae -> absent' if l != 'absent' else '')
    if l.startswith('branched'): return ('branched', 'ROUTINE' if l != 'branched' else '', 'arborescent = branched' if 'arbor' in l else '')
    if l.startswith('cirriform'): return ('cirriform', 'ROUTINE' if l.split('(')[0].split('-')[0].strip() != 'cirriform' or ';' in l else '', 'form detail moved to gill_surface' if '-' in l.split('(')[0] else ('hedge by author dropped' if 'hedges' in l else ''))
    if l.startswith('suspected') : return ('?', 'UNCERTAIN', 'branchiae only suspected by author')
    if 'arborescent branchiae absent' in l: return ('?', 'UNCERTAIN', 'only arborescent type excluded; other types not addressed')
    return ('?', 'UNCERTAIN', 'unrecognised')
cat('gills','br_form',gills)
def gsurf(sp, r):
    l = lo(r)
    if 'annulate' in l or 'wrinkled' in l: return ('annulate', '' if 'annulate' in l and '(' not in l else 'ROUTINE', 'annulate/wrinkled')
    if 'mostly smooth but' in l: return ('smooth | annulate', 'UNCERTAIN', 'mostly smooth, a few annulated: polymorphic')
    if '-smooth' in l: return ('smooth', '', '')
    return ('?', '', '')
cat('gill_surface','br_form',gsurf)
def glen(sp, r):
    l = lo(r)
    if l.startswith('about equal'): return ('equal', 'ROUTINE', 'minor regional exceptions dropped')
    if l.startswith('shorter than or about equal'): return ('shorter | equal', 'UNCERTAIN', 'author gives both')
    if re.match(r'(zonal|longest|long mid|longer than lappets|peak|variable|long mid-body|short; longest|longer than body segment)', l) or 'longest' in l or 'zonal' in l or 'peak' in l: return ('varies', 'ROUTINE', 'length differs along body')
    if l.startswith('shorter') or l.startswith('short'): return ('shorter', 'ROUTINE' if l not in ('shorter',) else '', 'shorter than segment length/body width')
    return ('?', 'UNCERTAIN', 'absolute length or no ratio')
cat('gill_length','br_length',glen)
# lateral lobes presence
for sp in SP:
    n, ne, ex = RAW['lap_noto_first'].get(sp, ''), RAW['lap_neuro_first'].get(sp, ''), RAW['lap_extent'].get(sp, '')
    ab = [x for x in (n, ne, ex) if x.lower().startswith('absent')]
    pr = [x for x in (n, ne, ex) if x and not x.lower().startswith('absent') and not x.startswith('achaetous') and not x.startswith('tubercles')]
    allraw = ' || '.join(x for x in (n, ne, ex) if x)
    if ab and pr and sp != 'Travisia hernandezalcantarai': put('lateral_lobes', sp, '?', allraw, 'UNCERTAIN', 'sources inside the row conflict (absent vs present)')
    elif ab: put('lateral_lobes', sp, 'absent', allraw, 'ROUTINE', 'derived from lobe columns')
    elif sp == 'Travisia profundi': put('lateral_lobes', sp, '?', allraw, 'UNCERTAIN', 'small oval papillae, not true lappets')
    elif pr: put('lateral_lobes', sp, 'present', allraw, 'ROUTINE', 'derived from lobe columns')
    else: put('lateral_lobes', sp, '?')
def lshape(sp, r):
    l = lo(r)
    ov = {'Travisia chiloensis':('?','UNCERTAIN','arrangement (crown of 8), no shape'),'Travisia concinna':('?','UNCERTAIN','position only'),
          'Travisia forbesii':('rounded | triangular','UNCERTAIN','"rounded or conical, blunt"'),'Travisia novaezealandi':('rounded','UNCERTAIN','rounded, flattened, glandular; flattened ignored'),
          'Travisia nigrocincta':('papilla','UNCERTAIN','two very small knobs per parapodium (may not be lobes)'),'Travisia gravieri':('papilla','ROUTINE','minute papillae')}
    if sp in ov: return ov[sp]
    if 'leaf' in l or l.startswith('broad, flattened'): return ('foliaceous', 'ROUTINE', 'leaf-like/broad flattened')
    if 'globular' in l or l.startswith('rounded'): return ('rounded', 'ROUTINE', '')
    if 'triangular' in l or 'conical' in l: return ('triangular', 'ROUTINE', 'triangular/conical merged')
    return ('?', 'UNCERTAIN', 'unrecognised')
cat('lobe_shape','lap_shape',lshape)
def mvg(sp, r):
    l = lo(r)
    ov = {'Travisia hobsonae':('posterior','ROUTINE','from ~ch14 to posterior end (weak)'),'Travisia hernandezalcantarai':('posterior','ROUTINE','last 10-12 segments only'),
          'Travisia amoyana':('absent','UNCERTAIN','"absent (variable: last 4 segments in some)"'),'Travisia japonica':('absent','UNCERTAIN','tentative reading'),
          'Travisia horsti':('absent','ROUTINE','true groove absent; midline marked by tubercle interruption')}
    if sp in ov: return ov[sp]
    if l.startswith('absent'): return ('absent', 'ROUTINE' if l != 'absent' else '', '')
    if l.startswith('present'): return ('present', 'ROUTINE' if l != 'present' else '', 'parenthetical dropped')
    return ('?', 'UNCERTAIN', 'unrecognised')
cat('mid_ventral_groove','mvg',mvg)
def pap(sp, r):
    l = lo(r)
    ov = {'Travisia parva':('absent','ROUTINE','no papillae'),'Travisia lithophila':('?','UNCERTAIN','finely reticulated skin, papillae not stated'),
          'Travisia monroi':('?','UNCERTAIN','only posterior chaetigers described'),'Travisia novaezealandi':('?','UNCERTAIN','only terminal segment described'),
          'Travisia nigrocincta':('?','UNCERTAIN','pigment pattern only'),'Travisia glabra':('?','UNCERTAIN','rugosity only'),'Travisia forbesii':('?','UNCERTAIN','"granulated/punctured" not equated with papillae'),
          'Travisia zieglerae':('?','UNCERTAIN','squarish lobes (rugose)'),'Travisia kerguelensis':('?','UNCERTAIN','terminal segment only'),'Travisia gravieri':('?','UNCERTAIN','tessellated, no papillae stated'),
          'Travisia araciae':('present','ROUTINE','small papillae visible after staining')}
    if sp in ov: return ov[sp]
    if l.startswith('papillae absent') or l.startswith('absent'): return ('absent', 'ROUTINE', 'papillae absent (adopted-table definition)')
    if re.search(r'papill|pustul|tubercle|vesicular', l): return ('present', 'ROUTINE', 'papillae/pustules/tubercles merged')
    if 'polygon' in l: return ('present', 'ROUTINE', 'polygonal papillae')
    return ('?', 'UNCERTAIN', 'unrecognised')
cat('epidermal_papillae','epid',pap)
def cren(sp, r):
    l = lo(r)
    ov = {'Travisia hobsonae':('absent | present','UNCERTAIN','depends on individual size'),'Travisia japonica':('?','UNCERTAIN','only last somite slightly crenate'),
          'Travisia oksae':('?','UNCERTAIN','"19-27": segment range only'),'Travisia pupa':('?','UNCERTAIN','only first somite'),'Travisia foetida':('?','UNCERTAIN','only first segment described'),
          'Travisia lithophila':('?','UNCERTAIN','lappet vanishing, not crenulation'),'Travisia abyssorum':('?','UNCERTAIN','lateral groove, not crenulation'),
          'Travisia glandulosa':('?','UNCERTAIN','lateral groove, not crenulation'),'Travisia profundi':('?','UNCERTAIN','papilla-free zone/furrow'),
          'Travisia fusiformis':('absent','ROUTINE','lateral crenulation sensu stricto absent; creases ignored'),'Travisia olens':('present','ROUTINE','from ~ch20'),
          'Travisia gravieri':('absent','ROUTINE','')}
    if sp in ov: return ov[sp]
    if l.startswith('absent'): return ('absent', 'ROUTINE' if l != 'absent' else '', 'parenthetical dropped')
    if l.startswith('present'): return ('present', 'ROUTINE' if l != 'present' else '', 'extent (posterior segments) dropped')
    return ('?', 'UNCERTAIN', 'unrecognised')
cat('lateral_crenulation','crenul',cren)
def prost(sp, r):
    l = lo(r)
    ov = {'Travisia chiloensis':('?','UNCERTAIN','club-shaped sensory process only'),'Travisia antarctica':('?','UNCERTAIN','broadly triangular depressed lobe; tip not stated'),
          'Travisia arborifera':('?','UNCERTAIN','"rounded with conical tip": both'),'Travisia novaezealandi':('?','UNCERTAIN','length/width ratio only'),
          'Travisia tribus':('pointed','ROUTINE','pointed cone'),'Travisia una':('pointed','ROUTINE','pointed cone'),'Travisia glabra':('blunt','ROUTINE','narrow lobe rounded anteriorly'),
          'Travisia granulata':('blunt','UNCERTAIN','"conical, blunt, prominent"'),'Travisia fusus':('blunt','UNCERTAIN','subconical, blunt tip'),'Travisia brevis':('blunt','UNCERTAIN','short blunt cone'),
          'Travisia elongata':('?','UNCERTAIN','conical with set-off terminal piece; tip not stated'),'Travisia abyssorum':('blunt','ROUTINE','short, blunt'),
          'Travisia profundi':('blunt','ROUTINE','rounded (blunt)')}
    if sp in ov: return ov[sp]
    if 'truncate' in l: return ('truncate', '', '')
    if re.search(r'pointed|acute|acuminate|sharply|triangular|conical|cone|tapering', l): return ('pointed', 'ROUTINE', 'conical/triangular/acute merged as pointed')
    if re.search(r'blunt|rounded', l): return ('blunt', 'ROUTINE', 'rounded/blunt merged')
    return ('?', 'UNCERTAIN', 'unrecognised')
cat('prostomium','prost',prost)
def nuch(sp, r):
    l = lo(r)
    if re.search(r'slit|split', l): return ('slit', 'ROUTINE' if l != 'slit-shaped (fendido)' else '', 'slit/split merged; Spanish fendido = split')
    if 'c-shaped' in l: return ('C-shaped', '', '')
    if 'pit' in l: return ('pit', 'ROUTINE', 'pits')
    if re.search(r'round', l) and 'lobes' not in l: return ('round', 'ROUTINE', '')
    return ('?', 'ROUTINE', 'only presence/position stated, no shape')
cat('nuchal_organ_shape','nuchal',nuch)
def mouth(sp, r):
    l = lo(r)
    ov = {'Travisia novaezealandi':('?','UNCERTAIN','bare "1": meaning unclear'),'Travisia glabra':('?','UNCERTAIN','anterior margin of first segment; not comparable'),
          'Travisia nigrocincta':('?','UNCERTAIN','position relative to prostomium only'),'Travisia sanrikuensis':('?','UNCERTAIN','"on/near peristomium"'),
          'Travisia zieglerae':('?','UNCERTAIN','"transverse slit to chaetiger 1"'),'Travisia japonica':('at chaetiger 2','UNCERTAIN','"within ch2 (first annulus)"'),
          'Travisia olens':('after chaetiger 1','UNCERTAIN','on buccal segment behind chaetiger-1 bundles'),'Travisia horsti':('after chaetiger 1','UNCERTAIN','at/just posterior to chaetiger 1')}
    if sp in ov: return ov[sp]
    if re.search(r'between ch(aetigers?)? ?1|posterior to the first chaetal|chaetiger1 located before', l): return ('after chaetiger 1', 'ROUTINE' if 'between' not in l else 'ROUTINE', '"between ch1-ch2" and "posterior to first chaetal bundle" merged')
    if re.search(r'chaetiger 2|at ch2|within chaetiger 2', l): return ('at chaetiger 2', 'ROUTINE', 'merged')
    return ('?', 'UNCERTAIN', 'unrecognised')
cat('mouth_position','mouth',mouth)
def pvent(sp, r):
    l = lo(r)
    ov = {'Travisia doellojuradoi':('?','UNCERTAIN','anal tube, no ventral lobe stated'),'Travisia horsti':('?','UNCERTAIN','terminal swelling only'),'Travisia kerguelensis':('?','UNCERTAIN','knob-like projections only')}
    if sp in ov: return ov[sp]
    if l.startswith('absent'): return ('absent', '', '')
    if l.startswith('present') or 'present' in l: return ('present', 'ROUTINE', 'shape detail moved to ventral_lobe_shape')
    return ('?', 'UNCERTAIN', 'unrecognised')
cat('pygidial_ventral_lobe','pyg_ventral',pvent)
def pvshape(sp, r):
    l = lo(r)
    if l.startswith('absent'): return ('-', 'ROUTINE', 'lobe absent -> not applicable')
    for k, v in (('keel', 'keel'), ('triangular', 'triangular'), ('conical', 'conical'), ('rounded', 'rounded')):
        if k in l: return (v, 'ROUTINE', 'from ventral-lobe cell')
    return ('?', '', '')
cat('ventral_lobe_shape','pyg_ventral',pvshape)
def chae(sp, r):
    l = lo(r)
    ov = {'Travisia amoyana':('limbate','ROUTINE','limbate capillaries'),'Travisia oksae':('smooth','UNCERTAIN','"smooth, bilimbate"'),
          'Travisia concinna':('smooth | hirsute','UNCERTAIN','two chaetal types (smooth; serrulate-ciliate=hirsute)'),
          'Travisia oregonensis':('spinulose | hirsute','UNCERTAIN','author gives spinulose/hirsute'),'Travisia nigrocincta':('smooth','UNCERTAIN','glassy simple unlimbate capillaries'),
          'Travisia gravieri':('?','UNCERTAIN','"absent (per original examination)": not accepted as value'),'Travisia glabra':('?','UNCERTAIN','"simple narrow capillaries"'),
          'Travisia granulata':('?','ROUTINE','not characterised'),'Travisia fusus':('?','ROUTINE','not categorised'),'Travisia profundi':('?','ROUTINE','not categorised'),
          'Travisia horsti':('?','UNCERTAIN','"capillary" only'),'Travisia sanrikuensis':('?','UNCERTAIN','"capillary" only'),'Travisia japonica':('?','UNCERTAIN','"capillary (fine, striate)"'),
          'Travisia foetida':('hirsute','ROUTINE','hispid=hirsute (Hobson re-exam)'),'Travisia hobsonae':('hirsute','ROUTINE','hirsute/hispid'),'Travisia pupa':('hirsute','ROUTINE','hirsute/hispid')}
    if sp in ov: return ov[sp]
    if 'hirsute' in l or 'hispid' in l: return ('hirsute', 'ROUTINE', 'hispid/hirsute merged')
    if 'spinulose' in l: return ('spinulose', 'ROUTINE' if l != 'spinulose' else '', '')
    if l.startswith('smooth') or 'smooth' in l: return ('smooth', 'ROUTINE' if l != 'smooth' else '', 'extra remarks dropped')
    return ('?', 'UNCERTAIN', 'unrecognised')
cat('chaetae','chaetae',chae)
# ---- gills absent -> NA for gill-dependent characters ----
for ch in ('gill_first_chaetiger','gill_last_chaetiger','gill_pairs','gill_free_posterior_chaetigers','gill_length','gill_surface'):
    for sp in SP:
        if OUT['gills'].get(sp) == 'absent' and OUT[ch].get(sp) == '?':
            put(ch, sp, '-', 'gills absent', 'ROUTINE', 'derived: gills absent -> not applicable')
# ---------- character metadata ----------
META = [
 # name, type, unit, phrase, state definitions, key_policy
 ('total_somites','num','segments','Total number of segments (somites) including achaetous ones','', 'ok'),
 ('total_chaetigers','num','chaetigers','Total number of chaetigers','', 'ok'),
 ('achaetous_anterior','count','segments','Number of achaetous anterior segments','', 'ok'),
 ('gill_first_chaetiger','count','chaetiger','Branchiae first present on chaetiger','', 'ok'),
 ('gill_last_chaetiger','num','chaetiger','Branchiae last present on chaetiger','', 'ok'),
 ('gill_pairs','num','pairs','Number of pairs of branchiae','', 'ok'),
 ('gill_free_posterior_chaetigers','num','chaetigers','Number of posterior chaetigers without branchiae','', 'ok'),
 ('lobe_notopodial_first','num','chaetiger','Notopodial lateral lobes first present on chaetiger (any size)','', 'ok'),
 ('lobe_neuropodial_first','num','chaetiger','Neuropodial lateral lobes first present on chaetiger (any size)','', 'ok'),
 ('lobe_well_dev_from','num','chaetiger','Lateral lobes well developed from chaetiger','', 'ok'),
 ('triannulate_last_chaetiger','num','chaetiger','Last triannulate chaetiger (upper end of triannulate zone)','', 'avoid (user: annulation not used as fork)'),
 ('uniannulate_first_chaetiger','num','chaetiger','First uniannulate chaetiger of posterior zone','', 'avoid (user: annulation not used as fork)'),
 ('annuli_on_chaetiger1','count','annuli','Number of annuli on chaetiger 1','', 'avoid (user: annulation not used as fork)'),
 ('nephridial_pore_first','count','chaetiger','Nephridial pores first present on chaetiger','', 'ok'),
 ('nephridial_pore_last','count','chaetiger','Nephridial pores last present on chaetiger','', 'ok'),
 ('interramal_organ_first','count','chaetiger','Interramal sense organs first present on chaetiger','', 'ok'),
 ('interramal_organ_last','num','chaetiger','Interramal sense organs last present on chaetiger','', 'ok'),
 ('pygidial_lobes','num','lobes','Number of pygidial lobes/papillae around anus','', 'avoid (user: tail features not used in key)'),
 ('pygidial_cirri','num','cirri','Number of pygidial cirri','', 'avoid (user: tail features not used in key)'),
 ('pygidial_interramal_cirri','num','cirri','Number of interramal anal cirri','', 'avoid (user: tail features not used in key)'),
 ('body_length_mm','num','mm','Body length','', 'size only; poor key character'),
 ('body_width_mm','num','mm','Body width','', 'size only; poor key character'),
 ('gills','cat','','Branchiae form',{'absent':'no branchiae','cirriform':'simple cirriform branchiae','branched':'branched/arborescent branchiae'}, 'ok'),
 ('gill_surface','cat','','Branchial surface',{'smooth':'smooth','annulate':'annulate/transversely wrinkled'}, 'avoid (user: gill annulation not used as fork)'),
 ('gill_length','cat','','Branchial length relative to segment length/body width',{'shorter':'shorter than segment length or body width','equal':'about equal to segment length','varies':'length differs markedly along body'}, 'ok'),
 ('lateral_lobes','cat','','Lateral (epipodial) lobes on trunk',{'absent':'absent','present':'present'}, 'ok'),
 ('lobe_shape','cat','','Shape of lateral lobes',{'triangular':'triangular or conical','rounded':'rounded/globular','foliaceous':'leaf-like or broad flattened','papilla':'minute papilla/knob'}, 'ok'),
 ('mid_ventral_groove','cat','','Mid-ventral groove',{'absent':'absent','present':'along body','posterior':'only posterior part of body'}, 'avoid (user: mid-ventral groove not used as fork)'),
 ('epidermal_papillae','cat','','Epidermal papillae/pustules',{'absent':'no conspicuous papillae','present':'papillae, pustules or tubercles present'}, 'ok'),
 ('lateral_crenulation','cat','','Lateral crenulation of posterior segments',{'absent':'absent','present':'present'}, 'ok'),
 ('prostomium','cat','','Prostomium shape',{'pointed':'conical/triangular/acute (unless described blunt)','blunt':'rounded or blunt','truncate':'truncate'}, 'ok'),
 ('nuchal_organ_shape','cat','','Nuchal organ shape',{'slit':'slit or split','C-shaped':'C-shaped','pit':'pit','round':'round'}, 'ok'),
 ('mouth_position','cat','','Position of mouth',{'after chaetiger 1':'between chaetigers 1 and 2 / behind first chaetal bundle','at chaetiger 2':'at or within chaetiger 2'}, 'ok (two states may be one condition; review)'),
 ('pygidial_ventral_lobe','cat','','Ventral lobe of pygidium',{'absent':'absent','present':'present'}, 'avoid (user: tail features not used in key)'),
 ('ventral_lobe_shape','cat','','Shape of pygidial ventral lobe',{'rounded':'rounded','conical':'conical','triangular':'triangular','keel':'keel-like'}, 'avoid (user: tail features not used in key)'),
 ('chaetae','cat','','Chaetal type',{'smooth':'smooth capillaries','spinulose':'spinulose capillaries','hirsute':'hirsute/hispid capillaries','limbate':'limbate capillaries'}, 'ok'),
]
FREE = [('n_spec','number of specimens: not a taxonomic character'),('material','type/material notes'),('note_general','empty column'),
 ('colour','colour depends on fixation/preservation state; free text'),('mg','methyl-green staining pattern; free text, one-off'),
 ('body_shape','only 3 cells filled'),('tl_depth','type-locality depth/ecology, multiple sites, not morphology'),
 ('lap_extent','extent of lobes: free text; presence folded into lateral_lobes'),('ann_bi','biannulate zone: redundant with triannulate/uniannulate columns')]
chars = [m[0] for m in META]
# ---------- write ----------
def w(path, header, data):
    with open(D/path, 'w', encoding='utf-8-sig', newline='') as f:
        c = csv.writer(f); c.writerow(header); c.writerows(data)
w('travisia_lit_matrix.csv', ['taxon'] + chars, [[sp] + [OUT[c].get(sp, '?') for c in chars] for sp in SP])
cb = []
for name, typ, unit, phrase, states, pol in META:
    if typ == 'cat':
        for s, d in states.items(): cb.append([name, s, s, typ, unit, phrase, d, pol])
        if any(' | ' in OUT[name].get(sp, '') for sp in SP):
            pass
    else: cb.append([name, '', '', typ, unit, phrase, '', pol])
for name, why in FREE: cb.append([name, '', '', 'free', '', '', why, 'not in matrix'])
w('travisia_lit_codebook.csv', ['character', 'raw', 'state', 'type', 'unit', 'phrase', 'definition', 'key_policy'], cb)
w('travisia_lit_free.csv', ['species'] + [n for n, _ in FREE], [[sp] + [RAW[n].get(sp, '') for n, _ in FREE] for sp in SP])
with open(D/'travisia_lit_review.tsv', 'w', encoding='utf-8', newline='') as f:
    c = csv.writer(f, delimiter='\t'); c.writerow(['species', 'character', 'raw', 'canonical', 'level', 'reason'])
    for r in REV: c.writerow([x.replace('\t', ' ').replace('\n', ' ') for x in r])
from collections import Counter
print('chars', len(chars), Counter(m[1] for m in META), 'free', len(FREE))
print('review', len(REV), Counter(r[4] for r in REV))
print('unknown cells', sum(1 for c in chars for sp in SP if OUT[c].get(sp) == '?'), 'of', len(chars) * len(SP))
