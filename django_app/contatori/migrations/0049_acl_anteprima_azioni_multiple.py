"""Binding ACL v2 del pannello di anteprima e delle azioni su più righe.

Stessa regola della 0025/0041: binding solo se manca, nulla con un binding a prefisso
su /contatori/. Anteprima e azioni Consumabili in consultazione (come le schede e
«Leggi ora», che ricontrolla la gestione nella view); collegamento asset multiplo e
correzione IP multipla in gestione.
"""
from django.db import migrations

VIEW = "contatori.modulo.view"
GESTIONE = "contatori.gestione.manage"
ROUTE = {
    "anteprima": VIEW,
    "consumabili_azioni": VIEW,
    "macchine_collega_asset": GESTIONE,
    "discovery_correggi_ip": GESTIONE,
}
NOTA = "[CONTATORI_0049] binding anteprima e azioni multiple"


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
        ("contatori", "0048_acl_guida_calo_spiegato"),
    ]

    operations = [migrations.RunPython(avanti, indietro)]
