"""
PDF发票解析工具
用于提取和解析PDF格式发票中的信息
支持多种发票类型
"""
import pdfplumber
import re
import logging
import unicodedata
import datetime
from decimal import Decimal, InvalidOperation
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
        raw_text = "\n".join(
            [line.get("text", "") for line in self.pdf_str if line and line.get("text")]
        )
        self.full_text = unicodedata.normalize("NFKC", raw_text)
        
        # 扩展支持的发票类型
        self.title_type_dict = {
            "电子发票（增值税专用发票）": self.VAT_special_parser,
            "电子发票（普通发票）": self.VAT_normal_parser,
            "增值税普通发票": self.VAT_normal_parser,
            "增值税专用发票": self.VAT_special_parser,
            "航空运输电子客票行程单": self.flight_ticket_parser,
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
        if any(kw in product_name for kw in ("客运", "运输", "交通", "约车", "通行费")):
            self.value_dict["invoice_type"] = "TRANSPORT"
            return

        # 4. 默认为 OTHER
        self.value_dict["invoice_type"] = "OTHER"

    @staticmethod
    def _normalize_text(text: str) -> str:
        """对文本进行 Unicode NFKC 规范化，消除 PDF 中常见的中文变体字符问题。
        
        部分 PDF 中的中文会使用康熙部首/兼容字符（如 ⼦ U+2F06 替代 子 U+5B50），
        NFKC 规范化可将这些变体转换为标准形式。
        """
        return unicodedata.normalize("NFKC", text)

    def handle_by_title_type(self):
        """根据发票类型选择对应的解析器"""
        self.invoice_title = self.pdf_str[0]['text']
        normalized_title = self._normalize_text(self.invoice_title)

        # 先尝试精确匹配（规范化后）
        for invoice_type, parser in self.title_type_dict.items():
            if self._normalize_text(invoice_type) == normalized_title:
                return parser()

        # 如果没有精确匹配，尝试模糊匹配（规范化后）
        for invoice_type, parser in self.title_type_dict.items():
            if self._normalize_text(invoice_type) in normalized_title:
                return parser()

        # ── 智能回退：根据内容特征判断 ──

        # 网约车行程单不是发票，是发票附件，应通过附件上传而非发票上传
        ride_hailing_keywords = [
            '滴滴出行', '高德打车', '高德出行',
            'T3出行', '曹操出行', '首汽约车', '美团打车',
            '花小猪', '嘀嗒出行', '享道出行', '阳光出行',
        ]
        if any(kw in self.full_text for kw in ride_hailing_keywords):
            raise ValueError("该PDF是网约车行程单（发票附件），不是发票，请先上传对应发票")

        if "行程单" in self.invoice_title or "行程单" in self.full_text:
            raise ValueError("该PDF是行程单（发票附件），不是发票，请先上传对应发票")

        # 铁路电子客票
        if "中国铁路" in self.full_text and "电子客票" in self.full_text:
            return self.railway_ticket_parser()

        # 机票行程单特征词（中英文）
        flight_keywords = [
            "航空运输电子客票行程单",
            "FLIGHT", "AIRLINE", "TICKET",
            "航班号", "航班日期", "乘机日期",
            "燃油附加费", "机场建设费", "民航发展基金",
            "电子客票号码",
        ]
        if any(kw in self.full_text for kw in flight_keywords):
            return self.flight_ticket_parser()

        # 电子发票 / 增值税发票 — 回退到普通发票解析
        if "电子发票" in self.full_text or "增值税" in self.full_text:
            return self.VAT_normal_parser()

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
        # 表格数据行的拆分结果可能因空列而少于 8 个，按位置安全映射
        raw_list = product_info[0].split("\n")[1].split(" ")
        product_info_list = [item for item in raw_list if item]  # 过滤空字符串
        count = len(product_info_list)
        if count < 4:
            raise ValueError("发票商品信息不完整，无法解析")
        self.value_dict["product_name"] = product_info_list[0]
        # 末尾三项固定为 金额、税率、税额
        self.value_dict["money_without_tax"] = product_info_list[-3]
        self.value_dict["tax_rate"] = product_info_list[-2]
        self.value_dict["tax_amount"] = product_info_list[-1]
        # 中间可选列：规格型号、单位、数量、单价（可能部分或全部缺失）
        middle = product_info_list[1:-3] if count > 4 else []
        self.value_dict["specification_model"] = middle[0] if len(middle) > 0 else ""
        self.value_dict["unit"] = middle[1] if len(middle) > 1 else ""
        self.value_dict["quantity"] = middle[2] if len(middle) > 2 else ""
        self.value_dict["unit_price"] = middle[3] if len(middle) > 3 else ""
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

                amount_in_figures = extract_amount_from_text(price_info)
                if amount_in_figures == 0:
                    amount_in_figures = self._extract_total_amount_from_invoice_text()
                self.value_dict["amount_in_figures"] = str(amount_in_figures) if amount_in_figures else ""
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
        if amount == 0:
            amount = self._extract_total_amount_from_invoice_text()
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

    def _extract_total_amount_from_invoice_text(self) -> float:
        """从发票全文中提取价税合计小写金额。"""
        text = self.full_text
        patterns = [
            r'(?:价税合计|价税合计\s*\(小写\)|小写|金额合计|合计金额|合计)[:：]?[^\n\d]{0,30}[¥￥]?\s*([0-9][\d,]*\.\d{2})',
            r'(?:价税合计|小写)[\s\S]{0,80}?[¥￥]?\s*([0-9][\d,]*\.\d{2})',
            r'[¥￥]\s*([0-9][\d,]*\.\d{2})',
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                try:
                    return float(match.group(1).replace(',', ''))
                except ValueError:
                    continue

        candidates: list[float] = []
        for match in re.finditer(r'(?<!\d)([0-9][\d,]*\.\d{2})(?!\d)', text):
            try:
                value = float(match.group(1).replace(',', ''))
            except ValueError:
                continue
            if value > 0:
                candidates.append(value)
        return max(candidates) if candidates else 0.0

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

            # 提取具体开车时刻（如 10:15）
            time_match = re.search(r'(\d{4})[年.-](\d{1,2})[月.-](\d{1,2})日?\s*(\d{1,2}):(\d{2})\s*开', self.full_text)
            if time_match:
                self.value_dict["service_start_date"] = (
                    f"{time_match.group(1)}-{int(time_match.group(2)):02d}-{int(time_match.group(3)):02d}"
                    f"T{int(time_match.group(4)):02d}:{time_match.group(5)}:00"
                )
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

    # ── 航空运输电子客票行程单 ──────────────────────────────

    def flight_ticket_parser(self):
        """解析航空运输电子客票行程单（机票行程单）

        提取字段映射：
        - invoice_number   ← 电子客票号 / 行程单号 / 发票号码
        - amount           ← 合计金额（票价+燃油+民航发展基金）
        - invoice_date     ← 航班日期（乘机日期）
        - departure_place  ← 出发地 / 始发地
        - arrival_place    ← 到达地 / 目的地
        - product_name     ← "航空客票" + 航班号
        - specification_model ← 航班号 (e.g. CA1234)
        - unit             ← 舱位 (经济舱/商务舱/头等舱)
        - unit_price       ← 票价（不含税基价）
        - tax_rate         ← 燃油附加费
        - tax_amount       ← 民航发展基金 / 机场建设费
        - vendor_name      ← 航空公司名称
        """
        # 1. 电子客票号 / 行程单号
        ticket_no = self._extract_flight_ticket_number()
        if ticket_no:
            self.value_dict["invoice_number"] = ticket_no

        # 2. 金额：优先提取"合计"行，再拆分子项
        self._extract_flight_amounts()

        # 3. 航班日期（乘机日期，非开票日期）
        travel_date = self._extract_flight_travel_date()
        if travel_date:
            self.value_dict["invoice_date"] = travel_date
        else:
            # 回退：取非"开票日期"的第一个日期
            self.value_dict["invoice_date"] = self._extract_first_non_issue_date()

        # 3b. 提取航班起飞具体时刻（如 11:35），作为 service_start_date
        flight_time = self._extract_flight_departure_datetime()
        if flight_time:
            self.value_dict["service_start_date"] = flight_time

        # 4. 出发地 / 到达地
        departure, arrival = self._extract_flight_route_enhanced()
        if departure:
            self.value_dict["departure_place"] = departure
        if arrival:
            self.value_dict["arrival_place"] = arrival

        # 5. 航班号
        flight_no = self._extract_flight_number()
        if flight_no:
            self.value_dict["specification_model"] = flight_no

        # 6. 舱位
        cabin = self._extract_cabin_class()
        if cabin:
            self.value_dict["unit"] = cabin

        # 7. 航空公司
        airline = self._extract_airline_name()
        if airline:
            self.value_dict["vendor_name"] = airline

        # 8. 商品名称
        parts = ["航空客票"]
        if flight_no:
            parts.append(flight_no)
        self.value_dict["product_name"] = " ".join(parts)

        # 9. 回退发票号码提取
        if not self.value_dict.get("invoice_number"):
            invoice_num = self._extract_invoice_number()
            if invoice_num:
                self.value_dict["invoice_number"] = invoice_num

        return self.value_dict

    # ── 机票专项提取方法 ──────────────────────────────────

    def _extract_flight_ticket_number(self) -> str:
        """提取电子客票号 / 行程单号

        常见格式：
        - 电子客票号码: 999-1234567890
        - 电子客票号: 1234567890
        - 行程单号: 123456789012345
        - 客票号码: 9991234567890 (13 位数字)
        """
        patterns = [
            r'电子客票[号码号][:：]?\s*([\d]{10,16})',
            r'行程单[号码号][:：]?\s*([\d]{10,16})',
            r'客票[号码号][:：]?\s*([\d]{10,16})',
            r'(?:ETKT|e-ticket|eTicket)[:：]?\s*(\d{10,16})',
            # 纯 13 位数字（最常见）
            r'(?<!\d)(\d{13})(?!\d)',
        ]
        for pattern in patterns:
            match = re.search(pattern, self.full_text, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return ""

    def _extract_flight_amounts(self):
        """提取机票各项金额：票价、燃油附加费、民航发展基金、合计"""
        text = self.full_text

        # --- 票价（基价）---
        fare_patterns = [
            r'(?:票价|FARE)[:：]?\s*(?:CNY\s*)?[¥￥]?\s*([\d,]+\.[\d]{2})',
            r'票面[价费][:：]?\s*(?:CNY\s*)?[¥￥]?\s*([\d,]+\.[\d]{2})',
            r'(?:机票|客票)[价费][:：]?\s*(?:CNY\s*)?[¥￥]?\s*([\d,]+\.[\d]{2})',
            # 无语种前缀的简单格式
            r'(?:票价|FARE)[:：]?\s*([\d,]+\.[\d]{2})',
        ]
        for pat in fare_patterns:
            m = re.search(pat, text)
            if m:
                self.value_dict["unit_price"] = m.group(1).replace(",", "")
                self.value_dict["money_without_tax"] = m.group(1).replace(",", "")
                break

        # --- 燃油附加费 ---
        fuel_patterns = [
            r'(?:燃油附加[税费费]|FUEL)[:：]?\s*(?:CNY\s*)?[¥￥]?\s*([\d,]+\.[\d]{2})',
            r'(?:燃油[税费费]|FUEL\s*SURCHARGE)[:：]?\s*(?:CNY\s*)?[¥￥]?\s*([\d,]+\.[\d]{2})',
            r'YQ\s*[:：]?\s*(?:CNY\s*)?[¥￥]?\s*([\d,]+\.[\d]{2})',
        ]
        for pat in fuel_patterns:
            m = re.search(pat, text)
            if m:
                self.value_dict["tax_rate"] = m.group(1).replace(",", "")
                break

        # --- 民航发展基金 / 机场建设费 ---
        tax_patterns = [
            r'(?:民航(?:发展)?基金|AIRPORT\s*(?:TAX|FEE|CHARGE)?)[:：]?\s*(?:CNY\s*)?[¥￥]?\s*([\d,]+\.[\d]{2})',
            r'(?:机场(?:建设)?费|机场税)[:：]?\s*(?:CNY\s*)?[¥￥]?\s*([\d,]+\.[\d]{2})',
            r'TAX[:：]?\s*(?:CNY\s*)?[¥￥]?\s*([\d,]+\.[\d]{2})',
        ]
        for pat in tax_patterns:
            m = re.search(pat, text)
            if m:
                self.value_dict["tax_amount"] = m.group(1).replace(",", "")
                break

        # --- 合计金额（总价）---
        total_patterns = [
            r'(?:合计|总计|总价|票价合计|票款合计|支付金额)[:：]?\s*(?:CNY\s*)?[¥￥]?\s*([\d,]+\.[\d]{2})',
            r'合[计共][:：]?\s*(?:CNY\s*)?[¥￥]?\s*([\d,]+\.[\d]{2})',
            # 电子行程单特有格式：一行多个 CNY 金额，最后一个为合计
            # 如：至: CNY 871.56 CNY 110.09 9% CNY 88.35 CNY 50.00 CNY 0.00 CNY 1120.00
        ]

        # 针对多 CNY 行，提取所有 CNY 金额，取最后一个作为合计
        cnys = re.findall(r'CNY\s+([\d,]+\.[\d]{2})', text)
        if cnys:
            # 最后一个 CNY 通常是合计
            last_cny = cnys[-1].replace(",", "")
            # 但如果已经有其他模式匹配到合计，则不覆盖
            matched_total = False
            for pat in total_patterns:
                m = re.search(pat, text, re.MULTILINE)
                if m:
                    self.value_dict["amount_in_figures"] = m.group(1).replace(",", "")
                    self.value_dict["amount"] = m.group(1).replace(",", "")
                    matched_total = True
                    break
            if not matched_total and len(cnys) >= 2:
                self.value_dict["amount_in_figures"] = last_cny
                self.value_dict["amount"] = last_cny

            # 同时尝试拆分各项费用（票价、燃油、民航基金）
            header_match = re.search(
                r'票价\s+燃油附加费\s+(?:增值税税率\s+)?(?:增值税税额\s+)?民航发展基金\s+(?:其他税费\s+)?合计',
                text,
            )
            if header_match and len(cnys) >= 5:
                # 根据表头顺序：票价, 燃油附加费, (税率), (税额), 民航基金, (其他税费), 合计
                self.value_dict["unit_price"] = cnys[0].replace(",", "")
                self.value_dict["money_without_tax"] = cnys[0].replace(",", "")
                self.value_dict["tax_rate"] = cnys[1].replace(",", "")  # 燃油附加费
                # 跳过可能存在的增值税税额
                tax_offset = 3 if len(cnys) >= 6 else 2
                self.value_dict["tax_amount"] = cnys[tax_offset].replace(",", "") if tax_offset < len(cnys) - 1 else ""
        for pat in total_patterns:
            m = re.search(pat, text, re.MULTILINE)
            if m:
                self.value_dict["amount_in_figures"] = m.group(1).replace(",", "")
                self.value_dict["amount"] = m.group(1).replace(",", "")
                break

        # 回退：通用金额提取
        if not self.value_dict.get("amount"):
            amt = extract_amount_from_text(text)
            if amt > 0:
                self.value_dict["amount_in_figures"] = str(amt)
                self.value_dict["amount"] = str(amt)

    def _extract_flight_travel_date(self) -> str:
        """提取航班乘机日期（优先取标注为"航班日期"/"乘机日期"的日期）

        航班日期格式示例：
        - 航班日期: 2026年04月29日
        - 乘机日期: 2026-04-29
        - 旅行日期: 29APR26
        - DATE: 29APR 2026
        """
        text = self.full_text

        # 标准中文日期格式
        cn_patterns = [
            r'(?:航班日期|乘机日期|旅行日期|飞行日期|出发日期)[:：]?\s*(\d{4})[年/\-.](\d{1,2})[月/\-.](\d{1,2})日?',
            r'(?:FLIGHT\s*DATE|TRAVEL\s*DATE|DEP\s*DATE)[:：]?\s*(\d{4})[年/\-.](\d{1,2})[月/\-.](\d{1,2})日?',
        ]
        for pat in cn_patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return self._fmt_date(m.group(1), m.group(2), m.group(3))

        # 英文日期格式: 29APR26, 29APR2026
        en_match = re.search(
            r'(?:航班日期|乘机日期|旅行日期|DATE)[:：]?\s*(\d{1,2})\s*(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\s*(\d{2,4})',
            text, re.IGNORECASE,
        )
        if en_match:
            day, mon_str, year_str = en_match.group(1), en_match.group(2).upper(), en_match.group(3)
            mon_map = {'JAN':1,'FEB':2,'MAR':3,'APR':4,'MAY':5,'JUN':6,
                       'JUL':7,'AUG':8,'SEP':9,'OCT':10,'NOV':11,'DEC':12}
            if mon_str in mon_map:
                year = int(year_str)
                if year < 100:
                    year += 2000
                return f"{year:04d}-{mon_map[mon_str]:02d}-{int(day):02d}"

        return ""

    def _extract_flight_departure_datetime(self) -> str:
        """提取航班起飞具体时刻（日期+时间），用于 service_start_date

        从机票行程单中提取如 "2026年03月11日 11:35" 的日期时间。
        优先取航班行中出现的日期+时间（非开票日期行）。
        返回 ISO 格式字符串 "YYYY-MM-DDTHH:MM:SS" 或空字符串。
        """
        text = self.full_text

        # 机票行程单中航班行格式：
        #   自:郑州 新郑 山航 SC4943 S 2026年03月11日 11:35 S1 ...
        # 提取航班号后面的日期+时间
        patterns = [
            # 航班号后紧跟舱位+日期+时间：SC4943 S 2026年03月11日 11:35
            r'[A-Z]{2}\d{2,6}\s+[A-Z]\s+(\d{4})[年.-](\d{1,2})[月.-](\d{1,2})日?\s*(\d{1,2}):(\d{2})',
            # 更宽松：任意位置的四位年+月+日+时:分（排除开票/打印日期）
            r'(?<!\u5f00\u7968\u65e5\u671f)(?<!\u6253\u5370\u65e5\u671f)(?<!\u586b\u5f00\u65e5\u671f)'
            r'(\d{4})[年.-](\d{1,2})[月.-](\d{1,2})日?\s*(\d{1,2}):(\d{2})',
        ]
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                return (
                    f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
                    f"T{int(m.group(4)):02d}:{int(m.group(5)):02d}:00"
                )
        return ""

    def _extract_first_non_issue_date(self) -> str:
        """提取第一个非'开票日期'的日期，作为航班日期的回退方案"""
        text = self.full_text
        # 排除开票日期、打印日期、填开日期
        all_dates = re.finditer(
            r'(?:(开票日期|打印日期|填开日期|ISSUE\s*DATE)[:：]?\s*)?(\d{4})[年/\-.](\d{1,2})[月/\-.](\d{1,2})日?',
            text, re.IGNORECASE,
        )
        for match in all_dates:
            prefix = match.group(1)
            if not prefix:
                return self._fmt_date(match.group(2), match.group(3), match.group(4))
        return ""

    def _extract_flight_route_enhanced(self) -> tuple[str, str]:
        """增强版航程提取：出发地 → 到达地

        兼容格式：
        - 北京首都 → 上海虹桥
        - 出发地: 北京  到达地: 上海
        - PEK → SHA (三字码)
        - 北京首都机场 CA1234 上海虹桥机场
        - FROM: PEK  TO: SHA (英文标签)
        """
        text = self.full_text

        # 模式1：标记式 "出发地 xxx 到达地 yyy"（跨行匹配，支持 自/至 标签）
        m = re.search(
            r'(?:出发|始发|起飞|FROM|自)[地站城市机场]*[:：]?\s*([\u4e00-\u9fa5A-Z]{2,20})(?:机场|国际机场)?'
            r'.{0,80}?'
            r'(?:到达|目的|降落|TO|至)[地站城市机场]*[:：]?\s*([\u4e00-\u9fa5A-Z]{2,20})(?:机场|国际机场)?',
            text,
            re.DOTALL,
        )
        if m:
            dep = m.group(1).strip()
            arr = m.group(2).strip()
            if dep.upper() not in ('FROM', 'TO', '城市', '地', '站', '机场') and arr.upper() not in ('FROM', 'TO', '城市', '地', '站', '机场'):
                return dep, arr

        # 模式1b：逐行独立匹配 "出发XXX: YYY" 和 "到达XXX: ZZZ"
        # 新增支持中文电子行程单的 "自:" 和 "至:" 格式
        # 注意："至: CNY..." 是金额行，必须排除
        dep_candidate = ""
        arr_candidate = ""
        for line in self.pdf_str:
            line_text = (line or {}).get("text", "") or ""
            # 跳过金额行（包含 CNY 或 ¥ 的行）
            if re.search(r'(?:CNY|[¥￥]|\d+\.\d{2})', line_text):
                # 但如果该行也包含城市名/机场名，仍然可能是到达行
                # 金额行特征：有 "CNY" + 多个数字 → 跳过
                if re.search(r'CNY.*\d+\.\d{2}', line_text):
                    continue
            m_dep = re.match(
                r'(?:出发|始发|起飞|FROM|自)[地站城市机场]*[:：]?\s*([\u4e00-\u9fa5]{2,20})(?:机场|国际机场)?\s*$',
                line_text,
            )
            if m_dep and not dep_candidate:
                dep_candidate = m_dep.group(1).strip()
            m_arr = re.match(
                r'(?:到达|目的|降落|TO|至)[地站城市机场]*[:：]?\s*([\u4e00-\u9fa5]{2,20})(?:机场|国际机场)?\s*$',
                line_text,
            )
            if m_arr and not arr_candidate:
                arr_candidate = m_arr.group(1).strip()
        if dep_candidate and arr_candidate:
            return dep_candidate, arr_candidate

        # 模式2：箭头式 "北京 → 上海"（用 [^\S\n] 替代 \s 防止跨行误匹配）
        m = re.search(
            r'([\u4e00-\u9fa5]{2,20})(?:机场|国际机场)?'
            r'[^\S\n]*(?:至|到|→|->|—>|—|-)[^\S\n]*'
            r'([\u4e00-\u9fa5]{2,20})(?:机场|国际机场)?',
            text,
        )
        if m:
            return m.group(1).strip(), m.group(2).strip()

        # 模式3：三字码式 "PEK → SHA"
        m = re.search(
            r'\b([A-Z]{3})\b\s*(?:至|到|→|->)\s*\b([A-Z]{3})\b',
            text,
        )
        if m:
            return m.group(1).strip(), m.group(2).strip()

        # 模式4：机场名 + 航班号 + 机场名
        m = re.search(
            r'([\u4e00-\u9fa5]{2,20})(?:机场|国际机场)?'
            r'[^\S\n]+[A-Z]{2}\d{2,6}[^\S\n]+'
            r'([\u4e00-\u9fa5]{2,20})(?:机场|国际机场)?',
            text,
        )
        if m:
            return m.group(1).strip(), m.group(2).strip()

        # 逐行回退
        for line in self.pdf_str:
            line_text = (line or {}).get("text", "") or ""
            for pat in [
                r'([\u4e00-\u9fa5]{2,20})(?:机场|国际机场)?[^\S\n]*(?:至|到|→|->)[^\S\n]*([\u4e00-\u9fa5]{2,20})(?:机场|国际机场)?',
                r'([\u4e00-\u9fa5]{2,20})(?:机场|国际机场)?[^\S\n]+[A-Z]{2}\d{2,6}[^\S\n]+([\u4e00-\u9fa5]{2,20})(?:机场|国际机场)?',
            ]:
                m = re.search(pat, line_text)
                if m:
                    return m.group(1).strip(), m.group(2).strip()

        return "", ""

    def _extract_flight_number(self) -> str:
        """提取航班号

        常见格式：
        - CA1234, MU5678, CZ3972, 3U8765
        - 航班号: CA1234
        - FLIGHT: CA1234
        """
        text = self.full_text

        patterns = [
            r'航班[号码号][:：]?\s*([A-Z]{2}\d{2,6})',
            r'FLIGHT\s*(?:NO|NBR|#)?[:：]?\s*([A-Z]{2}\d{2,6})',
            r'(?:Flight|FLT)[:：]?\s*([A-Z]{2}\d{2,6})',
            # 独立出现: 字母字母数字数字数字数字
            r'\b([A-Z]{2}\d{3,6})\b',
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return m.group(1).upper()
        return ""

    def _extract_cabin_class(self) -> str:
        """提取舱位等级

        常见值: 经济舱(Y), 商务舱(C), 头等舱(F), 超级经济舱, etc.
        """
        text = self.full_text
        patterns = [
            r'舱[位等][:：]?\s*([\u4e00-\u9fa5A-Z]+)',
            r'(?:CLASS|CABIN)[:：]?\s*([A-Z])',
            r'(经济舱|商务舱|头等舱|超级经济舱|公务舱)',
            r'CLASS\s*[:：]?\s*([A-Z])',
            # 电子行程单特有格式：航班号后紧跟舱位代码（如 HU7736 V 2026...）
            r'[A-Z]{2}\d{2,6}\s+([A-Z])\s+\d{4}',
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                cabin = m.group(1).strip()
                # 统一中文
                cabin_map = {
                    'Y': '经济舱', 'C': '商务舱', 'F': '头等舱',
                    'J': '公务舱', 'W': '超级经济舱', 'S': '经济舱',
                    'V': '经济舱', 'B': '经济舱', 'H': '经济舱',
                    'K': '经济舱', 'L': '经济舱', 'M': '经济舱',
                    'N': '经济舱', 'Q': '经济舱', 'T': '经济舱',
                    'X': '经济舱', 'U': '经济舱', 'E': '经济舱',
                    'D': '商务舱', 'I': '商务舱', 'R': '商务舱',
                    'P': '头等舱', 'A': '头等舱',
                    '经济舱': '经济舱', '商务舱': '商务舱',
                    '头等舱': '头等舱', '超级经济舱': '超级经济舱',
                    '公务舱': '公务舱',
                }
                return cabin_map.get(cabin.upper() if cabin.isascii() else cabin, cabin)
        return ""

    def _extract_airline_name(self) -> str:
        """提取航空公司名称

        匹配常见航空公司：
        - 中国国际航空、东方航空、南方航空、海南航空
        - 春秋航空、吉祥航空、厦门航空、深圳航空、四川航空
        - Air China, China Eastern, China Southern
        """
        text = self.full_text

        # 标记式提取（要求标签后有冒号，防止误匹配标题行）
        m = re.search(
            r'(?:航空公司|承运人)\s*[:：]\s*([\u4e00-\u9fa5]{2,20}(?:航空)?)',
            text,
        )
        if m:
            name = m.group(1).strip()
            if len(name) >= 2 and name not in ('航班号', '座位等级', '日期', '时间', '免费行李'):
                return name

        # 英文标签（要求有冒号，避免 HELLO AIRLINE 被误匹配）
        m = re.search(
            r'(?:AIRLINE|CARRIER)\s*[:：]\s*([A-Za-z\s]{3,40}?)(?:\s{2,}|$|\n)',
            text, re.IGNORECASE,
        )
        if m:
            name = m.group(1).strip()
            if len(name) >= 3:
                return name

        # 关键词匹配常见航空公司
        airline_keywords = [
            ('中国国际航空', '中国国际航空'),
            ('国际航空', '中国国际航空'),
            ('Air China', '中国国际航空'),
            ('China Eastern', '东方航空'),
            ('东方航空', '东方航空'),
            ('中国东方航空', '东方航空'),
            ('China Southern', '南方航空'),
            ('南方航空', '南方航空'),
            ('中国南方航空', '南方航空'),
            ('Hainan Airlines', '海南航空'),
            ('海南航空', '海南航空'),
            ('春秋航空', '春秋航空'),
            ('Spring Airlines', '春秋航空'),
            ('吉祥航空', '吉祥航空'),
            ('Juneyao', '吉祥航空'),
            ('厦门航空', '厦门航空'),
            ('Xiamen Airlines', '厦门航空'),
            ('深圳航空', '深圳航空'),
            ('Shenzhen Airlines', '深圳航空'),
            ('四川航空', '四川航空'),
            ('Sichuan Airlines', '四川航空'),
            ('山东航空', '山东航空'),
            ('天津航空', '天津航空'),
            ('首都航空', '首都航空'),
            ('华夏航空', '华夏航空'),
            ('成都航空', '成都航空'),
            ('国航', '中国国际航空'),
            ('东航', '东方航空'),
            ('南航', '南方航空'),
            ('海航', '海南航空'),
        ]
        for keyword, name in airline_keywords:
            if keyword in text:
                return name

        return ""

    @staticmethod
    def _fmt_date(year: str, month: str, day: str) -> str:
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"

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
    match = re.search(r'[¥￥]\s*([\d,]+(?:\.\d{1,2})?)', text)
    if match:
        return float(match.group(1).replace(',', ''))
    match = re.search(r'(?:小写|价税合计|合计)[:：]?[^\d]{0,20}([\d,]+\.\d{2})', text)
    if match:
        return float(match.group(1).replace(',', ''))
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


class RideHailingTripStatementParser:
    """网约车行程单解析器。"""

    def __init__(self, file_path_or_obj):
        self.pdf = pdfplumber.open(file_path_or_obj)
        text_parts: list[str] = []
        for page in self.pdf.pages:
            page_text = page.extract_text() or ''
            if page_text:
                text_parts.append(page_text)
        self.full_text = unicodedata.normalize('NFKC', '\n'.join(text_parts))

    def _is_trip_statement(self) -> bool:
        """判断 PDF 内容是否像网约车行程单（而非普通发票）。"""
        text = self.full_text
        # 强特征：平台名称
        platform_keywords = [
            '滴滴出行', '高德打车', '高德出行',
            'T3出行', '曹操出行', '首汽约车', '美团打车',
            '花小猪', '嘀嗒出行', '享道出行', '阳光出行',
        ]
        if any(kw in text for kw in platform_keywords):
            return True

        # 中特征计数
        score = 0
        medium_keywords = ['行程单', '行程明细', '出行记录', '用车记录', '网约车']
        for kw in medium_keywords:
            if kw in text:
                score += 2

        weak_keywords = ['行程', '出行', '用车', '打车', '乘客']
        for kw in weak_keywords:
            if kw in text:
                score += 1

        # 日期+路线分隔符的行数（即行程明细行）
        route_lines = 0
        for line in text.splitlines():
            if re.search(r'\d{4}[年/\-.]\d{1,2}[月/\-.]\d{1,2}', line) and re.search(r'(?:→|->|至|到)', line):
                route_lines += 1
        if route_lines >= 2:
            score += 2

        return score >= 3

    def parse(self) -> dict:
        if not self._is_trip_statement():
            raise ValueError("该PDF不是网约车行程单")
        travel_start_date, travel_end_date = self._extract_travel_period()
        travel_details = self._extract_trip_details()
        departure_place, arrival_place = self._extract_route(travel_details)
        application_date = self._extract_application_date()
        return {
            'attachment_type': 'RIDE_HAILING_TRIP_STATEMENT',
            'travel_start_date': travel_start_date,
            'travel_end_date': travel_end_date,
            'travel_departure_place': departure_place,
            'travel_arrival_place': arrival_place,
            'travel_details': travel_details,
            'travel_total_amount': self._extract_total_amount(),
            'application_date': application_date or self._extract_gaode_issue_date(),
            'applicant_phone': self._extract_phone(),
        }

    def _extract_route(self, travel_details: list[dict] | None = None) -> tuple[str, str]:
        if travel_details:
            return (
                str(travel_details[0].get('departure_place') or ''),
                str(travel_details[-1].get('arrival_place') or ''),
            )

        text = self.full_text
        patterns = [
            r'(?:起点|出发地|上车地点|上车点)[:：]?\s*([^\n\r]{2,60}).{0,80}?(?:终点|目的地|到达地|下车地点|下车点)[:：]?\s*([^\n\r]{2,60})',
            r'([^\n\r]{2,40})\s*(?:→|->|至|到)\s*([^\n\r]{2,40})',
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.DOTALL)
            if match:
                return self._clean_place(match.group(1)), self._clean_place(match.group(2))

        starts = re.findall(r'(?:起点|出发地|上车地点|上车点)[:：]?\s*([^\n\r]{2,60})', text)
        ends = re.findall(r'(?:终点|目的地|到达地|下车地点|下车点)[:：]?\s*([^\n\r]{2,60})', text)
        return (
            self._clean_place(starts[0]) if starts else '',
            self._clean_place(ends[-1]) if ends else '',
        )

    def _extract_trip_details(self) -> list[dict]:
        details: list[dict] = []
        for line in self.full_text.splitlines():
            normalized = re.sub(r'\s+', ' ', line).strip()
            if not normalized:
                continue
            if not re.search(r'\d{4}[年/\-.]\d{1,2}[月/\-.]\d{1,2}', normalized):
                continue
            if not re.search(r'(?:→|->|至|到)', normalized):
                continue

            date_match = re.search(r'(\d{4}[年/\-.]\d{1,2}[月/\-.]\d{1,2}日?)', normalized)
            route_match = re.search(r'([^\s]{2,40})\s*(?:→|->|至|到)\s*([^\s]{2,40})', normalized)
            amount_match = re.search(r'(?:¥|￥)?\s*(\d+(?:\.\d{1,2})?)\s*元?', normalized)
            if not date_match or not route_match:
                continue

            departure = self._clean_place(route_match.group(1))
            arrival = self._clean_place(route_match.group(2))
            if not departure or not arrival:
                continue

            detail = {
                'date': self._normalize_date(date_match.group(1)),
                'departure_place': departure,
                'arrival_place': arrival,
                'amount': amount_match.group(1) if amount_match else '',
            }
            if detail not in details:
                details.append(detail)

        return details

    @staticmethod
    def _clean_place(value: str) -> str:
        value = re.sub(r'\s+', ' ', value or '').strip(' ：:;；,，。')
        value = re.split(r'\s{2,}|\t|订单|金额|费用|时间|日期|里程', value)[0].strip(' ：:;；,，。')
        return value[:100]

    def _extract_travel_period(self) -> tuple[str, str]:
        text = self.full_text
        patterns = [
            # 高德打车常见：行程周期 2026-01-01 至 2026-01-03 / 行程时间 2026.01.01-2026.01.03
            r'(?:行程|出行|用车|订单)(?:起止)?(?:日期|时间|周期)[:：]?\s*'
            r'(\d{4}[年/\-.]\d{1,2}[月/\-.]\d{1,2}日?)\s*(?:至|到|[-~—])\s*'
            r'(\d{4}[年/\-.]\d{1,2}[月/\-.]\d{1,2}日?)',
            r'(?:开始日期|起始日期|开始时间)[:：]?\s*(\d{4}[年/\-.]\d{1,2}[月/\-.]\d{1,2}日?).{0,40}?'
            r'(?:结束日期|截止日期|结束时间)[:：]?\s*(\d{4}[年/\-.]\d{1,2}[月/\-.]\d{1,2}日?)',
            r'(\d{4}[年/\-.]\d{1,2}[月/\-.]\d{1,2}日?)\s*(?:至|到|[-~—])\s*'
            r'(\d{4}[年/\-.]\d{1,2}[月/\-.]\d{1,2}日?)',
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.DOTALL)
            if match:
                return self._normalize_date(match.group(1)), self._normalize_date(match.group(2))

        # 高德明细表常按每一单列出用车时间，取明细中最早/最晚日期作为行程周期。
        dates = [self._normalize_date(match.group(0)) for match in re.finditer(r'\d{4}[年/\-.]\d{1,2}[月/\-.]\d{1,2}日?', text)]
        application_date = self._extract_application_date()
        issue_date = self._extract_gaode_issue_date()
        dates = [item for item in dates if item and item not in {application_date, issue_date}]
        unique_dates = [item for index, item in enumerate(dates) if item and item not in dates[:index]]
        if unique_dates:
            return min(unique_dates), max(unique_dates)
        if unique_dates:
            return unique_dates[0], unique_dates[0]
        return '', ''

    def _extract_total_amount(self) -> str:
        patterns = [
            # 高德打车常见：总金额/实付金额/行程金额/费用合计/合计(元)
            r'(?:行程|出行|用车|订单|费用)?(?:总金额|合计金额|总计|合计|实付金额|支付金额|行程金额|打车费|费用合计)(?:\(元\))?[:：]?\s*[¥￥]?\s*([\d,]+(?:\.\d{1,2})?)',
            r'(?:总金额|合计|实付)\s*[¥￥]?\s*([\d,]+(?:\.\d{1,2})?)\s*元',
            r'[¥￥]\s*([\d,]+(?:\.\d{1,2})?)',
        ]
        for pattern in patterns:
            match = re.search(pattern, self.full_text)
            if match:
                try:
                    return str(Decimal(match.group(1).replace(',', '')).quantize(Decimal('0.01')))
                except InvalidOperation:
                    continue
        # 表格明细兜底：高德行程单可能只在明细中列每单金额，取所有带“元”的金额求和。
        amounts: list[Decimal] = []
        for match in re.finditer(r'(?<!\d)(\d+(?:\.\d{1,2})?)\s*元', self.full_text):
            try:
                amount = Decimal(match.group(1))
                if amount > 0:
                    amounts.append(amount)
            except InvalidOperation:
                continue
        if len(amounts) >= 2:
            return str(sum(amounts).quantize(Decimal('0.01')))
        return ''

    def _extract_application_date(self) -> str:
        patterns = [
            r'(?:申请日期|申请时间|提交日期|提交时间|申请开票日期|开票申请时间)[:：]?\s*(\d{4}[年/\-.]\d{1,2}[月/\-.]\d{1,2}日?)',
            r'(?:开具日期|生成日期)[:：]?\s*(\d{4}[年/\-.]\d{1,2}[月/\-.]\d{1,2}日?)',
        ]
        for pattern in patterns:
            match = re.search(pattern, self.full_text)
            if match:
                return self._normalize_date(match.group(1))
        return ''

    def _extract_gaode_issue_date(self) -> str:
        patterns = [
            r'(?:行程单开具时间|行程单生成时间|开具时间|导出时间)[:：]?\s*(\d{4}[年/\-.]\d{1,2}[月/\-.]\d{1,2}日?)',
        ]
        for pattern in patterns:
            match = re.search(pattern, self.full_text)
            if match:
                return self._normalize_date(match.group(1))
        return ''

    def _extract_phone(self) -> str:
        match = re.search(r'(?:申请人手机号|申请人手机|手机号|联系电话|手机号码|乘客手机号|用户手机号|打车人手机)[:：]?\s*((?:\+?86[- ]?)?1[3-9]\d{9})', self.full_text)
        if match:
            return re.sub(r'[^0-9+]', '', match.group(1))
        masked_match = re.search(r'(?:手机号|手机号码|乘客手机号|用户手机号)[:：]?\s*(1[3-9]\d{2}\*{3,4}\d{4})', self.full_text)
        if masked_match:
            return masked_match.group(1)
        match = re.search(r'(?<!\d)(1[3-9]\d{9})(?!\d)', self.full_text)
        return match.group(1) if match else ''

    @staticmethod
    def _normalize_date(value: str) -> str:
        match = re.search(r'(\d{4})[年/\-.](\d{1,2})[月/\-.](\d{1,2})日?', value)
        if not match:
            return ''
        try:
            return datetime.date(int(match.group(1)), int(match.group(2)), int(match.group(3))).isoformat()
        except ValueError:
            return ''


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    parser = PDFInvoiceParser(
        "InvoiceManageBack/media/invoices/20260203_淘数科技郑州有限公司_26432000000258103741_3824.00.pdf")
    invoice_data = parser.parse()
    logger.info(f"解析结果: {invoice_data}")
