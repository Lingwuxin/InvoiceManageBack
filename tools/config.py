"""
OCR 和发票解析配置文件
"""

# OCR 引擎配置
OCR_CONFIG = {
    # 使用 PaddleOCR 版本：'v2' 或 'v3'
    'version': 'v3',
    
    # OCR 语言设置
    'lang': 'ch',  # 中文
    
    # 是否使用 GPU
    'use_gpu': False,
    
    # 是否使用方向分类器
    'use_angle_cls': True,
    
    # OCR 版本配置
    'ocr_version': 'PP-OCRv5',  # 'PP-OCRv3' 或 'PP-OCRv5'
    
    # 是否显示日志
    'show_log': False,
}

# PP-Structure 配置（表格和版面解析）
STRUCTURE_CONFIG = {
    # 是否启用表格识别
    'table': True,
    
    # 是否启用 OCR
    'ocr': True,
    
    # 是否启用版面分析
    'layout': True,
    
    # 是否恢复文档结构
    'recovery': True,
    
    # 语言
    'lang': 'ch',
    
    # 是否显示日志
    'show_log': False,
}

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
