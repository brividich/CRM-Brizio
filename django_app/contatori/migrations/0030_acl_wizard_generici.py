"""Binding ACL v2 dei wizard generici (dispositivo, MFC, profilo, colonna, sonda): gestione.

Le route della 0029 (solo dispositivo) sono state sostituite da ``wizard_avvia`` e
``wizard``: i binding vecchi creati dalla 0029 vengono rimossi, i nuovi creati solo
se mancano. Stessa regola della 0025/0027: con un binding a prefisso su /contatori/
non si crea nulla.
"""
from django.db import migrations

GESTIONE = "contatori.gestione.manage"
ROUTE_GESTIONE = ["wizard_avvia", "wizard"]
NOTA = "[CONTATORI_0030] binding wizard guidati"
NOTA_0029 = "[CONTATORI_0029] binding wizard dispositivo"


def avanti(apps, schema_editor):
    Permesso = apps.get_model("core", "PermissionDefinition")
    Binding = apps.get_model("core", "RoutePermissionBinding")
    Binding.objects.filter(note=NOTA_0029).delete()  # route non piu' esistenti
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
    # I binding della 0029 si ricreano rieseguendo la 0029 dopo averla annullata.


class Migration(migrations.Migration):

    dependencies = [
        ("contatori", "0029_acl_wizard_dispositivo"),
    ]

    operations = [migrations.RunPython(avanti, indietro)]
