"""
OCR-based invoice parser using PaddleOCR.
Fallback for image invoices and scanned PDFs.
"""
from __future__ import annotations

from typing import List, Optional
import os
import re

from paddleocr import PaddleOCR
from pdf2image import convert_from_path
from PIL import Image
import numpy as np

from .pdf_parser import extract_amount_from_text, extract_date_from_text

_OCR_ENGINE: Optional[PaddleOCR] = None


def get_ocr_engine(lang: str = "ch", use_gpu: bool = False) -> PaddleOCR:
    global _OCR_ENGINE
    if _OCR_ENGINE is None:
        _OCR_ENGINE = PaddleOCR(lang=lang, use_angle_cls=True, use_gpu=use_gpu)
    return _OCR_ENGINE


class OCRInvoiceParser:
    def __init__(
        self,
        file_path: str,
        lang: str = "ch",
        use_gpu: bool = False,
        max_pages: int = 2,
    ) -> None:
        self.file_path = file_path
        self.lang = lang
        self.use_gpu = use_gpu
        self.max_pages = max_pages

    def parse(self) -> dict:
        text = self._extract_text()
        return self._extract_fields(text)

    def _extract_text(self) -> str:
        if self.file_path.lower().endswith(".pdf"):
            images = self._pdf_to_images(self.file_path, self.max_pages)
        else:
            images = [Image.open(self.file_path)]

        ocr_engine = get_ocr_engine(lang=self.lang, use_gpu=self.use_gpu)
        text_lines: List[str] = []
        for image in images:
            ocr_result = ocr_engine.ocr(np.array(image), cls=True)
            for line in ocr_result:
                if not line:
                    continue
                for item in line:
                    if not item or len(item) < 2:
                        continue
                    text_lines.append(item[1][0])
        return "\n".join(text_lines)

    def _pdf_to_images(self, file_path: str, max_pages: int) -> List[Image.Image]:
        poppler_path = os.environ.get("POPPLER_PATH")
        images = convert_from_path(
            file_path,
            dpi=200,
            first_page=1,
            last_page=max_pages,
            poppler_path=poppler_path,
        )
        return images

    def _extract_fields(self, text: str) -> dict:
        result = {
            "invoice_number": "",
            "invoice_date": "",
            "amount": 0.0,
            "vendor_name": "",
            "tax_rate": "",
            "product_name": "",
            "specification_model": "",
            "unit": "",
            "quantity": "",
            "unit_price": "",
            "money_without_tax": "",
            "tax_amount": "",
            "amount_in_words": "",
            "amount_in_figures": "",
        }

        result["invoice_date"] = extract_date_from_text(text)
        amount = extract_amount_from_text(text)
        if amount:
            result["amount_in_figures"] = str(amount)
            result["amount"] = amount

        amount_words_match = re.search(r"大写[:：]?\s*([^\n\s]+)", text)
        if amount_words_match:
            result["amount_in_words"] = amount_words_match.group(1)

        tax_rate_match = re.search(r"税率[:：]?\s*([0-9]{1,2}%?)", text)
        if tax_rate_match:
            result["tax_rate"] = tax_rate_match.group(1)

        product_match = re.search(r"名称[:：]?\s*([^\n]+)", text)
        if product_match:
            result["product_name"] = product_match.group(1).strip()

        money_without_tax_match = re.search(r"不含税金额[:：]?\s*([\d.]+)", text)
        if money_without_tax_match:
            result["money_without_tax"] = money_without_tax_match.group(1)

        tax_amount_match = re.search(r"税额[:：]?\s*([\d.]+)", text)
        if tax_amount_match:
            result["tax_amount"] = tax_amount_match.group(1)

        return result
