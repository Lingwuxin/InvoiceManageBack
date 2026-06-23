from django.db import models
from django.db.models.signals import post_delete
from django.contrib.auth.models import AbstractUser
from django.dispatch import receiver

class User(AbstractUser):
    ROLE_CHOICES = (
        ('EMPLOYEE', 'Employee'),
        ('ACCOUNTANT', 'Accountant'),
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='EMPLOYEE')
    real_name = models.CharField(max_length=50, blank=True, null=True, verbose_name="姓名")
    company = models.CharField(max_length=100, blank=True, null=True, verbose_name="所属公司")
    city = models.CharField(max_length=50, blank=True, null=True, verbose_name="所属城市")
    department = models.CharField(max_length=100, blank=True, null=True, verbose_name="部门")
    dept_leader = models.CharField(max_length=50, blank=True, null=True, verbose_name="部门领导")

class Invoice(models.Model):
    INVOICE_TYPE_CHOICES = (
        ('TRANSPORT', '交通费'),
        ('ACCOMMODATION', '住宿费'),
        ('OTHER', '其他费用'),
    )

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='invoices')
    file = models.FileField(upload_to='invoices/')
    invoice_number = models.CharField(max_length=50, unique=True, verbose_name="发票号码")
    invoice_type = models.CharField(max_length=20, choices=INVOICE_TYPE_CHOICES, default='OTHER')
    amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    invoice_date = models.DateField(null=True, blank=True)
    product_name = models.CharField(max_length=255, null=True, blank=True)
    specification_model = models.CharField(max_length=255, null=True, blank=True)
    unit = models.CharField(max_length=50, null=True, blank=True)
    quantity = models.CharField(max_length=50, null=True, blank=True)
    unit_price = models.CharField(max_length=50, null=True, blank=True)
    money_without_tax = models.CharField(max_length=50, null=True, blank=True)
    tax_rate = models.CharField(max_length=50, null=True, blank=True)
    tax_amount = models.CharField(max_length=50, null=True, blank=True)
    amount_in_words = models.CharField(max_length=255, null=True, blank=True)
    amount_in_figures = models.CharField(max_length=50, null=True, blank=True)
    departure_place = models.CharField(max_length=100, null=True, blank=True)
    arrival_place = models.CharField(max_length=100, null=True, blank=True)
    # 发票服务起止时间 —— 主要用于火车票/机票的具体时刻及网约车（订单跨越多日的合并发票）等场景
    service_start_date = models.DateTimeField(null=True, blank=True, verbose_name="服务开始时间")
    service_end_date = models.DateTimeField(null=True, blank=True, verbose_name="服务结束时间")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Invoice {self.pk} - {self.user.username}"


class InvoiceAttachment(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='attachments')
    file = models.FileField(upload_to='invoice-attachments/')
    original_name = models.CharField(max_length=255)
    attachment_type = models.CharField(max_length=50, blank=True, default='', verbose_name="附件类型")
    travel_start_date = models.DateField(null=True, blank=True, verbose_name="行程开始日期")
    travel_end_date = models.DateField(null=True, blank=True, verbose_name="行程结束日期")
    travel_departure_place = models.CharField(max_length=100, blank=True, default='', verbose_name="行程出发地")
    travel_arrival_place = models.CharField(max_length=100, blank=True, default='', verbose_name="行程到达地")
    travel_details = models.JSONField(default=list, blank=True, verbose_name="行程明细")
    travel_total_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="行程总金额")
    application_date = models.DateField(null=True, blank=True, verbose_name="申请日期")
    applicant_phone = models.CharField(max_length=30, blank=True, default='', verbose_name="申请人手机号")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('created_at', 'id')

    def __str__(self):
        return f"InvoiceAttachment {self.pk} - {self.invoice.pk}"


@receiver(post_delete, sender=InvoiceAttachment)
def delete_invoice_attachment_file(sender, instance, **kwargs):
    if instance.file:
        instance.file.delete(save=False)


