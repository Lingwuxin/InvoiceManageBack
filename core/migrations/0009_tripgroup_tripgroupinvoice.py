from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0008_reimbursement_details'),
    ]

    operations = [
        migrations.CreateModel(
            name='TripGroup',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('source', models.CharField(choices=[('AUTO', '自动归组'), ('MANUAL', '手动归组')], default='AUTO', max_length=20)),
                ('home_city', models.CharField(blank=True, max_length=50, null=True)),
                ('start_date', models.DateField(blank=True, null=True)),
                ('end_date', models.DateField(blank=True, null=True)),
                ('duration_days', models.PositiveIntegerField(blank=True, null=True)),
                ('is_complete', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='trip_groups', to='core.user')),
            ],
            options={
                'ordering': ('start_date', 'created_at', 'id'),
            },
        ),
        migrations.CreateModel(
            name='TripGroupInvoice',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('sort_order', models.PositiveIntegerField(default=1)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('invoice', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='trip_group_invoices', to='core.invoice')),
                ('trip_group', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='trip_group_invoices', to='core.tripgroup')),
            ],
            options={
                'ordering': ('sort_order', 'id'),
            },
        ),
        migrations.AddConstraint(
            model_name='tripgroupinvoice',
            constraint=models.UniqueConstraint(fields=('invoice',), name='unique_invoice_trip_group'),
        ),
        migrations.AddConstraint(
            model_name='tripgroupinvoice',
            constraint=models.UniqueConstraint(fields=('trip_group', 'invoice'), name='unique_invoice_in_trip_group'),
        ),
    ]