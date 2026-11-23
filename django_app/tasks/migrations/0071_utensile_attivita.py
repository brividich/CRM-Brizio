"""Utensile della commessa collegato a un'attività (riquadro «Collegamenti»).

Solo una colonna facoltativa in più: le righe esistenti restano com'erano
(senza attività) e tornando indietro la colonna si toglie senza altre perdite.
"""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tasks", "0070_descrizione_pezzo"),
    ]

    operations = [
        migrations.AddField(
            model_name="projectutensile",
            name="task",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name="utensili_collegati", to="tasks.task", verbose_name="Attività",
            ),
        ),
    ]
