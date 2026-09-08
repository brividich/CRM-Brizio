"""Le categorie asset escono da "Navigazione" e vanno in una sezione propria.

Tredici categorie radice come voci di primo livello riempivano la sidebar e
spingevano sotto la piega le pagine che si usano davvero ("Il mio turno", il ramo
Manutenzione, gli strumenti). Una categoria pero' non e' una destinazione: e' un
filtro sull'inventario. Da qui la sezione dedicata, in fondo.

Non si annidano sotto un unico genitore perche' il guscio rende **due** livelli:
le sotto-categorie diventerebbero un terzo livello e sparirebbero dal menu.

I pulsanti vivono a database: cambiare il codice non basta, serve la migration.
Reversibile: al rollback le categorie tornano in MAIN.
"""
from django.db import migrations, models

from assets.services.sidebar_categories import CATEGORY_BUTTON_PREFIX

SECTION_MAIN = "MAIN"
SECTION_CATEGORIES = "CATEGORIES"


def _sposta(apps, section):
    Button = apps.get_model("assets", "AssetSidebarButton")
    return Button.objects.filter(code__startswith=CATEGORY_BUTTON_PREFIX).update(section=section)


def avanti(apps, schema_editor):
    spostati = _sposta(apps, SECTION_CATEGORIES)
    print(f"  [assets 0101] Pulsanti categoria spostati in 'Inventario per categoria': {spostati}")


def indietro(apps, schema_editor):
    _sposta(apps, SECTION_MAIN)


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0100_sidebar_manutenzione_riordino"),
    ]

    operations = [
        migrations.AlterField(
            model_name="assetsidebarbutton",
            name="section",
            field=models.CharField(
                choices=[
                    ("MAIN", "Navigazione"),
                    ("ANALYTICS", "Analisi e rischio"),
                    ("OPERATIONS", "Strumenti e gestione"),
                    ("CATEGORIES", "Inventario per categoria"),
                ],
                db_index=True,
                default="MAIN",
                max_length=20,
            ),
        ),
        migrations.RunPython(avanti, indietro),
    ]
