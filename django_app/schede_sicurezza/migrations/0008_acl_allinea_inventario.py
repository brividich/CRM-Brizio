"""Binding ACL v2 del pulsante «Allinea inventario asset» (gestione prodotti).

Binding solo se manca e se il permesso esiste; nulla con un binding a prefisso
su /schede-sicurezza/.
"""
from django.db import migrations

GESTISCI = "schede_sicurezza.prodotto.gestisci"
ROUTE = "schede_sicurezza:allinea_inventario"
NOTA = "[SDS_0008] binding allinea inventario asset"


def avanti(apps, schema_editor):
    Permesso = apps.get_model("core", "PermissionDefinition")
    Binding = apps.get_model("core", "RoutePermissionBinding")
    if not Permesso.objects.filter(code=GESTISCI).exists():
        return
    if Binding.objects.filter(is_active=True, match_strategy="prefix",
                              path_pattern__in=["/schede-sicurezza/", "/schede-sicurezza"]).exists():
        return
    if Binding.objects.filter(route_name=ROUTE).exists():
        return
    Binding.objects.create(route_name=ROUTE, path_pattern="", match_strategy="exact",
                           permission_id=GESTISCI, source_app="schede_sicurezza", priority=80,
                           is_active=True, note=NOTA)


def indietro(apps, schema_editor):
    apps.get_model("core", "RoutePermissionBinding").objects.filter(note=NOTA).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("schede_sicurezza", "0007_una_scheda_corrente"),
        ("core", "0034_permissiondefinition_rolepermissiongrant_and_more"),
    ]

    operations = [migrations.RunPython(avanti, indietro)]
