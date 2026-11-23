# dichot (CCB-ID)

## 1 定位与许可证
- 与检索表无关：高光谱遥感树种分类（Anderson 2018 CCB-ID，"dichotomous"仅为命名双关）。dichot/README.md:3-5
- 许可证 MIT (c) 2020 Christopher Anderson。dichot/LICENSE:1-3
- 结论：对 keykit 无直接参考价值，仅作排除记录。

## 2 输入格式
- training.csv：第 1 列 crown_id，其余列为光谱波段特征（数值）。dichot/dichot/read.py:74-90
- species_id.csv：crown_id、species_id、species 三列（还有 genus 版）。read.py:45-48,66-69
- bands.csv：Wavelength、Flag(1=好波段)。read.py:24-27

## 3 输出格式
- 各物种预测概率（csv，-o）；模型存 pickle。README.md:33-34；dichot/write.py:19-30（write.predictions.to_csv/to_raster 为空实现 pass，write.py:10-16）

## 4 建表算法
- 无检索表构建。核心是 sklearn GradientBoosting + RandomForest 两模型集成，概率 sigmoid 校准（cv=3），多模型取均值。dichot/_core.py:104-107,123-126,257-258
- 类别平衡样本权重 compute_class_weight("balanced")。_core.py:44-66
- PCA 白化降维、PCA 离群剔除（>3σ）。dichot/transform.py:17；dichot/outliers.py:20-30
- 多态/缺失/成本/终止：不适用。

## 5 混合层级能力
- 仅有 genus_id 与 species_id 两级标签读取（read.py:53-71），无层级检索或分表。

## 6 校验与错误处理
- 基本无；is_raster 用 GDAL 能否打开判断，is_csv 仅看扩展名。read.py:93-124

## 7 可借鉴 / 不足
- 可借鉴：几乎无。唯一相关：类别不平衡加权、概率校准思路——但 keykit 是确定性规则表，不适用。
- 建议从调研清单剔除。
