"""Tipi di documento di partenza: si cambiano in Impostazioni."""
from django.db import migrations

TIPI = (
    ("Ciclo di lavoro", "Fasi, macchine e tempi dell'OP."),
    ("Disegno", "Disegno del particolare alla revisione dell'OP."),
    ("DIP / istruzione di produzione", "Istruzioni per il reparto."),
    ("Piano di controllo", "Controlli e frequenze."),
    ("Certificato materiale", "Certificati del materiale e dei trattamenti."),
    ("Rapporto di collaudo", "Misure e collaudo finale."),
    ("Dichiarazione di conformità", "CoC verso il cliente."),
    ("Altro", ""),
)


def crea(apps, schema_editor):
    Tipo = apps.get_model("produzione", "TipoDocumento")
    for ordine, (etichetta, descrizione) in enumerate(TIPI, start=1):
        Tipo.objects.get_or_create(etichetta=etichetta, defaults={"descrizione": descrizione, "ordine": ordine * 10})


class Migration(migrations.Migration):
    dependencies = [("produzione", "0001_initial")]
    operations = [migrations.RunPython(crea, migrations.RunPython.noop)]
