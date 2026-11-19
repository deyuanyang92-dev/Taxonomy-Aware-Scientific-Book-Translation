"""ppocr 的图像变换（worker 与 scripts/ocr_review.py 共用，保证复核时重建的页面图与识别时一致）。"""

import cv2
import numpy as np


def binarize(img):
    """背景归一（除以大尺度模糊的背景）后 Otsu 二值化：去发黄底色、阴影、透印。"""
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    bg = cv2.medianBlur(cv2.dilate(g, np.ones((7, 7), np.uint8)), 31)
    n = cv2.divide(g, bg, scale=255)
    _, b = cv2.threshold(n, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return cv2.cvtColor(b, cv2.COLOR_GRAY2BGR)


def rotate90(img, deg):
    return cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE if deg == 90 else cv2.ROTATE_90_COUNTERCLOCKWISE)


def deskew(img, angle):
    h, w = img.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_CUBIC, borderValue=(255, 255, 255))


def rebuild(img, meta):
    """按缓存记录（rotated / binarized / deskew）把原始渲染图变成识别时用的图。"""
    if meta.get("rotated"):
        img = rotate90(img, meta["rotated"])
    if meta.get("binarized"):
        img = binarize(img)
    if meta.get("deskew"):
        img = deskew(img, meta["deskew"])
    return img
