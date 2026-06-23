from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0016_add_trip_separator'),
    ]

    operations = [
        migrations.AddField(
            model_name='invoice',
            name='service_start_date',
            field=models.DateField(blank=True, null=True, verbose_name='服务开始时间'),
        ),
        migrations.AddField(
            model_name='invoice',
            name='service_end_date',
            field=models.DateField(blank=True, null=True, verbose_name='服务结束时间'),
        ),
        migrations.CreateModel(
            name='EmailAccount',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('email_address', models.EmailField(max_length=254, verbose_name='邮箱地址')),
                ('imap_host', models.CharField(max_length=120, verbose_name='IMAP 服务器')),
                ('imap_port', models.PositiveIntegerField(default=993)),
                ('use_ssl', models.BooleanField(default=True)),
                ('username', models.CharField(blank=True, help_text='留空则使用邮箱地址', max_length=120)),
                ('password', models.CharField(max_length=255, verbose_name='密码/授权码')),
                ('folder', models.CharField(default='INBOX', max_length=60)),
                ('keywords', models.CharField(default='发票,行程单,机票,电子客票', help_text='匹配邮件标题的关键词，逗号分隔，命中任一即处理', max_length=255)),
                ('poll_interval_minutes', models.PositiveIntegerField(default=15)),
                ('enabled', models.BooleanField(default=True)),
                ('last_checked_at', models.DateTimeField(blank=True, null=True)),
                ('last_error', models.TextField(blank=True, default='')),
                ('last_uid', models.CharField(blank=True, default='', help_text='已处理过的最大 UID', max_length=64)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='email_account', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='ProcessedEmail',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('message_uid', models.CharField(max_length=64)),
                ('message_id', models.CharField(blank=True, default='', max_length=255)),
                ('subject', models.CharField(blank=True, default='', max_length=255)),
                ('received_at', models.DateTimeField(blank=True, null=True)),
                ('processed_at', models.DateTimeField(auto_now_add=True)),
                ('invoices_created', models.PositiveIntegerField(default=0)),
                ('attachments_attached', models.PositiveIntegerField(default=0)),
                ('note', models.CharField(blank=True, default='', max_length=255)),
                ('account', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='processed_emails', to='core.emailaccount')),
            ],
            options={
                'ordering': ('-processed_at',),
            },
        ),
        migrations.AddConstraint(
            model_name='processedemail',
            constraint=models.UniqueConstraint(fields=('account', 'message_uid'), name='unique_account_message_uid'),
        ),
    ]
