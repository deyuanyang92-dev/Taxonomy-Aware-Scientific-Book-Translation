# 本地多毛类文献检索表体例调研 (local_keys.md)

方法与范围
- 文献库：/mnt/n/多毛类分类文献-薛整理-杨接力（2906 个 PDF）。pdftotext -layout 全文抽取，未逐页看图。
- 扫描：对前 764 个文件（find 顺序，按目录字母序，Taxonomy 中 A–H 开头作者为主，加 Sipuncula/Echiura）逐页找“>=5 行以数字开头且 >=4 行含点线”的页，命中 104 个文件。全库未扫完，**结论偏向 A–H 作者，未覆盖 I–Z**（未确证的部分不下判断）。
- 版面为 pdftotext 的 -layout 近似，非原图；⟶ 表示原文此处有大段空白（右对齐的去向栏）。老书（Day 1967、Fauvel 1947 等）OCR 有噪声，样例保留噪声以示原貌。
- 所有出处均为本地路径，前缀均为 /mnt/n/多毛类分类文献-薛整理-杨接力 。

## 一、逐篇记录

### 1. Fauchald 1977, The polychaete worms (家检索表，a/b + 回指)
- 路径：/Taxonomy/Fauchald K/Fauchald, 1977-The polychaete worms.pdf，页 23（PDF 页）
- 体例：编号 + 小写 a/b；括号内写“来源号”回指，如 60a (59a)；a/b 分行各自顶格。
- 去向：右侧大空白后写科名（大写），或写跳转号；长正文续行缩进与 a/b 对齐。
- 点线：只在部分行出现（.... COSSURIDAE），多数行用空白代替。
- 跨页：未确证（本页中段）。
- 样例：
```
60a (59a).    Both composite falcigers and simple setae present   ⟶   ACROCIRRIDAE (part)
60b (59a).    All setae simple, distally curved or straight, sometimes acicular   ⟶   CIRRATULIDAE (part)
61a (59b).    With a single mid-dorsal palp on one of the first setigers (setigers 3-6 usually) .... COSSURIDAE
62a (61b).    With series of long, slender branchial filaments and tentacular and dorsal cirri along the body (often
   ⟶   lost, scars remain)   ⟶   63
```

### 2. Bartholomew 2001, Key to Polychaete Families of Chesapeake Bay
- 路径：/Taxonomy/Bartholomew A/Bartholomew, 2001-Key to Polychaete Families of Chesapeake Bay and ….pdf，页 2
- 体例：1a / b.（b 行省略数字）；去向为行末“…….2”（数字）或科名右对齐。
- 点线：有，单行密点线 + 去向；长正文换行后，点线只出现在最后一行。含 “helpful hint:” 非标准插入语。
- 样例：
```
2a. Dorsal felt largely obscuring elytra (see below); helpful hints: this worm looks like it
has fur on its dorsal side, hence its common name "sea mouse"………….Aphroditidae
b. Dorsum without felt, elytra or scars clearly visible…………………………………….3
3a. Neurosetae composite, notosetae simple; all posterior segments with elytra or
scars…………………………………………………………………………...Sigalionidae
```

### 3. Böggemann 2009, abyssal SE Atlantic (Org. Divers. Evol. 9: 251–428)
- 路径：/Taxonomy/Boggemann M/Boggemann, 2009-Polychaetes of the abyssal SE Atlantic.pdf，页 14（期刊页 264）
- 体例：1. / – （第二支用 en dash，无数字）；去向：数字或科名，均右对齐；点线填满。前有说明句“This key is limited to taxa present…”。
- 样例：
```
1.  Dorsum more or less covered with series of elytra (scales) ................................................................................... 2
–   Dorsum without elytra or elytral scars .................................................................................................................. 5
2.  Prostomium with 1–3 antennae; harpoon-shaped notochaetae absent .................................................................. 3
–   Prostomium with one median antenna; some notochaetae harpoon-shaped ..................................... Aphroditidae
```

