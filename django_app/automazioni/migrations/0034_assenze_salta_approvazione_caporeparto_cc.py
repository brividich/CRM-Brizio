"""Richieste con «Salta approvazione»: caporeparto in CC se l'ha inserita l'ufficio assenze.

In produzione la mail «Inserimento …» andava solo ad assenza@ (CC vuoto): la 0031
si fermava e il caporeparto non veniva mai avvisato. Ora la mail si divide anche
da quella forma: inserita da un caporeparto (CAR) → solo assenza@; da altri →
assenza@ con il caporeparto del dipendente in CC.

Fail-closed: se le regole non sono quelle attese non tocca niente e lo segnala.
"""
from django.db import migrations


def applica(apps, schema_editor):
    from automazioni.assenze_avviso_inserimento import applica as _applica

    models = tuple(apps.get_model("automazioni", name)
                   for name in ("AutomationRule", "AutomationAction", "AutomationCondition"))
    try:
        result = _applica(models=models)
    except ValueError as exc:
        print(f"\n  [automazioni.0034] Caporeparto in CC con salta approvazione NON applicato: {exc}")
        return
    print(f"\n  [automazioni.0034] Caporeparto in CC con salta approvazione: {result}")


class Migration(migrations.Migration):

    dependencies = [
        ("automazioni", "0033_assenze_una_sola_mail_salta_approvazione"),
    ]

    operations = [
        migrations.RunPython(applica, migrations.RunPython.noop),
    ]
