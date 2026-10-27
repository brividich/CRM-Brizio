"""Vista dell'elenco dipendenti «Mansioni e costi» (27/10/2026).

Come la 0158: create-only, il reverse toglie solo il preset creato qui. Le
colonne del costo orario sono sensibili (permesso HR): chi non ce l'ha vede la
vista senza quelle colonne.
"""
from django.db import migrations

CODICE = "mansioni_costi"
CHIAVI = ["reparto", "area_aziendale", "ruoli", "n_mansioni", "classificazione", "coefficienti", "costo_orario",
          "costo_orario_mese"]


def avanti(apps, schema_editor):
    Vista = apps.get_model("anagrafica", "VistaElenco")
    Vista.objects.get_or_create(codice=CODICE, defaults={
        "nome": "Mansioni e costi",
        "descrizione": "Classificazione, coefficienti e costo orario (questo solo per HR).",
        "predefinita": False, "preset": True, "ordine": 70,
        "colonne": [{"chiave": k, "visibile": True, "larghezza": 0} for k in CHIAVI],
    })


def indietro(apps, schema_editor):
    apps.get_model("anagrafica", "VistaElenco").objects.filter(codice=CODICE, preset=True).delete()


class Migration(migrations.Migration):
    dependencies = [("anagrafica", "0206_subnav_coefficienti_costo_orario")]
    operations = [migrations.RunPython(avanti, indietro)]