### 4. Budaeva & Fauchald 2008, Onuphidae
- 路径：/Taxonomy/Budaeva N/Budaeva & Fauchald, 2008-Onuphidae.pdf，页 14
- 体例：1 / –（无句点）；去向可为数字或学名+作者+年（斜体学名，Nothria conchylega Sars, 1835）；**检索表条目后插入 Distribution: 段落**（检索表与物种描述交织）。长文无点线时点线收到最后一行。
- 样例：
```
2 Peristomial cirri absent; tubes transparent, wholly secreted by inhabitants, round in transverse section .....
    ....................................................................................................................... Hyalinoecia spp. (see below)
- Peristomial cirri present; tubes with a parchment-like inner lining and an outer layer of foreign particles 3
```

### 5. Choi et al. 2020, Neoamphitrite (Zookeys 类期刊格式，物种级)
- 路径：/Taxonomy/Choi HK/Choi et al., 2020-Neoamphitrite undevigintipes.pdf，页 9
- 体例：1 / –；编号与正文之间用大空白（制表位）；标题“Key to known species of the genus Neoamphitrite Hessle, 1917”含属名+作者+年。
- 去向：数字右对齐；学名（带作者年）去向单独占一行，点线自成一行（**长条目：点线换行后再写去向**）。
- 样例：
```
1          Notopodia present on first 15 chaetigers........................................................
           ......................................N. hydrothermalis Reuscher, Fiege & Wehe, 2012
–          Notopodia present on more than first 15 chaetigers.....................................2
```

### 6. Capa & Murray 2016, Pseudobranchiomma (ZooKeys 类)
- 路径：/Taxonomy/Capa M/Capa & Murray, 2016-Combined morphological and molecular data unveils relationships ….pdf，页 29
- 体例：1 / –；去向可多值：学名 + 作者 + 年 + (产地) + (Fig. 11)；**一个终点后接“or *reportedly present …”附加行**；条目内连字符断词（gen-/erally）。
- 样例：
```
3         Radioles with paired compound eyes present.................................................
          ....................................... P. grandis (Baird, 1865) (New Zealand) (Fig. 11)
          or *reportedly present P. serratibranchis (Grube, 1878) (Philippines)
–         Radioles without distinct radiolar eyes.........................................................4
5         Radioles with up to 25 serrations and coloured transverse bands; thorax gen-
          erally with 8 thoracic chaetigers; thoracic uncini with 6–7 rows of teeth........
          ..............................................P. orientalis (McIntosh, 1885) (Hong Kong)
```
- 跨页：本页表头在上页；图（Figure 11）夹在检索表中间，表被图打断 → 需支持图插入检索表。

### 7. Bastida-Zavala 2008, Serpulids from Eastern Pacific
- 路径：/Taxonomy/Bastida-Zavala JR/Bastida-Zavala, 2008-Serpulids from Eastern Pacific.pdf，页 9
- 体例：1 / –，**且第二支起带回指号**：“2 (1)”，“3 (2)”。去向：数字或学名。点线极长。
- 样例：
```
1 Without operculum ........................................
- With operculum .......................................
2 (1) Collar chaetae limbate or capillaries; uncini with long fang .....................................................Protula ..
-    Collar chaetae modified, with distal limba; uncini with short peg ....
3 (2) Uncini with teeth; thoracic membrane well developed ........................................................................
```

### 8. Fauchald 1986, Eunice of Australia (Rec. Aust. Mus. 38: 260–261)
- 路径：/Taxonomy/Fauchald K/Fauchald, 1986-Eunice of Australia.pdf，页 21–22
- 体例：13. / --（双连字符）；**叶端种名前加星号 * 标记本文研究种**；去向为数字或种名（小写种加名省略属名）。续行缩进与首行正文对齐。
- 样例：
```
13.   Antennae without articulations. . .......................................... gracilis
--Antennae beaded. .................................................... *curticirris
18.   Ventral cirri in median and posterior setigers forming a scoop around the
      lower edge of the parapodia. ....................................... *tribranchiata
```

