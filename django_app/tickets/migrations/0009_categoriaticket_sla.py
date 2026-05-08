from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tickets', '0008_ticket_include_in_maintenance_register'),
    ]

    operations = [
        migrations.AddField(
            model_name='categoriaticket',
            name='sla_ore_risposta',
            field=models.PositiveIntegerField(
                blank=True,
                null=True,
                help_text='SLA risposta (ore). Vuoto = nessuno SLA.',
            ),
        ),
        migrations.AddField(
            model_name='categoriaticket',
            name='sla_ore_risoluzione',
            field=models.PositiveIntegerField(
                blank=True,
                null=True,
                help_text='SLA risoluzione (ore). Vuoto = nessuno SLA.',
            ),
        ),
    ]
