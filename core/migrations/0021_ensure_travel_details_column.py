from django.db import migrations


def ensure_travel_details_column(apps, schema_editor):
    table_name = 'core_invoiceattachment'
    column_name = 'travel_details'
    existing_columns = {
        column.name
        for column in schema_editor.connection.introspection.get_table_description(
            schema_editor.connection.cursor(),
            table_name,
        )
    }
    if column_name in existing_columns:
        return

    vendor = schema_editor.connection.vendor
    if vendor == 'mysql':
        schema_editor.execute(
            f'ALTER TABLE `{table_name}` ADD COLUMN `{column_name}` JSON NULL'
        )
    elif vendor == 'sqlite':
        schema_editor.execute(
            f'ALTER TABLE "{table_name}" ADD COLUMN "{column_name}" text NULL'
        )
    else:
        schema_editor.execute(
            f'ALTER TABLE "{table_name}" ADD COLUMN "{column_name}" jsonb NULL'
        )


class Migration(migrations.Migration):

    atomic = False

    dependencies = [
        ('core', '0020_invoiceattachment_travel_places'),
    ]

    operations = [
        migrations.RunPython(ensure_travel_details_column, migrations.RunPython.noop),
    ]