### 9. Glasby 1999, Namanereidinae Pt.1
- 路径：/Taxonomy/Glasby CJ/Glasby, 1999-Namanereidinae (Nereididae), Pt. 1.pdf，页 29
- 体例：1 / ——（em dash 双连）；多分支（三支：1/——/——）；去向在末行点线后。
- 样例：
```
1       Heterogomph falcigers present in sub- and supra-preacicular
        fascicle in all parapodia ........................................................
—— Heterogomph falcigers in anterior parapodia, replaced by
   heterogomph spinigers posteriorly in sub- and supra-preacicular
   fascicle ........................................................................
—— Only heterogomph spinigers present in sub- and supra-preacicular
```
- 特点：**一个号下三分支**；正文自第二行起缩进与第一行不同（挂缩进）。

### 10. Hobson & Banse 1981, Sedentaria NE Pacific / Banse & Hobson 1974, Errantia
- 路径：/Taxonomy/Banse K/Hobson & Banse, 1981-Sedent Polys NE Pacific.pdf 页 44；/Taxonomy/Banse K/Banse & Hobson, 1974-Errante Polys NE Pacific.pdf 页 36
- 体例：编号只写在“第一支”行，第二支无标记（靠缩进/空白）；去向为属名右对齐，**或数字（跳转）**；括号内含 [补充说明]、(as in Fig. 4c) 图引用。
- 点线：长点线 + 属名。
- 样例：
```
8    Dorsal sense organ long, extending over several to many segments. With
     genital pouches (as in Fig. 4e [check median region]). Gills present through
     median region ............................................................................................ Laonice
     Dorsal sense organ short [prostomial extension not beyond setiger 2 or 3].
     Without genital pouches. Gills (as in Fig. 4a) present only anteriorly .... Aonides
```
- 去向与点线在不同列：属名有时被排版截断（OCR 噪声 “Aonidest”）。

### 11. Day 1967, A monograph on the Polychaeta of Southern Africa (Pt. I Errantia)
- 路径：/Taxonomy/Day JH/Day, 1967-A monograph on the Polychaeta of Southern Africa, Pt. I. Errantia.pdf，页 34；Pt. II Sedentaria 页 18
- 体例：编号 1 / "—"（em dash 竖列）；**去向栏：科名（大写）+ (p. 30) 页码引用，或数字**；图引用 (fig. 0.2.1)。点线写作 "......" 并成列。
- OCR 严重噪声，但可见：编号单独成行居左，描述在下，去向右栏。
- 样例（原貌）：
```
 1
       (fig.   0.2.1)   ..........
     Elytra {dorsal scales) present on many segments, at least in the anterior half of the body
                        .............                                             ,\PHR0DITII>.\F, (p. 30)
 -
 2
     Elytra absent
```

### 12. Fauvel 1923, Faune de France Errantes
- 路径：/Taxonomy/Fauvel P/Fauvel, 1923-Fauna de France Errantes.pdf，页 148（书页 145）
- 体例：1. / -（单连字符）；去向：种名 + “, p. 155”（页码引用，**无点线或用句点串 “. .”**）；也有“. . . . .”稀疏点（点与空格交替）。
- 样例：
```
  - Cirres dorsaux rougeâtres ou brunâtres.     . P. ruhiginosa, p. 155
  4. Cirres dorsaux blanchâtres avec tache centralo brune. . . . .
      . . . . . . . . . . . . . . . . . P. vittata, p. 157
  6. Cirres dorsaux ovales ou cordiformes (fig. Si, e). • . ..   ⟶   7
```

