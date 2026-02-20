from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0007_alter_invoice_invoice_number'),
    ]

    operations = [
        migrations.AddField(
            model_name='reimbursement',
            name='details',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
