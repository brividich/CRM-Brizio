"""Sidebar asset: information architecture pulita a sezioni.

Riorganizza la navigazione asset eliminando le ripetizioni e separando la
navigazione per categoria dagli strumenti operativi:

    NAVIGAZIONE (MAIN)
      Cruscotto                  -> /assets/ (dashboard)
      Inventario completo        -> /assets/lista/
      <gruppi categoria>         (auto da AssetCategory via rebuild)

    STRUMENTI E GESTIONE (OPERATIONS)
      Manutenzione               -> /assets/manutenzione/
        Da fare / Scadenzario / Impostazioni
      Componenti
      Mappa officina
      Calendario asset
      Report asset
      Licenze software

    AMMINISTRAZIONE (template, gated can_gestione_admin)
      Impostazioni

Rimuove i pulsanti legacy/orfani basati sulla vecchia navigazione per
asset_type ("Asset Infrastruttura" / "Carroponti e paranchi") che
duplicavano le categorie d'inventario.

Non modifica i dati AssetCategory: i gruppi categoria sono rigenerati in
sola lettura da rebuild_category_sidebar.
"""
from django.db import migrations

from assets.services.sidebar_categories import rebuild_category_sidebar


ORPHAN_CODES = ["asset-infrastruttura", "carroponti-e-paranchi"]

# (code, label, target_url, active_match, section, parent_code, is_subitem, sort_order)
FUNCTIONAL_BUTTONS = [
    # --- NAVIGAZIONE (MAIN) ---------------------------------------------------
    ("cruscotto", "Cruscotto", "/assets/", "", "MAIN", None, False, 10),
    ("inventario", "Inventario completo", "django:assets:asset_list?rows={rows}", "", "MAIN", None, False, 12),
    # --- STRUMENTI E GESTIONE (OPERATIONS) ------------------------------------
    ("maintenance_hub", "Manutenzione", "django:assets:maintenance_hub", "/assets/manutenzione/", "OPERATIONS", None, False, 10),
    ("maintenance_da_fare", "Da fare", "/assets/manutenzione/?tab=da_fare", "tab=da_fare", "OPERATIONS", "maintenance_hub", True, 11),
    ("maintenance_scadenzario", "Scadenzario", "/assets/manutenzione/?tab=scadenzario", "tab=scadenzario", "OPERATIONS", "maintenance_hub", True, 12),
    ("maintenance_impostazioni", "Impostazioni", "django:assets:maintenance_impostazioni", "/assets/manutenzione/impostazioni/", "OPERATIONS", "maintenance_hub", True, 13),
    ("componenti", "Componenti", "django:assets:asset_component_list", "/assets/componenti/", "OPERATIONS", None, False, 20),
    ("mappa_officina", "Mappa officina", "django:assets:plant_layout_map", "/assets/work-machines/map/", "OPERATIONS", None, False, 30),
    ("calendario_main", "Calendario asset", "django:assets:calendario_asset", "/assets/calendario/", "OPERATIONS", None, False, 40),
    ("report_asset", "Report asset", "django:assets:reports", "/assets/reports/", "OPERATIONS", None, False, 50),
    ("licenze", "Licenze software", "django:assets:software_license_list", "/assets/licenze/", "OPERATIONS", None, False, 60),
]

# Pulsanti funzionali storici ora consolidati nelle voci sopra (rimossi se
# presenti, per evitare doppioni/orfani nelle sezioni).
STALE_FUNCTIONAL_CODES = [
    "dispositivi_it", "asset_produzione", "mappa_main", "manut_per_main",
    "scadenze", "contratti", "manut_schedule", "impostazioni",
    "impost_template", "impost_regole",
]


def forwards(apps, schema_editor):
    AssetCategory = apps.get_model("assets", "AssetCategory")
    AssetSidebarButton = apps.get_model("assets", "AssetSidebarButton")

    # 1. Rimuove orfani legacy e pulsanti funzionali storici sostituiti.
    AssetSidebarButton.objects.filter(code__in=ORPHAN_CODES + STALE_FUNCTIONAL_CODES).delete()

    # 2. Riallinea i pulsanti funzionali alla nuova IA.
    #    Prima i nodi radice (servono come parent), poi le sottovoci.
    #    NB: nelle migration il save() custom del modello non gira, quindi
    #    section e is_subitem vanno impostati esplicitamente.
    by_code = {}
    for code, label, target, match, section, parent_code, is_sub, order in FUNCTIONAL_BUTTONS:
        if parent_code is not None:
            continue
        obj, _ = AssetSidebarButton.objects.update_or_create(
            code=code,
            defaults=dict(
                section=section, parent=None, label=label,
                target_url=target, active_match=match,
                is_subitem=is_sub, sort_order=order, is_visible=True,
            ),
        )
        by_code[code] = obj
    for code, label, target, match, section, parent_code, is_sub, order in FUNCTIONAL_BUTTONS:
        if parent_code is None:
            continue
        parent = by_code.get(parent_code)
        AssetSidebarButton.objects.update_or_create(
            code=code,
            defaults=dict(
                section=section, parent=parent, label=label,
                target_url=target, active_match=match,
                is_subitem=is_sub, sort_order=order, is_visible=True,
            ),
        )

    # 3. Risincronizza i gruppi categoria dall'albero AssetCategory.
    #    (rimuove catnav-* + codici legacy/orfani e li rigenera; report_asset
    #    get_or_create non tocca quello appena impostato sopra).
    rebuild_category_sidebar(AssetCategory, AssetSidebarButton)


def backwards(apps, schema_editor):
    # Lo stato precedente (sidebar mista, orfani inclusi) non e' ripristinabile
    # in modo affidabile (coerente con 0074/0076).
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0077_wm_map_edit_permission"),
        ("assets", "0078_alter_assetsidebarbutton_section"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