### 13. Fauvel 1947, Annélides polychètes de Nouvelle-Calédonie (TABLEAU DES GENRES)
- 路径：/Taxonomy/Fauvel P/Fauvel, 1947-Annélides polychètes de Nouvelle-Calédonie et des Îles Gambier.pdf，页 16
- 体例：1. / -（以及 “.-”），去向：(p. 13), Iphione. 即“(页码), 属名.”；回指无。
- 样例：
```
  1. 2 antennes, 12-13 paires d'élytres                                               ,............ (p. 13), Iphione.
. - 3 antennes ...;.....................................................                                                   2.
  3. Plus de 21 paires d'élytres, des lamelles ventrales. . .. (p. 19), "Gastrolepidia.
```
- 法语表头：TABLEAU DES GENRES / TABLEAU DES FAMILLES。

### 14. Fauvel 1927, Polychètes sédentaires (TABLEAU DES FAMILLES)
- 路径：/Taxonomy/Fauvel P/Fauvel, 1927-Polychètes sédentaires. Addenda aux errantes, Arachiannélides, Echiuriens.pdf，页 8
- 体例：1. / -；点线用 “. . • • .”，去向数字右对齐；长条目换行后继续点线。
- 样例：
```
1. Corps divisé en régions bien .tranchées. . . • • . .   ⟶   8
- Corps non divisé en régions bien tranchées • . . . .   ⟶   2
2. Corps à segments nombreux. Pas de branchies anales, pas de
   large bouclier ventral. . • • • • '. . • • • . . . • 3
```

### 15. Bianchi 1981, Policheti Serpuloidei (意大利语 CHIAVE AI GENERI)
- 路径：/Taxonomy/Bianchi CN/Bianchi, 1981-POLICHETI SERPULOIDEI.pdf，页 36
- 体例：1 - （数字 + 空格 + 连字符 + 正文）；去向：属名，点线连接。标题：CHIAVE AI GENERI。
- 样例：
```
 1 -animali di acque dolci sotterranee (zone carsiche). . Marifugia
```

### 16. Cutler 1994, The Sipuncula（含 OCR 字距噪声）
- 路径：/Sipuncula References/Cutler, 1994-The Sipuncula.pdf，页 48（书页 33）
- 体例：3. / -；去向：种名（缩写属名，如 S. polymyotus）右对齐；**条目中间插注释行 (S. p. inclusus may have ...) 继续点线**；条目换行含软连字符 pro­cesses。
- 样例：
```
3. Elongate, filiform papillae on mid-trunk, 2 4 -3 0 L M B s. . . . S. longipapillosus
-   Trunk without elongate p a p illa e .................................... 4
6. Retractor m uscle origins united by continuous m uscle sheet (Fig. 7 A ) ..............
    ................................................................................. S. marcusi
7. 2 0 -2 4 L M B s; brain flattened, length greater than width, without distinct pro­
    cesses .............................................................................. S. norvegicus
```

### 17. Gallardo 1967 / Arias 2013 / Barbara 1959 等（命中点线页，但多为 TOC 或名录）
- Gallardo 1967（/Taxonomy/Gallardo VA/…）、Arias et al. 2013（Eurythoe）、Barbara 1959 的命中页含 key 与名录混杂；未逐篇核对（未确证）。

### 18. 日文/中文
- Sato 1935《日本動物分類·第六巻》（/Sipuncula References/Sato, 1935-日本動物分類-第六捲.pdf；Echiura references 同名）：目次含“日本産…属ノ検索表 / 種ノ検索表”，正文检索表页 p41、p77 附近（PDF 页），OCR 日文质量差，**体例未确证**（只确认有条目名“検索表”，页码为目次 35、38、42）。
- 中文检索表：本次扫描范围（A–H）未找到中文检索表 PDF；文件 /Taxonomy/Boggemann M/2005Bggemann角吻沙蚕科.pdf 为英文正文，不是中文。**中文检索表体例：未确证**。
- 德文：Augener 1913/1922/1924、Ehlers 1897/1905/1913 全文含“Bestimmungstabelle / Übersicht der”，但这些抽到的 PDF 多为合订本，命中页是昆虫/蚯蚓等无关内容，本次未取得多毛类德文表样例（未确证）。

