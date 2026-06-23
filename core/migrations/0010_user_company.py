from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0009_tripgroup_tripgroupinvoice'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='company',
            field=models.CharField(blank=True, max_length=100, null=True, verbose_name='所属公司'),
        ),
    ]