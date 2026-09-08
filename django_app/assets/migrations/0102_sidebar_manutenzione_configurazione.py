"""Il ramo Manutenzione si divide in "Manutenzione" e "Configurazione".

Il sottomenu elencava nove voci di seguito, mescolando cio' che si apre ogni
giorno (Da fare, Scadenze, Interventi) con cio' che si tocca una volta ogni sei
mesi (Gruppi asset, Fornitori, Impostazioni). Chi lavora doveva leggere l'intera
lista per trovare le tre voci che gli servono.

Ora sono due rami:

    Manutenzione     Da fare · Scadenze · Interventi · Piani · Cruscotto · Storico
    Configurazione   Attivita' · Gruppi asset · Fornitori · Copertura · Parametri

"Quadro" diventa "Cruscotto" e "Impostazioni" diventa "Parametri": l'URL non
cambia, cambia solo l'etichetta. Compaiono due voci che esistevano come pagina ma
non nel menu: "Attivita'" (il catalogo di cosa fare) e "Copertura" (la matrice
asset x piano).

Perche' una migration e non un default: i pulsanti della sidebar vivono a
database e il seed usa ``get_or_create``, quindi cambiare il codice non tocca
nessuna installazione esistente.

Reversibile: al rollback le voci tornano tutte sotto "Manutenzione" con le
etichette di prima, e il ramo "Configurazione" viene rimosso.
"""
from django.db import migrations

SECTION_OPERATIONS = "OPERATIONS"

# code -> (label nuova, sort_order nuovo)
MANUTENZIONE = {
    "maintenance_da_fare": ("Da fare", 10),
    "maintenance_scadenzario": ("Scadenze", 20),
    "maintenance_interventi": ("Interventi", 30),
    "maintenance_piani": ("Piani", 40),
    "maintenance_quadro": ("Cruscotto", 50),
    "maintenance_storico": ("Storico", 60),
}

# code -> (label, target_url, active_match, sort_order)
CONFIGURAZIONE = [
    ("maintenance_attivita", "Attività", "django:assets:maintenance_template_list",
     "/assets/manutenzione/templates/", 10),
    ("maintenance_asset_groups", "Gruppi asset", "django:assets:asset_group_list",
     "/assets/manutenzione/gruppi/", 20),
    ("maintenance_fornitori", "Fornitori", "django:assets:maintenance_suppliers",
     "/assets/manutenzione/fornitori/", 30),
    ("maintenance_copertura", "Copertura", "django:assets:maintenance_coverage",
     "/assets/manutenzione/copertura/", 40),
    ("maintenance_impostazioni", "Parametri", "django:assets:maintenance_impostazioni",
     "/assets/manutenzione/impostazioni/", 50),
]

# Stato precedente, per il rollback.
PRIMA = {
    "maintenance_da_fare": ("Da fare", 10),
    "maintenance_scadenzario": ("Scadenze", 20),
    "maintenance_quadro": ("Quadro", 30),
    "maintenance_interventi": ("Interventi", 40),
    "maintenance_piani": ("Piani", 50),
    "maintenance_asset_groups": ("Gruppi asset", 60),
    "maintenance_storico": ("Storico", 70),
    "maintenance_fornitori": ("Fornitori", 90),
    "maintenance_impostazioni": ("Impostazioni", 110),
}


def avanti(apps, schema_editor):
    Button = apps.get_model("assets", "AssetSidebarButton")

    hub = Button.objects.filter(code="maintenance_hub").first()
    if hub is None:
        return

    for code, (label, order) in MANUTENZIONE.items():
        Button.objects.filter(code=code).update(
            label=label, parent=hub, sort_order=order, is_visible=True
        )

    config, _ = Button.objects.get_or_create(
        code="maintenance_configurazione",
        defaults={
            "section": SECTION_OPERATIONS,
            "parent": None,
            "label": "Configurazione",
            # Il ramo apre sul catalogo attivita': un genitore che non porta da
            # nessuna parte e' una voce che delude chi la clicca.
            "target_url": "django:assets:maintenance_template_list",
            "active_match": "",
            "is_subitem": False,
            "sort_order": (hub.sort_order or 0) + 1,
            "is_visible": True,
        },
    )

    creati = 0
    for code, label, target, match, order in CONFIGURAZIONE:
        _, created = Button.objects.update_or_create(
            code=code,
            defaults={
                "section": SECTION_OPERATIONS,
                "parent": config,
                "label": label,
                "target_url": target,
                "active_match": match,
                "is_subitem": True,
                "sort_order": order,
                "is_visible": True,
            },
        )
        creati += int(created)

    print(
        f"  [assets 0102] Ramo Manutenzione riordinato ({len(MANUTENZIONE)} voci); "
        f"Configurazione con {len(CONFIGURAZIONE)} voci ({creati} nuove)."
    )


def indietro(apps, schema_editor):
    Button = apps.get_model("assets", "AssetSidebarButton")
    hub = Button.objects.filter(code="maintenance_hub").first()
    for code, (label, order) in PRIMA.items():
        Button.objects.filter(code=code).update(label=label, parent=hub, sort_order=order)
    # Le due voci che prima non esistevano nel menu se ne vanno con il ramo.
    Button.objects.filter(code__in=["maintenance_attivita", "maintenance_copertura"]).delete()
    Button.objects.filter(code="maintenance_configurazione").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0101_sidebar_sezione_categorie"),
    ]

    operations = [
        migrations.RunPython(avanti, indietro),
    ]
