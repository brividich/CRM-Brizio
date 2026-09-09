"""Rettifica della 0102: "Attivita'" e "Parametri" erano la stessa pagina.

La 0102 ha creato una voce "Attivita'" verso ``maintenance_template_list``
accanto a "Parametri" verso ``maintenance_impostazioni``. Ma la prima e' un
**redirect permanente** alla seconda (``/assets/manutenzione/templates/`` ->
``/assets/manutenzione/impostazioni/?tab=catalogo``), e quella pagina ha una
scheda sola: due voci di menu che portano allo stesso posto, con l'evidenziazione
dell'attivo che si sarebbe accesa su quella sbagliata.

Resta una voce sola, chiamata con cio' che contiene — il catalogo di cosa fare —
invece che "Impostazioni", che faceva sembrare un pannello tecnico la pagina dove
si definiscono le attivita' di manutenzione.

Nessun URL cambia: ``/assets/manutenzione/impostazioni/`` continua a rispondere,
e anche il vecchio ``/assets/manutenzione/templates/`` che ci redirige sopra.
"""
from django.db import migrations


def avanti(apps, schema_editor):
    Button = apps.get_model("assets", "AssetSidebarButton")

    rimossi, _ = Button.objects.filter(code="maintenance_attivita").delete()
    aggiornati = Button.objects.filter(code="maintenance_impostazioni").update(
        label="Attività",
        target_url="django:assets:maintenance_impostazioni",
        active_match="/assets/manutenzione/impostazioni/",
        sort_order=10,
    )
    print(
        f"  [assets 0103] Voce duplicata rimossa: {rimossi}; "
        f"'Impostazioni' rinominata 'Attività': {aggiornati}."
    )


def indietro(apps, schema_editor):
    Button = apps.get_model("assets", "AssetSidebarButton")
    config = Button.objects.filter(code="maintenance_configurazione").first()
    Button.objects.filter(code="maintenance_impostazioni").update(
        label="Parametri", sort_order=50
    )
    if config is not None:
        Button.objects.get_or_create(
            code="maintenance_attivita",
            defaults={
                "section": "OPERATIONS",
                "parent": config,
                "label": "Attività",
                "target_url": "django:assets:maintenance_template_list",
                "active_match": "/assets/manutenzione/templates/",
                "is_subitem": True,
                "sort_order": 10,
                "is_visible": True,
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0102_sidebar_manutenzione_configurazione"),
    ]

    operations = [
        migrations.RunPython(avanti, indietro),
    ]
