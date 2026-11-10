"""Richieste con «Salta approvazione»: la mail arriva anche al dipendente, tranne la malattia.

Finora andava solo ad assenza@ (e al caporeparto): permessi, ferie e flessibilità
inseriti dall'amministrazione per conto del dipendente non gli venivano comunicati.
Dettagli in ``automazioni.assenze_avviso_inserimento.avvisa_dipendente``.
Fail-closed: se la regola non ha la forma attesa non tocca niente e lo segnala.
"""
from django.db import migrations


def applica(apps, schema_editor):
    from automazioni.assenze_avviso_inserimento import avvisa_dipendente

    models = tuple(apps.get_model("automazioni", name)
                   for name in ("AutomationRule", "AutomationAction", "AutomationCondition"))
    try:
        result = avvisa_dipendente(models=models)
    except ValueError as exc:
        print(f"\n  [automazioni.0037] Mail al dipendente con salta approvazione NON applicata: {exc}")
        return
    print(f"\n  [automazioni.0037] Mail al dipendente con salta approvazione: {result}")


class Migration(migrations.Migration):
    dependencies = [
        ("automazioni", "0036_assenze_malattia_avviso_capo_doppio"),
    ]

    operations = [
        migrations.RunPython(applica, migrations.RunPython.noop),
    ]
