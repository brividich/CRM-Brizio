"""Categorie DPI delle vie respiratorie rimaste con l'icona predefinita (gilet): passano al respiratore.

Le categorie create dall'import storico («Protezione vie respiratorie», ...) non
avevano un'icona scelta e prendevano quella predefinita, il gilet ad alta
visibilità: sull'etichetta SDS un respiratore stampato come gilet. Si toccano
solo le categorie con «respir» o «mascher» nel nome e l'icona ancora al valore
predefinito: un'icona scelta a mano resta com'è. Nessun ritorno all'indietro.
"""
from django.db import migrations

PREDEFINITE = {"", "vest", "🦺"}


def assegna_respiratore(apps, schema_editor):
    CategoriaDPI = apps.get_model("dpi", "CategoriaDPI")
    for categoria in CategoriaDPI.objects.all().only("pk", "nome", "icona_emoji"):
        nome = (categoria.nome or "").casefold()
        if ("respir" in nome or "mascher" in nome) and (categoria.icona_emoji or "") in PREDEFINITE:
            CategoriaDPI.objects.filter(pk=categoria.pk).update(icona_emoji="mask")


class Migration(migrations.Migration):
    dependencies = [("dpi", "0012_campi_cifrati")]

    operations = [migrations.RunPython(assegna_respiratore, migrations.RunPython.noop)]
