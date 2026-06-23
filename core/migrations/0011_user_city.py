from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0010_user_company'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='city',
            field=models.CharField(blank=True, max_length=50, null=True, verbose_name='所属城市'),
        ),
    ]