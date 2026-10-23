"""Assemblea sindacale e Flessibilità con «Salta approvazione»: niente doppia mail ad
assenza@. Dettagli in ``automazioni.assenze_avviso_speciali``.

Fail-closed per regola: quello che non ha la forma attesa resta com'è e lo si
scrive nel log; il deploy prosegue.
"""
from django.db import migrations


def applica(apps, schema_editor):
    from automazioni.assenze_avviso_speciali import applica as _applica

    models = tuple(apps.get_model("automazioni", name) for name in ("AutomationRule", "AutomationAction"))
    try:
        result = _applica(models=models)
    except Exception as exc:  # noqa: BLE001 - il deploy non si ferma per una regola mail
        print(f"\n  [automazioni.0032] Assemblea/Flessibilità con salta approvazione NON applicato: {exc}")
        return
    print(f"\n  [automazioni.0032] Assemblea/Flessibilità con salta approvazione: {result}")


class Migration(migrations.Migration):

    dependencies = [
        ("automazioni", "0031_assenze_avviso_salta_approvazione"),
    ]

    operations = [
        migrations.RunPython(applica, migrations.RunPython.noop),
    ]
