"""对已存在的行程单（InvoiceAttachment）进行去重清洗。

去重策略：
- 同一发票下，保留最早创建的行程单，删除后续重复的。
- "重复"定义为：同一发票下 attachment_type='RIDE_HAILING_TRIP_STATEMENT'，
  且 travel_start_date、travel_end_date、travel_total_amount 均相同（即相同数据）。
- 同时删除同一发票下多余的非行程单重复附件（按 original_name 和文件大小分组）。
"""

from collections import defaultdict
from django.core.management.base import BaseCommand
from core.models import Invoice, InvoiceAttachment


class Command(BaseCommand):
    help = '清洗重复的行程单和附件记录'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='仅列出重复项，不实际删除')
        parser.add_argument('--invoice-id', dest='invoice_id', type=int, help='只处理指定发票 ID')

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        invoice_id = options.get('invoice_id')

        queryset = Invoice.objects.prefetch_related('attachments').order_by('id')
        if invoice_id:
            queryset = queryset.filter(pk=invoice_id)

        total_cleaned = 0
        total_removed = 0

        for invoice in queryset:
            attachments = list(invoice.attachments.all())
            if len(attachments) <= 1:
                continue

            removed = self._dedup_attachments(invoice, attachments, dry_run)
            if removed:
                total_cleaned += 1
                total_removed += removed

        if dry_run:
            self.stdout.write(self.style.WARNING(
                f'\n[DRY-RUN] 将清理 {total_cleaned} 张发票下的 {total_removed} 条重复附件。'
                f'去掉 --dry-run 以实际执行。'
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f'\n完成：清理了 {total_cleaned} 张发票下的 {total_removed} 条重复附件。'
            ))

    # ── 去重逻辑 ──────────────────────────────────────────────

    def _dedup_attachments(self, invoice: Invoice, attachments: list, dry_run: bool) -> int:
        """对一张发票的所有附件去重，返回删除数量。"""
        removed = 0

        # 1) 行程单去重：按 (start_date, end_date, total_amount) 分组
        statements = [a for a in attachments if a.attachment_type == 'RIDE_HAILING_TRIP_STATEMENT']
        removed += self._dedup_group(invoice, statements, dry_run,
                                     group_key=lambda a: (
                                         a.travel_start_date,
                                         a.travel_end_date,
                                         str(a.travel_total_amount) if a.travel_total_amount is not None else '',
                                     ),
                                     label='行程单')

        # 2) 非行程单附件去重：按 (original_name, 文件大小) 分组
        other_attachments = [
            a for a in attachments
            if a.attachment_type != 'RIDE_HAILING_TRIP_STATEMENT'
        ]
        removed += self._dedup_group(invoice, other_attachments, dry_run,
                                     group_key=lambda a: (
                                         a.original_name or '',
                                         self._file_size(a),
                                     ),
                                     label='附件')

        return removed

    def _dedup_group(self, invoice: Invoice, items: list, dry_run: bool,
                     group_key, label: str) -> int:
        """对一组附件按 key 分组，每组只保留最早的一条，删除其余。"""
        if len(items) <= 1:
            return 0

        groups: dict[tuple, list] = defaultdict(list)
        for item in items:
            key = group_key(item)
            groups[key].append(item)

        removed = 0
        for key, group in groups.items():
            if len(group) <= 1:
                continue
            # 按创建时间升序，保留第一条
            group.sort(key=lambda a: a.created_at)
            keep = group[0]
            to_delete = group[1:]

            for dup in to_delete:
                self.stdout.write(
                    f'  [{invoice.user.username}] 发票 #{invoice.pk} {invoice.invoice_number}'
                    f' — {label}重复 (保留 #{keep.pk}, 删除 #{dup.pk}'
                    f' {dup.original_name or "(无名称)"})'
                )
                if not dry_run:
                    dup.delete()  # post_delete 信号会自动删除磁盘文件
                removed += 1

        return removed

    @staticmethod
    def _file_size(attachment: InvoiceAttachment) -> int:
        """返回附件的文件大小（字节），获取失败返回 0。"""
        try:
            if attachment.file:
                return attachment.file.size or 0
        except Exception:
            pass
        return 0
