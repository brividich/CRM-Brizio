"""Soppressioni: data del promemoria «in scadenza» mandato dal ciclo del SOC (una volta per scadenza)."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("security", "0039_titoli_in_italiano"),
    ]

    operations = [
        migrations.AddField(
            model_name="securityalertsuppressionrule",
            name="promemoria_il",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
