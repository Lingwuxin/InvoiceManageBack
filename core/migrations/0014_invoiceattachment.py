from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0013_tripgroup_title'),
    ]

    operations = [
        migrations.CreateModel(
            name='InvoiceAttachment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('file', models.FileField(upload_to='invoice-attachments/')),
                ('original_name', models.CharField(max_length=255)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('invoice', models.ForeignKey(on_delete=models.deletion.CASCADE, related_name='attachments', to='core.invoice')),
            ],
            options={
                'ordering': ('created_at', 'id'),
            },
        ),
    ]