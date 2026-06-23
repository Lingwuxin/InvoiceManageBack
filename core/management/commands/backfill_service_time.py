"""
重新解析已有运输类发票的 PDF，补全 service_start_date。
用法: python manage.py backfill_service_time [--dry-run]
"""
from django.core.management.base import BaseCommand
from core.models import Invoice


class Command(BaseCommand):
    help = '为已有的火车票/机票发票补全 service_start_date'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='仅列出将要更新的发票，不实际写入',
        )

    def handle(self, **options):
        dry_run = options['dry_run']
        qs = Invoice.objects.filter(
            invoice_type='TRANSPORT',
            service_start_date__isnull=True,
        )
        total = qs.count()
        self.stdout.write(f'找到 {total} 张缺少 service_start_date 的运输类发票')
        if total == 0:
            return

        updated = 0
        skipped = 0
        for invoice in qs.iterator():
            try:
                file = invoice.file
                if not file:
                    skipped += 1
                    self.stdout.write(self.style.WARNING(
                        f'  跳过 #{invoice.id}：无附件文件'
                    ))
                    continue

                from tools.pdf_parser import PDFInvoiceParser
                file.open('rb')
                try:
                    parser = PDFInvoiceParser(file)
                    parsed = parser.parse()
                finally:
                    file.close()

                dt_str = parsed.get('service_start_date')
                if not dt_str:
                    skipped += 1
                    self.stdout.write(f'  跳过 #{invoice.id}：PDF 中无时刻信息')
                    continue

                import datetime as dt
                from django.utils.timezone import make_aware
                naive = dt.datetime.fromisoformat(dt_str)
                invoice.service_start_date = make_aware(naive)

                if dry_run:
                    self.stdout.write(
                        f'  [DRY-RUN] #{invoice.id} {invoice.invoice_number} '
                        f'{invoice.departure_place}→{invoice.arrival_place} '
                        f'=> {dt_str}'
                    )
                else:
                    invoice.save(update_fields=['service_start_date'])
                    self.stdout.write(
                        f'  ✓ #{invoice.id} {invoice.invoice_number} '
                        f'{invoice.departure_place}→{invoice.arrival_place} '
                        f'=> {dt_str}'
                    )
                updated += 1

            except Exception as exc:
                skipped += 1
                self.stdout.write(self.style.ERROR(
                    f'  失败 #{invoice.id}: {exc}'
                ))

        self.stdout.write(self.style.SUCCESS(
            f'完成：更新 {updated} 张，跳过 {skipped} 张'
            + (' (DRY-RUN 模式，未实际写入)' if dry_run else '')
        ))
