"""Unisce i due flussi di approvazione Assenze, che partivano entrambi a ogni richiesta.

Con le regole «assenze-pa-richiesta-approvazione-caporeparto» e
«au-assenze-unico-branch-per-tipo» attive insieme il caporeparto riceveva due mail
di approvazione; approvando quella del flusso ramificato la richiesta restava «in
attesa» e la mailbox assenza@ non veniva avvisata. Si applica l'unione già prevista
da ``merge_assenze_flows`` (originali conservati, disattivati) e si sostituisce il
segnaposto HR dell'approvazione finale delle ferie lunghe con la mailbox assenze.

Fail-closed: se le regole non sono quelle censite dall'audit non tocca niente e lo
segnala; il deploy prosegue.
"""
from django.db import migrations

ASSENZE_MAILBOX = "assenza@costruzioninovicrom.it"


def unisci(apps, schema_editor):
    from automazioni.assenze_flow_merge import merge_flows

    models = tuple(apps.get_model("automazioni", name)
                   for name in ("AutomationRule", "AutomationAction", "AutomationCondition"))
    try:
        result = merge_flows(apply=True, hr_recipient=ASSENZE_MAILBOX, models=models)
    except ValueError as exc:
        print(f"\n  [automazioni.0030] Unione flussi Assenze NON applicata: {exc}")
        return
    print(f"\n  [automazioni.0030] Unione flussi Assenze: {result}")


class Migration(migrations.Migration):

    dependencies = [
        ("automazioni", "0029_disattiva_regola_anomalie_modificata"),
    ]

    operations = [
        migrations.RunPython(unisci, migrations.RunPython.noop),
    ]
