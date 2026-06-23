import os
import io
from pathlib import Path

import pdfplumber
from django.conf import settings
from pypdf import PdfReader, PdfWriter
from PIL import Image


def _is_pdf(path: str) -> bool:
    return path.lower().endswith('.pdf')


# A4 = 595 x 842 pt; A5 = 595 x 421 pt
A4_W, A4_H = 595, 842
A5_W, A5_H = 595, 421


def _detect_content_bbox(
    page_bytes: bytes, page_w: float, page_h: float
) -> tuple[float, float, float, float]:
    """检测 PDF 单页中实际内容的包围盒（PDF 坐标，原点左下角）。

    返回 (x0, y0, x1, y1)。若页面无任何可识别对象，则回退到整页 MediaBox。
    """
    with pdfplumber.open(io.BytesIO(page_bytes)) as pdf:
        ppage = pdf.pages[0]
        xs0: list[float] = []
        ys0: list[float] = []
        xs1: list[float] = []
        ys1: list[float] = []
        for obj_type in ('chars', 'lines', 'rects', 'curves', 'images'):
            for obj in getattr(ppage, obj_type, []) or []:
                try:
                    xs0.append(float(obj['x0']))
                    xs1.append(float(obj['x1']))
                    ys0.append(float(obj['y0']))
                    ys1.append(float(obj['y1']))
                except (KeyError, TypeError, ValueError):
                    continue

        if not xs0:
            return (0.0, 0.0, page_w, page_h)

        pad = 4.0
        x0 = max(0.0, min(xs0) - pad)
        x1 = min(page_w, max(xs1) + pad)
        y0 = max(0.0, min(ys0) - pad)
        y1 = min(page_h, max(ys1) + pad)
        if x1 <= x0 or y1 <= y0:
            return (0.0, 0.0, page_w, page_h)
        return (x0, y0, x1, y1)


def _convert_image_to_a5(image_path: str) -> bytes:
    """将图片转换为 A5 尺寸 PDF 字节，内容按比例缩放居中。"""
    img = Image.open(image_path)
    if img.mode in ('RGBA', 'P'):
        img = img.convert('RGB')

    margin = 18
    max_w = A5_W - margin * 2
    max_h = A5_H - margin * 2
    ratio = min(max_w / img.width, max_h / img.height, 1.0)
    new_w = int(img.width * ratio)
    new_h = int(img.height * ratio)
    img = img.resize((new_w, new_h), Image.LANCZOS)

    canvas = Image.new('RGB', (A5_W, A5_H), (255, 255, 255))
    x = (A5_W - new_w) // 2
    y = (A5_H - new_h) // 2
    canvas.paste(img, (x, y))

    buf = io.BytesIO()
    canvas.save(buf, format='PDF', resolution=72.0)
    return buf.getvalue()


def _page_to_a5(page_bytes: bytes) -> bytes:
    """将单页 PDF 缩放到 A5 尺寸（595×421），按内容包围盒等比放大并居中。

    源 PDF 页面常常带有大量空白（例如发票内容只占 A4 顶部），如果直接按 MediaBox
    缩放会让真实内容显得极小。这里先用 pdfplumber 找出内容包围盒，再把该盒子整体
    放到 A5 的可用区域内。
    """
    reader = PdfReader(io.BytesIO(page_bytes))
    page = reader.pages[0]

    page_w = float(page.mediabox.width)
    page_h = float(page.mediabox.height)

    bx0, by0, bx1, by1 = _detect_content_bbox(page_bytes, page_w, page_h)
    bbox_w = bx1 - bx0
    bbox_h = by1 - by0

    output = PdfWriter()
    a5_page = output.add_blank_page(width=A5_W, height=A5_H)

    margin = 4
    avail_w = A5_W - margin * 2
    avail_h = A5_H - margin * 2
    scale = min(avail_w / bbox_w, avail_h / bbox_h)
    new_w = bbox_w * scale
    new_h = bbox_h * scale
    # 让源页面中 (bx0, by0) 映射到 A5 上指定位置，从而把内容盒子放到目标区域中央
    tx = margin + (avail_w - new_w) / 2 - bx0 * scale
    ty = margin + (avail_h - new_h) / 2 - by0 * scale

    a5_page.merge_transformed_page(page, (scale, 0, 0, scale, tx, ty))

    buf = io.BytesIO()
    output.write(buf)
    buf.seek(0)
    return buf.read()


def _page_bytes(page) -> bytes:
    """将单个 PDF 页面提取为独立的 PDF 字节。"""
    writer = PdfWriter()
    writer.add_page(page)
    buf = io.BytesIO()
    writer.write(buf)
    buf.seek(0)
    return buf.read()


