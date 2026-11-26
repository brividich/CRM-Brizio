from django.db import migrations

NOTA = "[FORMAZIONE_0265] copiato dalla rotta sorella"
ROTTE = {
    "anagrafica:formazione_corsi_azione": ("anagrafica:formazione_scadenze_ricalcola",),
}


def avanti(apps, schema_editor):
    Binding = apps.get_model("core", "RoutePermissionBinding")
    for sorella, rotte in ROTTE.items():
        modello = Binding.objects.filter(route_name=sorella, is_active=True).order_by("-priority", "pk").first()
        if modello is None:
            continue
        for rotta in rotte:
            if not Binding.objects.filter(route_name=rotta).exists():
                Binding.objects.create(route_name=rotta, path_pattern="", match_strategy=modello.match_strategy,
                                       permission_id=modello.permission_id, source_app="anagrafica",
                                       priority=modello.priority, is_active=True, note=NOTA)


def indietro(apps, schema_editor):
    rotte = [r for g in ROTTE.values() for r in g]
    apps.get_model("core", "RoutePermissionBinding").objects.filter(route_name__in=rotte, note=NOTA).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0034_permissiondefinition_rolepermissiongrant_and_more"),
        ("anagrafica", "0264_coerenza_menu_nomi"),
    ]

    operations = [migrations.RunPython(avanti, indietro)]
