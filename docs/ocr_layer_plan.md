# OCR 层软件设计 plan

日期：2026-11-22。状态：草案，待用户确认。依据：`bench/summary_150.md`（每语种 n=50，对 Datalab 金标，金标不是人工真值）、`docs/ocr_eval/LEDGER.tsv`、`test-ocr/PLAN.md`。

## 1. 目标

`docstore textify` 按资料语种自动选最优 OCR 引擎，结果写入 docstore 页面 JSON，换引擎只改路由表，不改调用方。

## 2. 现状（已核代码）

| 项 | 现状 | 出处 |
|---|---|---|
| 引擎接口 | `run(pdf_path, page_no, dpi) -> (text, conf)`，已有 rapidocr / tesseract / ppocr | `docstore/engines/__init__.py` |
| 默认引擎 | `["rapidocr", "tesseract"]`，与语种无关 | `docstore/textify.py:198` |
| Tesseract 语言包 | 按语种查表，ru/la 已按测评改为 `+eng` | `docstore/textify.py:112` |
| 云 API（PaddleOCR-VL） | 只在 `scripts/bench/paddle_api.py`，未进 docstore | 脚本 |
| 统一适配器 | 未做 | `docs/ocr_multi_engine_plan.md` §4 |

缺口：测评结论（最优引擎因语种而异）没有落到 `textify` 的默认行为上。

## 3. 引擎路由表（来自测评，CER 对 Datalab 金标）

| 语种 | 主引擎 | CER | 备选 | 依据 |
|---|---|---|---|---|
| ru | Tesseract `rus+eng`（best 模型） | 0.130 | PP-OCRv5 det + cyrillic rec 0.143 | summary_150 ru |
| fr | 本地 PP-OCRv6 medium | 0.107 | Tesseract best+eng 0.115 | summary_150 fr |
| la | 云 PaddleOCR-VL-1.6 | 0.118 | 本地 PP-OCRv6 medium 0.139 | summary_150 la |
| zh | PP-OCRv6 medium | 0.039（n=27） | - | LEDGER |
| ja | PP-OCRv6 medium | 0.048（n=14） | - | LEDGER |
| de | Tesseract `deu`（未测，沿用） | 未确证 | - | 用户 2026-11-22 取消德文测评 |
| en | 沿用现有默认 | 未测 | - | - |

注意：zh/ja 样本量小；la 主引擎依赖云端，离线时降级到本地备选。

## 4. 设计

1. **路由表放配置，不写死在代码**：新增 `docstore/rules/ocr_routes.toml`，键为语种，值为 `primary`、`fallback`、`params`、`evidence`（指向 summary 行）。`textify` 在 `engines=None` 时读它。
2. **适配器**：保持现有 `(pdf_path, page_no, dpi) -> (text, conf)` 签名，新增 `paddle_vl`（云）引擎，复用 `scripts/bench/paddle_api.py` 的调用与 `clean_md`。不另建接口，避免改动已有引擎。
3. **降级**：主引擎失败（无网络、无密钥、限流）时自动走 fallback，并在页面 JSON 的 `engine` 字段记实际用的引擎。
4. **缓存键**含引擎、版本、参数哈希、dpi（沿用 `ppocr.py` 缓存做法）。
5. **共识与质检**：`consensus.py` / `qc.py` 保持现状；融合实验（`scripts/bench/fusion_exp.py`）结论是逐页择优上界仅降 0.001–0.013，不作主路线。
6. **密钥**不入库，走环境变量（见记忆 api-keys-locations）。

## 5. 不做

- 不再扩评测配置，不做德文（用户 2026-11-22）。
- 不把 Datalab 金标当人工真值；结论一律标集名和 n。
- 不做多引擎融合作为默认路径。

## 6. 步骤与验收

| # | 步骤 | 验收命令 |
|---|---|---|
| 1 | 写 `ocr_routes.toml` 和读取函数 `route_for(lang)` | `pytest tests/test_ocr_routes.py`（每语种返回表中引擎；未知语种回落默认） |
| 2 | `textify` 在 `engines=None` 时用路由 | 现有 `tests/test_tess_lang.py` 仍过；新增路由接入用例 |
| 3 | 新增 `paddle_vl` 引擎与降级 | 模拟无密钥时降级用例；真实 la 3 页小样 |
| 4 | 小样回归：每语种 5 页，CER 与 summary_150 同口径比对 | `scripts/bench/score_runs.py` |
| 5 | `ruff check`、`mypy` 过改动文件；LEDGER 追加一行 | - |

## 7. 用户已定（2026-11-22）

1. la 默认云端 VL-1.6（免费额度），本地 PP-OCRv6 作降级。
2. en 暂不测，沿用现状（旧默认 rapidocr + tesseract）。

## 8. 进度（2026-11-22）

| # | 状态 | 证据 |
|---|---|---|
| 1 | 完成 | `docstore/rules/ocr_routes.toml`、`docstore/ocr_routes.py`、`tests/test_ocr_routes.py` |
| 2 | 完成 | `textify` 在 `engines=None` 时按语种路由；`test_tess_lang.py` 仍过 |
| 3 | 完成 | `docstore/engines/paddle_vl.py` + 降级；la 真实 2 页冒烟通过（fabr1780 p60/p150，输出长度与金标相近，18–72 s/页） |
| 4 | 未做 | 每语种 5 页 CER 回归 |
| 5 | 部分 | 新文件 ruff、mypy 通过；LEDGER 待步骤 4 后追加 |

行为变化：有路由的语种只跑单引擎，页面等级为 `ocr_raw`（旧默认是双引擎投票，可达 `ocr_sampled`）。
