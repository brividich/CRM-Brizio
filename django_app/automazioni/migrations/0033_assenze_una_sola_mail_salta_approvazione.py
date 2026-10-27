"""Richieste con «Salta approvazione»: una sola mail ad assenza@ («Inserimento …»).

La 0031 faceva due cose insieme e in produzione si è fermata sulla prima (la mail
di inserimento non aveva il caporeparto in CC), quindi non ha aggiunto nemmeno la
condizione che toglie la seconda mail «Approvazione …». Qui solo quella.

Fail-closed: se le regole non sono quelle attese non tocca niente e lo segnala.
"""
from django.db import migrations


def applica(apps, schema_editor):
    from automazioni.assenze_avviso_inserimento import togli_doppione

    models = tuple(apps.get_model("automazioni", name)
                   for name in ("AutomationRule", "AutomationAction", "AutomationCondition"))
    try:
        result = togli_doppione(models=models)
    except ValueError as exc:
        print(f"\n  [automazioni.0033] Una sola mail ad assenza@ NON applicato: {exc}")
        return
    print(f"\n  [automazioni.0033] Una sola mail ad assenza@ con salta approvazione: {result}")


class Migration(migrations.Migration):

    dependencies = [
        ("automazioni", "0032_assenze_speciali_salta_approvazione"),
    ]

    operations = [
        migrations.RunPython(applica, migrations.RunPython.noop),
    ]
