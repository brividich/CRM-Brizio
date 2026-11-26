"""Un corso, un completamento: chi ha già completato un corso e-learning (dal portale o dal
link aperto) risulta completato anche nelle sessioni online dello stesso corso a cui è
iscritto. Da qui in poi lo fa ``services.sessione_online.completa_iscrizioni_da_record``;
questa migrazione allinea i completamenti già fatti. Non crea completamenti nuovi."""
from decimal import Decimal

from django.db import migrations
from django.db.models import Q


def allinea(apps, schema_editor):
    Record = apps.get_model("anagrafica", "TrainingEmployeeRecord")
    Enrollment = apps.get_model("anagrafica", "TrainingEnrollment")
    record = (Record.objects.filter(enrollment__isnull=True, annullato_il__isnull=True, corso__is_elearning=True)
              .order_by("pk"))
    for r in record:
        qs = (Enrollment.objects
              .filter(legacy_anagrafica_id=r.legacy_anagrafica_id, sessione__corso_id=r.corso_id,
                      record_completamento__isnull=True)
              .exclude(stato__in=("COMPLETATO", "RITIRATO"))
              .exclude(sessione__stato="ANNULLATA")
              .filter(Q(sessione__modalita="ONLINE")
                      | Q(sessione__lezione_online__pubblicata_il__isnull=False,
                          sessione__lezione_online__test_in_aula=False)))
        calc = r.completion_calculation_snapshot_json or {}
        try:
            punteggio = Decimal(str(calc.get("quiz_punteggio_pct"))) if calc.get("quiz_punteggio_pct") else None
        except Exception:  # noqa: BLE001
            punteggio = None
        collegato = False
        for e in qs:
            e.stato = "COMPLETATO"
            e.data_completamento = r.data_completamento
            e.verifica_superata = True
            e.idoneo = True
            e.percentuale_presenza = Decimal("100")
            e.modalita_verifica = "TEST"
            e.data_verifica = r.data_completamento
            if punteggio is not None:
                e.punteggio = punteggio
            nota = f"Completato con il corso online il {r.data_completamento:%d-%m-%Y} (completamento #{r.pk})."
            e.note = ((e.note + "\n") if e.note else "") + nota
            e.save()
            if not collegato:
                Record.objects.filter(pk=r.pk).update(enrollment_id=e.pk, sessione_id=e.sessione_id)
                collegato = True


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0256_organigramma_ufficiale"),
    ]

    operations = [
        migrations.RunPython(allinea, migrations.RunPython.noop),
    ]
