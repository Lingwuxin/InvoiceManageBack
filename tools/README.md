# 工具模块 (Tools)

此目录包含发票系统的各类工具函数和处理模块。

## 目录结构

```
tools/
├── __init__.py              # 包初始化文件
├── pdf_parser.py            # PDF发票解析模块（待完成）
├── README.md                # 本文档
└── [其他工具模块]
```

## PDF 发票解析

### 功能说明

`pdf_parser.py` 模块提供了 `PDFInvoiceParser` 类，用于解析PDF格式的发票文件。

### 待实现功能

1. **`PDFInvoiceParser` 类**
   - `parse()`: 解析PDF并提取发票信息
   - `extract_text()`: 从PDF提取纯文本
   - `validate()`: 验证解析结果的有效性

2. **辅助函数**
   - `extract_amount_from_text()`: 从文本中提取金额
   - `extract_date_from_text()`: 从文本中提取日期

### 使用示例

```python
from tools import PDFInvoiceParser

# 初始化解析器
parser = PDFInvoiceParser('/path/to/invoice.pdf')

# 解析发票
invoice_data = parser.parse()

# 输出示例
# {
#     'invoice_number': '2024-001',
#     'invoice_date': '2024-02-10',
#     'amount': 1000.00,
#     'vendor_name': '某公司',
#     'vendor_address': '地址信息',
#     'description': '发票描述'
# }

# 验证数据
if parser.validate():
    print("发票数据有效")
```

### 推荐依赖库

- **PyPDF2**: 基础PDF处理
- **pdfplumber**: 强大的PDF文本/表格提取
- **pdf2image + Tesseract**: 图片类型PDF的OCR识别
- **pypdf** / **pypdf2**: PDF操作和文本提取

### 安装依赖

```bash
# 安装到项目依赖
uv pip install pdfplumber  # 推荐
# 或
uv pip install PyPDF2
```

### 实现建议

1. **从PDF提取文本**
   - 使用 pdfplumber 提取结构化表格和文本
   - 处理多页PDF的情况

2. **字段识别**
   - 使用正则表达式识别发票编号、日期、金额等字段
   - 考虑不同发票格式的差异

3. **数据验证**
   - 验证金额格式和数值范围
   - 验证日期的有效性
   - 验证必填字段的存在

4. **错误处理**
   - 处理PDF格式错误或损坏的文件
   - 处理文本提取失败的情况
   - 提供有意义的错误信息

## 集成到系统

完成实现后，可以在 `core/views.py` 中集成此工具：

```python
from tools import PDFInvoiceParser

# 在发票上传处理中使用
invoice_file_path = invoice.file.path
parser = PDFInvoiceParser(invoice_file_path)
invoice_data = parser.parse()

# 更新发票记录中的字段
invoice.amount = invoice_data.get('amount')
invoice.invoice_number = invoice_data.get('invoice_number')
invoice.invoice_date = invoice_data.get('invoice_date')
invoice.save()
```

## 后续扩展

- 支持图片格式发票的OCR识别
- 支持Excel格式数据
- 发票数据的智能匹配和去重
- 发票异常检测和告警
