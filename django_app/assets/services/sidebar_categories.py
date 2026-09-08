"""Generazione della sidebar asset a partire dall'albero delle categorie.

Ogni categoria radice diventa un gruppo della sidebar e ogni sotto-categoria una
voce cliccabile che apre l'inventario filtrato su quella categoria (e le sue
discendenti).

I gruppi vivono nella sezione ``CATEGORIES`` ("Inventario per categoria"), separata
dalla navigazione vera: una categoria e' un **filtro**, non una destinazione, e con
tredici radici di primo livello dentro "Navigazione" le pagine che si usano davvero
finivano sotto la piega.

La logica e' isolata qui per essere riusabile sia dalle migration (con i modelli
storici di ``apps.get_model``) sia dal management command ``sync_sidebar_categories``
(con i modelli reali): per questo ``rebuild_category_sidebar`` riceve le classi
modello come argomenti e usa solo ORM puro.
"""
from __future__ import annotations

# Codici dei vecchi pulsanti basati su asset_type, sostituiti dalla navigazione
# per categoria. Vengono rimossi al rebuild per evitare voci duplicate/orfane.
LEGACY_BUTTON_CODES = [
    "dispositivi_it",
    "asset_produzione",
    "dev_server",
    "dev_pc",
    "dev_rete",
    "dev_tvcc",
    "dev_fonia",
    "dev_calendario",
    "dev_manut_per",
    "dev_reports",
    "prod_cnc",
    "prod_carroponti",
    "prod_macch_utensili",
    "prod_reports",
    # Orfani della vecchia navigazione per asset_type: duplicavano le categorie
    # (es. "Apparecchi di Presa e Sollevamento") con link /assets/dispositivi/?asset_type=...
    "asset-infrastruttura",
    "carroponti-e-paranchi",
]

# Prefisso dei pulsanti generati automaticamente da questa logica.
CATEGORY_BUTTON_PREFIX = "catnav-"

# I gruppi categoria stanno in una sezione propria, quindi il sort_order deve solo
# preservare l'ordine fra loro: parte da 10 e cresce di uno per radice.
_CATEGORY_GROUP_BASE_ORDER = 10

# Sezione dedicata alle categorie (``AssetSidebarButton.SECTION_CATEGORIES``).
# Costante locale e non import del modello: questo modulo gira anche dentro le
# migration, con i modelli storici di ``apps.get_model``.
SECTION_CATEGORIES = "CATEGORIES"


def category_sidebar_target(category_id: int) -> str:
    """URL sidebar che apre l'inventario filtrato su una categoria."""
    return f"django:assets:asset_list?asset_category={int(category_id)}&rows={{rows}}"


def category_sidebar_active_match(category_id: int) -> str:
    """Substring usata per marcare attiva la voce sidebar della categoria."""
    return f"asset_category={int(category_id)}"


def rebuild_category_sidebar(AssetCategory, AssetSidebarButton) -> tuple[int, int]:
    """(Ri)costruisce i gruppi sidebar dalle categorie radice attive.

    Idempotente: rimuove i pulsanti categoria preesistenti (e i legacy basati
    su asset_type) e li ricrea dall'albero corrente. Non tocca gli altri
    pulsanti (Cruscotto, strumenti, Operativita).

    Ritorna ``(numero_gruppi, numero_voci)``.
    """
    AssetSidebarButton.objects.filter(code__in=LEGACY_BUTTON_CODES).delete()
    AssetSidebarButton.objects.filter(code__startswith=CATEGORY_BUTTON_PREFIX).delete()

    roots = list(
        AssetCategory.objects.filter(parent__isnull=True, is_active=True)
        .order_by("sort_order", "label", "id")
    )

    groups = 0
    items = 0
    for root_index, root in enumerate(roots):
        group_order = _CATEGORY_GROUP_BASE_ORDER + root_index
        group = AssetSidebarButton.objects.create(
            code=f"{CATEGORY_BUTTON_PREFIX}root-{root.id}",
            section=SECTION_CATEGORIES,
            parent=None,
            label=root.label[:120],
            target_url=category_sidebar_target(root.id),
            active_match=category_sidebar_active_match(root.id),
            is_subitem=False,
            sort_order=group_order,
            is_visible=True,
        )
        groups += 1

        children = list(
            AssetCategory.objects.filter(parent_id=root.id, is_active=True)
            .order_by("sort_order", "label", "id")
        )
        for child_index, child in enumerate(children):
            AssetSidebarButton.objects.create(
                code=f"{CATEGORY_BUTTON_PREFIX}{child.id}",
                section=SECTION_CATEGORIES,
                parent=group,
                label=child.label[:120],
                target_url=category_sidebar_target(child.id),
                active_match=category_sidebar_active_match(child.id),
                is_subitem=True,
                sort_order=group_order * 100 + child_index,
                is_visible=True,
            )
            items += 1

    # Garantisce che i report restino raggiungibili: il vecchio gruppo che li
    # ospitava (asset_produzione/dispositivi_it) viene rimosso dal rebuild.
    # Vivono nella sezione strumenti (OPERATIONS), separati dalle categorie.
    AssetSidebarButton.objects.get_or_create(
        code="report_asset",
        defaults={
            "section": "OPERATIONS",
            "parent": None,
            "label": "Report asset",
            "target_url": "django:assets:reports",
            "active_match": "/assets/reports/",
            "is_subitem": False,
            "sort_order": 50,
            "is_visible": True,
        },
    )

    return groups, items
