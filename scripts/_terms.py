"""共享：读取术语库。"""
import csv, pathlib
T = pathlib.Path(__file__).resolve().parents[1] / 'terms'
def rows(name):
    p = T / name
    if not p.exists(): return []
    return list(csv.DictReader(p.open(encoding='utf8'), delimiter='\t'))
def taxa():
    """拉丁名 → (中文, 阶元, 依据)。高阶元_核定 覆盖 名录。中文为 '—' 或空者视为用拉丁名。"""
    out = {}
    for r in rows('名录_刘瑞玉2008_环节动物.tsv'):
        out[r['拉丁名']] = (r['中文名'], r['阶元'], r.get('来源', ''))
    for r in rows('高阶元_核定.tsv'):
        zh = (r.get('核定中文名') or '').strip()
        out[r['拉丁名']] = (zh, r.get('阶元', ''), (r.get('依据(书名+页码或URL)') or '')[:60])
    return out
