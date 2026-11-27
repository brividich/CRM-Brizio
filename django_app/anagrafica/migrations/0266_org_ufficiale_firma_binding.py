"""Firma su portale dell'organigramma ufficiale: binding ACL delle pagine nuove (schema della 0256).

Firmare e vedere le immagini firmate = come vedere l'organigramma (chi firma lo
controlla la vista); inviare in firma e impostare le firme = come pubblicare.
"""
from django.db import migrations

NOTA = "[ORG_UFF_FIRMA_0266] copiato da {}"
COPIE = {
    "anagrafica:organigramma_ufficiale_vedi": ("anagrafica:organigramma_ufficiale_firma",
                                               "anagrafica:organigramma_ufficiale_firma_immagine",
                                               "anagrafica:organigramma_ufficiale_mia_immagine"),
    "anagrafica:organigramma_ufficiale_pubblica": ("anagrafica:organigramma_ufficiale_invia",
                                                   "anagrafica:organigramma_ufficiale_firme_impostazioni"),
}


def avanti(apps, schema_editor):
    Binding = apps.get_model("core", "RoutePermissionBinding")
    for sorgente, rotte in COPIE.items():
        modello = Binding.objects.filter(route_name=sorgente, is_active=True).order_by("-priority", "pk").first()
        if modello is None:
            continue
        for rotta in rotte:
            if Binding.objects.filter(route_name=rotta).exists():
                continue
            Binding.objects.create(
                route_name=rotta, path_pattern="", match_strategy=modello.match_strategy,
                permission_id=modello.permission_id, source_app="anagrafica", priority=modello.priority,
                is_active=True, note=NOTA.format(sorgente),
            )
    Link = apps.get_model("anagrafica", "SubnavLinkAnagrafica")
    for link in Link.objects.filter(url_value="anagrafica:organigramma"):
        nomi = [n.strip() for n in (link.active_view_names or "").split(",") if n.strip()]
        if "anagrafica:organigramma_ufficiale_firma" not in nomi:
            nomi.append("anagrafica:organigramma_ufficiale_firma")
        valore = ",".join(nomi)
        if len(valore) <= 500 and valore != link.active_view_names:
            link.active_view_names = valore
            link.save(update_fields=["active_view_names"])


def indietro(apps, schema_editor):
    Binding = apps.get_model("core", "RoutePermissionBinding")
    tutte = [r for rotte in COPIE.values() for r in rotte]
    Binding.objects.filter(route_name__in=tutte, note__startswith="[ORG_UFF_FIRMA_0266]").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0265_ricalcola_scadenze_permessi"),
    ]

    operations = [migrations.RunPython(avanti, indietro)]