def _merge_two_a5_to_a4(top_bytes: bytes, bottom_bytes: bytes) -> bytes:
    """将两张 A5 发票上下拼接到同一页 A4，保持 A5 原比例，仅做平移。"""
    top_reader = PdfReader(io.BytesIO(top_bytes))
    bottom_reader = PdfReader(io.BytesIO(bottom_bytes))

    top_page = top_reader.pages[0]
    bottom_page = bottom_reader.pages[0]

    output = PdfWriter()
    a4_page = output.add_blank_page(width=A4_W, height=A4_H)

    margin = 6
    gap = 6
    # 两张 A5 的总高度 + 边距 + 间隙 应 <= A4_H
    # 可用单区高度
    usable_half = (A4_H - margin * 2 - gap) / 2
    # A5 本身 595×421，在 A4 的半区内可能需要轻微缩放
    scale = min((A4_W - margin * 2) / A5_W, usable_half / A5_H)

    new_w = A5_W * scale
    new_h = A5_H * scale
    center_x = margin + (A4_W - margin * 2 - new_w) / 2

    # 上半区：居中在上半部分
    top_y = margin + usable_half + gap + (usable_half - new_h) / 2
    a4_page.merge_transformed_page(
        top_page,
        (scale, 0, 0, scale, center_x, top_y),
    )

    # 下半区：居中在下半部分
    bottom_y = margin + (usable_half - new_h) / 2
    a4_page.merge_transformed_page(
        bottom_page,
        (scale, 0, 0, scale, center_x, bottom_y),
    )

    buf = io.BytesIO()
    output.write(buf)
    buf.seek(0)
    return buf.read()


def _add_a5_to_a4(writer: PdfWriter, a5_bytes: bytes):
    """将单张 A5 发票放到 A4 页面的上半区（单数余票时使用）。"""
    reader = PdfReader(io.BytesIO(a5_bytes))
    page = reader.pages[0]

    a4_page = writer.add_blank_page(width=A4_W, height=A4_H)
    margin = 6
    avail_w = A4_W - margin * 2
    avail_h = A4_H - margin * 2
    scale = min(avail_w / A5_W, avail_h / A5_H)
    new_w = A5_W * scale
    new_h = A5_H * scale
    x = margin + (avail_w - new_w) / 2
    y = margin + (avail_h - new_h) / 2 + (avail_h / 2 - new_h) / 2

    a4_page.merge_transformed_page(
        page,
        (scale, 0, 0, scale, x, y),
    )


def _get_file_bytes(file_path: str) -> bytes:
    """从本地路径读取文件内容。"""
    full_path = Path(file_path)
    if not full_path.is_absolute():
        full_path = Path(settings.BASE_DIR) / file_path
    return full_path.read_bytes()


def build_trip_merged_pdf(
    invoice_files: list[str],
    attachment_files: list[str],
) -> bytes:
    """
    将同一个行程的发票拼接到同一个 PDF 中：
    - 发票先缩放到 A5 尺寸，然后两两上下拼接到同一页 A4；
    - 附件每个单独一页（A4 全页）。

    参数：
        invoice_files: 发票文件路径列表（PDF 或图片）
        attachment_files: 附件文件路径列表（PDF 或图片）

    返回：
        合并后的 PDF 字节内容
    """
    # 1. 将所有发票统一转成 A5 单页
    invoice_pages: list[bytes] = []
    for f in invoice_files:
        fpath = f
        if fpath.startswith('/media/'):
            fpath = str(Path(settings.BASE_DIR) / fpath.lstrip('/'))
        elif fpath.startswith('/'):
            fpath = str(Path(settings.MEDIA_ROOT).parent / fpath.lstrip('/'))
        elif not Path(fpath).is_absolute():
            fpath = str(Path(settings.MEDIA_ROOT) / fpath)

        if _is_pdf(fpath):
            pdf_bytes = _get_file_bytes(fpath)
            reader = PdfReader(io.BytesIO(pdf_bytes))
            for page in reader.pages:
                invoice_pages.append(_page_to_a5(_page_bytes(page)))
        else:
            invoice_pages.append(_convert_image_to_a5(fpath))

    # 2. 发票两两上下拼接到 A4
    writer = PdfWriter()
    i = 0
    while i < len(invoice_pages):
        if i + 1 < len(invoice_pages):
            merged = _merge_two_a5_to_a4(invoice_pages[i], invoice_pages[i + 1])
            merged_reader = PdfReader(io.BytesIO(merged))
            writer.add_page(merged_reader.pages[0])
            i += 2
        else:
            _add_a5_to_a4(writer, invoice_pages[i])
            i += 1

    # 3. 附件每个单独 A4 一页
    for f in attachment_files:
        fpath = f
        if fpath.startswith('/media/'):
            fpath = str(Path(settings.BASE_DIR) / fpath.lstrip('/'))
        elif fpath.startswith('/'):
            fpath = str(Path(settings.MEDIA_ROOT).parent / fpath.lstrip('/'))
        elif not Path(fpath).is_absolute():
            fpath = str(Path(settings.MEDIA_ROOT) / fpath)

        if _is_pdf(fpath):
            pdf_bytes = _get_file_bytes(fpath)
            reader = PdfReader(io.BytesIO(pdf_bytes))
            for page in reader.pages:
                writer.add_page(page)
        else:
            writer.add_page(_convert_image_to_a5(fpath))

    buf = io.BytesIO()
    writer.write(buf)
    buf.seek(0)
    return buf.read()
