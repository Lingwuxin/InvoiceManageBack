"""邮件抓取与发票自动入库服务。

主流程：
1. 通过 IMAP 连接用户邮箱，按 UID 拉取自上次处理后到达的邮件。
2. 检查邮件标题是否包含用户配置的关键词（如"发票/行程单/机票"）。
3. 标题命中后，不再在邮件层做平台判断；直接收集 PDF 附件和 ZIP 压缩包内的 PDF，
    按后端发票上传接口的处理语义逐个解析：发票入库，行程单自动匹配并关联发票。

注意：
- 仅处理 PDF 附件和 ZIP 内 PDF，其他类型文件忽略。
- 发票号码若已存在则跳过，避免重复入库。
"""

from __future__ import annotations

import datetime
import email
import imaplib
import io
import logging
import unicodedata
import zipfile
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from email.header import decode_header
from email.message import Message
from typing import Iterable, Optional

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from .models import EmailAccount, Invoice, InvoiceAttachment, ProcessedEmail, User
from .trip_groups import regroup_auto_trip_groups
from tools.pdf_parser import PDFInvoiceParser, RideHailingTripStatementParser

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# 数据结构
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class FetchSummary:
    checked: int = 0
    matched: int = 0
    invoices_created: int = 0
    attachments_attached: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            'checked': self.checked,
            'matched': self.matched,
            'invoices_created': self.invoices_created,
            'attachments_attached': self.attachments_attached,
            'skipped': self.skipped,
            'errors': self.errors,
        }


@dataclass
class _Attachment:
    filename: str
    content: bytes


# ─────────────────────────────────────────────────────────────────────────────
# 顶层入口
# ─────────────────────────────────────────────────────────────────────────────

def fetch_account(account: EmailAccount, max_messages: int = 50) -> FetchSummary:
    """从指定邮箱账户拉取并处理新邮件。"""
    summary = FetchSummary()
    if not account.enabled:
        summary.errors.append('邮箱未启用')
        return summary

    try:
        with _open_imap(account) as imap:
            imap.select(account.folder or 'INBOX')
            uids = _search_new_uids(imap, account)
            if max_messages and len(uids) > max_messages:
                uids = uids[-max_messages:]
            keyword_list = account.keyword_list

            for uid in uids:
                summary.checked += 1
                try:
                    msg = _fetch_message(imap, uid)
                    if msg is None:
                        continue
                    subject = _decode_subject(msg.get('Subject', ''))
                    if not _subject_matches(subject, keyword_list):
                        # 仍然记录到 ProcessedEmail，避免重复检查
                        ProcessedEmail.objects.update_or_create(
                            account=account,
                            message_uid=uid,
                            defaults={
                                'message_id': msg.get('Message-ID', '')[:255],
                                'subject': subject[:255],
                                'received_at': _parse_date(msg.get('Date')),
                                'invoices_created': 0,
                                'attachments_attached': 0,
                                'note': 'subject not matched',
                            },
                        )
                        summary.skipped += 1
                        _bump_last_uid(account, uid)
                        continue
                    summary.matched += 1
                    result = _process_message(account, uid, msg, subject)
                    summary.invoices_created += result['invoices_created']
                    summary.attachments_attached += result['attachments_attached']
                    _bump_last_uid(account, uid)
                except Exception as exc:  # noqa: BLE001
                    logger.exception('处理邮件 %s 失败: %s', uid, exc)
                    summary.errors.append(f'UID {uid}: {exc}')

        account.last_checked_at = timezone.now()
        account.last_error = ''
        account.save(update_fields=['last_checked_at', 'last_error', 'last_uid'])
    except Exception as exc:  # noqa: BLE001
        logger.exception('IMAP 连接失败: %s', exc)
        account.last_error = str(exc)
        account.last_checked_at = timezone.now()
        account.save(update_fields=['last_checked_at', 'last_error'])
        summary.errors.append(str(exc))
    return summary


