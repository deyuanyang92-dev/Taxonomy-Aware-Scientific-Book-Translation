"""PaddleOCR AI Studio 云 API（PaddleOCR-VL，免费额度）。

密钥读环境变量 PADDLEOCR_TOKEN 或 ~/.paddleocr_aistudio_token，不入库。缺密钥或调用失败抛 RuntimeError，
由 textify 按路由表降级到本地引擎。模型名可用 DOCSTORE_PADDLE_VL_MODEL 覆盖（缺省 PaddleOCR-VL-1.6）。
返回文本经 clean_md 去 markdown/HTML 标记（与 bench 评分同口径）；云 API 不给置信度，返回 None。
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import fitz

URL = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
OPT = {"useDocOrientationClassify": False, "useDocUnwarping": False, "useChartRecognition": False}
TIMEOUT_S = 600


def clean_md(t: str) -> str:
    t = re.sub(r"!\[.*?\]\(.*?\)", "", t)
    t = re.sub(r"^#+\s*", "", t, flags=re.M)
    t = re.sub(r"</?[a-z][^>]*>", "", t)
    return re.sub(r"[*_]{1,3}", "", t)


def _token() -> str:
    tok = os.environ.get("PADDLEOCR_TOKEN")
    if tok:
        return tok.strip()
    p = Path.home() / ".paddleocr_aistudio_token"
    if p.exists():
        return p.read_text().strip()
    raise RuntimeError("缺 PaddleOCR 云密钥（PADDLEOCR_TOKEN 或 ~/.paddleocr_aistudio_token）")


def _page_pdf(pdf_path: str, page_no: int) -> bytes:
    with fitz.open(pdf_path) as src, fitz.open() as out:
        out.insert_pdf(src, from_page=page_no - 1, to_page=page_no - 1)
        return out.tobytes()


def paddle_vl_run(pdf_path: str, page_no: int, dpi: int) -> tuple[str, float | None]:
    """一页 -> 云端识别 -> 纯文本。dpi 不用（云端自行渲染）。"""
    import requests

    headers = {"Authorization": f"bearer {_token()}"}
    model = os.environ.get("DOCSTORE_PADDLE_VL_MODEL", "PaddleOCR-VL-1.6")
    try:
        r = requests.post(
            URL,
            headers=headers,
            data={"model": model, "optionalPayload": json.dumps(OPT)},
            files={"file": ("page.pdf", _page_pdf(pdf_path, page_no), "application/pdf")},
            timeout=120,
        )
        if r.status_code != 200:
            raise RuntimeError(f"PaddleOCR 云 HTTP {r.status_code}: {r.text[:200]}")
        job = r.json()["data"]["jobId"]
        t0 = time.monotonic()
        while time.monotonic() - t0 < TIMEOUT_S:
            time.sleep(3)
            k = requests.get(f"{URL}/{job}", headers=headers, timeout=60).json()["data"]
            if k["state"] == "done":
                txt = requests.get(k["resultUrl"]["jsonUrl"], timeout=120).text
                recs = [json.loads(ln)["result"] for ln in txt.strip().split("\n") if ln.strip()]
                md = "\n".join(res["markdown"]["text"] for rr in recs for res in rr["layoutParsingResults"])
                return clean_md(md), None
            if k["state"] == "failed":
                raise RuntimeError(f"PaddleOCR 云任务失败: {k.get('errorMsg')}")
        raise RuntimeError("PaddleOCR 云任务超时")
    except requests.RequestException as e:
        raise RuntimeError(f"PaddleOCR 云网络错误: {e!r}") from e
