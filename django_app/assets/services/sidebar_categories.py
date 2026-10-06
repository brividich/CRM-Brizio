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

# Aree d'uso: raggruppano le categorie radice in poche voci, per chi le usa
# (produzione, manutenzione, IT, HSE) invece che una radice per riga.
# Il confronto e' sull'etichetta della radice, senza maiuscole/spazi: le
# radici non elencate restano voci a se', dopo le aree, come prima.
# Un'area con una sola radice mostra direttamente le sotto-categorie di quella.
CATEGORY_AREAS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("produzione", "Produzione", ("CNC", "Macchine NO CE", "CMM", "Kardex")),
    (
        "sollevamento",
        "Sollevamento e movimentazione",
        ("Apparecchi di Presa e Sollevamento", "Mezzi di Movimentazione e Sollevamento"),
    ),
    (
        "impianti",
        "Impianti e servizi",
        (
            "Heating, Ventilation and Air Conditioning",
            "Impianti Fotovoltaici",
            "Impianto Fotovoltaico",
            "Impianti/Attrezzature a Pressione",
            "Impianti termici",
            "Lavatrici, Asciugatrici e affini",
        ),
    ),
    ("it", "Information Technology", ("Information Technology",)),
    ("sicurezza", "Sicurezza e ambiente", ("Prodotti Chimici",)),
)

# Dentro un'area il contesto e' gia' chiaro: nomi brevi per le radici lunghe,
# che altrimenti vanno a capo su due righe nella sidebar.
CATEGORY_SHORT_LABELS: dict[str, str] = {
    "apparecchi di presa e sollevamento": "Apparecchi di presa",
    "mezzi di movimentazione e sollevamento": "Mezzi di movimentazione",
    "heating, ventilation and air conditioning": "Climatizzazione (HVAC)",
    "impianti/attrezzature a pressione": "Attrezzature a pressione",
    "lavatrici, asciugatrici e affini": "Lavatrici e affini",
}

# Sezione dedicata alle categorie (``AssetSidebarButton.SECTION_CATEGORIES``).
# Costante locale e non import del modello: questo modulo gira anche dentro le
# migration, con i modelli storici di ``apps.get_model``.
SECTION_CATEGORIES = "CATEGORIES"


def _label_key(label: str) -> str:
    return " ".join(str(label or "").split()).casefold()


def category_sidebar_target(category_id: int) -> str:
    """URL sidebar che apre l'inventario filtrato su una categoria."""
    return f"django:assets:asset_list?asset_category={int(category_id)}&rows={{rows}}"


def category_sidebar_active_match(category_id: int) -> str:
    """Substring usata per marcare attiva la voce sidebar della categoria."""
    return f"asset_category={int(category_id)}"


def rebuild_category_sidebar(AssetCategory, AssetSidebarButton) -> tuple[int, int]:
    """(Ri)costruisce i gruppi sidebar dalle categorie radice attive.

    Le radici elencate in ``CATEGORY_AREAS`` sono raggruppate per area d'uso
    (la sidebar ha due soli livelli: area -> categoria radice, che filtra
    anche le sue discendenti); le altre restano gruppi a se'.

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
    roots_by_key = {_label_key(root.label): root for root in roots}
    placed: set[int] = set()
    counters = {"groups": 0, "items": 0, "order": _CATEGORY_GROUP_BASE_ORDER}

    def next_order() -> int:
        value = counters["order"]
        counters["order"] += 1
        return value

    def create_button(code, label, target, active, *, parent=None, order=0):
        return AssetSidebarButton.objects.create(
            code=code,
            section=SECTION_CATEGORIES,
            parent=parent,
            label=label[:120],
            target_url=target,
            active_match=active,
            is_subitem=parent is not None,
            sort_order=order,
            is_visible=True,
        )

    def children_of(category):
        return list(
            AssetCategory.objects.filter(parent_id=category.id, is_active=True)
            .order_by("sort_order", "label", "id")
        )

    def add_root_group(root, label=None):
        """Radice come gruppo: voce che filtra sulla radice + sotto-categorie."""
        order = next_order()
        group = create_button(
            f"{CATEGORY_BUTTON_PREFIX}root-{root.id}",
            label or root.label,
            category_sidebar_target(root.id),
            category_sidebar_active_match(root.id),
            order=order,
        )
        counters["groups"] += 1
        for child_index, child in enumerate(children_of(root)):
            create_button(
                f"{CATEGORY_BUTTON_PREFIX}{child.id}",
                child.label,
                category_sidebar_target(child.id),
                category_sidebar_active_match(child.id),
                parent=group,
                order=order * 100 + child_index,
            )
            counters["items"] += 1

    for area_code, area_label, root_labels in CATEGORY_AREAS:
        area_roots = [roots_by_key[key] for key in map(_label_key, root_labels) if key in roots_by_key]
        area_roots = [root for root in area_roots if root.id not in placed]
        if not area_roots:
            continue
        placed.update(root.id for root in area_roots)
        if len(area_roots) == 1:
            # Una radice sola: inutile un contenitore con un unico figlio.
            # Senza sotto-categorie vale il nome della categoria, piu' preciso.
            root = area_roots[0]
            add_root_group(root, label=area_label if children_of(root) else root.label)
            continue
        order = next_order()
        # Contenitore senza destinazione: il clic apre le sotto-voci. L'active
        # match su un parametro che non esiste evita che risulti "attivo" su
        # ogni pagina dell'inventario.
        area = create_button(
            f"{CATEGORY_BUTTON_PREFIX}area-{area_code}",
            area_label,
            "",
            f"catnav_area={area_code}",
            order=order,
        )
        counters["groups"] += 1
        for root_index, root in enumerate(area_roots):
            create_button(
                f"{CATEGORY_BUTTON_PREFIX}root-{root.id}",
                CATEGORY_SHORT_LABELS.get(_label_key(root.label), root.label),
                category_sidebar_target(root.id),
                category_sidebar_active_match(root.id),
                parent=area,
                order=order * 100 + root_index,
            )
            counters["items"] += 1

    # Radici fuori dalle aree: gruppo a se', come prima delle aree.
    for root in roots:
        if root.id not in placed:
            add_root_group(root)

    groups = counters["groups"]
    items = counters["items"]

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
