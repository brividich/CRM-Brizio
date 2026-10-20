"""Richieste con «Salta approvazione»: una sola mail ad assenza@, caporeparto in CC
solo se non l'ha inserita lui. Dettagli in ``automazioni.assenze_avviso_inserimento``.

Fail-closed: se le regole non sono quelle attese non tocca niente e lo segnala;
il deploy prosegue.
"""
from django.db import migrations


def applica(apps, schema_editor):
    from automazioni.assenze_avviso_inserimento import applica as _applica

    models = tuple(apps.get_model("automazioni", name)
                   for name in ("AutomationRule", "AutomationAction", "AutomationCondition"))
    try:
        result = _applica(models=models)
    except ValueError as exc:
        print(f"\n  [automazioni.0031] Avviso assenza@ con salta approvazione NON applicato: {exc}")
        return
    print(f"\n  [automazioni.0031] Avviso assenza@ con salta approvazione: {result}")


class Migration(migrations.Migration):

    dependencies = [
        ("automazioni", "0030_unisci_flussi_assenze"),
    ]

    operations = [
        migrations.RunPython(applica, migrations.RunPython.noop),
    ]
