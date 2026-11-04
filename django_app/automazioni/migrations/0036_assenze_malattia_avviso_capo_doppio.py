"""Malattia: al caporeparto una sola mail, quella di approvazione.

La regola importata da Power Automate «Avviso malattia al responsabile»
(``assenze-pa-malattia-avviso-capo``) veniva dal vecchio flusso, in cui la
malattia non si approvava: avvisava il caporeparto a ogni inserimento. Con
l'approvazione unificata (``assenze-approvazione-unificata``) la malattia passa
dall'approvazione del caporeparto, quindi il caporeparto riceveva due mail: la
richiesta da approvare e l'«Inserimento malattia». Con «Salta approvazione» lo
avvisa gia' la regola ``assenze-pa-skip-approvazione-avviso-inserimento`` (in CC).

La regola si disattiva, non si cancella: resta consultabile e riattivabile.
Fail-closed: senza l'approvazione unificata attiva non tocca niente.
"""
from django.db import migrations

REGOLA = "assenze-pa-malattia-avviso-capo"
UNIFICATA = "assenze-approvazione-unificata"


def applica(apps, schema_editor):
    AutomationRule = apps.get_model("automazioni", "AutomationRule")
    if not AutomationRule.objects.filter(code=UNIFICATA, is_active=True).exists():
        print(f"\n  [automazioni.0036] Avviso malattia al caporeparto NON disattivato: «{UNIFICATA}» non attiva.")
        return
    n = AutomationRule.objects.filter(code=REGOLA, is_active=True).update(is_active=False)
    print(f"\n  [automazioni.0036] Avviso malattia al caporeparto disattivato: {n} regola/e.")


class Migration(migrations.Migration):

    dependencies = [
        ("automazioni", "0035_email_inviate"),
    ]

    operations = [
        migrations.RunPython(applica, migrations.RunPython.noop),
    ]
