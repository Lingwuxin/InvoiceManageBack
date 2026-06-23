import datetime
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand
from django.utils.timezone import make_aware

from core.models import Invoice, User
from core.trip_groups import regroup_auto_trip_groups
from tools.pdf_parser import PDFInvoiceParser


class Command(BaseCommand):
    help = '重新解析已入库发票 PDF，并将解析结果回写到数据库。'

    def add_arguments(self, parser):
        parser.add_argument('--invoice-number', dest='invoice_number', help='只重解析指定发票号码')
        parser.add_argument('--user-id', dest='user_id', type=int, help='只重解析指定用户的发票')
        parser.add_argument('--dry-run', action='store_true', help='只打印解析结果，不写入数据库')

    def handle(self, *args, **options):
        queryset = Invoice.objects.select_related('user').order_by('id')
        if options.get('invoice_number'):
            queryset = queryset.filter(invoice_number=options['invoice_number'])
        if options.get('user_id'):
            queryset = queryset.filter(user_id=options['user_id'])

        total = queryset.count()
        success = 0
        failed = 0
        affected_users: set[int] = set()

        self.stdout.write(f'开始重解析 {total} 张发票')
        for invoice in queryset:
            if not invoice.file or not invoice.file.name.lower().endswith('.pdf'):
                self.stdout.write(self.style.WARNING(f'跳过 #{invoice.pk} {invoice.invoice_number}: 非 PDF 文件'))
                continue

            try:
                parser = PDFInvoiceParser(invoice.file.path)
                parsed = parser.parse()
            except Exception as exc:
                failed += 1
                self.stdout.write(self.style.ERROR(f'失败 #{invoice.pk} {invoice.invoice_number}: {exc}'))
                continue

            before = {
                'amount': str(invoice.amount) if invoice.amount is not None else '',
                'invoice_date': invoice.invoice_date.isoformat() if invoice.invoice_date else '',
                'amount_in_figures': invoice.amount_in_figures or '',
                'amount_in_words': invoice.amount_in_words or '',
                'product_name': invoice.product_name or '',
                'invoice_type': invoice.invoice_type or '',
            }

            self._apply_parsed_fields(invoice, parsed, dry_run=options['dry_run'])

            after = {
                'amount': str(invoice.amount) if invoice.amount is not None else '',
                'invoice_date': invoice.invoice_date.isoformat() if invoice.invoice_date else '',
                'amount_in_figures': invoice.amount_in_figures or '',
                'amount_in_words': invoice.amount_in_words or '',
                'product_name': invoice.product_name or '',
                'invoice_type': invoice.invoice_type or '',
            }
            changed = {key: (before[key], after[key]) for key in before if before[key] != after[key]}
            if changed:
                self.stdout.write(self.style.SUCCESS(f'更新 #{invoice.pk} {invoice.invoice_number}: {changed}'))
            else:
                self.stdout.write(f'无变化 #{invoice.pk} {invoice.invoice_number}')

            success += 1
            if invoice.invoice_type == 'TRANSPORT':
                affected_users.add(invoice.user_id)

        if not options['dry_run']:
            for user_id in affected_users:
                user = User.objects.filter(pk=user_id).first()
                if user:
                    regroup_auto_trip_groups(user)

        self.stdout.write(self.style.SUCCESS(f'完成：成功 {success}，失败 {failed}'))

    def _apply_parsed_fields(self, invoice: Invoice, parsed: dict, dry_run: bool = False) -> None:
        amount_value = parsed.get('amount_in_figures') or parsed.get('amount')
        if amount_value not in (None, ''):
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

        def clean_value(value):
            return value if value not in (None, '') else None

        invoice.product_name = clean_value(parsed.get('product_name'))
        invoice_type_val = parsed.get('invoice_type')
        if invoice_type_val:
            invoice.invoice_type = str(invoice_type_val)

        invoice.specification_model = clean_value(parsed.get('specification_model'))
        invoice.unit = clean_value(parsed.get('unit'))
        invoice.quantity = clean_value(parsed.get('quantity'))
        invoice.unit_price = clean_value(parsed.get('unit_price'))
        invoice.money_without_tax = clean_value(parsed.get('money_without_tax'))
        invoice.tax_rate = clean_value(parsed.get('tax_rate'))
        invoice.tax_amount = clean_value(parsed.get('tax_amount'))
        invoice.amount_in_words = clean_value(parsed.get('amount_in_words'))
        invoice.amount_in_figures = clean_value(parsed.get('amount_in_figures'))
        invoice.departure_place = clean_value(parsed.get('departure_place'))
        invoice.arrival_place = clean_value(parsed.get('arrival_place'))

        for field_name in ('service_start_date', 'service_end_date'):
            dt_value = parsed.get(field_name)
            if dt_value:
                try:
                    naive = datetime.datetime.fromisoformat(str(dt_value))
                    setattr(invoice, field_name, make_aware(naive))
                except (ValueError, TypeError):
                    pass

        if dry_run:
            return

        invoice.save(update_fields=[
            'amount',
            'invoice_date',
            'product_name',
            'specification_model',
            'unit',
            'quantity',
            'unit_price',
            'money_without_tax',
            'tax_rate',
            'tax_amount',
            'amount_in_words',
            'amount_in_figures',
            'invoice_type',
            'departure_place',
            'arrival_place',
            'service_start_date',
            'service_end_date',
        ])
