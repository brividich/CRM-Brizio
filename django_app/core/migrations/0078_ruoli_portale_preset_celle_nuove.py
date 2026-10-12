"""Preset dei ruoli: aggiunge le celle nuove (es. «dati riservati» dell'anagrafica).

Stessa regola della 0077: get_or_create, nessuna cella esistente viene
modificata, nessun ruolo viene creato se l'amministratore l'ha cancellato.
"""
from django.db import migrations


def seed(apps, schema_editor):
    from core.permessi.preset import PRESETS

    AccessGroup = apps.get_model("core", "AccessGroup")
    Cella = apps.get_model("core", "RuoloPermessoModulo")
    for preset in PRESETS:
        ruolo = AccessGroup.objects.filter(code=preset.codice).first()
        if ruolo is None:
            continue
        for modulo, azioni in preset.celle.items():
            for azione, ambito in azioni.items():
                Cella.objects.get_or_create(
                    ruolo_id=ruolo.id,
                    modulo=modulo,
                    azione=azione,
                    defaults={"ambito": ambito, "consentito": True, "note": f"preset {preset.chiave}"},
                )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0077_ruoli_portale_preset_e_menu"),
    ]

    operations = [
        migrations.RunPython(seed, reverse_code=migrations.RunPython.noop),
    ]