def fetch_due_accounts() -> dict:
    """处理所有到达轮询周期的邮箱账户，供后台定时任务调用。"""
    now = timezone.now()
    results = {}
    for account in EmailAccount.objects.filter(enabled=True):
        interval = max(1, account.poll_interval_minutes or 15)
        if account.last_checked_at and (now - account.last_checked_at).total_seconds() < interval * 60:
            continue
        summary = fetch_account(account)
        results[account.user.username] = summary.as_dict()
    return results


# ─────────────────────────────────────────────────────────────────────────────
# IMAP 辅助
# ─────────────────────────────────────────────────────────────────────────────

class _IMAPCtx:
    def __init__(self, account: EmailAccount):
        self.account = account
        self.conn: imaplib.IMAP4 | None = None

    def __enter__(self) -> imaplib.IMAP4:
        if self.account.use_ssl:
            self.conn = imaplib.IMAP4_SSL(self.account.imap_host, self.account.imap_port)
        else:
            self.conn = imaplib.IMAP4(self.account.imap_host, self.account.imap_port)
        username = self.account.username or self.account.email_address
        self.conn.login(username, self.account.password)
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        try:
            if self.conn is not None:
                try:
                    self.conn.close()
                except Exception:  # noqa: BLE001
                    pass
                self.conn.logout()
        except Exception:  # noqa: BLE001
            pass


def _open_imap(account: EmailAccount) -> _IMAPCtx:
    return _IMAPCtx(account)


def _search_new_uids(imap: imaplib.IMAP4, account: EmailAccount) -> list[str]:
    """按 UID 搜索新邮件，仅返回未处理过的。"""
    last_uid = account.last_uid.strip() if account.last_uid else ''
    if last_uid:
        try:
            next_uid = int(last_uid) + 1
            status, data = imap.uid('search', None, f'UID {next_uid}:*')
        except ValueError:
            status, data = imap.uid('search', None, 'ALL')
    else:
        # 第一次启用时，仅拉取近 7 天的邮件，避免一次性灌入大量历史
        since = (timezone.now() - datetime.timedelta(days=7)).strftime('%d-%b-%Y')
        status, data = imap.uid('search', None, f'(SINCE {since})')

    if status != 'OK' or not data or not data[0]:
        return []
    uids = data[0].split()
    # 去掉已处理过的
    processed = set(
        ProcessedEmail.objects.filter(account=account, message_uid__in=[u.decode() for u in uids])
        .values_list('message_uid', flat=True)
    )
    return [u.decode() for u in uids if u.decode() not in processed]


def _fetch_message(imap: imaplib.IMAP4, uid: str) -> Message | None:
    status, data = imap.uid('fetch', uid, '(RFC822)')
    if status != 'OK' or not data or not data[0]:
        return None
    raw = data[0][1] if isinstance(data[0], tuple) else None
    if not raw:
        return None
    return email.message_from_bytes(raw)


def _bump_last_uid(account: EmailAccount, uid: str) -> None:
    try:
        new_uid = int(uid)
        current = int(account.last_uid) if account.last_uid else 0
        if new_uid > current:
            account.last_uid = str(new_uid)
    except ValueError:
        account.last_uid = uid


# ─────────────────────────────────────────────────────────────────────────────
# 邮件内容处理
# ─────────────────────────────────────────────────────────────────────────────

def _decode_subject(raw: str) -> str:
    if not raw:
        return ''
    parts = decode_header(raw)
    decoded = []
    for text, charset in parts:
        if isinstance(text, bytes):
            try:
                decoded.append(text.decode(charset or 'utf-8', errors='replace'))
            except (LookupError, UnicodeDecodeError):
                decoded.append(text.decode('utf-8', errors='replace'))
        else:
            decoded.append(text)
    return ''.join(decoded).strip()


def _parse_date(raw: str | None) -> datetime.datetime | None:
    if not raw:
        return None
    try:
        return email.utils.parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None


def _subject_matches(subject: str, keywords: Iterable[str]) -> bool:
    if not keywords:
        return True
    norm = unicodedata.normalize('NFKC', subject or '')
    return any(kw and kw in norm for kw in keywords)


