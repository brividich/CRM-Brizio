"""Toglie le assegnazioni automatiche doppie: la persona è già iscritta a un'edizione aperta
dello stesso corso (es. «Online: slide + test»), quindi il corso lo fa da lì.

Solo assegnazioni create dalla sincronizzazione notturna («Obbligo: …»), ancora «Assegnato»
(mai avviate). Non tocca completamenti, iscrizioni né assegnazioni fatte da HR.
"""
from django.db import migrations


def togli_doppie(apps, schema_editor):
    TrainingAssignment = apps.get_model("anagrafica", "TrainingAssignment")
    TrainingEnrollment = apps.get_model("anagrafica", "TrainingEnrollment")
    iscritti = set(
        TrainingEnrollment.objects.exclude(stato__in=("ASSENTE", "NON_IDONEO", "RITIRATO"))
        .exclude(sessione__stato__in=("COMPLETATA", "ANNULLATA"))
        .filter(sessione__approvata_il__isnull=True)
        .values_list("sessione__corso_id", "legacy_anagrafica_id")
    )
    if not iscritti:
        return
    da_togliere = [
        pk for pk, corso_id, lid in TrainingAssignment.objects.filter(
            stato="ASSEGNATO", note__startswith="Obbligo:", assigned_by__isnull=True,
        ).values_list("pk", "corso_id", "legacy_anagrafica_id")
        if (corso_id, lid) in iscritti
    ]
    for i in range(0, len(da_togliere), 500):
        TrainingAssignment.objects.filter(pk__in=da_togliere[i:i + 500]).delete()


class Migration(migrations.Migration):
    dependencies = [("anagrafica", "0266_org_ufficiale_firma_binding")]
    operations = [migrations.RunPython(togli_doppie, migrations.RunPython.noop)]
