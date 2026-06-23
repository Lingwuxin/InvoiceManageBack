from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0011_user_city'),
    ]

    operations = [
        migrations.AddField(
            model_name='tripgroupinvoice',
            name='reimbursement_category',
            field=models.CharField(
                choices=[('TRANSPORT', '交通费'), ('ACCOMMODATION', '住宿费'), ('OTHER', '其他费用')],
                default='TRANSPORT',
                max_length=20,
            ),
        ),
    ]