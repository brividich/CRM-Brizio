"""Semina i 5 criteri del Mod. 05-01 con i pesi originali (20/15/25/20/20).

Da qui in poi la fonte di verità è il DB: ripesare o disattivare un criterio è
una scelta HR fatta dall'interfaccia, non una modifica di codice. La migrazione
è idempotente (``get_or_create`` sul codice) e non tocca i criteri già presenti.
"""
from django.db import migrations

from anagrafica.models_recruiting import CRITERI_SEED


def crea_criteri(apps, schema_editor):
    RecruitingCriterio = apps.get_model("anagrafica", "RecruitingCriterio")
    for payload in CRITERI_SEED:
        RecruitingCriterio.objects.get_or_create(
            codice=payload["codice"],
            defaults={
                "label": payload["label"],
                "descrizione": payload["descrizione"],
                "peso_percentuale": payload["peso_percentuale"],
                "ordine": payload["ordine"],
                "is_active": True,
            },
        )


def rimuovi_criteri(apps, schema_editor):
    RecruitingCriterio = apps.get_model("anagrafica", "RecruitingCriterio")
    codici = [payload["codice"] for payload in CRITERI_SEED]
    # Solo i criteri seed mai usati: se HR ha già valutato qualcuno la PROTECT
    # su CandidatoPunteggio impedisce comunque la cancellazione.
    RecruitingCriterio.objects.filter(codice__in=codici, punteggi__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0087_recruiting_mod0501"),
    ]

    operations = [
        migrations.RunPython(crea_criteri, rimuovi_criteri),
    ]
