"""Sidebar Assets divisa per aree: Inventario, Manutenzione e officina, IT e rete.

Prima «Configurazione» della Manutenzione conteneva anche licenze, catalogo
software, indirizzi IP e rack (lavoro dell'IT, non della manutenzione), e
«Componenti» stava fra gli strumenti invece che nell'inventario. Nessun URL
cambia: si spostano solo le voci. La guida esce dall'elenco e diventa un link
fisso in fondo alla sidebar (``base_shell.html``).

Le voci si cercano per codice: un'installazione che le ha tolte o rinominate a
mano da Impostazioni › Menu sidebar non viene ricreata.
"""

from django.db import migrations, models

IT = (
    ("licenze", "Licenze software", 10),
    ("catalogo_software", "Catalogo software", 20),
    ("rete_indirizzi", "Indirizzi IP", 30),
    ("rete_rack", "Rack e switch", 40),
)
OFFICINA = (
    ("maintenance_hub", 10),
    ("maintenance_configurazione", 20),
    ("mappa_officina", 30),
    ("part_145_list", 40),
)
# Posizione di prima, per tornare indietro.
IT_PRIMA = {"licenze": 75, "catalogo_software": 80, "rete_indirizzi": 83, "rete_rack": 83}
OFFICINA_PRIMA = {"maintenance_hub": 10, "maintenance_configurazione": 11, "mappa_officina": 30, "part_145_list": 70}


def avanti(apps, schema_editor):
    Button = apps.get_model("assets", "AssetSidebarButton")
    for code, label, order in IT:
        Button.objects.filter(code=code).update(
            section="IT", parent=None, is_subitem=False, label=label, sort_order=order, is_visible=True
        )
    for code, order in OFFICINA:
        Button.objects.filter(code=code).update(section="OPERATIONS", sort_order=order)
    Button.objects.filter(code="componenti").update(
        section="MAIN", parent=None, is_subitem=False, sort_order=40
    )
    # «Rete» accanto alla sezione «IT e rete» confondeva: sono gli apparati.
    Button.objects.filter(code="networking", label="Rete").update(label="Apparati di rete")
    Button.objects.filter(code="guida_asset").update(is_visible=False)


def indietro(apps, schema_editor):
    Button = apps.get_model("assets", "AssetSidebarButton")
    configurazione = Button.objects.filter(code="maintenance_configurazione").first()
    for code, order in IT_PRIMA.items():
        Button.objects.filter(code=code).update(
            section="OPERATIONS", parent=configurazione, is_subitem=configurazione is not None, sort_order=order
        )
    for code, order in OFFICINA_PRIMA.items():
        Button.objects.filter(code=code).update(sort_order=order)
    Button.objects.filter(code="componenti").update(section="OPERATIONS", sort_order=20)
    Button.objects.filter(code="networking", label="Apparati di rete").update(label="Rete")
    Button.objects.filter(code="guida_asset").update(is_visible=True)


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0155_rack_rete"),
    ]

    operations = [
        migrations.AlterField(
            model_name="assetsidebarbutton",
            name="section",
            field=models.CharField(
                choices=[
                    ("MAIN", "Inventario"),
                    ("OPERATIONS", "Manutenzione e officina"),
                    ("IT", "IT e rete"),
                    ("ANALYTICS", "Analisi e rischio"),
                    ("CATEGORIES", "Inventario per categoria"),
                ],
                db_index=True,
                default="MAIN",
                max_length=20,
            ),
        ),
        migrations.RunPython(avanti, indietro),
    ]
