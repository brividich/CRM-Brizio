"""Storico del costo orario (27/10/2026): binding ACL e voce del menu.

Il binding si copia dalla pagina «Costo orario» (schema della 0185); la pagina
accende Amministrazione → Cedolini come «Costo orario» (0206). Nella view vale
comunque il permesso HR riservato.
"""
from django.db import migrations

ROTTA, SORELLA = "anagrafica:costo_orario_storico", "anagrafica:costo_orario"
NOTA = "[COSTO_0208] copiato da anagrafica:costo_orario"
VOCE = "anagrafica:retribuzioni_globale"


def avanti(apps, schema_editor):
    Binding = apps.get_model("core", "RoutePermissionBinding")
    if not Binding.objects.filter(route_name=ROTTA).exists():
        modello = None
        for candidata in (SORELLA, "anagrafica:retribuzioni_globale", "anagrafica:dipendenti_list"):
            modello = Binding.objects.filter(route_name=candidata, is_active=True).order_by("-priority", "pk").first()
            if modello is not None:
                break
        if modello is not None:
            Binding.objects.create(
                route_name=ROTTA, path_pattern="", match_strategy=modello.match_strategy,
                permission_id=modello.permission_id, source_app="anagrafica", priority=modello.priority,
                is_active=True, note=NOTA,
            )
    Link = apps.get_model("anagrafica", "SubnavLinkAnagrafica")
    for link in Link.objects.filter(url_value=VOCE):
        nomi = [n.strip() for n in (link.active_view_names or VOCE).split(",") if n.strip()]
        if ROTTA not in nomi:
            nomi.append(ROTTA)
            link.active_view_names = ",".join(nomi)
            link.save(update_fields=["active_view_names"])


def indietro(apps, schema_editor):
    apps.get_model("core", "RoutePermissionBinding").objects.filter(route_name=ROTTA, note=NOTA).delete()
    Link = apps.get_model("anagrafica", "SubnavLinkAnagrafica")
    for link in Link.objects.filter(url_value=VOCE):
        nomi = [n.strip() for n in (link.active_view_names or "").split(",") if n.strip() and n.strip() != ROTTA]
        link.active_view_names = ",".join(nomi)
        link.save(update_fields=["active_view_names"])


class Migration(migrations.Migration):
    dependencies = [
        ("anagrafica", "0207_vista_elenco_mansioni_costi"),
        ("core", "0001_initial"),
    ]
    operations = [migrations.RunPython(avanti, indietro)]
