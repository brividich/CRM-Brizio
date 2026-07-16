"""Fase 2 — unificazione ruoli: assorbe i «Ruoli aziendali» nel catalogo unico.

Per ogni ``RuoloAziendale`` (per nome, case-insensitive) crea il corrispondente
``RuoloOperativo`` se non esiste già. Idempotente: i nomi già presenti nel
catalogo unico non vengono duplicati. Non elimina i ``RuoloAziendale`` (restano
per compatibilità con il campo testuale ``ruolo_aziendale`` finché non è
migrato del tutto).
"""
from django.db import migrations


def merge_ruoli_aziendali(apps, schema_editor):
    RuoloAziendale = apps.get_model("anagrafica", "RuoloAziendale")
    RuoloOperativo = apps.get_model("anagrafica", "RuoloOperativo")

    existing = {
        (r.nome or "").strip().casefold()
        for r in RuoloOperativo.objects.all()
    }
    for az in RuoloAziendale.objects.all():
        nome = (az.nome or "").strip()
        key = nome.casefold()
        if not nome or key in existing:
            continue
        RuoloOperativo.objects.create(
            nome=nome,
            descrizione=(az.descrizione or ""),
            is_active=bool(getattr(az, "is_active", True)),
        )
        existing.add(key)


def noop(apps, schema_editor):
    # Non si eliminano i ruoli unificati in reverse: sarebbe distruttivo e i
    # ruoli potrebbero aver ricevuto assegnazioni nel frattempo.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0084_alter_ruolooperativo_options_and_more"),
    ]

    operations = [
        migrations.RunPython(merge_ruoli_aziendali, noop),
    ]