def _iter_pdf_attachments(msg: Message) -> Iterable[_Attachment]:
    for part in msg.walk():
        if part.is_multipart():
            continue
        disposition = part.get('Content-Disposition', '') or ''
        filename = part.get_filename()
        if filename:
            filename = _decode_subject(filename)
        if not filename and 'attachment' not in disposition.lower():
            continue
        if not filename:
            continue
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        lower_name = filename.lower()
        if lower_name.endswith('.pdf'):
            yield _Attachment(filename=filename, content=bytes(payload))
            continue
        if lower_name.endswith('.zip'):
            yield from _extract_pdf_attachments_from_zip(filename, bytes(payload))


def _extract_pdf_attachments_from_zip(zip_filename: str, content: bytes) -> Iterable[_Attachment]:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            for info in archive.infolist():
                if info.is_dir() or not info.filename.lower().endswith('.pdf'):
                    continue
                with archive.open(info) as fp:
                    pdf_content = fp.read()
                safe_name = info.filename.replace('\\', '/').split('/')[-1]
                yield _Attachment(filename=safe_name or f'{zip_filename}.pdf', content=pdf_content)
    except zipfile.BadZipFile:
        logger.info('附件 %s 不是有效 ZIP，已跳过', zip_filename)


def _process_message(account: EmailAccount, uid: str, msg: Message, subject: str) -> dict:
    """处理单封邮件：解析并入库附件。"""
    attachments = list(_iter_pdf_attachments(msg))
    invoices_created = 0
    attachments_attached = 0
    created_invoices: list[Invoice] = []

    user = account.user

    with transaction.atomic():
        non_invoice_attachments: list[_Attachment] = []
        for att in attachments:
            invoice_created, invoice, should_try_statement = _process_pdf_as_invoice_upload(user, att)
            if invoice_created:
                invoices_created += 1
            if invoice is not None and invoice not in created_invoices:
                created_invoices.append(invoice)
            if should_try_statement:
                non_invoice_attachments.append(att)

        for att in non_invoice_attachments:
            if _process_pdf_as_trip_statement_upload(user, att, created_invoices):
                attachments_attached += 1

        ProcessedEmail.objects.update_or_create(
            account=account,
            message_uid=uid,
            defaults={
                'message_id': msg.get('Message-ID', '')[:255],
                'subject': subject[:255],
                'received_at': _parse_date(msg.get('Date')),
                'invoices_created': invoices_created,
                'attachments_attached': attachments_attached,
                'note': '',
            },
        )

    if any(inv.invoice_type == 'TRANSPORT' for inv in created_invoices):
        try:
            regroup_auto_trip_groups(user)
        except Exception:  # noqa: BLE001
            logger.exception('自动重组行程失败')

    return {
        'invoices_created': invoices_created,
        'attachments_attached': attachments_attached,
    }


def _process_pdf_as_invoice_upload(user: User, att: _Attachment) -> tuple[bool, Optional[Invoice], bool]:
    """按发票上传接口语义处理 PDF。返回：是否新增发票、发票对象、是否需要继续尝试行程单。"""
    try:
        parser = PDFInvoiceParser(io.BytesIO(att.content))
        parsed = parser.parse()
    except Exception as exc:  # noqa: BLE001
        logger.info('附件 %s 不是可识别的发票: %s', att.filename, exc)
        return False, None, True

    invoice_number = parsed.get('invoice_number')
    if not invoice_number:
        return False, None, True
    existing = Invoice.objects.filter(invoice_number=invoice_number).first()
    if existing is not None:
        logger.info('邮件中的发票 %s 已存在，跳过', invoice_number)
        return False, existing, False

    invoice = Invoice(user=user, invoice_number=invoice_number)
    invoice.file.save(att.filename, ContentFile(att.content), save=False)
    _apply_parsed_fields(invoice, parsed)
    invoice.save()
    return True, invoice, False


