"""PP-OCRv5 常驻子进程（在装有 paddleocr 的独立 venv 里运行，不进 docstore 主环境）。

stdin 每行一个 PNG 路径；stdout 每行一个 JSON 数组 [[box4点, 文本, 置信度], ...]。
模型名由 argv[1] 给出（缺省 PP-OCRv5_server），PP-OCRv5 单模型覆盖简繁中文、日文、英文。
"""

import json
import os
import sys

from ppocr_img import binarize, deskew, rotate90  # 同目录（worker 以脚本方式运行）

from paddleocr import PaddleOCR

model = sys.argv[1] if len(sys.argv) > 1 else "PP-OCRv5_server"
_kw = dict(
    text_detection_model_name=model + "_det",
    text_recognition_model_name=model + "_rec",
    use_doc_orientation_classify=False,
    use_doc_unwarping=False,
    use_textline_orientation=False,
)
# 检测框外扩比例（缺省 1.5）；行末单字被截时调大（DOCSTORE_PPOCR_UNCLIP）
if os.environ.get("DOCSTORE_PPOCR_UNCLIP"):
    _kw["text_det_unclip_ratio"] = float(os.environ["DOCSTORE_PPOCR_UNCLIP"])
# 调参扫描：DOCSTORE_PPOCR_PARAMS='{"text_det_thresh":0.2,"use_textline_orientation":true}' 覆盖上面任何构造参数
if os.environ.get("DOCSTORE_PPOCR_PARAMS"):
    _kw.update(json.loads(os.environ["DOCSTORE_PPOCR_PARAMS"]))
ocr = PaddleOCR(**_kw)


def run(img):
    r = ocr.predict(img)[0]
    return [[[[float(x), float(y)] for x, y in poly], str(t), float(s)]
            for poly, t, s in zip(r["rec_polys"], r["rec_texts"], r["rec_scores"])]


def score(rows):
    return sum(s * len(t) for _, t, s in rows)


def looks_rotated(rows):
    """整页转了 90°（横排的表、图）：竖长框（高 > 1.5 宽）占有字框的 4 成以上，且平均置信度 < 0.75。"""
    big = [r for r in rows if len(r[1]) >= 3]
    if len(big) < 5:
        return False
    tall = sum(1 for poly, _, _ in big
               if (max(p[1] for p in poly) - min(p[1] for p in poly)) > 1.5 * (max(p[0] for p in poly) - min(p[0] for p in poly)))
    return tall >= 0.4 * len(big) and sum(r[2] for r in big) / len(big) < 0.75


def mean_conf(rows):
    return sum(r[2] for r in rows) / len(rows) if rows else 0.0


def skew_angle(rows):
    """长行框上边倾角的中位数（度）；长行不足 5 条返回 0。"""
    import math

    angs = sorted(math.degrees(math.atan2(p[1][1] - p[0][1], p[1][0] - p[0][0]))
                  for p, _, _ in rows if p[1][0] - p[0][0] > 200)
    return angs[len(angs) // 2] if len(angs) >= 5 else 0.0


def adaptive(img, rows, info):
    """难扫描件自适应（bench/quality.py 评测：退化页平均 CER 13.7%→3.9%，清晰页不变）：
    1) 平均置信度 < 0.93 时用二值化图再识别，取「置信度×字数」高者（去透印：41%→0.5%）；
    2) 倾角 > 0.8° 时纠斜重识（倾斜 2° 的页 14.2%→0.3%；阈值 0.3° 会误纠正常页）。"""

    work = img
    mc = mean_conf(rows)
    # 插图页（字少）不做二值化：二值化会多检出低置信乱码，「置信度×字数」反而更高（Imajima2001 p.78：5→49 字，置信 0.68→0.41）
    if mc < 0.93 and sum(len(r[1]) for r in rows) >= 80:
        b = binarize(img)
        rb = run(b)
        if score(rb) > score(rows) and mean_conf(rb) >= mc - 0.01:
            rows, work, info["binarized"] = rb, b, True
    a = skew_angle(rows)
    if abs(a) > 0.8:
        dw = deskew(work, a)
        rd = run(dw)
        if mean_conf(rd) >= mean_conf(rows) - 0.02:  # 纠斜后置信度明显下降则退回
            rows, work, info["deskew"] = rd, dw, round(a, 2)
    return rows, work


ADAPTIVE = os.environ.get("DOCSTORE_PPOCR_ADAPTIVE", "1") != "0"
print("READY", flush=True)
for line in sys.stdin:
    path = line.strip()
    if not path:
        continue
    try:
        import cv2

        img = cv2.imread(path)
        rows = run(img)
        info = {"width": img.shape[1]}
        if looks_rotated(rows):  # 整页转了 90°：试两个方向，取「置信度×字数」最高者
            best = (score(rows), rows, 0, img)
            for deg in (90, 270):
                im = rotate90(img, deg)
                rr = run(im)
                if score(rr) > best[0]:
                    best = (score(rr), rr, deg, im)
            _, rows, deg, img = best
            if deg:
                info["rotated"] = deg
                info["width"] = img.shape[1]
        if ADAPTIVE:
            rows, img = adaptive(img, rows, info)
        print(json.dumps({"rows": rows, **info}, ensure_ascii=False), flush=True)
    except Exception as e:  # noqa: BLE001 — 一页失败不拖垮常驻进程
        print(json.dumps({"error": repr(e)}), flush=True)
