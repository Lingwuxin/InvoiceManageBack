"""
OCR 和发票解析配置文件
"""

# 发票解析配置
INVOICE_CONFIG = {
    # PDF 转图片的 DPI
    'pdf_dpi': 200,
    
    # 最大处理页数
    'max_pages': 2,
    
    # 支持的发票类型
    'supported_types': [
        '电子发票（增值税专用发票）',
        '电子发票（普通发票）',
        '增值税普通发票',
        '增值税专用发票',
    ],
    
    # 是否启用双引擎模式（v2 备用）
    'dual_engine': True,
    
    # 字段提取置信度阈值
    'confidence_threshold': 0.8,
}

# 印章检测配置
SEAL_CONFIG = {
    # 是否启用印章检测
    'enabled': False,
    
    # 印章检测置信度阈值
    'confidence_threshold': 0.7,
}
