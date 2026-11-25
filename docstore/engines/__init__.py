"""OCR engines for docstore."""

from .paddle_vl import paddle_vl_run
from .ppocr import ppocr_run
from .rapidocr import rapidocr_run
from .tesseract import tesseract_run

ENGINE_MAP = {
    "rapidocr": rapidocr_run,
    "tesseract": tesseract_run,
    "ppocr": ppocr_run,
    "paddle_vl": paddle_vl_run,
}

