"""Catalogo unico dei ruoli — riallineamento dei residui.

La 0085 aveva copiato una tantum ``RuoloAziendale`` → ``RuoloOperativo``. Da
quando anche il dropdown «Ruolo aziendale» della scheda dipendente legge il
catalogo unico, un eventuale ruolo rimasto solo nella tabella legacy sparirebbe
dalla tendina: qui lo si riporta nel catalogo. Idempotente, come la 0085.
"""
from django.db import migrations


def riallinea(apps, schema_editor):
    RuoloAziendale = apps.get_model("anagrafica", "RuoloAziendale")
    RuoloOperativo = apps.get_model("anagrafica", "RuoloOperativo")

    existing = {
        (r.nome or "").strip().casefold()
        for r in RuoloOperativo.objects.all()
    }
    for az in RuoloAziendale.objects.all():
        # `RuoloOperativo.nome` è più corto (100) e unique: si tronca e si
        # ricontrolla, così un troncamento che collide non fa saltare la migration.
        nome = (az.nome or "").strip()[:100]
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
    # Reverse distruttivo: i ruoli possono aver ricevuto assegnazioni.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0109_alter_aliasesameprotocollo_options_and_more"),
    ]

    operations = [
        migrations.RunPython(riallinea, noop),
    ]
