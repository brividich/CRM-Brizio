"""Binding ACL v2 del wizard «Nuovo dispositivo SNMP» (gestione), solo se manca.

Stessa regola della 0025/0027: se un binding a prefisso copre gia' /contatori/ non si
crea nulla, e un binding gia' presente sulla route (anche disattivato) resta.
"""
from django.db import migrations

GESTIONE = "contatori.gestione.manage"
ROUTE_GESTIONE = ["snmp_wizard_dispositivo_avvia", "snmp_wizard_dispositivo"]
NOTA = "[CONTATORI_0029] binding wizard dispositivo"


def avanti(apps, schema_editor):
    Permesso = apps.get_model("core", "PermissionDefinition")
    Binding = apps.get_model("core", "RoutePermissionBinding")
    if not Permesso.objects.filter(code=GESTIONE).exists():
        return  # la 0025 crea il permesso: senza, nessun binding orfano
    coperto = Binding.objects.filter(is_active=True, match_strategy="prefix",
                                     path_pattern__in=["/contatori/", "/contatori"]).exists()
    if coperto:
        return
    for nome in ROUTE_GESTIONE:
        route = f"contatori:{nome}"
        if Binding.objects.filter(route_name=route).exists():
            continue
        Binding.objects.create(route_name=route, path_pattern="", match_strategy="exact",
                               permission_id=GESTIONE, source_app="contatori", priority=80,
                               is_active=True, note=NOTA)


def indietro(apps, schema_editor):
    apps.get_model("core", "RoutePermissionBinding").objects.filter(note=NOTA).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("contatori", "0028_dispositivo_verificato_community_senza_default"),
    ]

    operations = [migrations.RunPython(avanti, indietro)]
