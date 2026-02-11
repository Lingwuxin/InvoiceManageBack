"""
OCR-based invoice parser using PaddleOCR 3.x.
Fallback for image invoices and scanned PDFs.
Supports PP-OCRv5 for improved accuracy.
"""
from __future__ import annotations

from typing import List, Optional, Dict, Any
import os
import re
import logging

from paddleocr import PaddleOCR
from pdf2image import convert_from_path
from PIL import Image
import numpy as np

from .pdf_parser import extract_amount_from_text, extract_date_from_text
from .config import OCR_CONFIG

logger = logging.getLogger(__name__)

# 全局 OCR 引擎缓存
_OCR_ENGINES: Dict[str, PaddleOCR] = {}


def get_ocr_engine(
    lang: str = "ch",
    ocr_version: str = "PP-OCRv5"
) -> PaddleOCR:
    """
    获取或创建 OCR 引擎实例（单例模式）
    
    Args:
        lang: 语言，默认中文
        ocr_version: OCR 版本，'PP-OCRv3' 或 'PP-OCRv5'
    
    Returns:
        PaddleOCR 实例
    """
    global _OCR_ENGINES
    cache_key = f"{lang}_{ocr_version}"
    
    if cache_key not in _OCR_ENGINES:
        # PaddleOCR 3.x API 变化：不再使用 use_gpu, use_angle_cls, show_log 参数
        _OCR_ENGINES[cache_key] = PaddleOCR(
            lang=lang,
            ocr_version=ocr_version
        )
    return _OCR_ENGINES[cache_key]


class OCRInvoiceParser:
    """
    基于 PaddleOCR 3.x 的发票解析器
    支持图片和扫描版 PDF
    """
    
    def __init__(
        self,
        file_path: str,
        lang: str = None,
        max_pages: int = None,
        ocr_version: str = None,
    ) -> None:
        self.file_path = file_path
        # 使用配置文件的默认值
        self.lang = lang or OCR_CONFIG.get('lang', 'ch')
        self.max_pages = max_pages or OCR_CONFIG.get('max_pages', 2)
        self.ocr_version = ocr_version or OCR_CONFIG.get('ocr_version', 'PP-OCRv5')

    def parse(self) -> dict:
        """
        解析发票
        
        Returns:
            包含发票字段的字典
        """
        text = self._extract_text()
        return self._extract_fields(text)

    def _extract_text(self) -> str:
        """
        从图片或 PDF 提取文本
        
        Returns:
            提取的文本内容
        """
        if self.file_path.lower().endswith(".pdf"):
            images = self._pdf_to_images(self.file_path, self.max_pages)
        else:
            # 打开图片并转换为 RGB 模式，确保与 PDF 转换的图片格式一致
            img = Image.open(self.file_path)
            # 如果是 RGBA、P 等模式，转换为 RGB
            if img.mode not in ('RGB', 'L'):
                img = img.convert('RGB')
            assert type(img) == Image.Image
            images = [img]

        ocr_engine = get_ocr_engine(
            lang=self.lang,
            ocr_version=self.ocr_version
        )
        
        text_lines: List[str] = []
        for image in images:
            try:
                # PaddleOCR 3.x: cls 参数已移除，方向分类在初始化时配置
                ocr_result = ocr_engine.predict(np.array(image))
                logger.debug(f"OCR 结果: {ocr_result}")
            except Exception as e:
                # 记录异常但继续处理
                logger.warning(f"OCR 处理异常: {type(e).__name__}: {str(e)[:100]}")
                ocr_result = None
            
            # PaddleOCR 3.x 返回格式可能有变化，需要兼容处理
            if not ocr_result:
                continue
                
            for line in ocr_result:
                if not line:
                    continue
                for item in line:
                    if not item or len(item) < 2:
                        continue
                    # PaddleOCR 3.3.0 格式: [box, text] 或 [box, (text, confidence)]
                    # 兼容两种格式
                    if isinstance(item[1], tuple):
                        # 格式: [box, (text, confidence)]
                        text, confidence = item[1]
                    else:
                        # 格式: [box, text]
                        text = item[1]
                        confidence = 1.0  # 默认置信度
                    
                    # 只添加高置信度的文本
                    if confidence > 0.5:
                        text_lines.append(text)
        
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
if __name__ == "__main__":
    # 简单测试
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    parser = OCRInvoiceParser("D:\\Code\\InvoiceManage\\InvoiceManageBack\\media\\invoices\\过节费-张赟.pdf")
    parsed_data = parser.parse()
    logger.info(f"解析结果: {parsed_data}")