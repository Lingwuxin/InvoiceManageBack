from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0014_invoiceattachment'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='dept_leader',
            field=models.CharField(blank=True, max_length=50, null=True, verbose_name='部门领导'),
        ),
    ]