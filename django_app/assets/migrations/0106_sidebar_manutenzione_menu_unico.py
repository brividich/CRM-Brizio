"""Sidebar Manutenzione allineata alla definizione unica (``assets.maintenance_nav``).

Fino alla 0104 il ramo Manutenzione della sidebar e la barra di sezione erano due
navigazioni diverse della stessa sezione. Ora la barra si costruisce da
``maintenance_nav`` e la sidebar viene allineata qui, con una copia congelata
della stessa definizione (un test verifica che coincidano).

    Manutenzione     Panoramica · Da fare · Calendario · Scadenzario · Interventi · Storico · Report
    Configurazione   Piani · Catalogo attivita' · Gruppi asset · Copertura · Fornitori
                     · Contratti assistenza · Licenze software

Cosa cambia rispetto a prima:
- Calendario, Report e Licenze entrano nel ramo (erano voci sciolte);
- Contratti assistenza torna nel menu (la 0079 l'aveva tolto);
- Piani passa in Configurazione: si imposta, non si apre ogni giorno;
- "Cruscotto" diventa "Panoramica" e apre il ramo; "Scadenze" diventa "Scadenzario".

Nessun URL cambia. Idempotente e reversibile.
"""
from django.db import migrations

SECTION = "OPERATIONS"

# (code, label, target_url, active_match, sort_order)
MANUTENZIONE = [
    ("maintenance_quadro", "Panoramica", "django:assets:maintenance_responsabile", "/assets/manutenzione/quadro/", 10),
    ("maintenance_da_fare", "Da fare", "django:assets:maintenance_da_fare", "/assets/manutenzione/da-fare/", 20),
    ("calendario_main", "Calendario", "django:assets:calendario_asset", "/assets/calendario/", 30),
    ("maintenance_scadenzario", "Scadenzario", "django:assets:maintenance_scadenze", "/assets/manutenzione/scadenze/", 40),
    ("maintenance_interventi", "Interventi", "django:assets:wo_list", "/assets/workorders/", 50),
    ("maintenance_storico", "Storico", "django:assets:maintenance_history", "/assets/manutenzione/storico/", 60),
    ("report_asset", "Report", "django:assets:reports?scope=production", "/assets/reports/", 70),
]
CONFIGURAZIONE = [
    ("maintenance_piani", "Piani", "django:assets:maintenance_plan_list", "/assets/manutenzione/piani/", 10),
    ("maintenance_impostazioni", "Catalogo attività", "django:assets:maintenance_impostazioni",
     "/assets/manutenzione/impostazioni/", 20),
    ("maintenance_asset_groups", "Gruppi asset", "django:assets:asset_group_list", "/assets/manutenzione/gruppi/", 30),
    ("maintenance_copertura", "Copertura", "django:assets:maintenance_coverage", "/assets/manutenzione/copertura/", 40),
    ("maintenance_fornitori", "Fornitori", "django:assets:maintenance_suppliers", "/assets/manutenzione/fornitori/", 50),
    ("maintenance_contratti", "Contratti assistenza", "django:assets:assistance_contract_list",
     "/assets/manutenzione/contratti/", 60),
    ("licenze", "Licenze software", "django:assets:software_license_list", "/assets/licenze/", 70),
]

# Stato della 0102/0103, per il rollback.
PRIMA_FIGLI = {
    "maintenance_da_fare": ("maintenance_hub", "Da fare", 10),
    "maintenance_scadenzario": ("maintenance_hub", "Scadenze", 20),
    "maintenance_interventi": ("maintenance_hub", "Interventi", 30),
    "maintenance_piani": ("maintenance_hub", "Piani", 40),
    "maintenance_quadro": ("maintenance_hub", "Cruscotto", 50),
    "maintenance_storico": ("maintenance_hub", "Storico", 60),
    "maintenance_impostazioni": ("maintenance_configurazione", "Attività", 10),
    "maintenance_asset_groups": ("maintenance_configurazione", "Gruppi asset", 20),
    "maintenance_fornitori": ("maintenance_configurazione", "Fornitori", 30),
    "maintenance_copertura": ("maintenance_configurazione", "Copertura", 40),
}
PRIMA_SCIOLTE = {
    # code -> (label, target_url, sort_order), come dalla 0079
    "calendario_main": ("Calendario asset", "django:assets:calendario_asset", 40),
    "report_asset": ("Report asset", "django:assets:reports", 50),
    "licenze": ("Licenze software", "django:assets:software_license_list", 60),
}


def avanti(apps, schema_editor):
    Button = apps.get_model("assets", "AssetSidebarButton")

    hub = Button.objects.filter(code="maintenance_hub").first()
    if hub is None:
        # Installazione senza il ramo manutenzione: non si appende nulla nel vuoto.
        return
    section = hub.section or SECTION
    hub.target_url = "django:assets:maintenance_responsabile"
    hub.is_visible = True
    hub.save(update_fields=["target_url", "is_visible"])

    config, _ = Button.objects.get_or_create(
        code="maintenance_configurazione",
        defaults={
            "section": section,
            "parent": None,
            "label": "Configurazione",
            "target_url": "django:assets:maintenance_plan_list",
            "active_match": "",
            "is_subitem": False,
            "sort_order": (hub.sort_order or 0) + 1,
            "is_visible": True,
        },
    )
    config.target_url = "django:assets:maintenance_plan_list"
    config.is_visible = True
    config.save(update_fields=["target_url", "is_visible"])

    for parent, rows in ((hub, MANUTENZIONE), (config, CONFIGURAZIONE)):
        for code, label, target, match, order in rows:
            Button.objects.update_or_create(
                code=code,
                defaults={
                    "section": section,
                    "parent": parent,
                    "label": label,
                    "target_url": target,
                    "active_match": match,
                    "is_subitem": True,
                    "sort_order": order,
                    "is_visible": True,
                },
            )
    print(
        f"  [assets 0106] Menu Manutenzione unico: {len(MANUTENZIONE)} voci operative, "
        f"{len(CONFIGURAZIONE)} di configurazione."
    )


def indietro(apps, schema_editor):
    Button = apps.get_model("assets", "AssetSidebarButton")
    parents = {b.code: b for b in Button.objects.filter(code__in=["maintenance_hub", "maintenance_configurazione"])}
    hub = parents.get("maintenance_hub")
    if hub is not None:
        Button.objects.filter(pk=hub.pk).update(target_url="django:assets:maintenance_hub")
    config = parents.get("maintenance_configurazione")
    if config is not None:
        Button.objects.filter(pk=config.pk).update(target_url="django:assets:maintenance_template_list")
    for code, (parent_code, label, order) in PRIMA_FIGLI.items():
        parent = parents.get(parent_code)
        if parent is not None:
            Button.objects.filter(code=code).update(parent=parent, label=label, sort_order=order)
    for code, (label, target, order) in PRIMA_SCIOLTE.items():
        Button.objects.filter(code=code).update(
            parent=None, is_subitem=False, label=label, target_url=target, sort_order=order
        )
    Button.objects.filter(code="maintenance_contratti").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0105_assetdocument_file_max_length"),
    ]

    operations = [
        migrations.RunPython(avanti, indietro),
    ]
