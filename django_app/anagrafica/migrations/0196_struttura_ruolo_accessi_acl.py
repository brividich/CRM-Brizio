"""Binding ACL della modifica degli accessi dalla scheda del ruolo (Struttura organizzativa):
copiato da quello della pagina. Nella view resta il controllo proprio (solo superuser e
amministratori del portale, come «Ruoli e permessi»)."""
from django.db import migrations

ROTTE = {
    "anagrafica:struttura_ruolo_accessi": "anagrafica:struttura_org",
}
NOTA = "[STRUTTURA_ORG_0196] copiato da {}"


def avanti(apps, schema_editor):
    Binding = apps.get_model("core", "RoutePermissionBinding")
    for rotta, sorella in ROTTE.items():
        if Binding.objects.filter(route_name=rotta).exists():
            continue
        modello = None
        for candidata in (sorella, "anagrafica:dipendenti_list"):
            modello = Binding.objects.filter(route_name=candidata, is_active=True).order_by("-priority", "pk").first()
            if modello is not None:
                break
        if modello is None:
            continue
        Binding.objects.create(
            route_name=rotta, path_pattern="", match_strategy=modello.match_strategy,
            permission_id=modello.permission_id, source_app="anagrafica", priority=modello.priority,
            is_active=True, note=NOTA.format(sorella),
        )


def indietro(apps, schema_editor):
    Binding = apps.get_model("core", "RoutePermissionBinding")
    for rotta, sorella in ROTTE.items():
        Binding.objects.filter(route_name=rotta, note=NOTA.format(sorella)).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0195_regola_formazione_mansione_lavorativa"),
    ]

    operations = [
        migrations.RunPython(avanti, indietro),
    ]
