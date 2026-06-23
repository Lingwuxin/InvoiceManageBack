from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0018_change_service_dates_to_datetime'),
    ]

    operations = [
        migrations.AddField(
            model_name='invoiceattachment',
            name='applicant_phone',
            field=models.CharField(blank=True, default='', max_length=30, verbose_name='申请人手机号'),
        ),
        migrations.AddField(
            model_name='invoiceattachment',
            name='application_date',
            field=models.DateField(blank=True, null=True, verbose_name='申请日期'),
        ),
        migrations.AddField(
            model_name='invoiceattachment',
            name='attachment_type',
            field=models.CharField(blank=True, default='', max_length=50, verbose_name='附件类型'),
        ),
        migrations.AddField(
            model_name='invoiceattachment',
            name='travel_end_date',
            field=models.DateField(blank=True, null=True, verbose_name='行程结束日期'),
        ),
        migrations.AddField(
            model_name='invoiceattachment',
            name='travel_start_date',
            field=models.DateField(blank=True, null=True, verbose_name='行程开始日期'),
        ),
        migrations.AddField(
            model_name='invoiceattachment',
            name='travel_total_amount',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True, verbose_name='行程总金额'),
        ),
    ]