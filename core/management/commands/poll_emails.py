"""定时轮询所有启用了的邮箱账户，抓取并解析新邮件中的发票附件。

使用方式::

    # 单次执行
    python manage.py poll_emails --once

    # 后台守护循环（每 60 秒检查一次哪些账户到达轮询间隔）
    python manage.py poll_emails --interval 60
"""

import logging
import time

from django.core.management.base import BaseCommand

from core.email_service import fetch_due_accounts

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = '轮询启用的邮箱账户，抓取发票邮件'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true', help='只执行一次后退出')
        parser.add_argument('--interval', type=int, default=60, help='守护循环检查间隔秒数')

    def handle(self, *args, **options):
        once = options['once']
        interval = max(10, options['interval'])
        while True:
            results = fetch_due_accounts()
            if results:
                self.stdout.write(self.style.SUCCESS(f'本轮处理结果: {results}'))
            if once:
                break
            time.sleep(interval)
