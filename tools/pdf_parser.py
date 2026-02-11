"""
PDF发票解析工具 (Updated for PaddleOCR 3.x)
用于提取和解析PDF格式发票中的信息
支持多种发票类型
"""
import pdfplumber
import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class PDFInvoiceParser:
    """
    PDF发票解析器
    负责提取PDF发票中的以下信息：
    - 发票编号
    - 发票日期
    - 金额
    - 供应商信息
    - 其他相关字段
    
    支持的发票类型：
    - 电子发票（增值税专用发票）
    - 电子发票（普通发票）
    - 增值税普通发票
    """

    def __init__(self, file_path: str):
        """
        初始化解析器

        Args:
            file_path: PDF文件路径
        """
        self.file_path = file_path
        self.value_dict = {
            "invoice_number": "",      # 发票编号
            "invoice_date": "",        # 发票日期
            "amount": 0.0,            # 发票金额
            "vendor_name": "",         # 供应商名称
            "tax_rate": "",           # 税率
            "product_name": "",       # 商品名称
            "specification_model": "",  # 规格型号
            "unit": "",  # 单位
            "quantity": "",  # 数量
            "unit_price": "",  # 单价
            "money_without_tax": "",  # 不含税金额
            "tax_amount": "",  # 税额
            "amount_in_words": "",    # 金额（大写）
            "amount_in_figures": "",  # 金额（小写）
        }
        self.pdf = pdfplumber.open(self.file_path)
        self.pdf_str = self.pdf.pages[0].extract_text_lines()
        self.pdf_table = self.pdf.pages[0].extract_table()
        self.full_text = "\n".join(
            [line.get("text", "") for line in self.pdf_str if line and line.get("text")]
        )
        
        # 扩展支持的发票类型
        self.title_type_dict = {
            "电子发票（增值税专用发票）": self.VAT_special_parser,
            "电子发票（普通发票）": self.VAT_normal_parser,
            "增值税普通发票": self.VAT_normal_parser,
            "增值税专用发票": self.VAT_special_parser,
        }

    def parse(self) -> dict:
        handled_data = self.handle_by_title_type()
        return handled_data

    def handle_by_title_type(self):
        """根据发票类型选择对应的解析器"""
        self.invoice_title = self.pdf_str[0]['text']
        if self.invoice_title in self.title_type_dict:
            return self.title_type_dict[self.invoice_title]()
        else:
            # 如果没有精确匹配，尝试模糊匹配
            for invoice_type, parser in self.title_type_dict.items():
                if invoice_type in self.invoice_title:
                    return parser()
            raise ValueError(f"不支持的发票类型: {self.invoice_title}")
    
    # 增值税专票处理器
    def VAT_special_parser(self):
        """解析增值税专用发票"""
        if self.pdf_table is None:
            raise ValueError("无法提取PDF表格内容")
        product_info = self.pdf_table[1]
        price_info = self.pdf_table[2][2]
        if price_info is None:
            raise ValueError("无法提取发票中的金额信息")
        self.value_dict["amount_in_words"] = price_info.split(" ")[0]
        self.value_dict["amount_in_figures"] = extract_amount_from_text(
            price_info)
        self.value_dict["amount"] = self.value_dict["amount_in_figures"]
        if product_info[0] is None:
            raise ValueError("无法提取发票中的商品信息")
        product_info_list = product_info[0].split("\n")[1].split(" ")
        self.value_dict["product_name"] = product_info_list[0]
        self.value_dict["specification_model"] = product_info_list[1]
        self.value_dict["unit"] = product_info_list[2]
        self.value_dict["quantity"] = product_info_list[3]
        self.value_dict["unit_price"] = product_info_list[4]
        self.value_dict["money_without_tax"] = product_info_list[5]

        self.value_dict["tax_rate"] = product_info_list[6]
        self.value_dict["tax_amount"] = product_info_list[7]
        self.value_dict["invoice_date"] = extract_date_from_text(self.full_text)
        return self.value_dict
    
    # 增值税普通发票处理器
    def VAT_normal_parser(self):
        """解析增值税普通发票"""
        # 普通发票的格式可能与专票不同，这里提供基础实现
        if self.pdf_table is None:
            # 如果没有表格，尝试从文本提取
            return self._extract_from_text()
        
        try:
            # 尝试从表格提取信息（格式可能与专票不同）
            product_info = self.pdf_table[1] if len(self.pdf_table) > 1 else None
            price_info = self.pdf_table[2][2] if len(self.pdf_table) > 2 and len(self.pdf_table[2]) > 2 else None
            
            if price_info:
                self.value_dict["amount_in_words"] = price_info.split(" ")[0] if " " in price_info else ""
                self.value_dict["amount_in_figures"] = extract_amount_from_text(price_info)
                self.value_dict["amount"] = self.value_dict["amount_in_figures"]
            
            if product_info and product_info[0]:
                # 尝试解析商品信息
                product_text = product_info[0]
                if "\n" in product_text:
                    product_lines = product_text.split("\n")
                    if len(product_lines) > 1:
                        product_info_list = product_lines[1].split(" ")
                        if len(product_info_list) > 0:
                            self.value_dict["product_name"] = product_info_list[0]
            
            # 提取日期
            self.value_dict["invoice_date"] = extract_date_from_text(self.full_text)
            
            # 提取发票号码
            invoice_num = self._extract_invoice_number()
            if invoice_num:
                self.value_dict["invoice_number"] = invoice_num
            
            return self.value_dict
        
        except Exception as e:
            # 如果表格解析失败，回退到文本提取
            logger.warning(f"表格解析失败，使用文本提取: {e}")
            return self._extract_from_text()
    
    def _extract_from_text(self) -> dict:
        """从纯文本中提取发票信息（备用方法）"""
        # 提取金额
        amount = extract_amount_from_text(self.full_text)
        if amount:
            self.value_dict["amount"] = amount
            self.value_dict["amount_in_figures"] = str(amount)
        
        # 提取日期
        self.value_dict["invoice_date"] = extract_date_from_text(self.full_text)
        
        # 提取发票号码
        invoice_num = self._extract_invoice_number()
        if invoice_num:
            self.value_dict["invoice_number"] = invoice_num
        
        # 提取大写金额
        amount_words_match = re.search(r"[大价]写[:：]?\s*([^\n\s]+)", self.full_text)
        if amount_words_match:
            self.value_dict["amount_in_words"] = amount_words_match.group(1)
        
        return self.value_dict
    
    def _extract_invoice_number(self) -> str:
        """提取发票号码"""
        # 常见的发票号码格式
        patterns = [
            r"发票号码[:：]?\s*([A-Z0-9]+)",
            r"No[:.]?\s*([A-Z0-9]+)",
            r"号码[:：]?\s*([A-Z0-9]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, self.full_text)
            if match:
                return match.group(1)
        return ""

    def extract_text(self) -> str:
        """
        从PDF提取纯文本

        Returns:
            PDF中的文本内容
        """
        raise NotImplementedError("请实现文本提取逻辑")

    def validate(self) -> bool:
        """
        验证解析的发票信息是否完整和有效

        Returns:
            bool: 数据有效性
        """
        raise NotImplementedError("请实现验证逻辑")


# 辅助函数示例（如需要）


def extract_amount_from_text(text: str) -> float:
    """
    从文本中提取金额

    Args:
        text: 包含金额信息的文本

    Returns:
        提取的金额值
    """
    match = re.search(r'¥([\d.]+)', text)
    if match:
        return float(match.group(1))
    return 0.0


def extract_date_from_text(text: str) -> str:
    """
    从文本中提取日期

    Args:
        text: 包含日期信息的文本

    Returns:
        提取的日期字符串（ISO格式：YYYY-MM-DD）
    """
    patterns = [
        r'(\d{4})[年/\-\.](\d{1,2})[月/\-\.](\d{1,2})日?',
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            year = int(match.group(1))
            month = int(match.group(2))
            day = int(match.group(3))
            return f"{year:04d}-{month:02d}-{day:02d}"
    return ""


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    parser = PDFInvoiceParser(
        "InvoiceManageBack/media/invoices/20260203_淘数科技郑州有限公司_26432000000258103741_3824.00.pdf")
    invoice_data = parser.parse()
    logger.info(f"解析结果: {invoice_data}")
