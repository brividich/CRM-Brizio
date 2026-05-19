"""Generazione della sidebar asset a partire dall'albero delle categorie.

La navigazione asset e' guidata dalle ``AssetCategory``: ogni categoria radice
diventa un gruppo della sidebar ("Navigazione principale") e ogni sotto-categoria
una voce cliccabile che apre l'inventario filtrato su quella categoria (e le sue
discendenti).

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
]

# Prefisso dei pulsanti generati automaticamente da questa logica.
CATEGORY_BUTTON_PREFIX = "catnav-"

# Range di sort_order riservato ai gruppi categoria (tra "Cruscotto"=10 e gli
# strumenti a partire da 45/50).
_CATEGORY_GROUP_BASE_ORDER = 20


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
    SECTION_MAIN = "MAIN"

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
            section=SECTION_MAIN,
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
                section=SECTION_MAIN,
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
    AssetSidebarButton.objects.get_or_create(
        code="report_asset",
        defaults={
            "section": SECTION_MAIN,
            "parent": None,
            "label": "Report asset",
            "target_url": "django:assets:reports",
            "active_match": "/assets/reports/",
            "is_subitem": False,
            "sort_order": 55,
            "is_visible": True,
        },
    )

    return groups, items
