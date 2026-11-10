#!/usr/bin/env bash
# 把 yzz-translate 已有术语表和参考语料导入 yiku 术语库（可重复运行：重复条目自动跳过）。
# 层级依 TERMS.md（用户 2026-11-08/09 裁定）：用户核定 0 > 记述该类群的动物志 1 > 近海1988 2 > 刘2008 名录 3 > 名词委 4。
set -euo pipefail
T=~/.claude/skills/yzz-translate/terms
C="/mnt/p/翻译-译作/一些经典译作/参考库"
V="已核,Y,N,图像核对,索引核对,OCR直接"

yiku source add yzz_核定 --title "用户/主会话核定（yzz-translate terms）" --kind user --domain 分类学
yiku source add 动物志09 --title "中国动物志 环节动物门 多毛纲 卷9 叶须虫目 1997" --kind authority --tier 1 --domain 分类学
yiku source add 动物志33 --title "中国动物志 多毛纲 卷33 沙蚕目 2004" --kind authority --tier 1 --domain 分类学
yiku source add 动物志46 --title "中国动物志 星虫动物门 螠虫动物门 卷46" --kind authority --tier 1 --domain 分类学
yiku source add 动物志54 --title "中国动物志 多毛纲 卷54 缨鳃虫目 2014" --kind authority --tier 1 --domain 分类学
yiku source add 近海1988 --title "杨德渐、孙瑞平 1988 中国近海多毛环节动物" --kind authority --tier 2 --domain 分类学
yiku source add 刘瑞玉2008 --title "刘瑞玉 主编 2008 中国海洋生物名录" --kind checklist --tier 3 --domain 分类学
yiku source add 洪德元2016 --title "洪德元 2016 生物多样性 24(3):360–361; 24(9):979–999" --kind zh_original --domain 进化生物学 \
  --path "$C/洪德元2016" --note "植物学家；population 译居群（分类与进化），种群用于生态学（980 页脚注）"

yiku import $T/高阶元_核定.tsv --source yzz_核定 --en 拉丁名 --zh 核定中文名 --domain 分类学 --status 已核 --note-col '依据(书名+页码或URL)'
yiku import $T/形态术语_分科.tsv --source yzz_核定 --en English --zh 中文 --scope-col 适用类群 --domain 分类学 --status-col 状态 --verified-values 已核 --note-col 依据
yiku import $T/形态术语_核定.tsv --source yzz_核定 --en English --zh 核定中文 --domain 分类学 --status 已核 --note-col '依据(书名+页/URL)'
yiku import $T/系统发育术语_核定.tsv --source yzz_核定 --en English --zh 建议中文 --domain 分子系统学 --status 已核 --note-col '依据(出处+页码/URL)'
for v in 09 33 46 54; do
  f=$T/基准_动物志$v.tsv; en=$(head -1 "$f" | cut -f1); ck=$(head -1 "$f" | cut -f9)
  yiku import "$f" --source 动物志$v --en "$en" --zh 中文名 --domain 分类学 --page-col PDF页 --status-col "$ck" --verified-values "$V"
done
f=$T/基准_近海1988.tsv; yiku import "$f" --source 近海1988 --en "$(head -1 "$f" | cut -f1)" --zh 中文名 --domain 分类学 --page-col PDF页 --status-col "$(head -1 "$f" | cut -f9)" --verified-values "$V"
yiku import $T/名录_刘瑞玉2008_环节动物.tsv --source 刘瑞玉2008 --en 拉丁名 --zh 中文名 --domain 分类学
yiku import $T/基准_种_刘瑞玉2008.tsv --source 刘瑞玉2008 --en 名录拉丁名 --zh 中文名 --domain 分类学 --context-col 来源

# 洪德元：只导术语，不导整句定义引译和人名（那些留在参考库作译风参考）
python3 - "$C/洪德元2016/术语对照.tsv" "$C/洪德元2016/_yiku_import.tsv" <<'P'
import csv, sys
r = csv.DictReader(open(sys.argv[1], encoding="utf-8-sig"), delimiter="\t")
w = csv.writer(open(sys.argv[2], "w", encoding="utf8", newline=""), delimiter="\t", lineterminator="\n")
w.writerow(["en", "zh", "domain", "page", "context", "note"])
for x in r:
    if x["类别"] in ("定义引译", "人名机构"):
        continue
    dom = "*" if x["类别"] == "学名与类群" else "进化生物学"
    w.writerow([x["en"], x["zh"], dom, x["页码"], x["原文片段"], x["备注"]])
P
yiku import "$C/洪德元2016/_yiku_import.tsv" --source 洪德元2016 --domain-col domain --page-col page --context-col context --note-col note
yiku stats
