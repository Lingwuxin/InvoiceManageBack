from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0019_invoiceattachment_trip_statement_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='invoiceattachment',
            name='travel_arrival_place',
            field=models.CharField(blank=True, default='', max_length=100, verbose_name='行程到达地'),
        ),
        migrations.AddField(
            model_name='invoiceattachment',
            name='travel_departure_place',
            field=models.CharField(blank=True, default='', max_length=100, verbose_name='行程出发地'),
        ),
        migrations.AddField(
            model_name='invoiceattachment',
            name='travel_details',
            field=models.JSONField(blank=True, default=list, verbose_name='行程明细'),
        ),
    ]