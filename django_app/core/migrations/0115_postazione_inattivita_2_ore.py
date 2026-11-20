"""Postazioni condivise: inattività di base 2 ore (era 10 minuti).

Con 10 minuti l'operatore che compila a lungo una pagina senza navigare (es. apertura
anomalie) tornava a «Chi sei?» e il salvataggio finiva in errore. Le postazioni con
meno di 2 ore passano a 2 ore.
"""
from django.db import migrations, models


def _porta_a_due_ore(apps, schema_editor):
    Postazione = apps.get_model("core", "PostazioneCondivisa")
    Postazione.objects.filter(minuti_inattivita__lt=120).update(minuti_inattivita=120)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0114_sharedtableview"),
    ]

    operations = [
        migrations.AlterField(
            model_name="postazionecondivisa",
            name="minuti_inattivita",
            field=models.PositiveSmallIntegerField(
                default=120,
                help_text="Dopo questi minuti senza usare il portale si torna alla scelta dell'operatore.",
            ),
        ),
        migrations.RunPython(_porta_a_due_ore, migrations.RunPython.noop),
    ]
