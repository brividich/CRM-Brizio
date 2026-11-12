"""Binding ACL v2 di «Topologia» (consultazione) e «Porte» dell'apparato (gestione).

Stessa regola della 0025/0049: binding solo se manca, nulla con un binding a prefisso
su /contatori/. La topologia è in sola lettura; le porte si modificano solo con la gestione.
"""
from django.db import migrations

VIEW = "contatori.modulo.view"
GESTIONE = "contatori.gestione.manage"
ROUTE = {
    "topologia": VIEW,
    "dispositivo_porte": GESTIONE,
}
NOTA = "[CONTATORI_0052] binding topologia e porte"


def avanti(apps, schema_editor):
    Permesso = apps.get_model("core", "PermissionDefinition")
    Binding = apps.get_model("core", "RoutePermissionBinding")
    if not Permesso.objects.filter(code__in=[GESTIONE, VIEW]).count() == 2:
        return  # la 0025 crea i permessi: senza, nessun binding orfano
    if Binding.objects.filter(is_active=True, match_strategy="prefix",
                              path_pattern__in=["/contatori/", "/contatori"]).exists():
        return
    for nome, code in ROUTE.items():
        route = f"contatori:{nome}"
        if Binding.objects.filter(route_name=route).exists():
            continue
        Binding.objects.create(route_name=route, path_pattern="", match_strategy="exact",
                               permission_id=code, source_app="contatori", priority=80,
                               is_active=True, note=NOTA)


def indietro(apps, schema_editor):
    apps.get_model("core", "RoutePermissionBinding").objects.filter(note=NOTA).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("contatori", "0051_porte_apparato_topologia"),
    ]

    operations = [migrations.RunPython(avanti, indietro)]
