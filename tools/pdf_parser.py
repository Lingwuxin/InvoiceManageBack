"""
PDF发票解析工具
用于提取和解析PDF格式发票中的信息
"""
import pdfplumber
import re


class PDFInvoiceParser:
    """
    PDF发票解析器
    负责提取PDF发票中的以下信息：
    - 发票编号
    - 发票日期
    - 金额
    - 供应商信息
    - 其他相关字段
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
        self.title_type_dict = {
            "电子发票（增值税专用发票）": self.VAT_special_paser
        }

    def parse(self) -> dict:
        handled_data = self.handle_by_title_type()
        return handled_data

    def handle_by_title_type(self):
        self.invoice_title = self.pdf_str[0]['text']
        if self.invoice_title in self.title_type_dict:
            return self.title_type_dict[self.invoice_title]()
        else:
            raise ValueError("不支持的发票类型")
    # 增值税专票处理器

    def VAT_special_paser(self):
        
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
    parser = PDFInvoiceParser(
        "InvoiceManageBack/media/invoices/20260203_淘数科技郑州有限公司_26432000000258103741_3824.00.pdf")
    invoice_data = parser.parse()
    print(invoice_data)
