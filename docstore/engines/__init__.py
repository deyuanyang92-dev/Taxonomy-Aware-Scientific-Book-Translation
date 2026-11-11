"""OCR engines for docstore."""

from .rapidocr import rapidocr_run
from .tesseract import tesseract_run

ENGINE_MAP = {
    "rapidocr": rapidocr_run,
    "tesseract": tesseract_run,
}

