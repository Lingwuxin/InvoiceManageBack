"""
基于 PP-StructureV3 的发票结构化解析器
支持复杂表格、版面分析和关键信息提取
"""
from __future__ import annotations

from typing import List, Dict, Any, Optional
import os
import re

from paddleocr import PPStructureV3
from pdf2image import convert_from_path
from PIL import Image
import numpy as np

from .pdf_parser import extract_amount_from_text, extract_date_from_text
from .config import STRUCTURE_CONFIG, INVOICE_CONFIG

# 全局 Structure 引擎缓存
_STRUCTURE_ENGINE: Optional[PPStructureV3] = None


def get_structure_engine() -> PPStructureV3:
    """
    获取或创建 PP-StructureV3 引擎实例（单例模式）
    
    Returns:
        PPStructureV3 实例
    """
    global _STRUCTURE_ENGINE
    
    if _STRUCTURE_ENGINE is None:
        # PaddleOCR 3.x API: PPStructureV3 不再接受参数
        _STRUCTURE_ENGINE = PPStructureV3()
    
    return _STRUCTURE_ENGINE


class StructureInvoiceParser:
    """
    基于 PP-StructureV3 的发票解析器
    支持复杂表格、版面分析和智能字段提取
    """
    
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
        self.structure_result = None

    def parse(self) -> dict:
        """
        解析发票，提取结构化信息
        
        Returns:
            包含发票字段的字典
        """
        # 1. 执行结构化识别
        self.structure_result = self._extract_structure()
        
        # 2. 从结构化结果中提取字段
        return self._extract_fields_from_structure()

    def _extract_structure(self) -> List[Dict[str, Any]]:
        """
        使用 PP-StructureV3 提取文档结构
        
        Returns:
            结构化识别结果列表
        """
        if self.file_path.lower().endswith(".pdf"):
            images = self._pdf_to_images(self.file_path, self.max_pages)
        else:
            images = [Image.open(self.file_path)]

        structure_engine = get_structure_engine()
        
        all_results = []
        for image in images:
            result = structure_engine(np.array(image))
            if result:
                all_results.extend(result)
        
        return all_results

    def _pdf_to_images(self, file_path: str, max_pages: int) -> List[Image.Image]:
        """将 PDF 转换为图片"""
        poppler_path = os.environ.get("POPPLER_PATH")
        dpi = INVOICE_CONFIG.get('pdf_dpi', 200)
        
        images = convert_from_path(
            file_path,
            dpi=dpi,
            first_page=1,
            last_page=max_pages,
            poppler_path=poppler_path,
        )
        return images

    def _extract_fields_from_structure(self) -> dict:
        """
        从 PP-Structure 结果中提取发票字段
        
        Returns:
            字段字典
        """
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

        if not self.structure_result:
            return result

        # 提取所有文本和表格
        all_text = []
        tables = []
        
        for item in self.structure_result:
            if item['type'] == 'text':
                # 提取文本区域的 OCR 结果
                if 'res' in item:
                    for line in item['res']:
                        if 'text' in line:
                            all_text.append(line['text'])
            
            elif item['type'] == 'table':
                # 提取表格内容
                if 'res' in item:
                    tables.append(item['res'])

        # 合并所有文本
        full_text = "\n".join(all_text)

        # 1. 提取日期
        result["invoice_date"] = extract_date_from_text(full_text)

        # 2. 提取金额
        amount = extract_amount_from_text(full_text)
        if amount:
            result["amount_in_figures"] = str(amount)
            result["amount"] = amount

        # 3. 尝试从文本中提取大写金额
        amount_words_match = re.search(r"[大价]写[:：]?\s*([^\n\s]+)", full_text)
        if amount_words_match:
            result["amount_in_words"] = amount_words_match.group(1)

        # 4. 提取发票编号
        invoice_num_match = re.search(r"发票号码[:：]?\s*([A-Z0-9]+)", full_text)
        if invoice_num_match:
            result["invoice_number"] = invoice_num_match.group(1)

        # 5. 从表格中提取商品信息
        if tables:
            self._extract_product_info_from_table(tables[0], result)

        return result

    def _extract_product_info_from_table(self, table: Dict[str, Any], result: dict) -> None:
        """
        从表格结构中提取商品信息
        
        Args:
            table: 表格数据
            result: 结果字典（会被修改）
        """
        # PP-Structure 的表格格式需要根据实际输出调整
        # 这里提供一个基本的框架
        try:
            if 'html' in table:
                # 如果有 HTML 格式的表格，可以解析
                # 这里先简单处理
                pass
            
            # 尝试从单元格中提取信息
            if 'cells' in table:
                for cell in table['cells']:
                    text = cell.get('text', '').strip()
                    # 根据关键词匹配提取信息
                    if '税率' in text:
                        # 尝试从同行或相邻单元格提取税率值
                        pass
        except Exception as e:
            # 表格解析失败，不影响其他字段
            print(f"表格解析警告: {e}")

    def get_layout_info(self) -> List[Dict[str, Any]]:
        """
        获取版面分析信息
        
        Returns:
            版面元素列表
        """
        if not self.structure_result:
            return []
        
        layout_items = []
        for item in self.structure_result:
            layout_items.append({
                'type': item.get('type'),
                'bbox': item.get('bbox'),
                'score': item.get('score', 0.0)
            })
        
        return layout_items
