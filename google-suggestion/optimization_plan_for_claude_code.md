# Taxonomy-Aware Scientific Book Translation 系統優化方案（給 Claude Code 執行清單）

> **適用專案**：[Taxonomy-Aware-Scientific-Book-Translation](https://drive.google.com/drive/folders/11hDuVsft1u9BW8IHLTQl-7UBYJILuL_e)
> **整理日期**：2026-11-19
> **核心目標**：(1) Google 翻譯初譯極速且抗限流；(2) LLM 校對大幅省 Token；(3) 排版修版實現秒級預覽；(4) 修復多進程併發與分類學 QA 漏洞。
> **執行規範（遵循倉庫 `AGENTS.md`）**：所有改動須補齊單元測試，執行 `python3 -m pytest -q tests yiku/tests` 全過，新程式碼通過 `ruff check` 與 `mypy`；不刪除或覆蓋任何使用者資料；改動 `scripts/` 或 `skill/` 後視需要同步。

---

## 一、實測基準數據與瓶頸定位

以下數據來自對倉庫原始檔案的本機沙箱實測與 `cProfile` 熱點剖析（註：測試環境無對外網路，Google 翻譯網路層以本機多執行緒 HTTP 伺服器模擬；其餘 SQLite、`taxoblocks.risk()`、400 頁 `python-docx` 建置與 LibreOffice PDF 轉檔均為真實執行）：

| 模組與測試場景 | 現有實作實測 | 優化方案實測 | 根因與影響 |
|---|---|---|---|
| `transqa/taxoblocks.py` 德→英（100 段正確譯文） | **67/100 誤報**（`number: 67`） | **0/100 誤報** | `_NUM` 未正規化德文小數逗號 `1,5` 與千分位 `1.200`，三分之二乾淨段落白送 LLM。 |
| `transqa/taxoblocks.py` 英→中（100 段正確譯文） | **100/100 誤報**（`term: 100, length: 100, name: 50`） | **0/100 誤報** | 譯成中文時長度比 `0.6–1.6` 與 `\w` 詞邊界導致 `--risky-only` **完全失效**；`Dorsal cirrus` 等詞組被 `_EPITHET` 誤判為拉丁雙名。 |
| `scripts/gtrans.py` SQLite 快取寫入（2,000 段，8 執行緒） | `0.096s`（逐段 `commit`） | `0.050s`（批次 50 段 + `NORMAL`） | **快 1.9×**；預查改 `SELECT IN` 從 `0.010s` 降至 `0.005s`（在 WSL `/mnt/p` 磁碟上效益更大）。 |
| `scripts/gtrans.py` HTTP 請求（1,000 次，8 執行緒） | `1.038s`（`urllib` 短連線） | `0.646s`（`http.client` 長連線） | 僅本機 TCP 即**快 1.6×**；真實 HTTPS 省去每段 TLS 握手後加速更顯著。 |
| `scripts/auto_translate.py` `stage_draft` 去重（5,000 段） | `0.076s`（`list` $O(N^2)$） | `0.0011s`（`set` $O(1)$） | **快 71×**。 |
| `booklayout/builder.py` 400 頁 DOCX 建置（350 屬、40 圖） | `7.12s`（`add_runs` 佔 CPU **78.2%**） | 5 頁局部預覽 **`0.097s`** | `cProfile` 顯示 `add_runs` 對每個 run 重複寫預設字體/字號/粗斜體，觸發 `124,712` 次 `first_child_found_in`（3.43s）與 `2,249,384` 次 `qn()`（1.00s）。 |
| 排版修改後看 PDF（DOCX + LibreOffice 端到端） | 全書 `11.75s`（實務 500 頁大圖為 60–110s） | 5 頁局部預覽 **`1.48s`** | 端到端**快 7.9×**（實務大書與兩遍排版相比可快 **40× 以上**）。 |

---

## 二、P0 優先級：排版秒級預覽與 DOCX 建置提速

### 任務 1：新增 `booklayout` 局部快排預覽（`--pages` / `--chapter`）與即時 HTML 預覽
* **目標檔案**：[booklayout/cli.py](https://drive.google.com/file/d/1alzv9gopI9cc597XDhTfGjb6QvptVrwp/view?usp=drivesdk)、[booklayout/builder.py](https://drive.google.com/file/d/1w7HpAdnPBnpJ3PeF12I9rX9MLVz_mFjD/view?usp=drivesdk)
* **痛點**：目前只要改動 1 行譯文或 1 條檢索表，就必須重排整本 400–600 頁 DOCX 並跑 LibreOffice 轉整本 PDF（單遍 60–110 秒，兩遍 2–4 分鐘）。
* **具體改動**：
  1. 在 `booklayout build` 新增可選參數 `--pages <SPEC>`（支援 `277`、`275-280`、`12,45-48`）、`--chapter <NAME>` 與 `--preview`（自動跳過 `front_matter`、目錄與 `render_index`，僅編譯目標頁，預設前後各多帶 1 頁檢查跨頁接縫）。
  2. 新增 `booklayout preview` 子命令（快捷封裝）：
     * 預設 `--format html`：直接讀 `aligned.json` 與對應頁的 `source_figure_crops/`，產出單頁輕量 HTML/CSS（套用 `@page { size: 170mm 240mm; }`、版心 `134mm`、字號、右對齊點線檢索表、圖注樣式），耗時 **< 50 ms**，支援 `--watch` 監聽 `aligned.json` 變動自動重新整理。
     * 加 `--pdf` 時走局部 DOCX + LibreOffice 轉檔，約 **1.5–2 秒** 即可核對真實斷行與詞距。
  3. 完整交付仍維持既有的兩遍 `build -> map-pages -> build -> qa -> check`。
* **驗收標準**：
  * `booklayout build --pages 200-204 --preview --pdf` 僅輸出指定頁段，不產生空頁，端到端耗時 < 3 秒。
  * 新增測試覆蓋頁碼解析（單頁、區間、逗號組合）與跨頁銜接不崩潰。

### 任務 2：精簡 `builder.py` 的 `add_runs()` 冗餘 XML 寫入
* **目標檔案**：[booklayout/builder.py](https://drive.google.com/file/d/1w7HpAdnPBnpJ3PeF12I9rX9MLVz_mFjD/view?usp=drivesdk)
* **根因**：`setup()` 已在 `Normal` 樣式設定預設字體（`BODY_FONT`、`CJK_FONT`）與字號 `10.5pt`，但 `add_runs()` 仍對每個 run 強制寫入 `run.font.name`、`rFonts.set(eastAsia)`、`run.font.size`、`run.bold`、`run.italic`，造成 78.2% 的建置時間耗在 `python-docx` XML 節點查找。
* **具體改動**：
  * 預設值（`size == 10.5`、`bold is False`、`ital is False`、`color is None` 且不含漢字）直接繼承 `Normal` 樣式，不重複寫入對應 `w:rPr` 子節點。
  * 僅在非預設字號、粗體、斜體、自訂顏色或 `_CJK.search(chunk)` 命中時才寫入相應屬性。
  * 同時將 `add_runs()` 內的屬名正則編譯提至 `genera` 級別快取（避免 `genera` 集合超過 `re` 內部快取或重複排序 `sorted(genera)`）。
* **驗收標準**：
  * 既有 `tests/test_booklayout.py` 全部通過，產出 DOCX 在 Word 與 LibreOffice 顯示字體、字號、斜體與中文字元完全一致；400 頁 DOCX 建置時間顯著下降。

---

## 三、P0 優先級：校對極省 Token 優化

### 任務 3：修復 `transqa/taxoblocks.py` 的 `risk()` 誤報（讓 `--risky-only` 真正省 Token）
* **目標檔案**：[transqa/taxoblocks.py](https://drive.google.com/file/d/1pu_9e7PFDgtDqm6zP_rezo3_Ino-bS1A/view?usp=drivesdk)、[transqa/terms.py](https://drive.google.com/file/d/18eVa9B1QarkODhD12WZBB2nY2mgy1xh4/view?usp=drivesdk)
* **具體改動**：
  1. **數字正規化**：`taxoblocks.risk()` 移除簡陋的 `_NUM.findall()` 字串比對，改為直接呼叫 `transqa.core.numbers()`（統一處理千分位與小數逗號 `1,5` ↔ `1.5`）。
  2. **目標語自適應長度比**：短於 40 字元的段落不做長度比檢查；目標語為中文（`tl.startswith("zh")`）時長度比區間改為 `(0.18, 0.70)`，拉丁語系間維持 `(0.55, 1.70)`。
  3. **CJK 術語匹配修復**：`taxoblocks.py` 的 `has()` 與 `transqa/terms.py` 的 `normalize()` 偵測到 CJK 術語時不使用 `(?<!\w)...(?!\w)`（因 Python 的 `\w` 包含漢字，會導致無空格中文譯文完全匹配不到）；拉丁詞仍保留左詞邊界防誤傷。
  4. **收緊 `_EPITHET` 學名誤報**：在 `_STOP_EPI` 與首詞過濾名單中排除常見英文形態學開頭詞（如 `Dorsal`, `Ventral`, `Lateral`, `Anterior`, `Posterior`, `Median`, `Body`, `Prostomium` 等），避免 `Dorsal cirrus` 被當成拉丁雙名。
* **驗收標準**：
  * 針對德→英（含小數逗號/千分位）與英→中正確翻譯樣本，`risk()` 誤報率降至接近 0%；同時真正漏數字、漏否定詞、漏學名或漏術語的測試樣本 100% 仍被檢出。

### 任務 4：校對改為「跨頁緊湊打包 + 局部視窗 Judge + 精簡輸出」
* **目標檔案**：[scripts/auto_translate.py](https://drive.google.com/file/d/1sLo_76p0664ixWw5nszh4pbTvqeYcm-r/view?usp=drivesdk)、[scripts/fast_book.py](https://drive.google.com/file/d/13BtUWmxXfHYxrmFuQ3eQZkszpo-qCbP9/view?usp=drivesdk)、[scripts/gtrans.py](https://drive.google.com/file/d/13Ay36MQEW44c5IvHEtKJ6Krb19hKVAQt/view?usp=drivesdk)
* **具體改動**：
  1. **跨頁緊湊打包（`auto_translate.py`）**：`stage_revise()`（Lean 模式）與 `stage_check()`（`--risky-only`）改為先全書分流，再將真正要送模型的段落帶上 `⟦pN_sM⟧` ID 依目標字元數（例如 `3,000–4,000` 字元）動態打包成批次，不再按固定 3 頁切塊導致 1 句話就發一次 API。
  2. **局部視窗 Judge（`auto_translate.py`）**：
     * `--lean` 模式下預設 `--verify-mode judge`（第一模型未報錯則 **0 token 跳過第二模型**）。
     * `judge` 模式呼叫第二模型時，不再傳整塊 3 頁的 `Original + Translation`，改為僅截取每條候選 edit 所在的該頁/該段前後各 1 段作為局部視窗，預期再省 70%–85% 複核輸入 Token。
  3. **分層異模型複核（`fast_book.py`）**：將全書 `--allow-same-verify` 升級為可選分層策略——一般頁走快審，僅對 `negation_risk` 頁、檢索表頁與 `critical` 候選啟用異模型複核。
  4. **關閉不必要的輔助 LLM 呼叫與壓縮輸出**：
     * `--lean` 預設開啟 `--no-entities`（不額外花 LLM 抽專名，改靠本地 `yiku` 查表）。
     * `gtrans.py` 新增 `--lean` 或讓省 Token 場景走 `--llm-mode edits`（差量 JSON 改動，不整段重寫，輸出 Token 省 80%+），並將 `max_tokens` 統一接入 `token_economy.out_budget("json")`（避免寫死 `16000`），同時前置接入 `transqa.terms.normalize()` 做 0-token 清理。
* **驗收標準**：
  * `auto_translate.py` 測試通過；`judge` 模式在 `edits=[]` 時確認不觸發第二模型呼叫；輸出 `report.md` 清楚記錄跨頁打包後的實際批次數與 Token 節省量。

---

## 四、P1 優先級：Google 翻譯極速與穩定優化

### 任務 5：升級 `gtrans.py` 連線池、批次快取與術語預取
* **目標檔案**：[scripts/gtrans.py](https://drive.google.com/file/d/13Ay36MQEW44c5IvHEtKJ6Krb19hKVAQt/view?usp=drivesdk)、[scripts/auto_translate.py](https://drive.google.com/file/d/1sLo_76p0664ixWw5nszh4pbTvqeYcm-r/view?usp=drivesdk)
* **具體改動**：
  1. **標準庫 Keep-Alive 連線池**：保留標準庫（不改用易觸發 429 的 `requests`），將 `http_get()` 升級為以 `threading.local()` 維護 `http.client.HTTPSConnection` 長連線（支援 `Accept-Encoding: gzip` 解壓、連線中斷/RemoteDisconnected 時自動重建重試一次）。
  2. **SQLite 快取批次化**：
     * `Cache.__init__` 新增 `PRAGMA synchronous=NORMAL`（WAL 模式下安全且大幅減少 fsync 延遲）。
     * 新增 `Cache.missing_keys(texts)`：以每批 500 鍵執行 `SELECT key FROM cache WHERE key IN (...) AND trim(zh) != ''`，取代 `prefetch()` 開頭的 N 次單條查詢。
     * 新增 `Cache.put_many()` 或緩衝寫入：在 `prefetch()` 中每累積 30–50 筆（或超過 2 秒、`finally` 結束前）批次 `executemany` + `commit`，兼顧高速與斷點續跑安全。
  3. **術語探測併入併發預取**：在 `gtrans.py` 的 `run()` 預取階段，先收集所有單元的 `HARD` 術語清單一併丟進 `g.prefetch()`，避免主迴圈中 `self.g.term()` 在 `pause=(1.0, 2.0)` 下同步慢等。
  4. **雙端點分流與自適應併發**：正常時將流量分攤給 `translate.googleapis.com` 與 `clients5.google.com`；單一端點吃 429 只冷卻該端點並暫降併發，避免全體執行緒同時停擺；對極短段（如標題、術語）可選用 `clients5` 多 `q=` 參數批次查詢。
  5. **修復 `auto_translate.py` `stage_draft()` 的 $O(N^2)$ 掃描**：將 `if s.text in send` 改為 `send_set = set(send)`。
* **驗收標準**：
  * `tests/test_gtrans.py` 與 `tests/test_auto_translate.py` 全過；新增本地 mock server 測試驗證 Keep-Alive 連線複用、斷線自動重連與批次快取寫入一致性。

---

## 五、P2 優先級：多進程併發安全與分類學 QA 補完

### 任務 6：修復多進程 `usage.tsv` 寫鎖、跨進程預算與 API Client 複用
* **目標檔案**：[scripts/llm_engines.py](https://drive.google.com/file/d/1npnThJRT4S28Nw83NYQLKwlKiEcOgatG/view?usp=drivesdk)、[scripts/token_economy.py](https://drive.google.com/file/d/1opOJ4fZfjP5n9dG7GhO4rNv1_e1nlNHw/view?usp=drivesdk)、[scripts/auto_translate.py](https://drive.google.com/file/d/1sLo_76p0664ixWw5nszh4pbTvqeYcm-r/view?usp=drivesdk)、[scripts/fast_book.py](https://drive.google.com/file/d/13BtUWmxXfHYxrmFuQ3eQZkszpo-qCbP9/view?usp=drivesdk)
* **具體改動**：
  1. `llm_engines.py` 的 `log_usage()` 改用跨進程檔案鎖（Unix `fcntl.flock` / Windows `msvcrt.locking`），防止 `fast_book.py chapters` 多進程同時寫壞 `usage.tsv`。
  2. `llm_engines._deepseek()` 改用 thread-local / 單例 `anthropic.Anthropic` Client 複用連線池；並新增顯式參數 `thinking: bool | None = None`，取代 `auto_translate.py` 在多執行緒中修改全域 `os.environ`。
  3. `auto_translate.py` 的 `_ask_json()` 區分「JSON 格式解析失敗」（立即重試 + 附格式提醒）與「API 429/5xx」（指數退避 + 隨機 jitter），不再一律空等 30–90 秒。
  4. `auto_translate.py` 的 `apply_edits()` 改為按頁字典替換再 `whole(pt)` 重組，取代迴圈內重複 `pages(tgt)` 與全域字串 `replace`。
  5. `fast_book.py chapters` 結束後自動合併各章的 `report.md`、`usage.tsv` 與 `human_review_queue.csv` 至總工作目錄，並把 `YZZ_TOKEN_BUDGET` 按章拆分或共享。

### 任務 7：補齊 `transqa/taxonomy.py` 動物學三名法與檢索表相容性
* **目標檔案**：[transqa/taxonomy.py](https://drive.google.com/file/d/10Ybr-ve0ICdufn2pi9fqdkt1chdcwXYy/view?usp=drivesdk)
* **具體改動**：
  1. `latin_names()` 支援 ICZN 動物學三名法（不帶 `subsp.` 的 `*Genus species subspecies*`）與常見插入縮寫（`cf.`、`aff.`、`s.l.`、`s.str.`）。
  2. `key_edges()` 與 `auto_translate.py` 的 `key_structure()` 統一檢索表匹配規則：不再強制要求粗體 `**1(2)`，同時相容無粗體 `1(2)` 與 `1a.`/`1b.` 格式。
  3. `auto_translate.py` 並行改寫各塊時，於串行準備階段注入只讀的「上頁末段 + 最近上級分類標題（科/屬名）」作為 `CONTEXT (do not translate)`，減少跨頁代詞與縮寫屬名誤譯。

---

## 六、建議給 Claude Code 的執行順序

1. **第一批（立即可見體感差異）**：任務 1（`booklayout` 局部預覽）+ 任務 2（`add_runs` 精簡）→ 立刻解決排版改一點等很久的痛點。
2. **第二批（立刻省下大部分校對 Token）**：任務 3（`taxoblocks.risk()` 零誤報修復）+ 任務 4（跨頁打包與局部視窗 Judge）。
3. **第三批（Google 翻譯提速與多進程加固）**：任務 5（`gtrans.py` 長連線 + 批次快取 + 術語預取）+ 任務 6 & 7（併發鎖與分類學 QA 補完）。

每批完成後請執行 `python3 -m pytest -q tests yiku/tests`、`ruff check`、`mypy`，確認全綠後再進入下一批。
