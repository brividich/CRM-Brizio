from django.db import migrations

VOCI = (
    ("CHIUSURA", ("Dichiarazione", "Mail")),
    ("VERSIONE", ("Approvata", "Non richiesta approvazione")),
    ("CROSS", ("Non richiesta", "Inviata", "Inviata con ZPN", "Manca cross con ZPN", "Richiesta ma non fornita")),
)


def seed(apps, schema_editor):
    Opzione = apps.get_model("tasks", "FaiOpzione")
    for gruppo, etichette in VOCI:
        for indice, etichetta in enumerate(etichette, start=1):
            if not Opzione.objects.filter(gruppo=gruppo, etichetta__iexact=etichetta).exists():
                Opzione.objects.create(gruppo=gruppo, etichetta=etichetta, ordine=indice * 10)


class Migration(migrations.Migration):
    dependencies = [("tasks", "0057_fai_colonne_situazione")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
