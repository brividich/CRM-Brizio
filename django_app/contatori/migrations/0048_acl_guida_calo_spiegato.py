"""Binding ACL v2 della guida al nuovo indirizzo (consultazione) e di «calo spiegato» (gestione).

Stessa regola della 0025/0032/0041: binding solo se manca, nulla con un binding a
prefisso su /contatori/. Il vecchio indirizzo della guida (`riconciliazione_guida`)
tiene il suo binding e reindirizza.
"""
from django.db import migrations

VIEW = "contatori.modulo.view"
GESTIONE = "contatori.gestione.manage"
ROUTE = {"guida": VIEW, "lettura_calo_spiegato": GESTIONE}
NOTA = "[CONTATORI_0048] binding guida e calo spiegato"


def avanti(apps, schema_editor):
    Permesso = apps.get_model("core", "PermissionDefinition")
    Binding = apps.get_model("core", "RoutePermissionBinding")
    if not Permesso.objects.filter(code__in=[GESTIONE, VIEW]).count() == 2:
        return  # la 0025 crea i permessi: senza, nessun binding orfano
    if Binding.objects.filter(is_active=True, match_strategy="prefix",
                              path_pattern__in=["/contatori/", "/contatori"]).exists():
        return
    for nome, permesso in ROUTE.items():
        route = f"contatori:{nome}"
        if Binding.objects.filter(route_name=route).exists():
            continue
        Binding.objects.create(route_name=route, path_pattern="", match_strategy="exact",
                               permission_id=permesso, source_app="contatori", priority=80,
                               is_active=True, note=NOTA)


def indietro(apps, schema_editor):
    apps.get_model("core", "RoutePermissionBinding").objects.filter(note=NOTA).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("contatori", "0047_calo_spiegato"),
    ]

    operations = [migrations.RunPython(avanti, indietro)]
