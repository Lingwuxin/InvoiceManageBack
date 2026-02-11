#!/usr/bin/env python
"""
OCR 诊断脚本 - 测试上传的图片识别
"""
import os
import sys
from pathlib import Path

# 添加工程路径
sys.path.insert(0, os.path.dirname(__file__))

from tools.ocr_parser import OCRInvoiceParser

# 测试图片
test_images = [
    r"D:\Code\InvoiceManage\InvoiceManageBack\media\invoices\20260203_淘数科技郑州有限公司_26432000000258103741_3824.00.pdf",
]

print("=" * 80)
print("OCR 图片识别诊断")
print("=" * 80)

for img_path in test_images:
    if not os.path.exists(img_path):
        print(f"\n[错误] 文件不存在: {img_path}")
        continue
    
    print(f"\n开始处理: {Path(img_path).name}")
    print(f"文件大小: {os.path.getsize(img_path)} 字节")
    
    try:
        parser = OCRInvoiceParser(img_path, lang='ch')
        print("正在提取文本...")
        text = parser._extract_text()
        print(f"提取的文本长度: {len(text)} 字符")
        if text:
            print(f"完整文本内容:\n{'-'*60}\n{text}\n{'-'*60}")
        else:
            print("[警告] 未提取到文本")
        
        print("正在解析字段...")
        parsed = parser.parse()
        print(f"解析结果:")
        for key, value in parsed.items():
            if value:
                print(f"  {key}: {value}")
    except Exception as e:
        print(f"[异常] {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()

print("\n" + "=" * 80)
print("诊断完成")
print("=" * 80)
