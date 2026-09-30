from django.db import migrations


def seed(apps, schema_editor):
    from sistema_gestione.catalogo_27002 import CONTROLLI, ordine_di, tema_di

    Controllo = apps.get_model("sistema_gestione", "ControlloIso27002")
    esistenti = set(Controllo.objects.values_list("codice", flat=True))
    Controllo.objects.bulk_create([
        Controllo(codice=codice, titolo=titolo, tema=tema_di(codice), ordine=ordine_di(codice))
        for codice, titolo in CONTROLLI if codice not in esistenti
    ])


class Migration(migrations.Migration):
    dependencies = [("sistema_gestione", "0001_initial")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
