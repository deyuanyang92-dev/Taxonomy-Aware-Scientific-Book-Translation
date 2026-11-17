# 本地多毛类文献术语学习（2026-11-17）

## 家底
- docstore registry≈2948 条，多毛/环节相关约 2920
- 知识库：12 源、3478 页、8376 条 en–zh、10227 段 passages
- OCR：动物志 09/33/46/54、近海1988、若干学位论文
- ANNiKEY：518 条英文形态定义
- yiku 主库：`/mnt/p/翻译-译作/yiku/yiku.db`

## 本轮动作（Cursor）
- 家底盘点后，从知识库 **过滤导入候选约 4126 条**（志书/近海/学位论文；噪声对拒收数千）
- 两轮脚本：`scripts/learn_local_polychaete_terms.py` → 库 `/mnt/p/翻译-译作/yiku/yiku.db`
- ANNiKEY 515 条英文定义导出：`/mnt/p/翻译-译作/yiku/learning_2026-11-17/ANNiKEY_en_definitions.tsv`（只助义项，不直接定中文）
- yiku：分类学域约 1.6 万条；其中本轮多毛相关候选 4126；全库已核仍约 2801（升核需人工/页核）

## 导入样例（候选，待核）
- `binomial nomenclature` → 双名法（杨德渐2006 p.22）
- `cell theory` → 细胞学说（杨德渐2006 p.22）
- `subsidence theory` → 沉降说（杨德渐2006 p.22）
- `neritic province` → 近海区（杨德渐2006 p.24）
- `oceanic province` → 远洋区（杨德渐2006 p.24）
- `epipelagic zone` → 表水层（杨德渐2006 p.25）
- `mesopelagic zone` → 中水层（杨德渐2006 p.25）
- `bathypelagic zone` → 渐深水层（杨德渐2006 p.25）
- `abyssopelagic zone` → 深水层（杨德渐2006 p.25）
- `hadalpelagic zone` → 超深水层（杨德渐2006 p.25）
- `ocean bottom division` → 海底区（杨德渐2006 p.25）
- `shallow bottom` → 浅海底（杨德渐2006 p.25）
- `coastal zone` → 海岸带（杨德渐2006 p.25）
- `splash zone` → 浪击带（杨德渐2006 p.25）
- `intertidal zone` → 潮间带（杨德渐2006 p.25）
- `subintertidal zone` → 潮下带（杨德渐2006 p.26）
- `shelf zone` → 陆架带（杨德渐2006 p.26）
- `deep ocean bottom` → 深海底（杨德渐2006 p.26）
- `bathyal bottom` → 渐深海底（杨德渐2006 p.26）
- `abyssal bottom` → 深海底（杨德渐2006 p.26）

## yiku 现状
```json
{
  "total": 17365,
  "by_status": {
    "候选": 14544,
    "否决": 20,
    "已核": 2801
  },
  "by_domain": {
    "*": 24,
    "分子系统学": 78,
    "分类学": 16596,
    "科学史": 6,
    "进化生物学": 661
  },
  "polychaete_related": 4126
}
```

## 志书表述信号（passages）
- 形态/描述段落 passages≈10227
-   passages 含「具…个」: 1669
-   passages 含「长于」: 260
-   passages 含「短于」: 155
-   passages 含「疣足」: 3119
-   passages 含「刚毛」: 4508
-   passages 含「口前叶」: 1687

## 结论
1. **有用**：本地文献已足够支撑术语库；主杠杆是「有出处的 en–zh + 异写」而非整句 TM。
2. 知识库原 8376 条噪声不少（OCR/人名/句碎片）；本轮用规则过滤后再进 yiku，一律 **候选**。
3. 下一步：按志书页抽核高频形态词（口前叶/疣足/刚毛…）升「已核」；ANNiKEY 只助义项不直接给中文。
4. 译书时 `--engine none` + 本库 glossary，可继续压 LLM token。

## 升核与导出（全部推进，Cursor）
- 权威源一致形态词升核后，再清噪声（误升人名/粘连学名等退回候选）
- 导出 glossary：`/mnt/p/翻译-译作/yiku/learning_2026-11-17/glossary_多毛类_形态.tsv`（**1038** 行）
- yiku：已核约 **3373**（分类学域已核约 **2765**）；候选约 13972
- 样例已核：`prostomium→口前叶`，`parapodium→疣足`，`chaeta→刚毛`
- 用法：`--glossary` 指该 TSV + `--engine none`
- 脚本：`learn_local_polychaete_terms.py` / `promote_polychaete_terms.py` / `cleanup_bad_promotions.py` / `export_polychaete_glossary.py`
