"""Spegne la vecchia regola «AU-MAIL-ANOMALIE anomalia modificata».

Chiamava un endpoint del portale che non esiste più e andava in errore a ogni
modifica. Il riepilogo delle modifiche lo manda il modulo anomalie (coda di 5
minuti, flusso anomalie_pending_notifications). La regola resta, solo spenta.
"""
from django.db import migrations

CODE = "au-mail-anomalie-cc-car-update"


def disattiva(apps, schema_editor):
    AutomationRule = apps.get_model("automazioni", "AutomationRule")
    AutomationRule.objects.filter(code=CODE, is_active=True).update(is_active=False)


class Migration(migrations.Migration):

    dependencies = [
        ("automazioni", "0028_approval_links_branch_progress"),
    ]

    operations = [
        migrations.RunPython(disattiva, migrations.RunPython.noop),
    ]
