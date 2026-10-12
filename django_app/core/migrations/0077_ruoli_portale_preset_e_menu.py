"""Preset dei ruoli del portale + voce «Ruoli e permessi» nell'admin_subnav.

Crea solo ruoli e celle mancanti (get_or_create): non tocca nulla di gia'
personalizzato. Nessuna persona viene iscritta ai ruoli e l'interruttore del
sistema resta spento: gli accessi non cambiano finche' l'amministratore non
assegna i ruoli e non attiva il sistema dalla pagina.
"""
from django.db import migrations

NAV_CODE = "admin-ruoli-portale"
NAV_ITEM = dict(
    label="Ruoli e permessi",
    section="admin_subnav",
    parent_code="admin-portale",
    group="accessi",
    order=12,
    route_name="admin_portale:ruoli_portale",
    active_patterns="admin_portale:ruoli_portale*",
    description="Ruoli delle persone, matrice ruolo x modulo x azione, anteprima «cosa vede questa persona», registro modifiche.",
    is_visible=True,
    is_enabled=True,
)


def seed(apps, schema_editor):
    from core.permessi.preset import PRESETS

    AccessGroup = apps.get_model("core", "AccessGroup")
    Cella = apps.get_model("core", "RuoloPermessoModulo")
    for preset in PRESETS:
        ruolo, _creato = AccessGroup.objects.get_or_create(
            code=preset.codice,
            defaults={
                "label": preset.nome,
                "description": preset.descrizione[:500],
                "priority": preset.ordine,
                "amministratore": preset.amministratore,
                "vede_tutto": preset.vede_tutto,
                "preset": preset.chiave,
            },
        )
        for modulo, azioni in preset.celle.items():
            for azione, ambito in azioni.items():
                Cella.objects.get_or_create(
                    ruolo_id=ruolo.id,
                    modulo=modulo,
                    azione=azione,
                    defaults={"ambito": ambito, "consentito": True, "note": f"preset {preset.chiave}"},
                )
    apps.get_model("core", "NavigationItem").objects.get_or_create(code=NAV_CODE, defaults=NAV_ITEM)


def unseed(apps, schema_editor):
    apps.get_model("core", "NavigationItem").objects.filter(code=NAV_CODE).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0076_ruoli_portale_matrice"),
    ]

    operations = [
        migrations.RunPython(seed, reverse_code=unseed),
    ]