def _process_pdf_as_trip_statement_upload(user: User, att: _Attachment, created_invoices: list[Invoice]) -> bool:
    """按行程单上传接口语义处理 PDF。成功关联返回 True。"""
    try:
        parsed = RideHailingTripStatementParser(io.BytesIO(att.content)).parse()
    except Exception as exc:  # noqa: BLE001
        logger.info('附件 %s 不是可识别的行程单: %s', att.filename, exc)
        return False

    invoice = _find_matching_invoice_for_statement(user, parsed, created_invoices)
    if invoice is None:
        logger.info('未找到申请日期和总金额匹配的发票，跳过行程单附件 %s', att.filename)
        return False
    if invoice.attachments.filter(attachment_type='RIDE_HAILING_TRIP_STATEMENT').exists():
        logger.info('发票 %s 已有行程单，跳过重复附件 %s', invoice.invoice_number, att.filename)
        return False

    InvoiceAttachment.objects.create(
        invoice=invoice,
        file=ContentFile(att.content, name=att.filename),
        original_name=att.filename,
        attachment_type=parsed.get('attachment_type', 'RIDE_HAILING_TRIP_STATEMENT'),
        travel_start_date=_parse_iso_date(parsed.get('travel_start_date')),
        travel_end_date=_parse_iso_date(parsed.get('travel_end_date')),
        travel_departure_place=parsed.get('travel_departure_place', '') or '',
        travel_arrival_place=parsed.get('travel_arrival_place', '') or '',
        travel_details=parsed.get('travel_details') or [],
        travel_total_amount=_parse_decimal(parsed.get('travel_total_amount')),
        application_date=_parse_iso_date(parsed.get('application_date')),
        applicant_phone=parsed.get('applicant_phone', '') or '',
    )
    return True


def _find_matching_invoice_for_statement(user: User, parsed: dict, created_invoices: list[Invoice]) -> Optional[Invoice]:
    amount = _parse_decimal(parsed.get('travel_total_amount'))
    application_date = _parse_iso_date(parsed.get('application_date'))
    if amount is None or application_date is None:
        return None

    for invoice in created_invoices:
        if invoice.amount == amount and invoice.invoice_date == application_date:
            return invoice

    queryset = Invoice.objects.filter(user=user, amount=amount, invoice_date=application_date)
    transport_match = queryset.filter(invoice_type='TRANSPORT').first()
    return transport_match or queryset.first()


def _apply_parsed_fields(invoice: Invoice, parsed: dict) -> None:
    amount_value = parsed.get('amount_in_figures')
    if amount_value:
        try:
            invoice.amount = Decimal(str(amount_value))
        except (InvalidOperation, TypeError):
            pass
    date_value = parsed.get('invoice_date')
    if date_value:
        try:
            invoice.invoice_date = datetime.date.fromisoformat(str(date_value))
        except ValueError:
            pass

    def clean(value):
        return value if value not in (None, '') else None

    invoice.product_name = clean(parsed.get('product_name'))
    invoice.specification_model = clean(parsed.get('specification_model'))
    invoice.unit = clean(parsed.get('unit'))
    invoice.quantity = clean(parsed.get('quantity'))
    invoice.unit_price = clean(parsed.get('unit_price'))
    invoice.money_without_tax = clean(parsed.get('money_without_tax'))
    invoice.tax_rate = clean(parsed.get('tax_rate'))
    invoice.tax_amount = clean(parsed.get('tax_amount'))
    invoice.amount_in_words = clean(parsed.get('amount_in_words'))
    invoice.amount_in_figures = clean(parsed.get('amount_in_figures'))
    invoice.departure_place = clean(parsed.get('departure_place'))
    invoice.arrival_place = clean(parsed.get('arrival_place'))
    invoice_type_val = parsed.get('invoice_type')
    if invoice_type_val:
        invoice.invoice_type = str(invoice_type_val)

    # 服务开始/结束时间（datetime 字段）
    from django.utils.timezone import make_aware
    for field_name in ('service_start_date', 'service_end_date'):
        dt_value = parsed.get(field_name)
        if dt_value:
            try:
                naive = datetime.datetime.fromisoformat(str(dt_value))
                setattr(invoice, field_name, make_aware(naive))
            except (ValueError, TypeError):
                pass


def _parse_iso_date(value) -> datetime.date | None:
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(str(value))
    except ValueError:
        return None


def _parse_decimal(value) -> Decimal | None:
    if value in (None, ''):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError):
        return None


