# 书籍专业术语自动抽取（ATE）技术指南

在自然语言处理（NLP）中，从整本书籍中提取专业术语与固定词组被称为**自动术语抽取（Automatic Term Extraction, ATE）**。无需将几十万字全量输入大模型，通过本地 Python 脚本即可在数秒内将全书压缩为几百到几千条高纯度候选术语表（`.tsv`），兼具零成本与高召回率。

工程上的最佳实践是采用**“本地统计与句法粗筛（过滤 98% 噪音） + 可选小规模 LLM 精排”**的两段式漏斗架构。

---

## 一、纯脚本提取的 4 种核心算法对比

不同语言与学科的书籍，其术语构词规律差异较大。通常建议将**对比语料库（领域专有度）**与**句法模板 + 嵌套评分（C-Value）**组合使用：

| 方法 | 核心原理 | 擅长提取 | 局限性 | 常用 Python 工具 |
| :--- | :--- | :--- | :--- | :--- |
| **对比语料库法**<br>(Weirdness / Zipf 差值) | 比较词条在“本书词频”与“通用语料词频”的差值或比值 | **专业单词**、拉丁词根词、德语复合词 | 对由普通高频词组成的专业词组（如 *blind gut*）敏感度低 | `wordfreq`（支持 40+ 语种） |
| **句法规则 + C-Value** | 按词性模板抓取名词短语，再用 C-Value 扣除被更长术语嵌套的频次 | **多词专业词组**（自动区分 *anterior ventral cirrus* 与碎片 *ventral cirrus*） | 依赖词性标注准确度；单字/单词需额外算分 | `spaCy`、`pyate`、手写 C-Value |
| **无监督关键词提取**<br>(YAKE / RAKE / TextRank) | 利用词位、共现图或大小写特征打分 | 快速出草稿、不依赖外部词表 | 对整本书噪音较大，容易混入高频章节名和过渡词 | `yake`、`pke` |
| **正则 + 形态特征** | 匹配斜体、括号定义（如 `X (Y)`）、特定词缀（`-idae`, `-morph` 等） | 学科专名、缩写、首次出现带定义的术语 | 覆盖率有限，适合作为补充召回层 | `re` |

---

## 二、核心算法与工程设计思路

针对学术专著或技术书籍，推荐采用 **“句法候选召回 + `wordfreq` 领域专有度 + C-Value 嵌套去噪 + 原书例句回溯”** 流程：

1. **专业单词识别**：通过 `本书 Zipf 频率 - 通用语料 Zipf 频率` 的差值排序。专业词汇在通用语料库中通常极其罕见（Zipf 值低于 $3.5$），但在专业书中高频出现，极易区分。
2. **多词短语与 C-Value 去噪**：先通过词性模板（如 `(Adj/Noun)+ Noun`）完整抓取短语，再使用 **C-Value** 算法剔除“仅作为长词组的一部分、本身不独立成词”的伪短语碎片：
   $$\text{C-value}(a) = \log_2 |a| \cdot \left( f(a) - \frac{1}{|T_a|} \sum_{b \in T_a} f(b) \right)$$
   * $|a|$：短语包含的词数；
   * $f(a)$：短语在全书中的出现频次；
   * $T_a$：包含短语 $a$ 的所有更长候选词组集合。
3. **保留原书上下文例句**：在抽取词条时顺手记录它首次出现的句子。这能为后续人工复核或大模型批量翻译/分类提供消歧依据，彻底解决一词多义问题。

---

## 三、完整可运行 Python 脚本

### 1. 环境安装

以英文书籍为例，安装 `spaCy` 与 `wordfreq` 并下载基础英文语言模型：

```bash
pip install spacy wordfreq
python -m spacy download en_core_web_sm
```

### 2. 抽取脚本（`extract_terms.py`）

将书籍转为纯文本 `book.txt` 后运行以下脚本，输出按重要度排序的 `terms_candidates.tsv`：

