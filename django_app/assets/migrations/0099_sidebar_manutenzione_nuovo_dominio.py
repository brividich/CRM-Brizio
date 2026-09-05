"""Allinea la sidebar manutenzione alle superfici del nuovo dominio.

I pulsanti della sidebar vivono a database (``AssetSidebarButton``), impostati
dalla `0079`: «Da fare» e «Scadenzario» puntano a due schede in query string del
vecchio hub (`?tab=da_fare`, `?tab=scadenzario`), cioe' a pagine ritirate. Cambiare
i default nel codice non basta — il seed usa ``get_or_create`` e non tocca le righe
gia' esistenti — quindi il ripuntamento va fatto qui.

Aggiunge anche Quadro, Piani e Gruppi asset, che nella sidebar non c'erano: la
barra di sezione li ha, il menu laterale no, e due navigazioni che dicono cose
diverse sulla stessa sezione sono peggio di una sola incompleta.

Idempotente e reversibile.
"""

from django.db import migrations

# code -> (label, target_url, active_match, sort_order)
VOCI = {
    "maintenance_da_fare": ("Da fare", "django:assets:maintenance_da_fare", "/assets/manutenzione/da-fare/", 11),
    "maintenance_scadenzario": ("Scadenze", "django:assets:maintenance_scadenze", "/assets/manutenzione/scadenze/", 12),
    "maintenance_quadro": ("Quadro", "django:assets:maintenance_responsabile", "/assets/manutenzione/quadro/", 13),
    "maintenance_piani": ("Piani", "django:assets:maintenance_plan_list", "/assets/manutenzione/piani/", 14),
    "maintenance_asset_groups": ("Gruppi asset", "django:assets:asset_group_list", "/assets/manutenzione/gruppi/", 15),
    "maintenance_impostazioni": ("Impostazioni", "django:assets:maintenance_impostazioni", "/assets/manutenzione/impostazioni/", 16),
}

PRECEDENTI = {
    "maintenance_da_fare": ("Da fare", "/assets/manutenzione/?tab=da_fare", "tab=da_fare", 11),
    "maintenance_scadenzario": ("Scadenzario", "/assets/manutenzione/?tab=scadenzario", "tab=scadenzario", 12),
    "maintenance_impostazioni": ("Impostazioni", "django:assets:maintenance_impostazioni", "/assets/manutenzione/impostazioni/", 13),
}

AGGIUNTE = ["maintenance_quadro", "maintenance_piani", "maintenance_asset_groups"]


def _applica(apps, schema_editor):
    Button = apps.get_model("assets", "AssetSidebarButton")
    padre = Button.objects.filter(code="maintenance_hub").first()
    if padre is None:
        # Installazione senza il ramo manutenzione: non si appende nulla nel vuoto.
        return

    for code, (label, target, match, ordine) in VOCI.items():
        Button.objects.update_or_create(
            code=code,
            defaults={
                "section": padre.section,
                "label": label,
                "target_url": target,
                "active_match": match,
                "is_subitem": True,
                "parent": padre,
                "sort_order": ordine,
                "is_visible": True,
            },
        )


def _annulla(apps, schema_editor):
    Button = apps.get_model("assets", "AssetSidebarButton")
    for code, (label, target, match, ordine) in PRECEDENTI.items():
        Button.objects.filter(code=code).update(
            label=label, target_url=target, active_match=match, sort_order=ordine
        )
    Button.objects.filter(code__in=AGGIUNTE).delete()


class Migration(migrations.Migration):
    dependencies = [("assets", "0098_assetgroup_and_more")]
    operations = [migrations.RunPython(_applica, _annulla)]
