from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0012_tripgroupinvoice_reimbursement_category'),
    ]

    operations = [
        migrations.AddField(
            model_name='tripgroup',
            name='title',
            field=models.CharField(blank=True, max_length=120, null=True),
        ),
    ]