## 二、体例频次（启发式，n=104 个命中文件前 3 个命中页，含少量 TOC 噪声）
| 特征 | 命中文件数 |
|---|---|
| 含点线（≥6 个点） | 98 |
| 1 / – 或 1. / – 式（数字行 + 破折行） | 64 |
| 另一支以 – 或 — 起首 | 24 |
| a/b（1a/1b） | 8 |
| 回指 “2 (1)” | 4 |
| a/b + 回指 “2a (1a)” | 1 |
| 1 / 1'（撇号） | 1 |

人工核对的 15 篇清楚的检索表（上节 1–16）分布：
- 数字 + 破折（1 / – ）9 篇：Böggemann 2009、Budaeva & Fauchald 2008、Choi 2020、Capa & Murray 2016、Fauchald 1986（–– 双连）、Glasby 1999（—— 多支）、Fauvel 1923/1947/1927、Cutler 1994、Bianchi 1981。
- 数字 + 破折 + 回指 “2 (1)”：Bastida-Zavala 2008。
- a/b：Bartholomew 2001（b 行省数字）、Fauchald 1977（a/b + 回指 60a (59a)）。
- 第二支不写任何标记：Hobson & Banse 1981、Banse & Hobson 1974、Day 1967。
- 年代：1923–1994 的老书多为破折体 + 页码/科名；2000s+ 期刊论文基本为 1 / –（ZooKeys/Zootaxa 一类模板）。

## 三、共同规则（从以上样本归纳；来源如各条所列）
1. 每个二歧对子由两条（偶有三条：Glasby 1999）组成，同一对子共享一个编号。
2. 第一支写编号；第二支写“–”/“—”/“——”/“--”（破折宽度不统一）或 b（a/b 体）；Hobson & Banse 完全不写。
3. 每条的去向：数字（继续）或分类单元名（终点）；终点可含作者、年、产地、图号、(see below)、(p. 30) 页码。
4. 去向通常右对齐于行尾；点线连接正文与去向；多行正文时，点线只在最后一行（Choi 2020、Capa & Murray 2016 把点线单独成行再写去向）。
5. 续行缩进（挂缩进）与第一行正文起点对齐（Glasby 1999、Fauchald 1986、Cutler 1994）。
6. 分类单元名（属/种）用斜体；科名多用大写（Day 1967、Fauchald 1977）或首字母大写（Böggemann 2009）。
7. 检索表标题：Key to ...（英），TABLEAU DES GENRES/FAMILLES（法），CHIAVE AI GENERI（意）。

## 四、值得排版工具支持的变体清单
1. 第二支标记：– / —— / -- / b / 无标记。
2. 编号：1 / 1. / 1a / 1a (59a)（带回指）/ 2 (1)。
3. 去向：数字、数字+页码、学名+作者+年、(p. N)、(Fig. N)、(see below)、“, p. 155”。
4. 同一对子 3 个分支。
5. 点线：长条目换行后点线单独成行；稀疏点（“. . .”）；无点线只留空白（Fauchald 1977）。
6. 去向后接附加行（“or *reportedly present …”、Distribution: 段落、注释行 (S. p. inclusus ...)）。
7. 条目中插入图（Capa & Murray 2016 图 11 夹在检索表中）与跨页续表（表头在上一页）。
8. 终点前缀标记（* 表示本文研究种，Fauchald 1986）。
9. 软连字符断词（gen-/erally，pro­cesses）；跨行断词不应拆学名。
10. 多语种标题。

## 五、局限
- 只看文字层，没有看图；点线是否为真点线、列对齐的像素细节未确证。
- 全库只扫了 764/2906 个文件（A–H 作者为主）；中文、德文多毛类检索表未取得样例。
- 频次表为启发式正则，非人工逐篇计数。
