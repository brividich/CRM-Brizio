"""Binding ACL v2 della pagina «Verifica OID» (gestione), solo se manca.

Stessa regola della 0025: se un binding a prefisso copre gia' /contatori/ non si
crea nulla, e un binding gia' presente sulla route (anche disattivato) resta.
"""
from django.db import migrations

GESTIONE = "contatori.gestione.manage"
ROUTE_GESTIONE = ["snmp_dispositivo_verifica_oid"]
NOTA = "[CONTATORI_0027] binding verifica OID"


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
        ("contatori", "0026_consumabili_storico"),
    ]

    operations = [migrations.RunPython(avanti, indietro)]
