"""Riordina il ramo «Manutenzione» della sidebar sulle superfici del dominio.

La `0099` ha ripuntato «Da fare» e «Scadenze» e aggiunto Quadro/Piani/Gruppi,
ma il ramo restava incompleto e disordinato: mancavano Interventi (gli ordini di
lavoro), Storico e Fornitori — presenti nella barra di sezione — mentre restavano
in primo piano due voci che vivono dentro «Impostazioni» (Regole manutenzione e
Catalogo attivita'). Due navigazioni che descrivono la stessa sezione in modo
diverso costano piu' di una sola navigazione completa.

Qui il sottomenu viene allineato 1:1 all'ordine della barra di sezione e le due
voci di configurazione vengono nascoste (non cancellate: restano modificabili da
Impostazioni > Menu sidebar e le rimette visibili un click).

Idempotente e reversibile.
"""

from django.db import migrations

# code -> (label, target_url, active_match, sort_order)
VOCI = {
    "maintenance_da_fare": ("Da fare", "django:assets:maintenance_da_fare", "/assets/manutenzione/da-fare/", 10),
    "maintenance_scadenzario": ("Scadenze", "django:assets:maintenance_scadenze", "/assets/manutenzione/scadenze/", 20),
    "maintenance_quadro": ("Quadro", "django:assets:maintenance_responsabile", "/assets/manutenzione/quadro/", 30),
    "maintenance_interventi": ("Interventi", "django:assets:wo_list", "/assets/workorders/", 40),
    "maintenance_piani": ("Piani", "django:assets:maintenance_plan_list", "/assets/manutenzione/piani/", 50),
    "maintenance_asset_groups": ("Gruppi asset", "django:assets:asset_group_list", "/assets/manutenzione/gruppi/", 60),
    "maintenance_storico": ("Storico", "django:assets:maintenance_history", "/assets/manutenzione/storico/", 70),
    "maintenance_fornitori": ("Fornitori", "django:assets:maintenance_suppliers", "/assets/manutenzione/fornitori/", 90),
    "maintenance_impostazioni": ("Impostazioni", "django:assets:maintenance_impostazioni", "/assets/manutenzione/impostazioni/", 110),
}

# Voci gia' presenti: si riordinano soltanto, l'etichetta resta quella scelta dall'utente.
RIORDINO = {
    "periodic_verifications": 80,
    "lifecycle_tracking": 85,
}

# Configurazione raggiungibile da «Impostazioni»: fuori dal primo livello del menu.
DA_NASCONDERE = ["maintenance_rules", "maintenance_templates"]

AGGIUNTE = ["maintenance_interventi", "maintenance_storico", "maintenance_fornitori"]


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

    for code, ordine in RIORDINO.items():
        Button.objects.filter(code=code).update(sort_order=ordine)

    Button.objects.filter(code__in=DA_NASCONDERE).update(is_visible=False)


def _annulla(apps, schema_editor):
    Button = apps.get_model("assets", "AssetSidebarButton")
    Button.objects.filter(code__in=AGGIUNTE).delete()
    Button.objects.filter(code__in=DA_NASCONDERE).update(is_visible=True)


class Migration(migrations.Migration):
    dependencies = [("assets", "0099_sidebar_manutenzione_nuovo_dominio")]
    operations = [migrations.RunPython(_applica, _annulla)]
