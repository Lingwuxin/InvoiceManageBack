"""
PDF发票解析工具
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

    def __init__(self, file_path_or_obj):
        """
        初始化解析器

        Args:
            file_path_or_obj: PDF文件路径 或 文件对象
        """
        self.file_path = file_path_or_obj if isinstance(file_path_or_obj, str) else None
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
            "invoice_type": "OTHER",  # 发票类型: TRANSPORT, ACCOMMODATION, OTHER
        }
        self.pdf = pdfplumber.open(file_path_or_obj)
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
            "中国铁路电子客票": self.railway_ticket_parser,
            "铁路电子客票": self.railway_ticket_parser,
        }

    def parse(self) -> dict:
        self.handle_by_title_type()
        self._classify_invoice_type()

        if not self.value_dict.get("invoice_number"):
            self.value_dict["invoice_number"] = self._extract_invoice_number()

        if not self.value_dict.get("invoice_number"):
            raise ValueError("无法识别发票号码，请检查是否为有效的发票文件")
            
        return self.value_dict

    def _classify_invoice_type(self):
        """根据发票内容自动归类"""
        # 1. 优先判定铁路和航空客票 (TRANSPORT)
        if "中国铁路" in self.full_text or "电子客票" in self.full_text or "航空运输电子客票行程单" in self.full_text:
            self.value_dict["invoice_type"] = "TRANSPORT"
            return
            
        product_name = self.value_dict.get("product_name", "") or ""
        vendor_name = self.value_dict.get("vendor_name", "") or ""
        
        # 2. 判定住宿 (ACCOMMODATION)
        # 关键词: 住宿费, 客房, 酒店
        if "住宿" in product_name or "客房" in product_name or "酒店" in vendor_name or "住宿" in vendor_name:
            self.value_dict["invoice_type"] = "ACCOMMODATION"
            return
            
        # 3. 判定其他交通 (TRANSPORT) - 如出租车, 网约车, 客运
        # 关键词: 客运, 运输, 交通, 约车
        if "客运" in product_name or "运输" in product_name or "交通" in product_name or "约车" in product_name or "通行费" in product_name:
            self.value_dict["invoice_type"] = "TRANSPORT"
            return

        # 4. 默认为 OTHER
        self.value_dict["invoice_type"] = "OTHER"

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
            
            # 尝试根据内容特征判断
            if "中国铁路" in self.full_text and "电子客票" in self.full_text:
                return self.railway_ticket_parser()
                
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
            # 尝试从表格提取信息
            # 1. 寻找金额信息（价税合计）
            price_info = None
            for row in self.pdf_table:
                if not row: continue
                # 检查第一列是否包含"价税合计"
                first_col = str(row[0]) if row[0] else ""
                if "价税合计" in first_col:
                    # 通常金额在同一行的后续列中
                    for cell in row:
                        if cell and ("小写" in str(cell) or "¥" in str(cell) or "￥" in str(cell)):
                             price_info = cell
                             break
                if price_info: break
            
            # 如果还没找到，尝试兼容旧逻辑（固定位置）
            if not price_info:
                 price_info = self.pdf_table[2][2] if len(self.pdf_table) > 2 and len(self.pdf_table[2]) > 2 else None
            
            if price_info:
                # 提取大写金额 (取空格前的内容，或者通过正则提取)
                if " " in price_info:
                     self.value_dict["amount_in_words"] = price_info.split(" ")[0]
                else:
                     amount_words_match = re.search(r"([^\x00-\xff]+)", price_info) # 简易匹配中文
                     if amount_words_match:
                         self.value_dict["amount_in_words"] = amount_words_match.group(1)

                self.value_dict["amount_in_figures"] = str(extract_amount_from_text(price_info))
                self.value_dict["amount"] = self.value_dict["amount_in_figures"]
            
            # 2. 尝试解析商品信息
            product_info = self.pdf_table[1] if len(self.pdf_table) > 1 else None
            if product_info and product_info[0]:
                product_text = product_info[0]
                # 尝试通过正则提取 *AAA*BBB 格式的商品名称
                match = re.search(r'(\*[^*]+\*[^\s]+)', product_text)
                if match:
                    self.value_dict["product_name"] = match.group(1)
                elif "\n" in product_text:
                    # 如果没有星号，尝试取第二行（通常第一行是表头）
                    product_lines = product_text.split("\n")
                    if len(product_lines) > 1:
                        # 过滤掉"合 计"行等
                        candidate = product_lines[1]
                        if "项目名称" not in candidate and "合 计" not in candidate:
                             self.value_dict["product_name"] = candidate.split(" ")[0]
                else:
                     # 简单的回退
                     self.value_dict["product_name"] = product_text.split(" ")[0]

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

    def railway_ticket_parser(self):
        """解析铁路电子客票"""
        # 尝试从文本提取信息
        
        # 金额：通常格式为 "价格：553.0元" 或 "¥553.0"
        self.value_dict["amount_in_figures"] = str(extract_amount_from_text(self.full_text))
        # 如果提取出的金额为0，尝试备用正则
        if float(self.value_dict["amount_in_figures"]) == 0:
             match = re.search(r'(?:票价|价格|金额)[:：]?\s*([0-9.]+)\s*元?', self.full_text)
             if match:
                 self.value_dict["amount_in_figures"] = match.group(1)

        self.value_dict["amount"] = self.value_dict["amount_in_figures"]
        
        # 日期：优先提取开车时间
        # 格式1：2024年05月20日10:30开
        # 格式2：开车时间：2024年05月20日10:30
        date_match = re.search(r'(\d{4})[年.-](\d{1,2})[月.-](\d{1,2})日?\s*\d{1,2}:\d{1,2}\s*开', self.full_text)
        if not date_match:
             date_match = re.search(r'开车时间[:：]?\s*(\d{4})[年.-](\d{1,2})[月.-](\d{1,2})', self.full_text)
             
        if date_match:
            self.value_dict["invoice_date"] = f"{date_match.group(1)}-{int(date_match.group(2)):02d}-{int(date_match.group(3)):02d}"
        else:
            # 尝试提取日期，但排除开票日期
            # 正则：匹配日期格式，且前面不能是 "开票日期" 或 "打印日期"
            # 这里简单起见，如果找不到开车时间，再使用通用提取，但为了避免提取到开票日期，我们可以先尝试把开票日期部分抹去再提取，或者更精细的正则
            # 由于铁路客票上通常只有两个明显日期：开车时间 和 开票日期。如果上面没提取到开车时间，大概率是OCR没识别出"开"字。
            # 策略：查找所有日期，如果某个日期前面有 "开票日期" 字样，就跳过它。
            
            all_dates = re.finditer(r'(?:(开票日期|打印日期)[:：]?\s*)?(\d{4})[年.-](\d{1,2})[月.-](\d{1,2})', self.full_text)
            found_date = ""
            for match in all_dates:
                prefix = match.group(1)
                if not prefix: # 前面没有"开票日期"前缀
                     found_date = f"{match.group(2)}-{int(match.group(3)):02d}-{int(match.group(4)):02d}"
                     # 铁路票上除了开票日期，另一个大概率就是乘车日期，取第一个非开票日期的日期
                     break
            
            if found_date:
                self.value_dict["invoice_date"] = found_date
            else:
                 self.value_dict["invoice_date"] = extract_date_from_text(self.full_text)
        
        # 发票号码
        invoice_num = self._extract_invoice_number()
        if invoice_num:
            self.value_dict["invoice_number"] = invoice_num
        
        # 商品名称 -> "铁路客票"
        self.value_dict["product_name"] = "铁路客票"

        # 提取车站信息 (例如: 郑州东 G415 长沙南)
        # 匹配模式: 中文站点 + 空格 + 车次(字母数字) + 空格 + 中文站点
        station_match = re.search(r'([\u4e00-\u9fa5]+)\s+[A-Z]\d+\s+([\u4e00-\u9fa5]+)', self.full_text)
        if station_match:
            self.value_dict["departure_place"] = station_match.group(1)
            self.value_dict["arrival_place"] = station_match.group(2)
        
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
    match = re.search(r'[¥￥]([\d.]+)', text)
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
