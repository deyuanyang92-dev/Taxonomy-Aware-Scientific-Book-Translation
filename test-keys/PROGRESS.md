# 进度 2026-11-24（第十一段）
## 目标
Ophelia 属物种检索表（用户在测试检索表制作水平）：以 Tebble 体式为主干，交付 Word+PDF。
## 已完成
- 用户指出旧表 examples/ophelia_judged.*（粗矩阵、计数分区间、体式被拆散）水平低；已查证属实（Tebble 1953: 365 检索表以 body formula 分种）。
- 新表：examples/ophelia_bodyformula.py 手工定义二歧树（35 种、33 偶句），脚本断言每种恰出现一次、偶句皆二分；走 keykit make 出 docx/pdf，verify 0 问题，PDF 2 页已目检。
- 主干：有无鳃 → 鳃起始刚节 Xa → Yb → Za → 有无 n → 鳃形（二叉 ashworthi、基部膨大 bulbibranchiata）→ 肛乳突；终点写全体式。
- 数据：/mnt/p/粘海蛹新种-宁德合作-2026/00_学习笔记/06_物种比较总表.md（34 种 + limacina）。
## 未完成 / 下一步
- 第一件：等用户对新表的意见。
- 根因防再犯未做：keykit 加检查——计数性状被分区间时报错；属的标准鉴别性状（Ophelia=体式）未用时报错；配测试。
- denticulata / neglecta 体式相同并列；glabra、simplex 无体式未收。
- 上段遗留：D 表改法待选；judge.apply() 就地改矩阵；中文二歧排版（--lang zh）未做。
- git 未提交；按路径精确 add。
## 关键决定
- 文献冲突不处理（用户 2026-11-24 明令），取总表首列数值。
- 检索表交付 = docx+pdf。
## 文件位置
- test-keys/examples/ophelia_bodyformula.{py,ir.json,docx,pdf,report.json}
- 旧表（作废参考）：test-keys/examples/ophelia_judged.*
- 物种知识库：/mnt/p/粘海蛹新种-宁德合作-2026/00_学习笔记/14_物种知识库/；性状证据 15_性状使用证据_2026-09-30.md
## 坑
- 做属级检索表前先查项目已有知识库与名家检索表（Tebble 1953），不要只用粗矩阵自动建树。
- 两个 make 并行会抢 soffice 配置目录；串行跑。
- 长去向文本（多种并列带命名人）会触发 L3；并列终点去命名人。
## 仍在跑的任务
- 无