```python
import csv
import math
import re
from collections import Counter, defaultdict
import spacy
from spacy.matcher import Matcher
from wordfreq import zipf_frequency


def extract_terms(
    text_path: str,
    out_tsv: str,
    lang: str = "en",
    spacy_model: str = "en_core_web_sm",
    min_freq: int = 3,
):
    # 关闭用不到的 NER 模块以大幅提升处理整本书的速度
    nlp = spacy.load(spacy_model, disable=["ner"])
    nlp.max_length = 5_000_000

    # 1. 定义名词短语词性模板: (形容词/名词/专有名词)+ 名词/专有名词
    matcher = Matcher(nlp.vocab)
    matcher.add(
        "TERM_NP",
        [
            [
                {"POS": {"IN": ["ADJ", "NOUN", "PROPN"]}, "OP": "+"},
                {"POS": {"IN": ["NOUN", "PROPN"]}},
            ]
        ],
    )

    with open(text_path, "r", encoding="utf-8") as f:
        raw_text = f.read()

    # 按空行切分段落，利用 nlp.pipe 流式批处理防止内存溢出
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", raw_text) if p.strip()]

    word_freq = Counter()
    phrase_freq = Counter()
    sample_context = {}
    total_tokens = 0

    for doc in nlp.pipe(paragraphs, batch_size=64):
        for sent in doc.sents:
            sent_text = re.sub(r"\s+", " ", sent.text.strip())

            # 统计实词词元（合并单复数）
            for tok in sent:
                if tok.is_alpha and not tok.is_stop and len(tok.text) >= 3:
                    total_tokens += 1
                    if tok.pos_ in {"NOUN", "PROPN", "ADJ"}:
                        lemma = tok.lemma_.lower()
                        word_freq[lemma] += 1
                        sample_context.setdefault(lemma, sent_text[:220])

            # 匹配多词专业短语候选
            matches = matcher(sent)
            for _, start, end in matches:
                span = sent[start:end]
                if 2 <= len(span) <= 5 and all(t.is_alpha or t.text == "-" for t in span):
                    # 仅对中心词（末词）做词元化合并复数，修饰词保留原形以维持固定搭配
                    norm_tokens = [t.text.lower() for t in span[:-1]] + [span[-1].lemma_.lower()]
                    phrase = " ".join(norm_tokens)
                    phrase_freq[phrase] += 1
                    sample_context.setdefault(phrase, sent_text[:220])

    # 2. 计算多词短语的 C-Value（从最长短语向短短语逐级扣除嵌套频次）
    cand_phrases = {p: c for p, c in phrase_freq.items() if c >= min_freq}
    sorted_phrases = sorted(cand_phrases.keys(), key=lambda x: len(x.split()), reverse=True)

    nested_sum = defaultdict(int)
    nested_cnt = defaultdict(int)
    c_values = {}

    for p in sorted_phrases:
        words = p.split()
        f_p = cand_phrases[p]
        if nested_cnt[p] == 0:
            score = math.log2(len(words)) * f_p
        else:
            score = math.log2(len(words)) * (f_p - nested_sum[p] / nested_cnt[p])
        c_values[p] = round(score, 2)

        # 将当前长短语的频次贡献给它的所有连续子短语
        n = len(words)
        for i in range(n):
            for j in range(i + 2, n + 1):
                if i == 0 and j == n:
                    continue
                sub = " ".join(words[i:j])
                if sub in cand_phrases:
                    nested_sum[sub] += f_p
                    nested_cnt[sub] += 1

    # 3. 计算领域专有度（书内 Zipf 频率 - 通用语料 Zipf 频率）
    def domain_specificity(term: str, freq: int) -> float:
        book_zipf = math.log10((freq / max(total_tokens, 1)) * 1e9)
        parts = term.split()
        # 取词组中最生僻实词的通用词频，避免常用介词/形容词拉高基准线
        gen_zipf = min(zipf_frequency(w, lang) for w in parts)
        return round(book_zipf - gen_zipf, 2)

    rows = []

    # 筛选多词短语
    for p, f in cand_phrases.items():
        spec = domain_specificity(p, f)
        if c_values[p] >= 2.0 and spec >= 1.0:
            rows.append(("phrase", p, f, spec, c_values[p], sample_context.get(p, "")))

    # 筛选高专有度单词（通用 Zipf < 3.5 的生僻或专业词汇）
    for w, f in word_freq.items():
        if f >= min_freq and zipf_frequency(w, lang) < 3.5:
            spec = domain_specificity(w, f)
            if spec >= 2.0:
                rows.append(("word", w, f, spec, 0.0, sample_context.get(w, "")))

    # 综合排序（优先展示有效短语，并结合专有度与频次对数）
    rows.sort(key=lambda r: (r[4] > 0, r[3] + math.log2(r[2] + 1)), reverse=True)

    with open(out_tsv, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(["type", "term", "freq", "specificity", "c_value", "sample_context"])
        writer.writerows(rows)

    print(f"Done: extracted {len(rows)} candidates -> {out_tsv}")


if __name__ == "__main__":
    extract_terms("book.txt", "terms_candidates.tsv", lang="en")
```

---

## 四、多语种适配与进阶调优技巧

### 1. 不同语种的分词与模板微调

* **西班牙语 / 法语**（`es_core_news_sm` / `fr_core_news_sm`）：形容词通常位于名词之后，且大量学术术语依赖介词连接。需将 `Matcher` 模板修改为 `NOUN + ADJ+` 以及 `NOUN + (de/del/d') + NOUN`。
* **德语**（`de_core_news_sm`）：德语复合名词天然连写成一个长词，单靠 `wordfreq` 专有度差值即可精准捞出绝大多数专业词汇；同时可利用“名词首字母大写”规则直接过滤非名词噪音。
* **日语**：切忌使用默认细粒度分词（会把长复合术语切碎）。建议使用 `SudachiPy` 并指定 **`SplitMode.C`（最长单位切分）**，再将连续的 `名詞`（或 `接頭辞 + 名詞+ + 接尾辞`）合并成块，同时单独提取连续片假名词组，对自然科学与人文专著效果极佳。
* **中文**：优先使用 `pkuseg`（加载医学/生物/领域词典）或 `hanlp`；若属于极冷门细分学科，建议直接使用**“互信息（PMI）+ 左右信息熵”**做无词典新词发现，无需依赖任何预置词表即可统计出高紧密度专有词组。

### 2. 数据清洗与去噪技巧

* **过滤人名、地名与参考文献噪音（章节分散度）**：将全书按章节或每 $5,000$ 词切分为若干块，统计每个候选词出现在多少个分块中。仅在单一页面集中出现 10 次的词多半是采样地名或引文作者；跨越 3 个以上章节出现的词大概率是核心术语。
* **OCR 历史文献错字合并**：若文本来自扫描版 PDF 的 OCR 识别，可在输出前引入 `rapidfuzz`，将编辑距离为 $1$ 且首字母相同的低频候选词自动归并到高频词条下（例如将 `cirrns` 合并进 `cirrus`）。
* **极低成本 LLM 精修**：脚本跑完后通常仅剩 $1,000 \sim 3,000$ 行 `.tsv`。将其按每批 $100$ 条发送给廉价快速模型，要求返回结构化 JSON（包含 `is_term`、`domain_tag`、`zh_translation`），整本书的术语表精修成本仅需几分钱，且准确率接近人工编纂。