class TripGroup(models.Model):
    SOURCE_CHOICES = (
        ('AUTO', '自动归组'),
        ('MANUAL', '手动归组'),
    )

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='trip_groups')
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='AUTO')
    title = models.CharField(max_length=120, blank=True, null=True)
    home_city = models.CharField(max_length=50, blank=True, null=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    duration_days = models.PositiveIntegerField(null=True, blank=True)
    is_complete = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('start_date', 'created_at', 'id')

    def __str__(self):
        return f"TripGroup {self.pk} - {self.user.username} - {self.source}"


class TripGroupInvoice(models.Model):
    CATEGORY_CHOICES = Invoice.INVOICE_TYPE_CHOICES

    trip_group = models.ForeignKey(TripGroup, on_delete=models.CASCADE, related_name='trip_group_invoices')
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='trip_group_invoices')
    reimbursement_category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='TRANSPORT')
    sort_order = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('sort_order', 'id')
        constraints = [
            models.UniqueConstraint(fields=('invoice',), name='unique_invoice_trip_group'),
            models.UniqueConstraint(fields=('trip_group', 'invoice'), name='unique_invoice_in_trip_group'),
        ]

    def __str__(self):
        return f"TripGroupInvoice {self.trip_group.pk} - {self.invoice.pk}"


class TripSeparator(models.Model):
    """行程周期分隔符 —— 用户在时间线上手动插入的行程结束标记。
    分隔符之前的所有未分隔发票（自上一个分隔符或列表起始）构成一个行程周期。
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='trip_separators')
    # 分隔符紧跟在哪张发票之后；为 None 表示在列表最开头之前（较少使用）
    after_invoice = models.ForeignKey(
        Invoice,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='trailing_separator',
    )
    label = models.CharField(max_length=120, blank=True, null=True, verbose_name="分隔备注")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('created_at', 'id')

    def __str__(self):
        label = self.label or '分隔符'
        invoice_ref = f'发票 #{self.after_invoice_id}' if self.after_invoice_id else '列表开头'
        return f'{label}（{invoice_ref}）'

class Reimbursement(models.Model):
    STATUS_CHOICES = (
        ('PENDING', 'Pending'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
    )
    applicant = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reimbursements')
    invoices = models.ManyToManyField(Invoice, related_name='reimbursements')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    reviewer = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_reimbursements')
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Reimbursement {self.pk} - {self.applicant.username}"


class EmailAccount(models.Model):
    """用户邮箱配置 —— 用于通过 IMAP 定时拉取发票邮件。"""
    PROTOCOL_CHOICES = (
        ('IMAP', 'IMAP'),
    )

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='email_account')
    email_address = models.EmailField(verbose_name="邮箱地址")
    imap_host = models.CharField(max_length=120, verbose_name="IMAP 服务器")
    imap_port = models.PositiveIntegerField(default=993)
    use_ssl = models.BooleanField(default=True)
    username = models.CharField(max_length=120, blank=True, help_text="留空则使用邮箱地址")
    # 注：此处密码以明文存储，建议在生产环境中接入加密层（如 cryptography.fernet）。
    password = models.CharField(max_length=255, verbose_name="密码/授权码")
    folder = models.CharField(max_length=60, default='INBOX')
    keywords = models.CharField(
        max_length=255,
        default='发票,行程单,机票,电子客票',
        help_text='匹配邮件标题的关键词，逗号分隔，命中任一即处理',
    )
    poll_interval_minutes = models.PositiveIntegerField(default=15)
    enabled = models.BooleanField(default=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default='')
    last_uid = models.CharField(max_length=64, blank=True, default='', help_text='已处理过的最大 UID')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"EmailAccount<{self.user.username}:{self.email_address}>"

    @property
    def keyword_list(self) -> list[str]:
        return [kw.strip() for kw in (self.keywords or '').split(',') if kw.strip()]


class ProcessedEmail(models.Model):
    """记录已处理过的邮件，避免重复处理。"""
    account = models.ForeignKey(EmailAccount, on_delete=models.CASCADE, related_name='processed_emails')
    message_uid = models.CharField(max_length=64)
    message_id = models.CharField(max_length=255, blank=True, default='')
    subject = models.CharField(max_length=255, blank=True, default='')
    received_at = models.DateTimeField(null=True, blank=True)
    processed_at = models.DateTimeField(auto_now_add=True)
    invoices_created = models.PositiveIntegerField(default=0)
    attachments_attached = models.PositiveIntegerField(default=0)
    note = models.CharField(max_length=255, blank=True, default='')

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=('account', 'message_uid'), name='unique_account_message_uid'),
        ]
        ordering = ('-processed_at',)

    def __str__(self):
        return f"ProcessedEmail<{self.account.user.username}:{self.message_uid}>"
